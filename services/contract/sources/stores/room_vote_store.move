module xaisen_contract::room_vote_store;

use sui::table::{Self, Table};
use sui::tx_context::TxContext;

const E_NOMINEE_NOT_FOUND: u64 = 21;
const E_ALREADY_VOTED: u64 = 16;
const E_PROPOSAL_NOT_FOUND: u64 = 17;
const E_PROPOSAL_EXPIRED: u64 = 18;
const E_PROPOSAL_ALREADY_FINALIZED: u64 = 19;
const DEFAULT_VOTE_DEADLINE_MS: u64 = 3_600_000;

public struct RoomAssignmentProposal has store {
    rental_id: u64,
    votes: Table<address, u64>,
    vote_counts: Table<u64, u64>,
    total_votes: u64,
    deadline_ms: u64,
    finalized: bool,
    assigned_node_id: u64,
}

public struct RoomVoteStore has store {
    proposals: Table<u64, RoomAssignmentProposal>,
}

public(package) fun new(ctx: &mut TxContext): RoomVoteStore { RoomVoteStore { proposals: table::new(ctx) } }

public(package) fun destroy_empty(store: RoomVoteStore) {
    let RoomVoteStore { proposals } = store;
    proposals.destroy_empty();
}

public(package) fun default_vote_deadline_ms(): u64 { DEFAULT_VOTE_DEADLINE_MS }

public(package) fun contains(store: &RoomVoteStore, rental_id: u64): bool { table::contains(&store.proposals, rental_id) }
public(package) fun assert_exists(store: &RoomVoteStore, rental_id: u64) {
    assert!(contains(store, rental_id), E_PROPOSAL_NOT_FOUND);
}
public(package) fun borrow(store: &RoomVoteStore, rental_id: u64): &RoomAssignmentProposal { table::borrow(&store.proposals, rental_id) }
public(package) fun borrow_mut(store: &mut RoomVoteStore, rental_id: u64): &mut RoomAssignmentProposal {
    table::borrow_mut(&mut store.proposals, rental_id)
}

public(package) fun insert(store: &mut RoomVoteStore, rental_id: u64, deadline_ms: u64, ctx: &mut TxContext) {
    table::add(&mut store.proposals, rental_id, RoomAssignmentProposal {
        rental_id, votes: table::new(ctx), vote_counts: table::new(ctx),
        total_votes: 0, deadline_ms, finalized: false, assigned_node_id: 0,
    });
}

public(package) fun remove(store: &mut RoomVoteStore, rental_id: u64): RoomAssignmentProposal {
    table::remove(&mut store.proposals, rental_id)
}

public(package) fun drop(proposal: RoomAssignmentProposal) {
    let RoomAssignmentProposal { rental_id: _, votes, vote_counts, total_votes: _, deadline_ms: _, finalized: _, assigned_node_id: _ } = proposal;
    votes.drop();
    vote_counts.drop();
}

public(package) fun assert_nominee_available(nominee_active: bool) { assert!(nominee_active, E_NOMINEE_NOT_FOUND); }
public(package) fun assert_not_finalized(proposal: &RoomAssignmentProposal) {
    assert!(!proposal.finalized, E_PROPOSAL_ALREADY_FINALIZED);
}
public(package) fun assert_not_expired(proposal: &RoomAssignmentProposal, timestamp_ms: u64) {
    assert!(timestamp_ms <= proposal.deadline_ms, E_PROPOSAL_EXPIRED);
}
public(package) fun assert_expired(proposal: &RoomAssignmentProposal, timestamp_ms: u64) {
    assert!(timestamp_ms > proposal.deadline_ms, E_PROPOSAL_EXPIRED);
}

public(package) fun add_vote(proposal: &mut RoomAssignmentProposal, voter: address, nominee_node_id: u64): u64 {
    assert!(!table::contains(&proposal.votes, voter), E_ALREADY_VOTED);
    table::add(&mut proposal.votes, voter, nominee_node_id);
    proposal.total_votes = proposal.total_votes + 1;
    if (table::contains(&proposal.vote_counts, nominee_node_id)) {
        let count = table::borrow_mut(&mut proposal.vote_counts, nominee_node_id);
        *count = *count + 1;
    } else {
        table::add(&mut proposal.vote_counts, nominee_node_id, 1);
    };
    *table::borrow(&proposal.vote_counts, nominee_node_id)
}

public(package) fun finalize(proposal: &mut RoomAssignmentProposal, assigned_node_id: u64) {
    proposal.finalized = true;
    proposal.assigned_node_id = assigned_node_id;
}

public(package) fun deadline_ms(proposal: &RoomAssignmentProposal): u64 { proposal.deadline_ms }
public(package) fun finalized(proposal: &RoomAssignmentProposal): bool { proposal.finalized }

public fun room_proposal_finalized(store: &RoomVoteStore, rental_id: u64): bool {
    assert_exists(store, rental_id);
    finalized(borrow(store, rental_id))
}

#[test_only]
public fun default_vote_deadline_ms_for_testing(): u64 { DEFAULT_VOTE_DEADLINE_MS }

#[test_only]
public fun destroy_room_proposal_for_testing(proposal: RoomAssignmentProposal) { drop(proposal); }

#[test_only]
public fun remove_room_proposal_for_testing(store: &mut RoomVoteStore, rental_id: u64) {
    let proposal = remove(store, rental_id);
    drop(proposal);
}
