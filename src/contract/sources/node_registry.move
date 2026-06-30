#[allow(lint(public_entry))]
module xaisen_contract::node_registry;

use std::vector;
use sui::balance::{Self, Balance};
use sui::clock::{Self, Clock};
use sui::coin::{Self, Coin};
use sui::event;
use sui::object::{Self, UID};
use sui::table::{Self, Table};
use sui::transfer;
use sui::tx_context::{Self, TxContext};

const E_EMPTY_METADATA_URI: u64 = 0;
const E_INVALID_METADATA_HASH: u64 = 1;
const E_NODE_NOT_FOUND: u64 = 2;
const E_NOT_NODE_OWNER: u64 = 3;
const E_INVALID_PRICE: u64 = 4;
const E_INSUFFICIENT_STAKE: u64 = 5;
const E_WORKER_UNAVAILABLE: u64 = 6;
const E_INVALID_PAYMENT_AMOUNT: u64 = 7;
const E_EMPTY_ROOM_NAME: u64 = 8;
const E_RENTAL_NOT_FOUND: u64 = 9;
const E_NOT_RENTAL_CLIENT: u64 = 10;
const E_RENTAL_NOT_PENDING: u64 = 11;
const E_WORKER_HAS_ACTIVE_RENTAL: u64 = 12;
const E_WORKER_ACTIVE: u64 = 13;
const E_INVALID_CAPACITY: u64 = 14;
const E_NOT_ACTIVE_WORKER: u64 = 15;
const E_ALREADY_VOTED: u64 = 16;
const E_PROPOSAL_NOT_FOUND: u64 = 17;
const E_PROPOSAL_EXPIRED: u64 = 18;
const E_PROPOSAL_ALREADY_FINALIZED: u64 = 19;
const E_INVALID_ROLE: u64 = 20;
const E_NOMINEE_NOT_FOUND: u64 = 21;

const METADATA_HASH_LENGTH: u64 = 32;
const MIN_WORKER_STAKE: u64 = 1_000;
const NO_ACTIVE_RENTAL: u64 = 0;
const RENTAL_PENDING: u8 = 0;
const RENTAL_AWAITING_ASSIGNMENT: u8 = 2;
const RENTAL_ACTIVE: u8 = 3;

const ROLE_SFU: u8 = 0;
const ROLE_COORDINATOR: u8 = 1;
const ROLE_ROUTER: u8 = 2;

const DEFAULT_VOTE_DEADLINE_MS: u64 = 3_600_000;

// ── Core structs ────────────────────────────────────────────────────

public struct Registry<phantom T> has key {
    id: UID,
    next_node_id: u64,
    next_rental_id: u64,
    node_count: u64,
    total_rewards_paid: u64,
    active_worker_count: u64,
    workers: Table<u64, WorkerRecord<T>>,
    rentals: Table<u64, RentalRecord<T>>,
    room_proposals: Table<u64, RoomAssignmentProposal>,
    next_role_proposal_id: u64,
    role_proposals: Table<u64, RoleProposal>,
    role_map: Table<u64, u8>,
    coordinator_endpoint: vector<u8>,
}

public struct WorkerRecord<phantom T> has store {
    owner: address,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    active: bool,
    rentable: bool,
    price_per_rental: u64,
    stake: Balance<T>,
    active_rental_id: u64,
    created_at_ms: u64,
    updated_at_ms: u64,
}

public struct RentalRecord<phantom T> has store {
    worker_node_id: u64,
    client: address,
    worker_owner: address,
    room_name: vector<u8>,
    capacity: u64,
    payment: Balance<T>,
    status: u8,
    created_at_ms: u64,
    completed_at_ms: u64,
}

public struct RoomAssignmentProposal has store {
    rental_id: u64,
    votes: Table<address, u64>,
    vote_counts: Table<u64, u64>,
    total_votes: u64,
    deadline_ms: u64,
    finalized: bool,
    assigned_node_id: u64,
}

public struct RoleProposal has store {
    role: u8,
    nominee_node_id: u64,
    proposer: address,
    votes_for: Table<address, bool>,
    vote_count: u64,
    deadline_ms: u64,
    finalized: bool,
    passed: bool,
}

// ── Events ──────────────────────────────────────────────────────────

public struct WorkerRegistered has copy, drop {
    node_id: u64,
    owner: address,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    price_per_rental: u64,
    stake_amount: u64,
    timestamp_ms: u64,
}

public struct WorkerMetadataUpdated has copy, drop {
    node_id: u64,
    owner: address,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    timestamp_ms: u64,
}

public struct WorkerStatusUpdated has copy, drop {
    node_id: u64,
    owner: address,
    active: bool,
    timestamp_ms: u64,
}

