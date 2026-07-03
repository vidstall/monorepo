module xaisen_contract::media_store;

use std::vector;
use sui::dynamic_field;
use sui::object::UID;

const E_INVALID_PRICE: u64 = 4;
const E_INVALID_PUBLIC_KEY: u64 = 22;
const E_INVALID_ENDPOINT: u64 = 23;
const E_CLUSTER_NOT_FOUND: u64 = 25;
const E_CLUSTER_INACTIVE: u64 = 26;
const E_NOT_CLUSTER_MEMBER: u64 = 28;

const X25519_PUBLIC_KEY_LENGTH: u64 = 32;
const MEDIA_PAYMENT_BPS: u64 = 8_000;
const BPS_DENOMINATOR: u64 = 10_000;

public struct NodeProfileKey has copy, drop, store { node_id: u64 }
public struct MediaClusterKey has copy, drop, store { cluster_id: u64 }
public struct ClusterMemberKey has copy, drop, store { cluster_id: u64, node_id: u64 }
public struct RoutedAssignmentKey has copy, drop, store { rental_id: u64 }

public struct NodeProfile has store {
    x25519_public_key: vector<u8>,
    broker_endpoint: vector<u8>,
    region: vector<u8>,
    cluster_id: u64,
}

public struct MediaCluster has store {
    owner_node_id: u64,
    treasury: address,
    client_url: vector<u8>,
    price_per_rental: u64,
    active: bool,
}

public struct RoutedAssignment has store {
    router_node_id: u64,
    media_node_id: u64,
    cluster_id: u64,
    revision: u64,
}

public(package) fun media_payment_bps(): u64 { MEDIA_PAYMENT_BPS }
public(package) fun bps_denominator(): u64 { BPS_DENOMINATOR }

public(package) fun set_node_profile(
    uid: &mut UID, node_id: u64, x25519_public_key: vector<u8>,
    broker_endpoint: vector<u8>, region: vector<u8>, cluster_id: u64,
) {
    assert!(vector::length(&x25519_public_key) == X25519_PUBLIC_KEY_LENGTH, E_INVALID_PUBLIC_KEY);
    assert!(vector::length(&broker_endpoint) > 0, E_INVALID_ENDPOINT);
    let key = NodeProfileKey { node_id };
    let profile = NodeProfile { x25519_public_key, broker_endpoint, region, cluster_id };
    if (dynamic_field::exists(uid, key)) {
        let old: NodeProfile = dynamic_field::remove(uid, key);
        let NodeProfile { x25519_public_key: _, broker_endpoint: _, region: _, cluster_id: _ } = old;
    };
    dynamic_field::add(uid, key, profile);
}

public(package) fun has_node_profile(uid: &UID, node_id: u64): bool {
    dynamic_field::exists(uid, NodeProfileKey { node_id })
}

fun profile(uid: &UID, node_id: u64): &NodeProfile {
    dynamic_field::borrow<NodeProfileKey, NodeProfile>(uid, NodeProfileKey { node_id })
}

public(package) fun node_x25519_public_key(uid: &UID, node_id: u64): vector<u8> { profile(uid, node_id).x25519_public_key }
public(package) fun node_broker_endpoint(uid: &UID, node_id: u64): vector<u8> { profile(uid, node_id).broker_endpoint }
public(package) fun node_region(uid: &UID, node_id: u64): vector<u8> { profile(uid, node_id).region }
public(package) fun node_cluster_id(uid: &UID, node_id: u64): u64 { profile(uid, node_id).cluster_id }

public(package) fun register_media_cluster(
    uid: &mut UID, owner_node_id: u64, treasury: address, client_url: vector<u8>, price_per_rental: u64,
): u64 {
    assert!(vector::length(&client_url) > 0, E_INVALID_ENDPOINT);
    assert!(price_per_rental > 0, E_INVALID_PRICE);
    let cluster_id = owner_node_id;
    let cluster_key = MediaClusterKey { cluster_id };
    assert!(!dynamic_field::exists(uid, cluster_key), E_INVALID_PRICE);
    dynamic_field::add(uid, cluster_key, MediaCluster { owner_node_id, treasury, client_url, price_per_rental, active: true });
    dynamic_field::add(uid, ClusterMemberKey { cluster_id, node_id: owner_node_id }, true);
    cluster_id
}

public(package) fun add_cluster_member(uid: &mut UID, cluster_id: u64, node_id: u64) {
    let key = ClusterMemberKey { cluster_id, node_id };
    if (!dynamic_field::exists(uid, key)) {
        dynamic_field::add(uid, key, true);
    };
}

public(package) fun is_cluster_member(uid: &UID, cluster_id: u64, node_id: u64): bool {
    dynamic_field::exists(uid, ClusterMemberKey { cluster_id, node_id })
}

