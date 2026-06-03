#[allow(lint(public_entry))]
module xaisen_contract::node_registry;

use std::vector;
use sui::clock::{Self, Clock};
use sui::event;
use sui::object::{Self, UID};
use sui::table::{Self, Table};
use sui::transfer;
use sui::tx_context::{Self, TxContext};

const E_EMPTY_METADATA_URI: u64 = 0;
const E_INVALID_METADATA_HASH: u64 = 1;
const E_NODE_NOT_FOUND: u64 = 2;
const E_NOT_NODE_OWNER: u64 = 3;
const METADATA_HASH_LENGTH: u64 = 32;

public struct Registry has key {
    id: UID,
    next_node_id: u64,
    node_count: u64,
    workers: Table<u64, WorkerRecord>,
}

public struct WorkerRecord has store, drop {
    owner: address,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    active: bool,
    created_at_ms: u64,
    updated_at_ms: u64,
}

public struct WorkerRegistered has copy, drop {
    node_id: u64,
    owner: address,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
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

fun init(ctx: &mut TxContext) {
    transfer::share_object(new_registry(ctx));
}

public entry fun register_worker(
    registry: &mut Registry,
    metadata_uri: vector<u8>,
    metadata_hash: vector<u8>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    validate_metadata(&metadata_uri, &metadata_hash);

    let node_id = registry.next_node_id;
    let owner = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);

    table::add(
        &mut registry.workers,
        node_id,
        WorkerRecord {
            owner,
            metadata_uri,
            metadata_hash,
            active: true,
            created_at_ms: timestamp_ms,
            updated_at_ms: timestamp_ms,
        },
    );

    registry.next_node_id = node_id + 1;
    registry.node_count = registry.node_count + 1;

    let record = table::borrow(&registry.workers, node_id);
    event::emit(WorkerRegistered {
        node_id,
        owner,
        metadata_uri: record.metadata_uri,
        metadata_hash: record.metadata_hash,
        timestamp_ms,
    });
}

public entry fun update_worker_metadata(
    registry: &mut Registry,
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

public entry fun set_worker_active(
    registry: &mut Registry,
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

    record.active = active;
    record.updated_at_ms = timestamp_ms;

    event::emit(WorkerStatusUpdated {
        node_id,
        owner: sender,
        active,
        timestamp_ms,
    });
}

public entry fun unregister_worker(
    registry: &mut Registry,
    node_id: u64,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);

    let sender = tx_context::sender(ctx);
    let record = table::borrow(&registry.workers, node_id);
    assert_worker_owner(record.owner, sender);

    let removed = table::remove(&mut registry.workers, node_id);
    registry.node_count = registry.node_count - 1;

    event::emit(WorkerUnregistered {
        node_id,
        owner: removed.owner,
    });
}

public fun node_exists(registry: &Registry, node_id: u64): bool {
    table::contains(&registry.workers, node_id)
}

public fun node_count(registry: &Registry): u64 {
    registry.node_count
}

public fun worker_owner(registry: &Registry, node_id: u64): address {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).owner
}

public fun worker_active(registry: &Registry, node_id: u64): bool {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).active
}

public fun worker_metadata_uri(registry: &Registry, node_id: u64): vector<u8> {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).metadata_uri
}

public fun worker_metadata_hash(registry: &Registry, node_id: u64): vector<u8> {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).metadata_hash
}

public fun worker_created_at_ms(registry: &Registry, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).created_at_ms
}

public fun worker_updated_at_ms(registry: &Registry, node_id: u64): u64 {
    assert_node_exists(registry, node_id);
    table::borrow(&registry.workers, node_id).updated_at_ms
}

fun new_registry(ctx: &mut TxContext): Registry {
    Registry {
        id: object::new(ctx),
        next_node_id: 1,
        node_count: 0,
        workers: table::new(ctx),
    }
}

fun validate_metadata(metadata_uri: &vector<u8>, metadata_hash: &vector<u8>) {
    assert!(vector::length(metadata_uri) > 0, E_EMPTY_METADATA_URI);
    assert!(vector::length(metadata_hash) == METADATA_HASH_LENGTH, E_INVALID_METADATA_HASH);
}

fun assert_node_exists(registry: &Registry, node_id: u64) {
    assert_node_present(node_exists(registry, node_id));
}

fun assert_node_present(exists: bool) {
    assert!(exists, E_NODE_NOT_FOUND);
}

fun assert_worker_owner(owner: address, sender: address) {
    assert!(owner == sender, E_NOT_NODE_OWNER);
}

#[test_only]
public fun new_registry_for_testing(ctx: &mut TxContext): Registry {
    new_registry(ctx)
}

#[test_only]
public fun destroy_registry_for_testing(registry: Registry) {
    let Registry {
        id,
        next_node_id: _,
        node_count,
        workers,
    } = registry;

    assert!(node_count == 0, E_NODE_NOT_FOUND);
    table::destroy_empty(workers);
    object::delete(id);
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