public struct WorkerUnregistered has copy, drop {
    node_id: u64,
    owner: address,
}

public struct WorkerPriceUpdated has copy, drop {
    node_id: u64,
    owner: address,
    price_per_rental: u64,
}

public struct WorkerStakeWithdrawn has copy, drop {
    node_id: u64,
    owner: address,
    stake_amount: u64,
}

public struct WorkerHired has copy, drop {
    rental_id: u64,
    node_id: u64,
    client: address,
    worker_owner: address,
    room_name: vector<u8>,
    capacity: u64,
    payment_amount: u64,
    timestamp_ms: u64,
}

public struct RentalCompleted has copy, drop {
    rental_id: u64,
    node_id: u64,
    client: address,
    worker_owner: address,
    payment_amount: u64,
    timestamp_ms: u64,
}

public struct RentalCanceled has copy, drop {
    rental_id: u64,
    node_id: u64,
    client: address,
    payment_amount: u64,
}

public struct WorkerRewardPaid has copy, drop {
    rental_id: u64,
    node_id: u64,
    worker_owner: address,
    payment_amount: u64,
}

public struct RoomOrderCreated has copy, drop {
    rental_id: u64,
    client: address,
    room_name: vector<u8>,
    capacity: u64,
    payment_amount: u64,
    deadline_ms: u64,
    timestamp_ms: u64,
}

public struct VoteCast has copy, drop {
    proposal_type: u8,
    proposal_id: u64,
    voter: address,
    voter_node_id: u64,
    timestamp_ms: u64,
}

public struct RoomAssignmentFinalized has copy, drop {
    rental_id: u64,
    assigned_node_id: u64,
    timestamp_ms: u64,
}

public struct RoleProposalCreated has copy, drop {
    proposal_id: u64,
    proposer: address,
    nominee_node_id: u64,
    role: u8,
    deadline_ms: u64,
    timestamp_ms: u64,
}

public struct RoleAssigned has copy, drop {
    proposal_id: u64,
    node_id: u64,
    role: u8,
    timestamp_ms: u64,
}

public struct ProposalExpired has copy, drop {
    proposal_type: u8,
    proposal_id: u64,
    timestamp_ms: u64,
}

// ── Existing entry functions ────────────────────────────────────────

public entry fun create_registry<T>(ctx: &mut TxContext) {
    transfer::share_object(new_registry<T>(ctx));
}

public entry fun register_worker<T>(
    registry: &mut Registry<T>,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    price_per_rental: u64,
    stake_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    validate_metadata(&metadata_uri, &metadata_hash);
    assert!(price_per_rental > 0, E_INVALID_PRICE);

    let stake_amount = coin::value(&stake_coin);
    assert!(stake_amount >= MIN_WORKER_STAKE, E_INSUFFICIENT_STAKE);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let node_id = registry.next_node_id;

    registry.next_node_id = node_id + 1;
    registry.node_count = registry.node_count + 1;
    registry.active_worker_count = registry.active_worker_count + 1;

    table::add(
        &mut registry.workers,
        node_id,
        WorkerRecord {
            owner: sender,
            metadata_uri,
            metadata_hash,
            active: true,
            rentable: true,
            price_per_rental,
            stake: coin::into_balance(stake_coin),
            active_rental_id: NO_ACTIVE_RENTAL,
            created_at_ms: timestamp_ms,
            updated_at_ms: timestamp_ms,
        },
    );

    let record = table::borrow(&registry.workers, node_id);
    event::emit(WorkerRegistered {
        node_id,
        owner: sender,
        metadata_uri: record.metadata_uri,
        metadata_hash: record.metadata_hash,
        price_per_rental,
        stake_amount,
        timestamp_ms,
    });
}

public entry fun update_worker_metadata<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    validate_metadata(&metadata_uri, &metadata_hash);
    assert_node_exists(registry, node_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let record = table::borrow_mut(&mut registry.workers, node_id);

    assert_worker_owner(record.owner, sender);

    record.metadata_uri = metadata_uri;
    record.metadata_hash = metadata_hash;
    record.updated_at_ms = timestamp_ms;

    event::emit(WorkerMetadataUpdated {
        node_id,
        owner: sender,
        metadata_uri: record.metadata_uri,
        metadata_hash: record.metadata_hash,
        timestamp_ms,
    });
}

public entry fun set_worker_active<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    active: bool,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let record = table::borrow_mut(&mut registry.workers, node_id);

    assert_worker_owner(record.owner, sender);

    let was_active = record.active;
    record.active = active;
    record.rentable = active;
    record.updated_at_ms = timestamp_ms;

    if (was_active && !active) {
        registry.active_worker_count = registry.active_worker_count - 1;
    } else if (!was_active && active) {
        registry.active_worker_count = registry.active_worker_count + 1;
    };

    event::emit(WorkerStatusUpdated {
        node_id,
        owner: sender,
        active,
        timestamp_ms,
    });
}

