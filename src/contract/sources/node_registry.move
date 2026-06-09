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

const METADATA_HASH_LENGTH: u64 = 32;
const MIN_WORKER_STAKE: u64 = 1_000;
const NO_ACTIVE_RENTAL: u64 = 0;
const RENTAL_PENDING: u8 = 0;

public struct Registry<phantom T> has key {
    id: UID,
    next_node_id: u64,
    next_rental_id: u64,
    node_count: u64,
    total_rewards_paid: u64,
    workers: Table<u64, WorkerRecord<T>>,
    rentals: Table<u64, RentalRecord<T>>,
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
    payment: Balance<T>,
    status: u8,
    created_at_ms: u64,
    completed_at_ms: u64,
}

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

    record.active = active;
    record.rentable = active;
    record.updated_at_ms = timestamp_ms;

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
    payment_coin: Coin<T>,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert_node_exists(registry, node_id);
    assert!(vector::length(&room_name) > 0, E_EMPTY_ROOM_NAME);

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
    assert_pending(rental.status);

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

public fun node_exists<T>(registry: &Registry<T>, node_id: u64): bool {
    table::contains(&registry.workers, node_id)
}

public fun node_count<T>(registry: &Registry<T>): u64 {
    registry.node_count
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

public fun rental_payment_amount<T>(registry: &Registry<T>, rental_id: u64): u64 {
    assert_rental_exists(registry, rental_id);
    balance::value(&table::borrow(&registry.rentals, rental_id).payment)
}

public fun total_rewards_paid<T>(registry: &Registry<T>): u64 {
    registry.total_rewards_paid
}

fun new_registry<T>(ctx: &mut TxContext): Registry<T> {
    Registry {
        id: object::new(ctx),
        next_node_id: 1,
        next_rental_id: 1,
        node_count: 0,
        total_rewards_paid: 0,
        workers: table::new(ctx),
        rentals: table::new(ctx),
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

fun assert_no_active_rental(active_rental_id: u64) {
    assert!(active_rental_id == NO_ACTIVE_RENTAL, E_WORKER_HAS_ACTIVE_RENTAL);
}

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
        workers,
        rentals,
    } = registry;
    id.delete();
    workers.destroy_empty();
    rentals.destroy_empty();
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
    record.active = active;
    record.rentable = active;
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

    transfer::public_transfer(coin::from_balance(stake, ctx), owner);
}
