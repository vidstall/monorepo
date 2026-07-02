module xaisen_contract::rental_store;

use std::vector;
use sui::balance::{Self, Balance};
use sui::coin::{Self, Coin};
use sui::table::{Self, Table};
use sui::tx_context::TxContext;

const E_INVALID_PAYMENT_AMOUNT: u64 = 7;
const E_EMPTY_ROOM_NAME: u64 = 8;
const E_RENTAL_NOT_FOUND: u64 = 9;
const E_NOT_RENTAL_CLIENT: u64 = 10;
const E_RENTAL_NOT_PENDING: u64 = 11;
const E_INVALID_CAPACITY: u64 = 14;

const RENTAL_PENDING: u8 = 0;
const RENTAL_AWAITING_ASSIGNMENT: u8 = 2;
const RENTAL_ACTIVE: u8 = 3;

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

public struct RentalStore<phantom T> has store {
    next_rental_id: u64,
    total_rewards_paid: u64,
    rentals: Table<u64, RentalRecord<T>>,
}

public(package) fun new<T>(ctx: &mut TxContext): RentalStore<T> {
    RentalStore { next_rental_id: 1, total_rewards_paid: 0, rentals: table::new(ctx) }
}

public(package) fun destroy_empty<T>(store: RentalStore<T>) {
    let RentalStore { next_rental_id: _, total_rewards_paid: _, rentals } = store;
    rentals.destroy_empty();
}

public(package) fun assert_room_name(room_name: &vector<u8>) { assert!(vector::length(room_name) > 0, E_EMPTY_ROOM_NAME); }
public(package) fun assert_capacity(capacity: u64) { assert!(capacity > 0, E_INVALID_CAPACITY); }
public(package) fun assert_payment_amount(amount: u64, expected: u64) { assert!(amount == expected, E_INVALID_PAYMENT_AMOUNT); }
public(package) fun assert_client(client: address, sender: address) { assert!(client == sender, E_NOT_RENTAL_CLIENT); }
public(package) fun assert_pending(status: u8) { assert!(status == RENTAL_PENDING, E_RENTAL_NOT_PENDING); }
public(package) fun assert_awaiting_assignment(status: u8) { assert!(status == RENTAL_AWAITING_ASSIGNMENT, E_RENTAL_NOT_PENDING); }
public(package) fun assert_pending_or_active(status: u8) {
    assert!(status == RENTAL_PENDING || status == RENTAL_ACTIVE, E_RENTAL_NOT_PENDING);
}

public(package) fun contains<T>(store: &RentalStore<T>, rental_id: u64): bool { table::contains(&store.rentals, rental_id) }
public(package) fun assert_exists<T>(store: &RentalStore<T>, rental_id: u64) { assert!(contains(store, rental_id), E_RENTAL_NOT_FOUND); }
public(package) fun borrow<T>(store: &RentalStore<T>, rental_id: u64): &RentalRecord<T> { table::borrow(&store.rentals, rental_id) }
public(package) fun borrow_mut<T>(store: &mut RentalStore<T>, rental_id: u64): &mut RentalRecord<T> {
    table::borrow_mut(&mut store.rentals, rental_id)
}

public(package) fun total_rewards_paid<T>(store: &RentalStore<T>): u64 { store.total_rewards_paid }
public(package) fun add_rewards_paid<T>(store: &mut RentalStore<T>, amount: u64) {
    store.total_rewards_paid = store.total_rewards_paid + amount;
}

public(package) fun insert<T>(
    store: &mut RentalStore<T>, worker_node_id: u64, client: address, worker_owner: address,
    room_name: vector<u8>, capacity: u64, payment_coin: Coin<T>, status: u8, timestamp_ms: u64,
): u64 {
    let rental_id = store.next_rental_id;
    store.next_rental_id = rental_id + 1;
    table::add(&mut store.rentals, rental_id, RentalRecord {
        worker_node_id, client, worker_owner, room_name, capacity,
        payment: coin::into_balance(payment_coin), status,
        created_at_ms: timestamp_ms, completed_at_ms: 0,
    });
    rental_id
}

