#[allow(lint(public_entry))]
module xaisen_contract::workers;

use std::vector;
use sui::clock::{Self, Clock};
use sui::coin::{Self, Coin};
use sui::transfer;
use sui::tx_context::{Self, TxContext};
use xaisen_contract::registry::Registry;
use xaisen_contract::worker_events;
use xaisen_contract::worker_store;

public entry fun register_worker<T>(
    registry: &mut Registry<T>,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    price_per_rental: u64,
    stake_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    worker_store::validate_metadata(&metadata_uri, &metadata_hash);
    worker_store::assert_price(price_per_rental);

    let stake_amount = coin::value(&stake_coin);
    worker_store::assert_stake(stake_amount);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let metadata_uri_for_event = copy metadata_uri;
    let metadata_hash_for_event = copy metadata_hash;

    let node_id = worker_store::insert(
        registry.workers_mut(), sender, metadata_uri, metadata_hash, price_per_rental, stake_coin, timestamp_ms,
    );

    let deactivated_ids = worker_store::sweep_stale(registry.workers_mut(), timestamp_ms);
    let mut i = 0;
    while (i < vector::length(&deactivated_ids)) {
        let stale_id = *vector::borrow(&deactivated_ids, i);
        let stale_owner = worker_store::owner(worker_store::borrow(registry.workers(), stale_id));
        worker_events::emit_worker_auto_deactivated(stale_id, stale_owner, timestamp_ms);
        i = i + 1;
    };

    worker_events::emit_worker_registered(
        node_id, sender, metadata_uri_for_event, metadata_hash_for_event, price_per_rental, stake_amount, timestamp_ms,
    );
}

public entry fun update_worker_metadata<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    worker_store::validate_metadata(&metadata_uri, &metadata_hash);
    worker_store::assert_exists(registry.workers(), node_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let metadata_uri_for_event = copy metadata_uri;
    let metadata_hash_for_event = copy metadata_hash;

    let record = worker_store::borrow_mut(registry.workers_mut(), node_id);
    worker_store::assert_owner(worker_store::owner(record), sender);
    worker_store::set_metadata(record, metadata_uri, metadata_hash, timestamp_ms);

    worker_events::emit_worker_metadata_updated(
        node_id, sender, metadata_uri_for_event, metadata_hash_for_event, timestamp_ms,
    );
}

public entry fun set_worker_active<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    active: bool,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    worker_store::assert_exists(registry.workers(), node_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let record = worker_store::borrow(registry.workers(), node_id);
    worker_store::assert_owner(worker_store::owner(record), sender);

    worker_store::set_active(registry.workers_mut(), node_id, active, timestamp_ms);

    worker_events::emit_worker_status_updated(node_id, sender, active, timestamp_ms);
}

public entry fun heartbeat_worker<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    worker_store::assert_exists(registry.workers(), node_id);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);
    let record = worker_store::borrow_mut(registry.workers_mut(), node_id);

    worker_store::assert_owner(worker_store::owner(record), sender);
    worker_store::touch(record, timestamp_ms);

    worker_events::emit_worker_heartbeat(node_id, timestamp_ms);
}

public entry fun update_worker_price<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    price_per_rental: u64,
    ctx: &mut TxContext,
) {
    worker_store::assert_exists(registry.workers(), node_id);
    worker_store::assert_price(price_per_rental);

    let sender = tx_context::sender(ctx);
    let record = worker_store::borrow_mut(registry.workers_mut(), node_id);
    worker_store::assert_owner(worker_store::owner(record), sender);
    worker_store::set_price(record, price_per_rental);

    worker_events::emit_worker_price_updated(node_id, sender, price_per_rental);
}

public entry fun unregister_worker<T>(registry: &mut Registry<T>, node_id: u64, ctx: &mut TxContext) {
    worker_store::assert_exists(registry.workers(), node_id);

    let sender = tx_context::sender(ctx);
    let record = worker_store::borrow(registry.workers(), node_id);
    worker_store::assert_owner(worker_store::owner(record), sender);
    worker_store::assert_no_active_rental(worker_store::active_rental_id(record));

    let (owner, stake) = worker_store::remove(registry.workers_mut(), node_id);
    transfer::public_transfer(coin::from_balance(stake, ctx), owner);
    worker_events::emit_worker_unregistered(node_id, owner);
}

public entry fun withdraw_worker_stake<T>(registry: &mut Registry<T>, node_id: u64, ctx: &mut TxContext) {
    worker_store::assert_exists(registry.workers(), node_id);

    let sender = tx_context::sender(ctx);
    let record = worker_store::borrow(registry.workers(), node_id);
    worker_store::assert_owner(worker_store::owner(record), sender);
    worker_store::assert_not_active(worker_store::active(record));
    worker_store::assert_no_active_rental(worker_store::active_rental_id(record));

    let (owner, stake) = worker_store::remove(registry.workers_mut(), node_id);
    let stake_amount = sui::balance::value(&stake);
    transfer::public_transfer(coin::from_balance(stake, ctx), owner);
    worker_events::emit_worker_stake_withdrawn(node_id, owner, stake_amount);
}
