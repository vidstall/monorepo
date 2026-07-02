module xaisen_contract::worker_events;

use sui::event;

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

public struct WorkerHeartbeat has copy, drop {
    node_id: u64,
    timestamp_ms: u64,
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

public(package) fun emit_worker_registered(
    node_id: u64, owner: address, metadata_uri: vector<u8>, metadata_hash: vector<u8>,
    price_per_rental: u64, stake_amount: u64, timestamp_ms: u64,
) {
    event::emit(WorkerRegistered { node_id, owner, metadata_uri, metadata_hash, price_per_rental, stake_amount, timestamp_ms });
}

public(package) fun emit_worker_metadata_updated(
    node_id: u64, owner: address, metadata_uri: vector<u8>, metadata_hash: vector<u8>, timestamp_ms: u64,
) {
    event::emit(WorkerMetadataUpdated { node_id, owner, metadata_uri, metadata_hash, timestamp_ms });
}

public(package) fun emit_worker_status_updated(node_id: u64, owner: address, active: bool, timestamp_ms: u64) {
    event::emit(WorkerStatusUpdated { node_id, owner, active, timestamp_ms });
}

public(package) fun emit_worker_unregistered(node_id: u64, owner: address) {
    event::emit(WorkerUnregistered { node_id, owner });
}

public(package) fun emit_worker_heartbeat(node_id: u64, timestamp_ms: u64) {
    event::emit(WorkerHeartbeat { node_id, timestamp_ms });
}

public(package) fun emit_worker_price_updated(node_id: u64, owner: address, price_per_rental: u64) {
    event::emit(WorkerPriceUpdated { node_id, owner, price_per_rental });
}

public(package) fun emit_worker_stake_withdrawn(node_id: u64, owner: address, stake_amount: u64) {
    event::emit(WorkerStakeWithdrawn { node_id, owner, stake_amount });
}
