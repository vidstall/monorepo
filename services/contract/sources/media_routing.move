#[allow(lint(public_entry))]
module xaisen_contract::media_routing;

use sui::clock::{Self, Clock};
use sui::tx_context::{Self, TxContext};
use xaisen_contract::governance_events;
use xaisen_contract::media_events;
use xaisen_contract::media_store;
use xaisen_contract::registry::Registry;
use xaisen_contract::rental_store;
use xaisen_contract::role_vote_store;
use xaisen_contract::room_vote_store;
use xaisen_contract::worker_store;

const E_NOT_ACTIVE_WORKER: u64 = 15;
const E_INVALID_PAYMENT_AMOUNT: u64 = 7;

public entry fun set_node_profile<T>(
    registry: &mut Registry<T>,
    node_id: u64,
    x25519_public_key: vector<u8>,
    broker_endpoint: vector<u8>,
    region: vector<u8>,
    cluster_id: u64,
    ctx: &mut TxContext,
) {
    worker_store::assert_exists(registry.workers(), node_id);
    let sender = tx_context::sender(ctx);
    worker_store::assert_owner(worker_store::owner(worker_store::borrow(registry.workers(), node_id)), sender);

    media_store::set_node_profile(registry.uid_mut(), node_id, x25519_public_key, broker_endpoint, region, cluster_id);
    media_events::emit_node_profile_updated(node_id, cluster_id);
}

public entry fun register_media_cluster<T>(
    registry: &mut Registry<T>,
    owner_node_id: u64,
    client_url: vector<u8>,
    price_per_rental: u64,
    ctx: &mut TxContext,
) {
    assert_node_role(registry, owner_node_id, role_vote_store::role_sfu());
    let sender = tx_context::sender(ctx);
    worker_store::assert_owner(worker_store::owner(worker_store::borrow(registry.workers(), owner_node_id)), sender);

    let cluster_id = media_store::register_media_cluster(registry.uid_mut(), owner_node_id, sender, client_url, price_per_rental);
    media_events::emit_media_cluster_registered(cluster_id, owner_node_id, sender, price_per_rental);
}

public entry fun add_media_cluster_member<T>(registry: &mut Registry<T>, cluster_id: u64, node_id: u64, ctx: &mut TxContext) {
    assert_node_role(registry, node_id, role_vote_store::role_sfu());
    let owner_node_id = media_store::cluster_owner_node_id(media_store::borrow_cluster(registry.uid(), cluster_id));
    let sender = tx_context::sender(ctx);
    worker_store::assert_owner(worker_store::owner(worker_store::borrow(registry.workers(), owner_node_id)), sender);
    media_store::add_cluster_member(registry.uid_mut(), cluster_id, node_id);
}

public entry fun set_media_cluster_active<T>(registry: &mut Registry<T>, cluster_id: u64, active: bool, ctx: &mut TxContext) {
    let owner_node_id = media_store::cluster_owner_node_id(media_store::borrow_cluster(registry.uid(), cluster_id));
    worker_store::assert_owner(
        worker_store::owner(worker_store::borrow(registry.workers(), owner_node_id)), tx_context::sender(ctx),
    );
    media_store::set_cluster_active(media_store::borrow_cluster_mut(registry.uid_mut(), cluster_id), active);
}

public entry fun update_cluster_price<T>(registry: &mut Registry<T>, cluster_id: u64, price_per_rental: u64, ctx: &mut TxContext) {
    let owner_node_id = media_store::cluster_owner_node_id(media_store::borrow_cluster(registry.uid(), cluster_id));
    worker_store::assert_owner(
        worker_store::owner(worker_store::borrow(registry.workers(), owner_node_id)), tx_context::sender(ctx),
    );
    media_store::set_cluster_price(media_store::borrow_cluster_mut(registry.uid_mut(), cluster_id), price_per_rental);
    media_events::emit_cluster_price_updated(cluster_id, price_per_rental);
}

