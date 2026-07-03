#[allow(lint(public_entry))]
module xaisen_contract::role_governance;

use sui::clock::{Self, Clock};
use sui::tx_context::{Self, TxContext};
use xaisen_contract::governance_events;
use xaisen_contract::registry::Registry;
use xaisen_contract::role_vote_store;
use xaisen_contract::room_vote_store;
use xaisen_contract::worker_store;

const PROPOSAL_TYPE_ROLE: u8 = 1;
const E_NOT_ACTIVE_WORKER: u64 = 15;

public entry fun propose_role<T>(
    registry: &mut Registry<T>,
    proposer_node_id: u64,
    nominee_node_id: u64,
    role: u8,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    role_vote_store::assert_valid_role(role);

    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);

    worker_store::assert_exists(registry.workers(), proposer_node_id);
    let proposer_record = worker_store::borrow(registry.workers(), proposer_node_id);
    worker_store::assert_owner(worker_store::owner(proposer_record), sender);
    assert!(worker_store::active(proposer_record), E_NOT_ACTIVE_WORKER);

    worker_store::assert_exists(registry.workers(), nominee_node_id);

    let deadline_ms = timestamp_ms + room_vote_store::default_vote_deadline_ms();
    let active_count = worker_store::active_worker_count(registry.workers());
    let auto_pass = active_count <= 1
        || (role == role_vote_store::role_router() && role_vote_store::active_router_count(registry.uid()) < 10);

    let proposal_id = role_vote_store::insert(
        registry.role_votes_mut(), sender, nominee_node_id, role, deadline_ms, auto_pass, ctx,
    );

    governance_events::emit_role_proposal_created(proposal_id, sender, nominee_node_id, role, deadline_ms, timestamp_ms);

    if (auto_pass) {
        let already_router = role_vote_store::has_worker_role(registry.role_votes(), nominee_node_id)
            && role_vote_store::worker_role(registry.role_votes(), nominee_node_id) == role_vote_store::role_router();
        role_vote_store::set_role(registry.role_votes_mut(), nominee_node_id, role);
        if (role == role_vote_store::role_router() && !already_router) {
            role_vote_store::increment_active_router_count(registry.uid_mut());
        } else if (already_router && role != role_vote_store::role_router()) {
            role_vote_store::decrement_active_router_count(registry.uid_mut());
        };
        governance_events::emit_role_assigned(proposal_id, nominee_node_id, role, timestamp_ms);
    };
}

public entry fun cast_role_vote<T>(
    registry: &mut Registry<T>,
    voter_node_id: u64,
    proposal_id: u64,
    clock: &Clock,
    ctx: &mut TxContext,
) {
    let sender = tx_context::sender(ctx);
    let timestamp_ms = clock::timestamp_ms(clock);

    worker_store::assert_exists(registry.workers(), voter_node_id);
    let voter_record = worker_store::borrow(registry.workers(), voter_node_id);
    worker_store::assert_owner(worker_store::owner(voter_record), sender);
    assert!(worker_store::active(voter_record), E_NOT_ACTIVE_WORKER);

    role_vote_store::assert_exists(registry.role_votes(), proposal_id);
    let proposal = role_vote_store::borrow_mut(registry.role_votes_mut(), proposal_id);
    role_vote_store::assert_not_finalized(proposal);
    role_vote_store::assert_not_expired(proposal, timestamp_ms);

    let vote_count = role_vote_store::add_vote(proposal, sender);

    governance_events::emit_vote_cast(PROPOSAL_TYPE_ROLE, proposal_id, sender, voter_node_id, timestamp_ms);

    let proposal = role_vote_store::borrow(registry.role_votes(), proposal_id);
    let nominee_node_id = role_vote_store::nominee_node_id(proposal);
    let role = role_vote_store::role(proposal);
    let active_count = worker_store::active_worker_count(registry.workers());

    if (vote_count * 2 > active_count) {
        let proposal = role_vote_store::borrow_mut(registry.role_votes_mut(), proposal_id);
        role_vote_store::finalize(proposal);
        let already_router = role_vote_store::has_worker_role(registry.role_votes(), nominee_node_id)
            && role_vote_store::worker_role(registry.role_votes(), nominee_node_id) == role_vote_store::role_router();
        role_vote_store::set_role(registry.role_votes_mut(), nominee_node_id, role);
        if (role == role_vote_store::role_router() && !already_router) {
            role_vote_store::increment_active_router_count(registry.uid_mut());
        } else if (already_router && role != role_vote_store::role_router()) {
            role_vote_store::decrement_active_router_count(registry.uid_mut());
        };
        governance_events::emit_role_assigned(proposal_id, nominee_node_id, role, timestamp_ms);
    };
}

public fun next_role_proposal_id<T>(registry: &Registry<T>): u64 {
    role_vote_store::next_role_proposal_id(registry.role_votes())
}

public fun has_worker_role<T>(registry: &Registry<T>, node_id: u64): bool {
    role_vote_store::has_worker_role(registry.role_votes(), node_id)
}

public fun worker_role<T>(registry: &Registry<T>, node_id: u64): u8 {
    role_vote_store::worker_role(registry.role_votes(), node_id)
}

public fun role_proposal_exists<T>(registry: &Registry<T>, proposal_id: u64): bool {
    role_vote_store::role_proposal_exists(registry.role_votes(), proposal_id)
}

public fun role_proposal_role<T>(registry: &Registry<T>, proposal_id: u64): u8 {
    role_vote_store::role_proposal_role(registry.role_votes(), proposal_id)
}

public fun role_proposal_nominee_node_id<T>(registry: &Registry<T>, proposal_id: u64): u64 {
    role_vote_store::role_proposal_nominee_node_id(registry.role_votes(), proposal_id)
}

public fun role_proposal_deadline_ms<T>(registry: &Registry<T>, proposal_id: u64): u64 {
    role_vote_store::role_proposal_deadline_ms(registry.role_votes(), proposal_id)
}

public fun role_proposal_finalized<T>(registry: &Registry<T>, proposal_id: u64): bool {
    role_vote_store::role_proposal_finalized(registry.role_votes(), proposal_id)
}
