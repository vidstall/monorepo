#[test_only]
module xaisen_contract::role_governance_tests;

use sui::clock;
use xaisen_contract::registry;
use xaisen_contract::role_governance;
use xaisen_contract::role_vote_store;
use xaisen_contract::room_vote_store;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const E_INVALID_ROLE: u64 = 20;
const E_PROPOSAL_NOT_FOUND: u64 = 17;
const E_NOT_ACTIVE_WORKER: u64 = 15;

#[test]
fun propose_role_creates_proposal() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 90);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);

    let mut propose_ctx = test_fixtures::ctx(test_fixtures::owner(), 91);
    role_governance::propose_role(&mut reg, 1, 1, role_vote_store::role_sfu_for_testing(), &clock, &mut propose_ctx);

    assert!(role_vote_store::role_proposal_exists(reg.role_votes(), 1));
    assert!(role_vote_store::has_worker_role(reg.role_votes(), 1));
    assert!(role_vote_store::worker_role(reg.role_votes(), 1) == role_vote_store::role_sfu_for_testing());

    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 1);
    role_vote_store::remove_role_map_entry_for_testing(reg.role_votes_mut(), 1);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun role_proposal_accessors_report_pending_state() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 94_1);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 94_2);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 94_3);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wc_ctx), &clock, &mut wc_ctx);

    assert!(role_vote_store::next_role_proposal_id(reg.role_votes()) == 1);

    clock::set_for_testing(&mut clock, 1000);
    let mut propose_ctx = test_fixtures::ctx(test_fixtures::owner(), 94_4);
    role_governance::propose_role(&mut reg, 1, 2, role_vote_store::role_router_for_testing(), &clock, &mut propose_ctx);

    assert!(role_vote_store::next_role_proposal_id(reg.role_votes()) == 2);
    assert!(role_vote_store::role_proposal_exists(reg.role_votes(), 1));
    assert!(role_vote_store::role_proposal_role(reg.role_votes(), 1) == role_vote_store::role_router_for_testing());
    assert!(role_vote_store::role_proposal_nominee_node_id(reg.role_votes(), 1) == 2);
    assert!(role_vote_store::role_proposal_deadline_ms(reg.role_votes(), 1) == 1000 + room_vote_store::default_vote_deadline_ms_for_testing());
    assert!(!role_vote_store::role_proposal_finalized(reg.role_votes(), 1));

    let mut wb_vote_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 94_5);
    role_governance::cast_role_vote(&mut reg, 2, 1, &clock, &mut wb_vote_ctx);
    assert!(role_vote_store::role_proposal_finalized(reg.role_votes(), 1));

    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 1);
    role_vote_store::remove_role_map_entry_for_testing(reg.role_votes_mut(), 2);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut wb_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 3, &mut wc_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_PROPOSAL_NOT_FOUND, location = xaisen_contract::role_vote_store)]
fun role_proposal_accessor_unknown_id_aborts() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 94_6);
    let reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    let _ = role_vote_store::role_proposal_role(reg.role_votes(), 1);

    registry::destroy_registry_for_testing(reg);
}

#[test]
fun cast_role_vote_majority_assigns_role() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 95);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 96);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 97);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wc_ctx), &clock, &mut wc_ctx);

    let mut propose_ctx = test_fixtures::ctx(test_fixtures::owner(), 98);
    role_governance::propose_role(&mut reg, 1, 2, role_vote_store::role_coordinator_for_testing(), &clock, &mut propose_ctx);

    assert!(!role_vote_store::has_worker_role(reg.role_votes(), 2));

    let mut wb_vote_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 99);
    role_governance::cast_role_vote(&mut reg, 2, 1, &clock, &mut wb_vote_ctx);

    assert!(role_vote_store::has_worker_role(reg.role_votes(), 2));
    assert!(role_vote_store::worker_role(reg.role_votes(), 2) == role_vote_store::role_coordinator_for_testing());

    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 1);
    role_vote_store::remove_role_map_entry_for_testing(reg.role_votes_mut(), 2);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut wb_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 3, &mut wc_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_ROLE, location = xaisen_contract::role_vote_store)]
fun propose_role_invalid_role_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 100);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);

    let mut propose_ctx = test_fixtures::ctx(test_fixtures::owner(), 101);
    role_governance::propose_role(&mut reg, 1, 1, 5, &clock, &mut propose_ctx);

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_ACTIVE_WORKER, location = xaisen_contract::role_governance)]
fun inactive_worker_cannot_vote_on_role() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 105);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 106);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 107);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wc_ctx), &clock, &mut wc_ctx);

    let mut propose_ctx = test_fixtures::ctx(test_fixtures::owner(), 108);
    role_governance::propose_role(&mut reg, 1, 2, role_vote_store::role_sfu_for_testing(), &clock, &mut propose_ctx);

    worker_accessors::set_worker_active_for_testing(reg.workers_mut(), 2, false);
    let mut wb_vote_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 109);
    role_governance::cast_role_vote(&mut reg, 2, 1, &clock, &mut wb_vote_ctx);

    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 1);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut wb_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 3, &mut wc_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}
