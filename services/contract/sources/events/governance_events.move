module xaisen_contract::governance_events;

use sui::event;

public struct RoomOrderCreated has copy, drop {
    rental_id: u64,
    client: address,
    room_name: vector<u8>,
    capacity: u64,
    payment_amount: u64,
    deadline_ms: u64,
    timestamp_ms: u64,
}

public struct VoteCast has copy, drop {
    proposal_type: u8,
    proposal_id: u64,
    voter: address,
    voter_node_id: u64,
    timestamp_ms: u64,
}

public struct RoomAssignmentFinalized has copy, drop {
    rental_id: u64,
    assigned_node_id: u64,
    timestamp_ms: u64,
}

public struct ProposalExpired has copy, drop {
    proposal_type: u8,
    proposal_id: u64,
    timestamp_ms: u64,
}

public struct RoleProposalCreated has copy, drop {
    proposal_id: u64,
    proposer: address,
    nominee_node_id: u64,
    role: u8,
    deadline_ms: u64,
    timestamp_ms: u64,
}

public struct RoleAssigned has copy, drop {
    proposal_id: u64,
    node_id: u64,
    role: u8,
    timestamp_ms: u64,
}

public(package) fun emit_room_order_created(
    rental_id: u64, client: address, room_name: vector<u8>, capacity: u64,
    payment_amount: u64, deadline_ms: u64, timestamp_ms: u64,
) {
    event::emit(RoomOrderCreated { rental_id, client, room_name, capacity, payment_amount, deadline_ms, timestamp_ms });
}

public(package) fun emit_vote_cast(proposal_type: u8, proposal_id: u64, voter: address, voter_node_id: u64, timestamp_ms: u64) {
    event::emit(VoteCast { proposal_type, proposal_id, voter, voter_node_id, timestamp_ms });
}

public(package) fun emit_room_assignment_finalized(rental_id: u64, assigned_node_id: u64, timestamp_ms: u64) {
    event::emit(RoomAssignmentFinalized { rental_id, assigned_node_id, timestamp_ms });
}

public(package) fun emit_proposal_expired(proposal_type: u8, proposal_id: u64, timestamp_ms: u64) {
    event::emit(ProposalExpired { proposal_type, proposal_id, timestamp_ms });
}

public(package) fun emit_role_proposal_created(
    proposal_id: u64, proposer: address, nominee_node_id: u64, role: u8, deadline_ms: u64, timestamp_ms: u64,
) {
    event::emit(RoleProposalCreated { proposal_id, proposer, nominee_node_id, role, deadline_ms, timestamp_ms });
}

public(package) fun emit_role_assigned(proposal_id: u64, node_id: u64, role: u8, timestamp_ms: u64) {
    event::emit(RoleAssigned { proposal_id, node_id, role, timestamp_ms });
}
