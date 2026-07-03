module xaisen_contract::media_events;

use sui::event;

public struct NodeProfileUpdated has copy, drop {
    node_id: u64,
    cluster_id: u64,
}

public struct MediaClusterRegistered has copy, drop {
    cluster_id: u64,
    owner_node_id: u64,
    treasury: address,
    price_per_rental: u64,
}

public struct ClusterPriceUpdated has copy, drop {
    cluster_id: u64,
    price_per_rental: u64,
}

public struct RoutedAssignmentUpdated has copy, drop {
    rental_id: u64,
    router_node_id: u64,
    media_node_id: u64,
    cluster_id: u64,
    revision: u64,
}

public struct RoutedPaymentSplit has copy, drop {
    rental_id: u64,
    media_amount: u64,
    router_amount: u64,
    media_treasury: address,
    router_owner: address,
}

public(package) fun emit_node_profile_updated(node_id: u64, cluster_id: u64) {
    event::emit(NodeProfileUpdated { node_id, cluster_id });
}

public(package) fun emit_media_cluster_registered(cluster_id: u64, owner_node_id: u64, treasury: address, price_per_rental: u64) {
    event::emit(MediaClusterRegistered { cluster_id, owner_node_id, treasury, price_per_rental });
}

public(package) fun emit_cluster_price_updated(cluster_id: u64, price_per_rental: u64) {
    event::emit(ClusterPriceUpdated { cluster_id, price_per_rental });
}

public(package) fun emit_routed_assignment_updated(
    rental_id: u64, router_node_id: u64, media_node_id: u64, cluster_id: u64, revision: u64,
) {
    event::emit(RoutedAssignmentUpdated { rental_id, router_node_id, media_node_id, cluster_id, revision });
}

public(package) fun emit_routed_payment_split(
    rental_id: u64, media_amount: u64, router_amount: u64, media_treasury: address, router_owner: address,
) {
    event::emit(RoutedPaymentSplit { rental_id, media_amount, router_amount, media_treasury, router_owner });
}