public entry fun update_worker_price<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    price_per_rental: u64,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);
    assert!(price_per_rental > 0, E_INVALID_PRICE);

    let sender = tx_context::sender(ctx);
    let record = table::borrow_mut(&mut registry.workers, node_id);
    assert_worker_owner(record.owner, sender);
    record.price_per_rental = price_per_rental;

    event::emit(WorkerPriceUpdated {
        node_id,
        owner: sender,
        price_per_rental,
    });
}

public entry fun unregister_worker<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);

    let sender = tx_context::sender(ctx);
    let record = table::borrow(&registry.workers, node_id);
    assert_worker_owner(record.owner, sender);
    assert_no_active_rental(record.active_rental_id);

    let was_active = record.active;

    let removed = table::remove(&mut registry.workers, node_id);
    registry.node_count = registry.node_count - 1;
    if (was_active) {
        registry.active_worker_count = registry.active_worker_count - 1;
    };
    let WorkerRecord {
        owner,
        metadata_uri: _,
        metadata_hash: _,
        active: _,
        rentable: _,
        price_per_rental: _,
        stake,
        active_rental_id: _,
        created_at_ms: _,
        updated_at_ms: _,
    } = removed;

    transfer::public_transfer(coin::from_balance(stake, ctx), owner);
    event::emit(WorkerUnregistered { node_id, owner });
}

public entry fun withdraw_worker_stake<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);

    let sender = tx_context::sender(ctx);
    let record = table::borrow(&registry.workers, node_id);
    assert_worker_owner(record.owner, sender);
    assert!(!record.active, E_WORKER_ACTIVE);
    assert_no_active_rental(record.active_rental_id);

    let removed = table::remove(&mut registry.workers, node_id);
    registry.node_count = registry.node_count - 1;
    let WorkerRecord {
        owner,
        metadata_uri: _,
        metadata_hash: _,
        active: _,
        rentable: _,
        price_per_rental: _,
        stake,
        active_rental_id: _,
        created_at_ms: _,
        updated_at_ms: _,
    } = removed;
    let stake_amount = balance::value(&stake);

    transfer::public_transfer(coin::from_balance(stake, ctx), owner);
    event::emit(WorkerStakeWithdrawn {
        node_id,
        owner,
        stake_amount,
    });
}

public entry fun hire_worker<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    room_name: vector<u8>,
    capacity: u64,
    payment_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);
    assert!(vector::length(&room_name) > 0, E_EMPTY_ROOM_NAME);
    assert!(capacity > 0, E_INVALID_CAPACITY);

    let payment_amount = coin::value(&payment_coin);
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let rental_id = registry.next_rental_id;
    let record = table::borrow_mut(&mut registry.workers, node_id);

    assert!(record.active && record.rentable, E_WORKER_UNAVAILABLE);
    assert_no_active_rental(record.active_rental_id);
    assert!(payment_amount == record.price_per_rental, E_INVALID_PAYMENT_AMOUNT);

    record.active_rental_id = rental_id;
    registry.next_rental_id = rental_id + 1;

    table::add(
        &mut registry.rentals,
        rental_id,
        RentalRecord {
            worker_node_id: node_id,
            client: sender,
            worker_owner: record.owner,
            room_name,
            capacity,
            payment: coin::into_balance(payment_coin),
            status: RENTAL_PENDING,
            created_at_ms: timestamp_ms,
            completed_at_ms: 0,
        },
    );

    let rental = table::borrow(&registry.rentals, rental_id);
    event::emit(WorkerHired {
        rental_id,
        node_id,
        client: sender,
        worker_owner: rental.worker_owner,
        room_name: rental.room_name,
        capacity,
        payment_amount,
        timestamp_ms,
    });
}

