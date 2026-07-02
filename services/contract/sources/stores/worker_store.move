module xaisen_contract::worker_store;

use std::vector;
use sui::balance::{Self, Balance};
use sui::coin::{Self, Coin};
use sui::table::{Self, Table};
use sui::tx_context::TxContext;

const E_EMPTY_METADATA_URI: u64 = 0;
const E_INVALID_METADATA_HASH: u64 = 1;
const E_NODE_NOT_FOUND: u64 = 2;
const E_NOT_NODE_OWNER: u64 = 3;
const E_INVALID_PRICE: u64 = 4;
const E_INSUFFICIENT_STAKE: u64 = 5;
const E_WORKER_HAS_ACTIVE_RENTAL: u64 = 12;
const E_WORKER_ACTIVE: u64 = 13;
const METADATA_HASH_LENGTH: u64 = 32;
const MIN_WORKER_STAKE: u64 = 1_000;
const NO_ACTIVE_RENTAL: u64 = 0;
const STALE_THRESHOLD_MS: u64 = 1_800_000; // 30 minutes
const SWEEP_CAP: u64 = 50; // max ids scanned per register_worker call

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

public struct WorkerStore<phantom T> has store {
    next_node_id: u64,
    node_count: u64,
    active_worker_count: u64,
    workers: Table<u64, WorkerRecord<T>>,
}

public(package) fun new<T>(ctx: &mut TxContext): WorkerStore<T> {
    WorkerStore { next_node_id: 1, node_count: 0, active_worker_count: 0, workers: table::new(ctx) }
}

public(package) fun destroy_empty<T>(store: WorkerStore<T>) {
    let WorkerStore { next_node_id: _, node_count: _, active_worker_count: _, workers } = store;
    workers.destroy_empty();
}

public(package) fun validate_metadata(uri: &vector<u8>, hash: &vector<u8>) {
    assert!(vector::length(uri) > 0, E_EMPTY_METADATA_URI);
    assert!(vector::length(hash) == METADATA_HASH_LENGTH, E_INVALID_METADATA_HASH);
}

public(package) fun assert_stake(stake_amount: u64) { assert!(stake_amount >= MIN_WORKER_STAKE, E_INSUFFICIENT_STAKE); }
public(package) fun assert_price(price_per_rental: u64) { assert!(price_per_rental > 0, E_INVALID_PRICE); }
public(package) fun assert_owner(owner: address, sender: address) { assert!(owner == sender, E_NOT_NODE_OWNER); }
public(package) fun assert_present(present: bool) { assert!(present, E_NODE_NOT_FOUND); }
public(package) fun assert_not_active(active: bool) { assert!(!active, E_WORKER_ACTIVE); }
public(package) fun assert_no_active_rental(active_rental_id: u64) {
    assert!(active_rental_id == NO_ACTIVE_RENTAL, E_WORKER_HAS_ACTIVE_RENTAL);
}

public(package) fun contains<T>(store: &WorkerStore<T>, node_id: u64): bool {
    table::contains(&store.workers, node_id)
}

public(package) fun assert_exists<T>(store: &WorkerStore<T>, node_id: u64) {
    assert_present(contains(store, node_id));
}

public(package) fun borrow<T>(store: &WorkerStore<T>, node_id: u64): &WorkerRecord<T> {
    table::borrow(&store.workers, node_id)
}

public(package) fun borrow_mut<T>(store: &mut WorkerStore<T>, node_id: u64): &mut WorkerRecord<T> {
    table::borrow_mut(&mut store.workers, node_id)
}

public(package) fun next_node_id<T>(store: &WorkerStore<T>): u64 { store.next_node_id }
public(package) fun node_count<T>(store: &WorkerStore<T>): u64 { store.node_count }
public(package) fun active_worker_count<T>(store: &WorkerStore<T>): u64 { store.active_worker_count }
public(package) fun no_active_rental(): u64 { NO_ACTIVE_RENTAL }
public(package) fun min_worker_stake(): u64 { MIN_WORKER_STAKE }

public(package) fun insert<T>(
    store: &mut WorkerStore<T>, owner: address, metadata_uri: vector<u8>, metadata_hash: vector<u8>,
    price_per_rental: u64, stake_coin: Coin<T>, timestamp_ms: u64,
): u64 {
    let node_id = store.next_node_id;
    store.next_node_id = node_id + 1;
    store.node_count = store.node_count + 1;
    store.active_worker_count = store.active_worker_count + 1;
    table::add(&mut store.workers, node_id, WorkerRecord {
        owner, metadata_uri, metadata_hash, active: true, rentable: true, price_per_rental,
        stake: coin::into_balance(stake_coin), active_rental_id: NO_ACTIVE_RENTAL,
        created_at_ms: timestamp_ms, updated_at_ms: timestamp_ms,
    });
    node_id
}