public(package) fun assert_cluster_member(uid: &UID, cluster_id: u64, node_id: u64) {
    assert!(is_cluster_member(uid, cluster_id, node_id), E_NOT_CLUSTER_MEMBER);
}

public(package) fun borrow_cluster(uid: &UID, cluster_id: u64): &MediaCluster {
    let key = MediaClusterKey { cluster_id };
    assert!(dynamic_field::exists(uid, key), E_CLUSTER_NOT_FOUND);
    dynamic_field::borrow(uid, key)
}

public(package) fun borrow_cluster_mut(uid: &mut UID, cluster_id: u64): &mut MediaCluster {
    let key = MediaClusterKey { cluster_id };
    assert!(dynamic_field::exists(uid, key), E_CLUSTER_NOT_FOUND);
    dynamic_field::borrow_mut(uid, key)
}

public(package) fun cluster_owner_node_id(cluster: &MediaCluster): u64 { cluster.owner_node_id }
public(package) fun cluster_treasury(cluster: &MediaCluster): address { cluster.treasury }
public(package) fun cluster_client_url(cluster: &MediaCluster): vector<u8> { cluster.client_url }
public(package) fun cluster_price(cluster: &MediaCluster): u64 { cluster.price_per_rental }
public(package) fun cluster_active(cluster: &MediaCluster): bool { cluster.active }
public(package) fun set_cluster_active(cluster: &mut MediaCluster, active: bool) { cluster.active = active; }
public(package) fun set_cluster_price(cluster: &mut MediaCluster, price_per_rental: u64) {
    assert!(price_per_rental > 0, E_INVALID_PRICE);
    cluster.price_per_rental = price_per_rental;
}
public(package) fun assert_cluster_active(cluster: &MediaCluster) { assert!(cluster.active, E_CLUSTER_INACTIVE); }

public(package) fun media_cluster_exists(uid: &UID, cluster_id: u64): bool {
    dynamic_field::exists(uid, MediaClusterKey { cluster_id })
}

public(package) fun has_routed_assignment(uid: &UID, rental_id: u64): bool {
    dynamic_field::exists(uid, RoutedAssignmentKey { rental_id })
}

public(package) fun upsert_routed_assignment(
    uid: &mut UID, rental_id: u64, router_node_id: u64, media_node_id: u64, cluster_id: u64,
): u64 {
    let key = RoutedAssignmentKey { rental_id };
    if (dynamic_field::exists(uid, key)) {
        let assignment: &mut RoutedAssignment = dynamic_field::borrow_mut(uid, key);
        assignment.router_node_id = router_node_id;
        assignment.media_node_id = media_node_id;
        assignment.cluster_id = cluster_id;
        assignment.revision = assignment.revision + 1;
        assignment.revision
    } else {
        dynamic_field::add(uid, key, RoutedAssignment { router_node_id, media_node_id, cluster_id, revision: 1 });
        1
    }
}

fun assignment(uid: &UID, rental_id: u64): &RoutedAssignment {
    dynamic_field::borrow<RoutedAssignmentKey, RoutedAssignment>(uid, RoutedAssignmentKey { rental_id })
}

public(package) fun routed_assignment_router(uid: &UID, rental_id: u64): u64 { assignment(uid, rental_id).router_node_id }
public(package) fun routed_assignment_cluster(uid: &UID, rental_id: u64): u64 { assignment(uid, rental_id).cluster_id }
public(package) fun routed_assignment_media(uid: &UID, rental_id: u64): u64 { assignment(uid, rental_id).media_node_id }
public(package) fun routed_assignment_revision(uid: &UID, rental_id: u64): u64 { assignment(uid, rental_id).revision }

public(package) fun remove_routed_assignment(uid: &mut UID, rental_id: u64): (u64, u64, u64) {
    let RoutedAssignment { router_node_id, media_node_id, cluster_id, revision: _ } =
        dynamic_field::remove(uid, RoutedAssignmentKey { rental_id });
    (router_node_id, media_node_id, cluster_id)
}

#[test_only]
public fun remove_routed_configuration_for_testing(uid: &mut UID, router_node_id: u64, media_node_id: u64, cluster_id: u64) {
    let router_profile: NodeProfile = dynamic_field::remove(uid, NodeProfileKey { node_id: router_node_id });
    let NodeProfile { x25519_public_key: _, broker_endpoint: _, region: _, cluster_id: _ } = router_profile;
    let media_profile: NodeProfile = dynamic_field::remove(uid, NodeProfileKey { node_id: media_node_id });
    let NodeProfile { x25519_public_key: _, broker_endpoint: _, region: _, cluster_id: _ } = media_profile;
    let _: bool = dynamic_field::remove(uid, ClusterMemberKey { cluster_id, node_id: media_node_id });
    let cluster: MediaCluster = dynamic_field::remove(uid, MediaClusterKey { cluster_id });
    let MediaCluster { owner_node_id: _, treasury: _, client_url: _, price_per_rental: _, active: _ } = cluster;
}