public entry fun complete_rental<T>(
    registry: &mut Registry<T>,
    rental_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert_rental_exists(registry, rental_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let rental = table::borrow(&registry.rentals, rental_id);
    assert_rental_client(rental.client, sender);
    assert_pending_or_active(rental.status);

    let node_id = rental.worker_node_id;
    let worker_owner = rental.worker_owner;
    let client = rental.client;
    let payment_amount = balance::value(&rental.payment);

    let record = table::borrow_mut(&mut registry.workers, node_id);
    record.active_rental_id = NO_ACTIVE_RENTAL;

    let removed = table::remove(&mut registry.rentals, rental_id);
    let RentalRecord {
        worker_node_id: _,
        client: _,
        worker_owner: _,
        room_name: _,
        capacity: _,
        payment,
        status: _,
        created_at_ms: _,
        completed_at_ms: _,
    } = removed;

    registry.total_rewards_paid = registry.total_rewards_paid + payment_amount;
    transfer::public_transfer(coin::from_balance(payment, ctx), worker_owner);

    event::emit(RentalCompleted {
        rental_id,
        node_id,
        client,
        worker_owner,
        payment_amount,
        timestamp_ms,
    });
    event::emit(WorkerRewardPaid {
        rental_id,
        node_id,
        worker_owner,
        payment_amount,
    });
}

public entry fun cancel_rental<T>(
    registry: &mut Registry<T>,
    rental_id: u64,
    ctx: &mut TxContext,
) {
    assert_rental_exists(registry, rental_id);

    let sender = tx_context::sender(ctx);
    let rental = table::borrow(&registry.rentals, rental_id);
    assert_rental_client(rental.client, sender);
    assert_pending(rental.status);

    let node_id = rental.worker_node_id;
    let client = rental.client;
    let payment_amount = balance::value(&rental.payment);

    let record = table::borrow_mut(&mut registry.workers, node_id);
    record.active_rental_id = NO_ACTIVE_RENTAL;

    let removed = table::remove(&mut registry.rentals, rental_id);
    let RentalRecord {
        worker_node_id: _,
        client: _,
        worker_owner: _,
        room_name: _,
        capacity: _,
        payment,
        status: _,
        created_at_ms: _,
        completed_at_ms: _,
    } = removed;

    transfer::public_transfer(coin::from_balance(payment, ctx), client);
    event::emit(RentalCanceled {
        rental_id,
        node_id,
        client,
        payment_amount,
    });
}

// ── Voting: room assignment ─────────────────────────────────────────

public entry fun order_room<T>(
    registry: &mut Registry<T>,
    room_name: vector<u8>,
    capacity: u64,
    payment_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert!(vector::length(&room_name) > 0, E_EMPTY_ROOM_NAME);
    assert!(capacity > 0, E_INVALID_CAPACITY);

    let payment_amount = coin::value(&payment_coin);
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let rental_id = registry.next_rental_id;
    registry.next_rental_id = rental_id + 1;

    let deadline_ms = timestamp_ms + DEFAULT_VOTE_DEADLINE_MS;

    table::add(
        &mut registry.rentals,
        rental_id,
        RentalRecord {
            worker_node_id: 0,
            client: sender,
            worker_owner: @0x0,
            room_name,
            capacity,
            payment: coin::into_balance(payment_coin),
            status: RENTAL_AWAITING_ASSIGNMENT,
            created_at_ms: timestamp_ms,
            completed_at_ms: 0,
        },
    );

    table::add(
        &mut registry.room_proposals,
        rental_id,
        RoomAssignmentProposal {
            rental_id,
            votes: table::new(ctx),
            vote_counts: table::new(ctx),
            total_votes: 0,
            deadline_ms,
            finalized: false,
            assigned_node_id: 0,
        },
    );

    let rental = table::borrow(&registry.rentals, rental_id);
    event::emit(RoomOrderCreated {
        rental_id,
        client: sender,
        room_name: rental.room_name,
        capacity,
        payment_amount,
        deadline_ms,
        timestamp_ms,
    });
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

    assert_node_exists(registry, voter_node_id);
    let voter_record = table::borrow(&registry.workers, voter_node_id);
    assert_worker_owner(voter_record.owner, sender);
    assert!(voter_record.active, E_NOT_ACTIVE_WORKER);

    assert_node_exists(registry, nominee_node_id);
    let nominee_record = table::borrow(&registry.workers, nominee_node_id);
    assert!(nominee_record.active, E_NOMINEE_NOT_FOUND);
    assert_no_active_rental(nominee_record.active_rental_id);

    assert!(table::contains(&registry.room_proposals, rental_id), E_PROPOSAL_NOT_FOUND);
    let proposal = table::borrow_mut(&mut registry.room_proposals, rental_id);
    assert!(!proposal.finalized, E_PROPOSAL_ALREADY_FINALIZED);
    assert!(timestamp_ms <= proposal.deadline_ms, E_PROPOSAL_EXPIRED);
    assert!(!table::contains(&proposal.votes, sender), E_ALREADY_VOTED);

    table::add(&mut proposal.votes, sender, nominee_node_id);
    proposal.total_votes = proposal.total_votes + 1;

    if (table::contains(&proposal.vote_counts, nominee_node_id)) {
        let count = table::borrow_mut(&mut proposal.vote_counts, nominee_node_id);
        *count = *count + 1;
    } else {
        table::add(&mut proposal.vote_counts, nominee_node_id, 1);
    };

    event::emit(VoteCast {
        proposal_type: 0,
        proposal_id: rental_id,
        voter: sender,
        voter_node_id,
        timestamp_ms,
    });

    let nominee_votes = *table::borrow(&proposal.vote_counts, nominee_node_id);
    let active_count = registry.active_worker_count;
    if (nominee_votes * 2 > active_count) {
        proposal.finalized = true;
        proposal.assigned_node_id = nominee_node_id;

        let rental = table::borrow_mut(&mut registry.rentals, rental_id);
        rental.worker_node_id = nominee_node_id;
        rental.worker_owner = table::borrow(&registry.workers, nominee_node_id).owner;
        rental.status = RENTAL_ACTIVE;

        let worker = table::borrow_mut(&mut registry.workers, nominee_node_id);
        worker.active_rental_id = rental_id;

        event::emit(RoomAssignmentFinalized {
            rental_id,
            assigned_node_id: nominee_node_id,
            timestamp_ms,
        });
    };
}

public entry fun cancel_expired_order<T>(
    registry: &mut Registry<T>,
    rental_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert_rental_exists(registry, rental_id);
    let rental = table::borrow(&registry.rentals, rental_id);
    assert!(rental.status == RENTAL_AWAITING_ASSIGNMENT, E_RENTAL_NOT_PENDING);

    assert!(table::contains(&registry.room_proposals, rental_id), E_PROPOSAL_NOT_FOUND);
    let proposal = table::borrow(&registry.room_proposals, rental_id);
    let timestamp_ms = clock::timestamp_ms(clock);
    assert!(timestamp_ms > proposal.deadline_ms, E_PROPOSAL_EXPIRED);
    assert!(!proposal.finalized, E_PROPOSAL_ALREADY_FINALIZED);

    let client = rental.client;

    let removed_proposal = table::remove(&mut registry.room_proposals, rental_id);
    let RoomAssignmentProposal {
        rental_id: _,
        votes,
        vote_counts,
        total_votes: _,
        deadline_ms: _,
        finalized: _,
        assigned_node_id: _,
    } = removed_proposal;
    votes.drop();
    vote_counts.drop();

    let removed_rental = table::remove(&mut registry.rentals, rental_id);
    let RentalRecord {
        worker_node_id: _,
        client: _,
        worker_owner: _,
        room_name: _,
        capacity: _,
        payment,
        status: _,
        created_at_ms: _,
        completed_at_ms: _,
    } = removed_rental;

    transfer::public_transfer(coin::from_balance(payment, ctx), client);

    event::emit(ProposalExpired {
        proposal_type: 0,
        proposal_id: rental_id,
        timestamp_ms,
    });
}

// ── Voting: infrastructure role assignment ──────────────────────────

public entry fun propose_role<T>(
    registry: &mut Registry<T>,
    proposer_node_id: u64,
    nominee_node_id: u64,
    role: u8,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert!(role <= ROLE_ROUTER, E_INVALID_ROLE);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);

    assert_node_exists(registry, proposer_node_id);
    let proposer_record = table::borrow(&registry.workers, proposer_node_id);
    assert_worker_owner(proposer_record.owner, sender);
    assert!(proposer_record.active, E_NOT_ACTIVE_WORKER);

    assert_node_exists(registry, nominee_node_id);

    let proposal_id = registry.next_role_proposal_id;
    registry.next_role_proposal_id = proposal_id + 1;

    let deadline_ms = timestamp_ms + DEFAULT_VOTE_DEADLINE_MS;

    let mut votes_for = table::new(ctx);
    table::add(&mut votes_for, sender, true);

    let active_count = registry.active_worker_count;
    let auto_pass = active_count <= 1;

    table::add(
        &mut registry.role_proposals,
        proposal_id,
        RoleProposal {
            role,
            nominee_node_id,
            proposer: sender,
            votes_for,
            vote_count: 1,
            deadline_ms,
            finalized: auto_pass,
            passed: auto_pass,
        },
    );

    event::emit(RoleProposalCreated {
        proposal_id,
        proposer: sender,
        nominee_node_id,
        role,
        deadline_ms,
        timestamp_ms,
    });

    if (auto_pass) {
        if (table::contains(&registry.role_map, nominee_node_id)) {
            let existing = table::borrow_mut(&mut registry.role_map, nominee_node_id);
            *existing = role;
        } else {
            table::add(&mut registry.role_map, nominee_node_id, role);
        };
        event::emit(RoleAssigned {
            proposal_id,
            node_id: nominee_node_id,
            role,
            timestamp_ms,
        });
    };
}

