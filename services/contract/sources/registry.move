module xaisen_contract::registry;

use sui::object::UID;
use sui::transfer;
use sui::tx_context::TxContext;
use xaisen_contract::rental_store::{Self, RentalStore};
use xaisen_contract::role_vote_store::{Self, RoleVoteStore};
use xaisen_contract::room_vote_store::{Self, RoomVoteStore};
use xaisen_contract::worker_store::{Self, WorkerStore};

public struct Registry<phantom T> has key {
    id: UID,
    workers: WorkerStore<T>,
    rentals: RentalStore<T>,
    room_votes: RoomVoteStore,
    role_votes: RoleVoteStore,
    coordinator_endpoint: vector<u8>,
}

fun new_registry<T>(ctx: &mut TxContext): Registry<T> {
    Registry {
        id: sui::object::new(ctx),
        workers: worker_store::new(ctx),
        rentals: rental_store::new(ctx),
        room_votes: room_vote_store::new(ctx),
        role_votes: role_vote_store::new(ctx),
        coordinator_endpoint: vector[],
    }
}

public entry fun create_registry<T>(ctx: &mut TxContext) {
    transfer::share_object(new_registry<T>(ctx));
}

public entry fun set_coordinator_endpoint<T>(registry: &mut Registry<T>, endpoint: vector<u8>, _ctx: &mut TxContext) {
    registry.coordinator_endpoint = endpoint;
}

public fun coordinator_endpoint<T>(registry: &Registry<T>): vector<u8> { registry.coordinator_endpoint }

public(package) fun uid<T>(registry: &Registry<T>): &UID { &registry.id }
public(package) fun uid_mut<T>(registry: &mut Registry<T>): &mut UID { &mut registry.id }

public(package) fun workers<T>(registry: &Registry<T>): &WorkerStore<T> { &registry.workers }
public(package) fun workers_mut<T>(registry: &mut Registry<T>): &mut WorkerStore<T> { &mut registry.workers }
public(package) fun rentals<T>(registry: &Registry<T>): &RentalStore<T> { &registry.rentals }
public(package) fun rentals_mut<T>(registry: &mut Registry<T>): &mut RentalStore<T> { &mut registry.rentals }
public(package) fun room_votes<T>(registry: &Registry<T>): &RoomVoteStore { &registry.room_votes }
public(package) fun room_votes_mut<T>(registry: &mut Registry<T>): &mut RoomVoteStore { &mut registry.room_votes }
public(package) fun role_votes<T>(registry: &Registry<T>): &RoleVoteStore { &registry.role_votes }
public(package) fun role_votes_mut<T>(registry: &mut Registry<T>): &mut RoleVoteStore { &mut registry.role_votes }

#[test_only]
public fun new_registry_for_testing<T>(ctx: &mut TxContext): Registry<T> { new_registry<T>(ctx) }

#[test_only]
public fun destroy_registry_for_testing<T>(registry: Registry<T>) {
    let Registry { id, workers, rentals, room_votes, role_votes, coordinator_endpoint: _ } = registry;
    id.delete();
    worker_store::destroy_empty(workers);
    rental_store::destroy_empty(rentals);
    room_vote_store::destroy_empty(room_votes);
    role_vote_store::destroy_empty(role_votes);
}
