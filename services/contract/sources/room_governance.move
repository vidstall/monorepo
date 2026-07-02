#[allow(lint(public_entry))]
module xaisen_contract::room_governance;

use sui::clock::{Self, Clock};
use sui::coin::{Self, Coin};
use sui::transfer;
use sui::tx_context::{Self, TxContext};
use xaisen_contract::governance_events;
use xaisen_contract::registry::Registry;
use xaisen_contract::rental_store;
use xaisen_contract::room_vote_store;
use xaisen_contract::worker_store;

const PROPOSAL_TYPE_ROOM: u8 = 0;
const E_NOT_ACTIVE_WORKER: u64 = 15;

public entry fun order_room<T>(
    registry: &mut Registry<T>,
    room_name: vector<u8>,
    capacity: u64,
    payment_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    rental_store::assert_room_name(&room_name);
    rental_store::assert_capacity(capacity);

    let payment_amount = coin::value(&payment_coin);
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let room_name_for_event = copy room_name;
    let deadline_ms = timestamp_ms + room_vote_store::default_vote_deadline_ms();

    let rental_id = rental_store::insert(
        registry.rentals_mut(), 0, sender, @0x0, room_name, capacity, payment_coin,
        rental_store::rental_awaiting_assignment(), timestamp_ms,
    );
    room_vote_store::insert(registry.room_votes_mut(), rental_id, deadline_ms, ctx);

    governance_events::emit_room_order_created(
        rental_id, sender, room_name_for_event, capacity, payment_amount, deadline_ms, timestamp_ms,
    );
}

public entry fun cast_room_vote<T>(
    registry: &mut Registry<T>,
    voter_node_id: u64,
    rental_id: u64,
    nominee_node_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);

    worker_store::assert_exists(registry.workers(), voter_node_id);
    let voter_record = worker_store::borrow(registry.workers(), voter_node_id);
    worker_store::assert_owner(worker_store::owner(voter_record), sender);
    assert!(worker_store::active(voter_record), E_NOT_ACTIVE_WORKER);

    worker_store::assert_exists(registry.workers(), nominee_node_id);
    let nominee_record = worker_store::borrow(registry.workers(), nominee_node_id);
    room_vote_store::assert_nominee_available(worker_store::active(nominee_record));
    worker_store::assert_no_active_rental(worker_store::active_rental_id(nominee_record));

    room_vote_store::assert_exists(registry.room_votes(), rental_id);
    let proposal = room_vote_store::borrow_mut(registry.room_votes_mut(), rental_id);
    room_vote_store::assert_not_finalized(proposal);
    room_vote_store::assert_not_expired(proposal, timestamp_ms);

    let nominee_votes = room_vote_store::add_vote(proposal, sender, nominee_node_id);

    governance_events::emit_vote_cast(PROPOSAL_TYPE_ROOM, rental_id, sender, voter_node_id, timestamp_ms);

    let active_count = worker_store::active_worker_count(registry.workers());
    if (nominee_votes * 2 > active_count) {
        let proposal = room_vote_store::borrow_mut(registry.room_votes_mut(), rental_id);
        room_vote_store::finalize(proposal, nominee_node_id);

        let rental = rental_store::borrow_mut(registry.rentals_mut(), rental_id);
        rental_store::set_worker_node_id(rental, nominee_node_id);
        let nominee_owner = worker_store::owner(worker_store::borrow(registry.workers(), nominee_node_id));
        let rental = rental_store::borrow_mut(registry.rentals_mut(), rental_id);
        rental_store::set_worker_owner(rental, nominee_owner);
        rental_store::set_status(rental, rental_store::rental_active());

        let worker_record = worker_store::borrow_mut(registry.workers_mut(), nominee_node_id);
        worker_store::set_active_rental_id(worker_record, rental_id);

        governance_events::emit_room_assignment_finalized(rental_id, nominee_node_id, timestamp_ms);
    };
}

public entry fun cancel_expired_order<T>(registry: &mut Registry<T>, rental_id: u64, clock: &Clock, ctx: &mut TxContext) {
    rental_store::assert_exists(registry.rentals(), rental_id);
    let rental = rental_store::borrow(registry.rentals(), rental_id);
    rental_store::assert_awaiting_assignment(rental_store::status(rental));

    room_vote_store::assert_exists(registry.room_votes(), rental_id);
    let proposal = room_vote_store::borrow(registry.room_votes(), rental_id);
    let timestamp_ms = clock::timestamp_ms(clock);
    room_vote_store::assert_expired(proposal, timestamp_ms);
    room_vote_store::assert_not_finalized(proposal);

    let client = rental_store::client(rental);

    let removed_proposal = room_vote_store::remove(registry.room_votes_mut(), rental_id);
    room_vote_store::drop(removed_proposal);

    let (_, _, _, payment) = rental_store::remove(registry.rentals_mut(), rental_id);
    transfer::public_transfer(coin::from_balance(payment, ctx), client);

    governance_events::emit_proposal_expired(PROPOSAL_TYPE_ROOM, rental_id, timestamp_ms);
}