public entry fun cast_role_vote<T>(
    registry: &mut Registry<T>,
    voter_node_id: u64,
    proposal_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);

    assert_node_exists(registry, voter_node_id);
    let voter_record = table::borrow(&registry.workers, voter_node_id);
    assert_worker_owner(voter_record.owner, sender);
    assert!(voter_record.active, E_NOT_ACTIVE_WORKER);

    assert!(table::contains(&registry.role_proposals, proposal_id), E_PROPOSAL_NOT_FOUND);
    let proposal = table::borrow_mut(&mut registry.role_proposals, proposal_id);
    assert!(!proposal.finalized, E_PROPOSAL_ALREADY_FINALIZED);
    assert!(timestamp_ms <= proposal.deadline_ms, E_PROPOSAL_EXPIRED);
    assert!(!table::contains(&proposal.votes_for, sender), E_ALREADY_VOTED);

    table::add(&mut proposal.votes_for, sender, true);
    proposal.vote_count = proposal.vote_count + 1;

    event::emit(VoteCast {
        proposal_type: 1,
        proposal_id,
        voter: sender,
        voter_node_id,
        timestamp_ms,
    });

    let vote_count = proposal.vote_count;
    let nominee_node_id = proposal.nominee_node_id;
    let role = proposal.role;
    let active_count = registry.active_worker_count;

    if (vote_count * 2 > active_count) {
        proposal.finalized = true;
        proposal.passed = true;

        if (table::contains(&registry.role_map, nominee_node_id)) {
            let existing = table::borrow_mut(&mut registry.role_map, nominee_node_id);
            *existing = role;
        } else {
            table::add(&mut registry.role_map, nominee_node_id, role);
        };

        event::emit(RoleAssigned {
            proposal_id,
            node_id: nominee_node_id,
            role,
            timestamp_ms,
        });
    };
}

