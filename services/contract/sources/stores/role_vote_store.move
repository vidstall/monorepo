module xaisen_contract::role_vote_store;

use sui::dynamic_field;
use sui::object::UID;
use sui::table::{Self, Table};
use sui::tx_context::TxContext;

const E_ALREADY_VOTED: u64 = 16;
const E_PROPOSAL_NOT_FOUND: u64 = 17;
const E_PROPOSAL_EXPIRED: u64 = 18;
const E_PROPOSAL_ALREADY_FINALIZED: u64 = 19;
const E_INVALID_ROLE: u64 = 20;
const E_ROLE_REQUIRED: u64 = 24;
const E_NODE_NOT_FOUND: u64 = 2;

const ROLE_SFU: u8 = 0;
const ROLE_COORDINATOR: u8 = 1;
const ROLE_ROUTER: u8 = 2;

public struct RoleProposal has store {
    role: u8,
    nominee_node_id: u64,
    proposer: address,
    votes_for: Table<address, bool>,
    vote_count: u64,
    deadline_ms: u64,
    finalized: bool,
    passed: bool,
}

public struct RoleVoteStore has store {
    next_role_proposal_id: u64,
    role_proposals: Table<u64, RoleProposal>,
    role_map: Table<u64, u8>,
}

public(package) fun new(ctx: &mut TxContext): RoleVoteStore {
    RoleVoteStore { next_role_proposal_id: 1, role_proposals: table::new(ctx), role_map: table::new(ctx) }
}

public(package) fun destroy_empty(store: RoleVoteStore) {
    let RoleVoteStore { next_role_proposal_id: _, role_proposals, role_map } = store;
    role_proposals.destroy_empty();
    role_map.destroy_empty();
}

public(package) fun assert_valid_role(role: u8) { assert!(role <= ROLE_ROUTER, E_INVALID_ROLE); }
public(package) fun role_sfu(): u8 { ROLE_SFU }
public(package) fun role_coordinator(): u8 { ROLE_COORDINATOR }
public(package) fun role_router(): u8 { ROLE_ROUTER }

// Tracked as a dynamic field on the Registry's UID (not a RoleVoteStore
// struct field) so this can be added in a package upgrade without breaking
// the struct layout of already-stored on-chain RoleVoteStore data.
public struct ActiveRouterCountKey has copy, drop, store {}

public(package) fun active_router_count(uid: &UID): u64 {
    if (dynamic_field::exists(uid, ActiveRouterCountKey {})) {
        *dynamic_field::borrow(uid, ActiveRouterCountKey {})
    } else {
        0
    }
}

public(package) fun increment_active_router_count(uid: &mut UID) {
    if (dynamic_field::exists(uid, ActiveRouterCountKey {})) {
        let count = dynamic_field::borrow_mut<ActiveRouterCountKey, u64>(uid, ActiveRouterCountKey {});
        *count = *count + 1;
    } else {
        dynamic_field::add(uid, ActiveRouterCountKey {}, 1u64);
    };
}

public(package) fun decrement_active_router_count(uid: &mut UID) {
    if (dynamic_field::exists(uid, ActiveRouterCountKey {})) {
        let count = dynamic_field::borrow_mut<ActiveRouterCountKey, u64>(uid, ActiveRouterCountKey {});
        if (*count > 0) { *count = *count - 1; };
    };
}

public(package) fun next_role_proposal_id(store: &RoleVoteStore): u64 { store.next_role_proposal_id }

public(package) fun contains(store: &RoleVoteStore, proposal_id: u64): bool { table::contains(&store.role_proposals, proposal_id) }
public(package) fun assert_exists(store: &RoleVoteStore, proposal_id: u64) {
    assert!(contains(store, proposal_id), E_PROPOSAL_NOT_FOUND);
}
public(package) fun borrow(store: &RoleVoteStore, proposal_id: u64): &RoleProposal { table::borrow(&store.role_proposals, proposal_id) }
public(package) fun borrow_mut(store: &mut RoleVoteStore, proposal_id: u64): &mut RoleProposal {
    table::borrow_mut(&mut store.role_proposals, proposal_id)
}

public(package) fun insert(
    store: &mut RoleVoteStore, proposer: address, nominee_node_id: u64, role: u8,
    deadline_ms: u64, auto_pass: bool, ctx: &mut TxContext,
): u64 {
    let proposal_id = store.next_role_proposal_id;
    store.next_role_proposal_id = proposal_id + 1;
    let mut votes_for = table::new(ctx);
    table::add(&mut votes_for, proposer, true);
    table::add(&mut store.role_proposals, proposal_id, RoleProposal {
        role, nominee_node_id, proposer, votes_for, vote_count: 1,
        deadline_ms, finalized: auto_pass, passed: auto_pass,
    });
    proposal_id
}

public(package) fun remove(store: &mut RoleVoteStore, proposal_id: u64): RoleProposal {
    table::remove(&mut store.role_proposals, proposal_id)
}

