#[test_only]
module xaisen_contract::media_routing_tests;

use sui::clock;
use xaisen_contract::media_routing;
use xaisen_contract::registry;
use xaisen_contract::rental_store;
use xaisen_contract::rentals;
use xaisen_contract::role_governance;
use xaisen_contract::role_vote_store;
use xaisen_contract::room_governance;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

#[test]
fun routed_order_registers_profiles_assigns_and_splits_payment() {
    let mut media_ctx = test_fixtures::ctx(test_fixtures::owner(), 200);
    let mut clock = clock::create_for_testing(&mut media_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut media_ctx);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut media_ctx), &clock, &mut media_ctx);
    role_governance::propose_role(&mut reg, 1, 1, role_vote_store::role_sfu_for_testing(), &clock, &mut media_ctx);

    let mut router_ctx = test_fixtures::ctx(test_fixtures::other(), 201);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(), test_fixtures::stake(&mut router_ctx), &clock, &mut router_ctx);
    // ROLE_ROUTER auto-passes here (fewer than 10 active routers), so no second vote is needed.
    role_governance::propose_role(&mut reg, 2, 2, role_vote_store::role_router_for_testing(), &clock, &mut router_ctx);

    let mut media_profile_ctx = test_fixtures::ctx(test_fixtures::owner(), 204);
    media_routing::set_node_profile(&mut reg, 1, test_fixtures::hash(3), b"https://media/broker", b"apac", 1, &mut media_profile_ctx);
    let mut cluster_ctx = test_fixtures::ctx(test_fixtures::owner(), 205);
    media_routing::register_media_cluster(&mut reg, 1, b"wss://media", test_fixtures::price(), &mut cluster_ctx);
    let mut router_profile_ctx = test_fixtures::ctx(test_fixtures::other(), 206);
    media_routing::set_node_profile(&mut reg, 2, test_fixtures::hash(4), b"https://router", b"apac", 0, &mut router_profile_ctx);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 202);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);
    let mut assign_ctx = test_fixtures::ctx(test_fixtures::other(), 207);
    media_routing::assign_routed_order(&mut reg, 2, 1, 1, 1, &clock, &mut assign_ctx);
    assert!(media_routing::routed_assignment_exists(&reg, 1));
    assert!(media_routing::routed_assignment_router(&reg, 1) == 2);
    assert!(media_routing::routed_assignment_cluster(&reg, 1) == 1);
    assert!(media_routing::routed_assignment_revision(&reg, 1) == 1);

    let mut reassign_ctx = test_fixtures::ctx(test_fixtures::other(), 208);
    media_routing::assign_routed_order(&mut reg, 2, 1, 1, 1, &clock, &mut reassign_ctx);
    assert!(media_routing::routed_assignment_revision(&reg, 1) == 2);
    clock::set_for_testing(&mut clock, 4000);
    let mut completion_ctx = test_fixtures::ctx(test_fixtures::client(), 209);
    rentals::complete_rental(&mut reg, 1, &clock, &mut completion_ctx);
    assert!(rental_store::total_rewards_paid(reg.rentals()) == test_fixtures::price());

    media_routing::remove_routed_configuration_for_testing(&mut reg, 2, 1, 1);
    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 1);
    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 2);
    role_vote_store::remove_role_map_entry_for_testing(reg.role_votes_mut(), 1);
    role_vote_store::remove_role_map_entry_for_testing(reg.role_votes_mut(), 2);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut media_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut router_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun update_cluster_price_changes_price() {
    let mut media_ctx = test_fixtures::ctx(test_fixtures::owner(), 300);
    let clock = clock::create_for_testing(&mut media_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut media_ctx);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut media_ctx), &clock, &mut media_ctx);
    role_governance::propose_role(&mut reg, 1, 1, role_vote_store::role_sfu_for_testing(), &clock, &mut media_ctx);
    let mut media_profile_ctx = test_fixtures::ctx(test_fixtures::owner(), 301);
    media_routing::set_node_profile(&mut reg, 1, test_fixtures::hash(3), b"https://media/broker", b"apac", 1, &mut media_profile_ctx);
    let mut cluster_ctx = test_fixtures::ctx(test_fixtures::owner(), 302);
    media_routing::register_media_cluster(&mut reg, 1, b"wss://media", test_fixtures::price(), &mut cluster_ctx);
    assert!(media_routing::media_cluster_price(&reg, 1) == test_fixtures::price());

    let mut router_ctx = test_fixtures::ctx(test_fixtures::other(), 303);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(), test_fixtures::stake(&mut router_ctx), &clock, &mut router_ctx);
    let mut router_profile_ctx = test_fixtures::ctx(test_fixtures::other(), 304);
    media_routing::set_node_profile(&mut reg, 2, test_fixtures::hash(4), b"https://router", b"apac", 0, &mut router_profile_ctx);

    let mut update_ctx = test_fixtures::ctx(test_fixtures::owner(), 305);
    media_routing::update_cluster_price(&mut reg, 1, 10_000_000, &mut update_ctx);
    assert!(media_routing::media_cluster_price(&reg, 1) == 10_000_000);

    media_routing::remove_routed_configuration_for_testing(&mut reg, 2, 1, 1);
    role_vote_store::remove_role_proposal_for_testing(reg.role_votes_mut(), 1);
    role_vote_store::remove_role_map_entry_for_testing(reg.role_votes_mut(), 1);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut media_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut router_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = 3, location = xaisen_contract::worker_store)]
fun update_cluster_price_rejects_non_owner() {
    let mut media_ctx = test_fixtures::ctx(test_fixtures::owner(), 310);
    let clock = clock::create_for_testing(&mut media_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut media_ctx);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut media_ctx), &clock, &mut media_ctx);
    role_governance::propose_role(&mut reg, 1, 1, role_vote_store::role_sfu_for_testing(), &clock, &mut media_ctx);
    let mut media_profile_ctx = test_fixtures::ctx(test_fixtures::owner(), 311);
    media_routing::set_node_profile(&mut reg, 1, test_fixtures::hash(3), b"https://media/broker", b"apac", 1, &mut media_profile_ctx);
    let mut cluster_ctx = test_fixtures::ctx(test_fixtures::owner(), 312);
    media_routing::register_media_cluster(&mut reg, 1, b"wss://media", test_fixtures::price(), &mut cluster_ctx);

    let mut intruder_ctx = test_fixtures::ctx(test_fixtures::other(), 313);
    media_routing::update_cluster_price(&mut reg, 1, 10_000_000, &mut intruder_ctx);

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut media_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}