// ── Public accessors ────────────────────────────────────────────────

public fun node_exists<T>(registry: &Registry<T>, node_id: u64): bool {
    table::contains(&registry.workers, node_id)
}

public fun node_count<T>(registry: &Registry<T>): u64 {
    registry.node_count
}

public fun active_worker_count<T>(registry: &Registry<T>): u64 {
    registry.active_worker_count
}

public fun worker_owner<T>(registry: &Registry<T>, node_id: u64): address {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).owner
}

public fun worker_active<T>(registry: &Registry<T>, node_id: u64): bool {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).active
}

public fun worker_rentable<T>(registry: &Registry<T>, node_id: u64): bool {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).rentable
}

public fun worker_price_per_rental<T>(registry: &Registry<T>, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).price_per_rental
}

public fun worker_stake_value<T>(registry: &Registry<T>, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    balance::value(&table::borrow(&registry.workers, node_id).stake)
}

public fun worker_active_rental_id<T>(registry: &Registry<T>, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).active_rental_id
}

public fun worker_metadata_uri<T>(registry: &Registry<T>, node_id: u64): vector<u8> {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).metadata_uri
}

public fun worker_metadata_hash<T>(registry: &Registry<T>, node_id: u64): vector<u8> {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).metadata_hash
}

public fun worker_created_at_ms<T>(registry: &Registry<T>, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).created_at_ms
}

public fun worker_updated_at_ms<T>(registry: &Registry<T>, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).updated_at_ms
}

public fun rental_exists<T>(registry: &Registry<T>, rental_id: u64): bool {
    table::contains(&registry.rentals, rental_id)
}

public fun rental_status<T>(registry: &Registry<T>, rental_id: u64): u8 {
    assert_rental_exists(registry, rental_id);
    table::borrow(&registry.rentals, rental_id).status
}

public fun rental_client<T>(registry: &Registry<T>, rental_id: u64): address {
    assert_rental_exists(registry, rental_id);
    table::borrow(&registry.rentals, rental_id).client
}

public fun rental_worker_node_id<T>(registry: &Registry<T>, rental_id: u64): u64 {
    assert_rental_exists(registry, rental_id);
    table::borrow(&registry.rentals, rental_id).worker_node_id
}

public fun rental_room_name<T>(registry: &Registry<T>, rental_id: u64): vector<u8> {
    assert_rental_exists(registry, rental_id);
    table::borrow(&registry.rentals, rental_id).room_name
}

public fun rental_capacity<T>(registry: &Registry<T>, rental_id: u64): u64 {
    assert_rental_exists(registry, rental_id);
    table::borrow(&registry.rentals, rental_id).capacity
}

public fun rental_payment_amount<T>(registry: &Registry<T>, rental_id: u64): u64 {
    assert_rental_exists(registry, rental_id);
    balance::value(&table::borrow(&registry.rentals, rental_id).payment)
}

public fun total_rewards_paid<T>(registry: &Registry<T>): u64 {
    registry.total_rewards_paid
}

