module xaisen_contract::rental_events;

use sui::event;

public struct WorkerHired has copy, drop {
    rental_id: u64,
    node_id: u64,
    client: address,
    worker_owner: address,
    room_name: vector<u8>,
    capacity: u64,
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

public(package) fun emit_worker_hired(
    rental_id: u64, node_id: u64, client: address, worker_owner: address, room_name: vector<u8>,
    capacity: u64, payment_amount: u64, timestamp_ms: u64,
) {
    event::emit(WorkerHired { rental_id, node_id, client, worker_owner, room_name, capacity, payment_amount, timestamp_ms });
}

public(package) fun emit_rental_completed(
    rental_id: u64, node_id: u64, client: address, worker_owner: address, payment_amount: u64, timestamp_ms: u64,
) {
    event::emit(RentalCompleted { rental_id, node_id, client, worker_owner, payment_amount, timestamp_ms });
}

public(package) fun emit_rental_canceled(rental_id: u64, node_id: u64, client: address, payment_amount: u64) {
    event::emit(RentalCanceled { rental_id, node_id, client, payment_amount });
}

public(package) fun emit_worker_reward_paid(rental_id: u64, node_id: u64, worker_owner: address, payment_amount: u64) {
    event::emit(WorkerRewardPaid { rental_id, node_id, worker_owner, payment_amount });
}