public(package) fun drop(proposal: RoleProposal) {
    let RoleProposal { role: _, nominee_node_id: _, proposer: _, votes_for, vote_count: _, deadline_ms: _, finalized: _, passed: _ } = proposal;
    votes_for.drop();
}

public(package) fun assert_not_finalized(proposal: &RoleProposal) { assert!(!proposal.finalized, E_PROPOSAL_ALREADY_FINALIZED); }
public(package) fun assert_not_expired(proposal: &RoleProposal, timestamp_ms: u64) {
    assert!(timestamp_ms <= proposal.deadline_ms, E_PROPOSAL_EXPIRED);
}

public(package) fun add_vote(proposal: &mut RoleProposal, voter: address): u64 {
    assert!(!table::contains(&proposal.votes_for, voter), E_ALREADY_VOTED);
    table::add(&mut proposal.votes_for, voter, true);
    proposal.vote_count = proposal.vote_count + 1;
    proposal.vote_count
}

public(package) fun finalize(proposal: &mut RoleProposal) {
    proposal.finalized = true;
    proposal.passed = true;
}

public(package) fun role(proposal: &RoleProposal): u8 { proposal.role }
public(package) fun nominee_node_id(proposal: &RoleProposal): u64 { proposal.nominee_node_id }
public(package) fun deadline_ms(proposal: &RoleProposal): u64 { proposal.deadline_ms }
public(package) fun finalized(proposal: &RoleProposal): bool { proposal.finalized }

public(package) fun set_role(store: &mut RoleVoteStore, node_id: u64, role: u8) {
    if (table::contains(&store.role_map, node_id)) {
        let existing = table::borrow_mut(&mut store.role_map, node_id);
        *existing = role;
    } else {
        table::add(&mut store.role_map, node_id, role);
    };
}

public(package) fun has_role(store: &RoleVoteStore, node_id: u64): bool { table::contains(&store.role_map, node_id) }
public(package) fun assert_has_role(store: &RoleVoteStore, node_id: u64, role: u8) {
    assert!(table::contains(&store.role_map, node_id), E_ROLE_REQUIRED);
    assert!(*table::borrow(&store.role_map, node_id) == role, E_ROLE_REQUIRED);
}

public fun has_worker_role(store: &RoleVoteStore, node_id: u64): bool { has_role(store, node_id) }
public fun worker_role(store: &RoleVoteStore, node_id: u64): u8 {
    assert!(table::contains(&store.role_map, node_id), E_NODE_NOT_FOUND);
    *table::borrow(&store.role_map, node_id)
}

public fun role_proposal_exists(store: &RoleVoteStore, proposal_id: u64): bool { contains(store, proposal_id) }
public fun role_proposal_role(store: &RoleVoteStore, proposal_id: u64): u8 {
    assert_exists(store, proposal_id);
    role(borrow(store, proposal_id))
}
public fun role_proposal_nominee_node_id(store: &RoleVoteStore, proposal_id: u64): u64 {
    assert_exists(store, proposal_id);
    nominee_node_id(borrow(store, proposal_id))
}
public fun role_proposal_deadline_ms(store: &RoleVoteStore, proposal_id: u64): u64 {
    assert_exists(store, proposal_id);
    deadline_ms(borrow(store, proposal_id))
}
public fun role_proposal_finalized(store: &RoleVoteStore, proposal_id: u64): bool {
    assert_exists(store, proposal_id);
    finalized(borrow(store, proposal_id))
}

#[test_only]
public fun role_sfu_for_testing(): u8 { ROLE_SFU }
#[test_only]
public fun role_coordinator_for_testing(): u8 { ROLE_COORDINATOR }
#[test_only]
public fun role_router_for_testing(): u8 { ROLE_ROUTER }
#[test_only]
public fun set_active_router_count_for_testing(uid: &mut UID, count: u64) {
    if (dynamic_field::exists(uid, ActiveRouterCountKey {})) {
        let existing = dynamic_field::borrow_mut<ActiveRouterCountKey, u64>(uid, ActiveRouterCountKey {});
        *existing = count;
    } else {
        dynamic_field::add(uid, ActiveRouterCountKey {}, count);
    };
}
#[test_only]
public fun remove_active_router_count_for_testing(uid: &mut UID) {
    if (dynamic_field::exists(uid, ActiveRouterCountKey {})) {
        let _: u64 = dynamic_field::remove(uid, ActiveRouterCountKey {});
    };
}

#[test_only]
public fun remove_role_proposal_for_testing(store: &mut RoleVoteStore, proposal_id: u64) {
    let proposal = remove(store, proposal_id);
    drop(proposal);
}

#[test_only]
public fun remove_role_map_entry_for_testing(store: &mut RoleVoteStore, node_id: u64) {
    table::remove(&mut store.role_map, node_id);
}