public fun has_worker_role<T>(registry: &Registry<T>, node_id: u64): bool {
    table::contains(&registry.role_map, node_id)
}

public fun worker_role<T>(registry: &Registry<T>, node_id: u64): u8 {
    assert!(table::contains(&registry.role_map, node_id), E_NODE_NOT_FOUND);
    *table::borrow(&registry.role_map, node_id)
}

public fun room_proposal_finalized<T>(registry: &Registry<T>, rental_id: u64): bool {
    assert!(table::contains(&registry.room_proposals, rental_id), E_PROPOSAL_NOT_FOUND);
    table::borrow(&registry.room_proposals, rental_id).finalized
}

public fun role_proposal_exists<T>(registry: &Registry<T>, proposal_id: u64): bool {
    table::contains(&registry.role_proposals, proposal_id)
}

public entry fun set_coordinator_endpoint<T>(
    registry: &mut Registry<T>,
    endpoint: vector<u8>,
    _ctx: &mut TxContext,
) {
    registry.coordinator_endpoint = endpoint;
}

public fun coordinator_endpoint<T>(registry: &Registry<T>): vector<u8> {
    registry.coordinator_endpoint
}

// ── Internal helpers ────────────────────────────────────────────────

fun new_registry<T>(ctx: &mut TxContext): Registry<T> {
    Registry {
        id: object::new(ctx),
        next_node_id: 1,
        next_rental_id: 1,
        node_count: 0,
        total_rewards_paid: 0,
        active_worker_count: 0,
        workers: table::new(ctx),
        rentals: table::new(ctx),
        room_proposals: table::new(ctx),
        next_role_proposal_id: 1,
        role_proposals: table::new(ctx),
        role_map: table::new(ctx),
        coordinator_endpoint: vector[],
    }
}

fun validate_metadata(metadata_uri: &vector<u8>, metadata_hash: &vector<u8>) {
    assert!(vector::length(metadata_uri) > 0, E_EMPTY_METADATA_URI);
    assert!(vector::length(metadata_hash) == METADATA_HASH_LENGTH, E_INVALID_METADATA_HASH);
}

fun assert_node_exists<T>(registry: &Registry<T>, node_id: u64) {
    assert_node_present(node_exists(registry, node_id));
}

fun assert_node_present(exists: bool) {
    assert!(exists, E_NODE_NOT_FOUND);
}

fun assert_rental_exists<T>(registry: &Registry<T>, rental_id: u64) {
    assert!(rental_exists(registry, rental_id), E_RENTAL_NOT_FOUND);
}

fun assert_worker_owner(owner: address, sender: address) {
    assert!(owner == sender, E_NOT_NODE_OWNER);
}

fun assert_rental_client(client: address, sender: address) {
    assert!(client == sender, E_NOT_RENTAL_CLIENT);
}

fun assert_pending(status: u8) {
    assert!(status == RENTAL_PENDING, E_RENTAL_NOT_PENDING);
}

fun assert_pending_or_active(status: u8) {
    assert!(status == RENTAL_PENDING || status == RENTAL_ACTIVE, E_RENTAL_NOT_PENDING);
}

fun assert_no_active_rental(active_rental_id: u64) {
    assert!(active_rental_id == NO_ACTIVE_RENTAL, E_WORKER_HAS_ACTIVE_RENTAL);
}

// ── Test-only helpers ───────────────────────────────────────────────

#[test_only]
public fun new_registry_for_testing<T>(ctx: &mut TxContext): Registry<T> {
    new_registry<T>(ctx)
}

#[test_only]
public fun destroy_registry_for_testing<T>(registry: Registry<T>) {
    let Registry {
        id,
        next_node_id: _,
        next_rental_id: _,
        node_count: _,
        total_rewards_paid: _,
        active_worker_count: _,
        workers,
        rentals,
        room_proposals,
        next_role_proposal_id: _,
        role_proposals,
        role_map,
        coordinator_endpoint: _,
    } = registry;
    id.delete();
    workers.destroy_empty();
    rentals.destroy_empty();
    room_proposals.destroy_empty();
    role_proposals.destroy_empty();
    role_map.destroy_empty();
}

#[test_only]
public fun destroy_room_proposal_for_testing(proposal: RoomAssignmentProposal) {
    let RoomAssignmentProposal {
        rental_id: _,
        votes,
        vote_counts,
        total_votes: _,
        deadline_ms: _,
        finalized: _,
        assigned_node_id: _,
    } = proposal;
    votes.drop();
    vote_counts.drop();
}