public entry fun assign_routed_order<T>(
    registry: &mut Registry<T>,
    router_node_id: u64,
    media_node_id: u64,
    cluster_id: u64,
    rental_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    assert_router_and_media(registry, router_node_id, media_node_id, cluster_id, tx_context::sender(ctx));
    rental_store::assert_exists(registry.rentals(), rental_id);

    let already_assigned = media_store::has_routed_assignment(registry.uid(), rental_id);
    if (!already_assigned) {
        let rental = rental_store::borrow(registry.rentals(), rental_id);
        rental_store::assert_awaiting_assignment(rental_store::status(rental));
        let payment_amount = rental_store::payment_amount(rental);
        let cluster_price = media_store::cluster_price(media_store::borrow_cluster(registry.uid(), cluster_id));
        assert!(payment_amount == cluster_price, E_INVALID_PAYMENT_AMOUNT);
        if (room_vote_store::contains(registry.room_votes(), rental_id)) {
            let proposal = room_vote_store::remove(registry.room_votes_mut(), rental_id);
            room_vote_store::drop(proposal);
        };
    };
    let revision = media_store::upsert_routed_assignment(registry.uid_mut(), rental_id, router_node_id, media_node_id, cluster_id);

    let treasury = media_store::cluster_treasury(media_store::borrow_cluster(registry.uid(), cluster_id));
    let rental = rental_store::borrow_mut(registry.rentals_mut(), rental_id);
    rental_store::set_worker_node_id(rental, media_node_id);
    rental_store::set_worker_owner(rental, treasury);
    rental_store::set_status(rental, rental_store::rental_active());

    media_events::emit_routed_assignment_updated(rental_id, router_node_id, media_node_id, cluster_id, revision);
    governance_events::emit_room_assignment_finalized(rental_id, media_node_id, clock::timestamp_ms(clock));
}

fun assert_router_and_media<T>(registry: &Registry<T>, router_node_id: u64, media_node_id: u64, cluster_id: u64, sender: address) {
    assert_node_role(registry, router_node_id, role_vote_store::role_router());
    assert_node_role(registry, media_node_id, role_vote_store::role_sfu());
    let router = worker_store::borrow(registry.workers(), router_node_id);
    worker_store::assert_owner(worker_store::owner(router), sender);
    assert!(worker_store::active(router), E_NOT_ACTIVE_WORKER);
    assert!(worker_store::active(worker_store::borrow(registry.workers(), media_node_id)), E_NOT_ACTIVE_WORKER);
    let cluster = media_store::borrow_cluster(registry.uid(), cluster_id);
    media_store::assert_cluster_active(cluster);
    media_store::assert_cluster_member(registry.uid(), cluster_id, media_node_id);
}

fun assert_node_role<T>(registry: &Registry<T>, node_id: u64, role: u8) {
    worker_store::assert_exists(registry.workers(), node_id);
    role_vote_store::assert_has_role(registry.role_votes(), node_id, role);
}

public fun has_node_profile<T>(registry: &Registry<T>, node_id: u64): bool { media_store::has_node_profile(registry.uid(), node_id) }
public fun node_x25519_public_key<T>(registry: &Registry<T>, node_id: u64): vector<u8> { media_store::node_x25519_public_key(registry.uid(), node_id) }
public fun node_broker_endpoint<T>(registry: &Registry<T>, node_id: u64): vector<u8> { media_store::node_broker_endpoint(registry.uid(), node_id) }
public fun node_region<T>(registry: &Registry<T>, node_id: u64): vector<u8> { media_store::node_region(registry.uid(), node_id) }
public fun node_cluster_id<T>(registry: &Registry<T>, node_id: u64): u64 { media_store::node_cluster_id(registry.uid(), node_id) }

public fun media_cluster_exists<T>(registry: &Registry<T>, cluster_id: u64): bool { media_store::media_cluster_exists(registry.uid(), cluster_id) }
public fun media_cluster_client_url<T>(registry: &Registry<T>, cluster_id: u64): vector<u8> {
    media_store::cluster_client_url(media_store::borrow_cluster(registry.uid(), cluster_id))
}
public fun media_cluster_price<T>(registry: &Registry<T>, cluster_id: u64): u64 {
    media_store::cluster_price(media_store::borrow_cluster(registry.uid(), cluster_id))
}
public fun media_cluster_active<T>(registry: &Registry<T>, cluster_id: u64): bool {
    media_store::cluster_active(media_store::borrow_cluster(registry.uid(), cluster_id))
}

public fun routed_assignment_exists<T>(registry: &Registry<T>, rental_id: u64): bool {
    media_store::has_routed_assignment(registry.uid(), rental_id)
}
public fun routed_assignment_router<T>(registry: &Registry<T>, rental_id: u64): u64 {
    media_store::routed_assignment_router(registry.uid(), rental_id)
}
public fun routed_assignment_cluster<T>(registry: &Registry<T>, rental_id: u64): u64 {
    media_store::routed_assignment_cluster(registry.uid(), rental_id)
}
public fun routed_assignment_media<T>(registry: &Registry<T>, rental_id: u64): u64 {
    media_store::routed_assignment_media(registry.uid(), rental_id)
}
public fun routed_assignment_revision<T>(registry: &Registry<T>, rental_id: u64): u64 {
    media_store::routed_assignment_revision(registry.uid(), rental_id)
}

#[test_only]
public fun remove_routed_configuration_for_testing<T>(
    registry: &mut Registry<T>, router_node_id: u64, media_node_id: u64, cluster_id: u64,
) {
    media_store::remove_routed_configuration_for_testing(registry.uid_mut(), router_node_id, media_node_id, cluster_id);
}
