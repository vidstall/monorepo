#[allow(lint(public_entry))]
module xaisen_contract::rentals;

use sui::clock::{Self, Clock};
use sui::coin::{Self, Coin};
use sui::transfer;
use sui::tx_context::{Self, TxContext};
use xaisen_contract::media_events;
use xaisen_contract::media_store;
use xaisen_contract::registry::Registry;
use xaisen_contract::rental_events;
use xaisen_contract::rental_store;
use xaisen_contract::worker_store;

const E_WORKER_UNAVAILABLE: u64 = 6;

public entry fun hire_worker<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    room_name: vector<u8>,
    capacity: u64,
    payment_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    worker_store::assert_exists(registry.workers(), node_id);
    rental_store::assert_room_name(&room_name);
    rental_store::assert_capacity(capacity);

    let payment_amount = coin::value(&payment_coin);
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let room_name_for_event = copy room_name;

    let record = worker_store::borrow(registry.workers(), node_id);
    assert!(worker_store::active(record) && worker_store::rentable(record), E_WORKER_UNAVAILABLE);
    worker_store::assert_no_active_rental(worker_store::active_rental_id(record));
    rental_store::assert_payment_amount(payment_amount, worker_store::price_per_rental(record));
    let worker_owner = worker_store::owner(record);

    let rental_id = rental_store::insert(
        registry.rentals_mut(), node_id, sender, worker_owner, room_name, capacity, payment_coin,
        rental_store::rental_pending(), timestamp_ms,
    );

    let record_mut = worker_store::borrow_mut(registry.workers_mut(), node_id);
    worker_store::set_active_rental_id(record_mut, rental_id);

    rental_events::emit_worker_hired(
        rental_id, node_id, sender, worker_owner, room_name_for_event, capacity, payment_amount, timestamp_ms,
    );
}

public entry fun complete_rental<T>(registry: &mut Registry<T>, rental_id: u64, clock: &Clock, ctx: &mut TxContext) {
    rental_store::assert_exists(registry.rentals(), rental_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let rental = rental_store::borrow(registry.rentals(), rental_id);
    rental_store::assert_client(rental_store::client(rental), sender);
    rental_store::assert_pending_or_active(rental_store::status(rental));

    let node_id = rental_store::worker_node_id(rental);
    let routed = media_store::has_routed_assignment(registry.uid(), rental_id);
    if (!routed) {
        let record = worker_store::borrow_mut(registry.workers_mut(), node_id);
        worker_store::set_active_rental_id(record, worker_store::no_active_rental());
    };

    let (_, client, worker_owner, mut payment) = rental_store::remove(registry.rentals_mut(), rental_id);
    let payment_amount = sui::balance::value(&payment);
    rental_store::add_rewards_paid(registry.rentals_mut(), payment_amount);

    if (routed) {
        let (router_node_id, _media_node_id, _cluster_id) = media_store::remove_routed_assignment(registry.uid_mut(), rental_id);
        let router_amount = payment_amount - ((payment_amount * media_store::media_payment_bps()) / media_store::bps_denominator());
        let router_payment = sui::balance::split(&mut payment, router_amount);
        let media_amount = sui::balance::value(&payment);
        let router_owner_for_event = worker_store::owner(worker_store::borrow(registry.workers(), router_node_id));
        transfer::public_transfer(coin::from_balance(payment, ctx), worker_owner);
        transfer::public_transfer(coin::from_balance(router_payment, ctx), router_owner_for_event);
        media_events::emit_routed_payment_split(rental_id, media_amount, router_amount, worker_owner, router_owner_for_event);
    } else {
        transfer::public_transfer(coin::from_balance(payment, ctx), worker_owner);
    };

    rental_events::emit_rental_completed(rental_id, node_id, client, worker_owner, payment_amount, timestamp_ms);
    rental_events::emit_worker_reward_paid(rental_id, node_id, worker_owner, payment_amount);
}

public entry fun cancel_rental<T>(registry: &mut Registry<T>, rental_id: u64, ctx: &mut TxContext) {
    rental_store::assert_exists(registry.rentals(), rental_id);

    let sender = tx_context::sender(ctx);
    let rental = rental_store::borrow(registry.rentals(), rental_id);
    rental_store::assert_client(rental_store::client(rental), sender);
    rental_store::assert_pending(rental_store::status(rental));

    let node_id = rental_store::worker_node_id(rental);

    let record = worker_store::borrow_mut(registry.workers_mut(), node_id);
    worker_store::set_active_rental_id(record, worker_store::no_active_rental());

    let (_, client, _, payment) = rental_store::remove(registry.rentals_mut(), rental_id);
    let payment_amount = sui::balance::value(&payment);
    transfer::public_transfer(coin::from_balance(payment, ctx), client);
    rental_events::emit_rental_canceled(rental_id, node_id, client, payment_amount);
}