#[test_only]
public fun destroy_role_proposal_for_testing(proposal: RoleProposal) {
    let RoleProposal {
        role: _,
        nominee_node_id: _,
        proposer: _,
        votes_for,
        vote_count: _,
        deadline_ms: _,
        finalized: _,
        passed: _,
    } = proposal;
    votes_for.drop();
}

#[test_only]
public fun remove_room_proposal_for_testing<T>(
    registry: &mut Registry<T>,
    rental_id: u64,
) {
    let proposal = table::remove(&mut registry.room_proposals, rental_id);
    destroy_room_proposal_for_testing(proposal);
}

#[test_only]
public fun remove_role_proposal_for_testing<T>(
    registry: &mut Registry<T>,
    proposal_id: u64,
) {
    let proposal = table::remove(&mut registry.role_proposals, proposal_id);
    destroy_role_proposal_for_testing(proposal);
}

#[test_only]
public fun remove_role_map_entry_for_testing<T>(
    registry: &mut Registry<T>,
    node_id: u64,
) {
    table::remove(&mut registry.role_map, node_id);
}

#[test_only]
public fun remove_rental_for_testing<T>(
    registry: &mut Registry<T>,
    rental_id: u64,
    ctx: &mut TxContext,
) {
    let removed = table::remove(&mut registry.rentals, rental_id);
    let RentalRecord {
        worker_node_id: _,
        client,
        worker_owner: _,
        room_name: _,
        capacity: _,
        payment,
        status: _,
        created_at_ms: _,
        completed_at_ms: _,
    } = removed;
    transfer::public_transfer(coin::from_balance(payment, ctx), client);
}

#[test_only]
public fun min_worker_stake_for_testing(): u64 {
    MIN_WORKER_STAKE
}

#[test_only]
public fun no_active_rental_for_testing(): u64 {
    NO_ACTIVE_RENTAL
}

#[test_only]
public fun assert_no_active_rental_for_testing(active_rental_id: u64) {
    assert_no_active_rental(active_rental_id);
}

#[test_only]
public fun rental_pending_for_testing(): u8 {
    RENTAL_PENDING
}

#[test_only]
public fun rental_awaiting_assignment_for_testing(): u8 {
    RENTAL_AWAITING_ASSIGNMENT
}

#[test_only]
public fun rental_active_for_testing(): u8 {
    RENTAL_ACTIVE
}

#[test_only]
public fun role_sfu_for_testing(): u8 {
    ROLE_SFU
}

#[test_only]
public fun role_coordinator_for_testing(): u8 {
    ROLE_COORDINATOR
}

#[test_only]
public fun role_router_for_testing(): u8 {
    ROLE_ROUTER
}

#[test_only]
public fun default_vote_deadline_ms_for_testing(): u64 {
    DEFAULT_VOTE_DEADLINE_MS
}

#[test_only]
public fun active_worker_count_for_testing<T>(registry: &Registry<T>): u64 {
    registry.active_worker_count
}

#[test_only]
public fun assert_rental_pending_for_testing(status: u8) {
    assert_pending(status);
}

#[test_only]
public fun validate_metadata_for_testing(metadata_uri: vector<u8>, metadata_hash: vector<u8>) {
    validate_metadata(&metadata_uri, &metadata_hash);
}

#[test_only]
public fun assert_node_present_for_testing(exists: bool) {
    assert_node_present(exists);
}

#[test_only]
public fun assert_worker_owner_for_testing(owner: address, sender: address) {
    assert_worker_owner(owner, sender);
}

#[test_only]
public fun assert_rental_client_for_testing(client: address, sender: address) {
    assert_rental_client(client, sender);
}

#[test_only]
public fun set_worker_active_for_testing<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    active: bool,
) {
    assert_node_exists(registry, node_id);
    let record = table::borrow_mut(&mut registry.workers, node_id);
    let was_active = record.active;
    record.active = active;
    record.rentable = active;
    if (was_active && !active) {
        registry.active_worker_count = registry.active_worker_count - 1;
    } else if (!was_active && active) {
        registry.active_worker_count = registry.active_worker_count + 1;
    };
}

#[test_only]
public fun remove_worker_for_testing<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);
    let record = table::borrow(&registry.workers, node_id);
    assert_no_active_rental(record.active_rental_id);
    let was_active = record.active;

    let removed = table::remove(&mut registry.workers, node_id);
    registry.node_count = registry.node_count - 1;
    if (was_active) {
        registry.active_worker_count = registry.active_worker_count - 1;
    };
    let WorkerRecord {
        owner,
        metadata_uri: _,
        metadata_hash: _,
        active: _,
        rentable: _,
        price_per_rental: _,
        stake,
        active_rental_id: _,
        created_at_ms: _,
        updated_at_ms: _,
    } = removed;

    transfer::public_transfer(coin::from_balance(stake, ctx), owner);
}
