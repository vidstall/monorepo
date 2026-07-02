module xaisen_contract::worker_accessors;

use xaisen_contract::worker_store::{Self, WorkerStore};

public fun node_exists<T>(store: &WorkerStore<T>, node_id: u64): bool {
    worker_store::contains(store, node_id)
}

public fun node_count<T>(store: &WorkerStore<T>): u64 { worker_store::node_count(store) }
public fun next_node_id<T>(store: &WorkerStore<T>): u64 { worker_store::next_node_id(store) }
public fun active_worker_count<T>(store: &WorkerStore<T>): u64 { worker_store::active_worker_count(store) }

public fun worker_owner<T>(store: &WorkerStore<T>, node_id: u64): address {
    worker_store::assert_exists(store, node_id);
    worker_store::owner(worker_store::borrow(store, node_id))
}

public fun worker_active<T>(store: &WorkerStore<T>, node_id: u64): bool {
    worker_store::assert_exists(store, node_id);
    worker_store::active(worker_store::borrow(store, node_id))
}

public fun worker_rentable<T>(store: &WorkerStore<T>, node_id: u64): bool {
    worker_store::assert_exists(store, node_id);
    worker_store::rentable(worker_store::borrow(store, node_id))
}

public fun worker_price_per_rental<T>(store: &WorkerStore<T>, node_id: u64): u64 {
    worker_store::assert_exists(store, node_id);
    worker_store::price_per_rental(worker_store::borrow(store, node_id))
}

public fun worker_stake_value<T>(store: &WorkerStore<T>, node_id: u64): u64 {
    worker_store::assert_exists(store, node_id);
    worker_store::stake_value(worker_store::borrow(store, node_id))
}

public fun worker_active_rental_id<T>(store: &WorkerStore<T>, node_id: u64): u64 {
    worker_store::assert_exists(store, node_id);
    worker_store::active_rental_id(worker_store::borrow(store, node_id))
}

public fun worker_metadata_uri<T>(store: &WorkerStore<T>, node_id: u64): vector<u8> {
    worker_store::assert_exists(store, node_id);
    worker_store::metadata_uri(worker_store::borrow(store, node_id))
}

public fun worker_metadata_hash<T>(store: &WorkerStore<T>, node_id: u64): vector<u8> {
    worker_store::assert_exists(store, node_id);
    worker_store::metadata_hash(worker_store::borrow(store, node_id))
}

public fun worker_created_at_ms<T>(store: &WorkerStore<T>, node_id: u64): u64 {
    worker_store::assert_exists(store, node_id);
    worker_store::created_at_ms(worker_store::borrow(store, node_id))
}

public fun worker_updated_at_ms<T>(store: &WorkerStore<T>, node_id: u64): u64 {
    worker_store::assert_exists(store, node_id);
    worker_store::updated_at_ms(worker_store::borrow(store, node_id))
}

#[test_only]
public fun min_worker_stake_for_testing(): u64 { worker_store::min_worker_stake() }
#[test_only]
public fun no_active_rental_for_testing(): u64 { worker_store::no_active_rental() }
#[test_only]
public fun assert_no_active_rental_for_testing(active_rental_id: u64) { worker_store::assert_no_active_rental(active_rental_id); }
#[test_only]
public fun validate_metadata_for_testing(metadata_uri: vector<u8>, metadata_hash: vector<u8>) {
    worker_store::validate_metadata(&metadata_uri, &metadata_hash);
}
#[test_only]
public fun assert_node_present_for_testing(present: bool) { worker_store::assert_present(present); }
#[test_only]
public fun assert_worker_owner_for_testing(owner: address, sender: address) { worker_store::assert_owner(owner, sender); }

#[test_only]
public fun active_worker_count_for_testing<T>(store: &WorkerStore<T>): u64 { worker_store::active_worker_count(store) }

#[test_only]
public fun set_worker_active_for_testing<T>(store: &mut WorkerStore<T>, node_id: u64, active: bool) {
    worker_store::assert_exists(store, node_id);
    worker_store::set_active_for_testing(store, node_id, active);
}

#[test_only]
public fun remove_worker_for_testing<T>(store: &mut WorkerStore<T>, node_id: u64, ctx: &mut sui::tx_context::TxContext) {
    worker_store::assert_exists(store, node_id);
    let record = worker_store::borrow(store, node_id);
    worker_store::assert_no_active_rental(worker_store::active_rental_id(record));
    let (owner, stake) = worker_store::remove(store, node_id);
    sui::transfer::public_transfer(sui::coin::from_balance(stake, ctx), owner);
}