public(package) fun remove<T>(store: &mut RentalStore<T>, rental_id: u64): (u64, address, address, Balance<T>) {
    let removed = table::remove(&mut store.rentals, rental_id);
    let RentalRecord {
        worker_node_id, client, worker_owner, room_name: _, capacity: _,
        payment, status: _, created_at_ms: _, completed_at_ms: _,
    } = removed;
    (worker_node_id, client, worker_owner, payment)
}

public(package) fun set_status<T>(record: &mut RentalRecord<T>, status: u8) { record.status = status; }
public(package) fun set_worker_node_id<T>(record: &mut RentalRecord<T>, worker_node_id: u64) { record.worker_node_id = worker_node_id; }
public(package) fun set_worker_owner<T>(record: &mut RentalRecord<T>, worker_owner: address) { record.worker_owner = worker_owner; }

public(package) fun worker_node_id<T>(record: &RentalRecord<T>): u64 { record.worker_node_id }
public(package) fun client<T>(record: &RentalRecord<T>): address { record.client }
public(package) fun worker_owner<T>(record: &RentalRecord<T>): address { record.worker_owner }
public(package) fun room_name<T>(record: &RentalRecord<T>): vector<u8> { record.room_name }
public(package) fun capacity<T>(record: &RentalRecord<T>): u64 { record.capacity }
public(package) fun payment_amount<T>(record: &RentalRecord<T>): u64 { balance::value(&record.payment) }
public(package) fun status<T>(record: &RentalRecord<T>): u8 { record.status }

public(package) fun rental_pending(): u8 { RENTAL_PENDING }
public(package) fun rental_awaiting_assignment(): u8 { RENTAL_AWAITING_ASSIGNMENT }
public(package) fun rental_active(): u8 { RENTAL_ACTIVE }

public fun rental_exists<T>(store: &RentalStore<T>, rental_id: u64): bool { contains(store, rental_id) }
public fun rental_status<T>(store: &RentalStore<T>, rental_id: u64): u8 {
    assert_exists(store, rental_id);
    status(borrow(store, rental_id))
}
public fun rental_client<T>(store: &RentalStore<T>, rental_id: u64): address {
    assert_exists(store, rental_id);
    client(borrow(store, rental_id))
}
public fun rental_worker_node_id<T>(store: &RentalStore<T>, rental_id: u64): u64 {
    assert_exists(store, rental_id);
    worker_node_id(borrow(store, rental_id))
}
public fun rental_room_name<T>(store: &RentalStore<T>, rental_id: u64): vector<u8> {
    assert_exists(store, rental_id);
    room_name(borrow(store, rental_id))
}
public fun rental_capacity<T>(store: &RentalStore<T>, rental_id: u64): u64 {
    assert_exists(store, rental_id);
    capacity(borrow(store, rental_id))
}
public fun rental_payment_amount<T>(store: &RentalStore<T>, rental_id: u64): u64 {
    assert_exists(store, rental_id);
    payment_amount(borrow(store, rental_id))
}

#[test_only]
public fun rental_pending_for_testing(): u8 { RENTAL_PENDING }
#[test_only]
public fun rental_awaiting_assignment_for_testing(): u8 { RENTAL_AWAITING_ASSIGNMENT }
#[test_only]
public fun rental_active_for_testing(): u8 { RENTAL_ACTIVE }
#[test_only]
public fun assert_rental_pending_for_testing(status: u8) { assert_pending(status); }
#[test_only]
public fun assert_rental_client_for_testing(client: address, sender: address) { assert_client(client, sender); }

#[test_only]
public fun remove_rental_for_testing<T>(store: &mut RentalStore<T>, rental_id: u64, ctx: &mut TxContext) {
    let (_, client, _, payment) = remove(store, rental_id);
    sui::transfer::public_transfer(coin::from_balance(payment, ctx), client);
}