public(package) fun remove<T>(store: &mut WorkerStore<T>, node_id: u64): (address, Balance<T>) {
    let removed = table::remove(&mut store.workers, node_id);
    store.node_count = store.node_count - 1;
    let WorkerRecord {
        owner, metadata_uri: _, metadata_hash: _, active, rentable: _, price_per_rental: _,
        stake, active_rental_id: _, created_at_ms: _, updated_at_ms: _,
    } = removed;
    if (active) { store.active_worker_count = store.active_worker_count - 1; };
    (owner, stake)
}

public(package) fun set_metadata<T>(
    record: &mut WorkerRecord<T>, metadata_uri: vector<u8>, metadata_hash: vector<u8>, timestamp_ms: u64,
) {
    record.metadata_uri = metadata_uri;
    record.metadata_hash = metadata_hash;
    record.updated_at_ms = timestamp_ms;
}

public(package) fun set_price<T>(record: &mut WorkerRecord<T>, price_per_rental: u64) { record.price_per_rental = price_per_rental; }
public(package) fun touch<T>(record: &mut WorkerRecord<T>, timestamp_ms: u64) { record.updated_at_ms = timestamp_ms; }
public(package) fun set_active_rental_id<T>(record: &mut WorkerRecord<T>, rental_id: u64) { record.active_rental_id = rental_id; }

public(package) fun set_active<T>(store: &mut WorkerStore<T>, node_id: u64, active: bool, timestamp_ms: u64) {
    let record = table::borrow_mut(&mut store.workers, node_id);
    let was_active = record.active;
    record.active = active;
    record.rentable = active;
    record.updated_at_ms = timestamp_ms;
    if (was_active && !active) { store.active_worker_count = store.active_worker_count - 1; }
    else if (!was_active && active) { store.active_worker_count = store.active_worker_count + 1; };
}

public(package) fun sweep_stale<T>(store: &mut WorkerStore<T>, now_ms: u64): vector<u64> {
    let mut deactivated = vector[];
    let upper = if (store.next_node_id > SWEEP_CAP + 1) { SWEEP_CAP + 1 } else { store.next_node_id };
    let mut id = 1;
    while (id < upper) {
        if (table::contains(&store.workers, id)) {
            let record = table::borrow(&store.workers, id);
            let is_active = record.active;
            let updated_at_ms = record.updated_at_ms;
            if (is_active && now_ms > updated_at_ms && (now_ms - updated_at_ms) > STALE_THRESHOLD_MS) {
                set_active(store, id, false, now_ms);
                vector::push_back(&mut deactivated, id);
            };
        };
        id = id + 1;
    };
    deactivated
}

#[test_only]
public fun sweep_cap_for_testing(): u64 { SWEEP_CAP }

public(package) fun owner<T>(record: &WorkerRecord<T>): address { record.owner }
public(package) fun active<T>(record: &WorkerRecord<T>): bool { record.active }
public(package) fun rentable<T>(record: &WorkerRecord<T>): bool { record.rentable }
public(package) fun price_per_rental<T>(record: &WorkerRecord<T>): u64 { record.price_per_rental }
public(package) fun stake_value<T>(record: &WorkerRecord<T>): u64 { balance::value(&record.stake) }
public(package) fun active_rental_id<T>(record: &WorkerRecord<T>): u64 { record.active_rental_id }
public(package) fun metadata_uri<T>(record: &WorkerRecord<T>): vector<u8> { record.metadata_uri }
public(package) fun metadata_hash<T>(record: &WorkerRecord<T>): vector<u8> { record.metadata_hash }
public(package) fun created_at_ms<T>(record: &WorkerRecord<T>): u64 { record.created_at_ms }
public(package) fun updated_at_ms<T>(record: &WorkerRecord<T>): u64 { record.updated_at_ms }

#[test_only]
public fun set_active_for_testing<T>(store: &mut WorkerStore<T>, node_id: u64, active: bool) {
    let record = table::borrow_mut(&mut store.workers, node_id);
    let was_active = record.active;
    record.active = active;
    record.rentable = active;
    if (was_active && !active) { store.active_worker_count = store.active_worker_count - 1; }
    else if (!was_active && active) { store.active_worker_count = store.active_worker_count + 1; };
}
