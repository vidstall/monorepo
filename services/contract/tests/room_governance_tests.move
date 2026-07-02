#[test_only]
module xaisen_contract::room_governance_tests;

use sui::clock;
use xaisen_contract::registry;
use xaisen_contract::rental_store;
use xaisen_contract::rentals;
use xaisen_contract::room_governance;
use xaisen_contract::room_vote_store;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const E_NOT_NODE_OWNER: u64 = 3;
const E_INVALID_CAPACITY: u64 = 14;

#[test]
fun order_room_creates_pending_proposal() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 50);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 51);

    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    assert!(rental_store::rental_exists(reg.rentals(), 1));
    assert!(rental_store::rental_status(reg.rentals(), 1) == rental_store::rental_awaiting_assignment_for_testing());
    assert!(rental_store::rental_capacity(reg.rentals(), 1) == test_fixtures::capacity());
    assert!(rental_store::rental_client(reg.rentals(), 1) == test_fixtures::client());
    assert!(rental_store::rental_payment_amount(reg.rentals(), 1) == test_fixtures::price());
    assert!(!room_vote_store::room_proposal_finalized(reg.room_votes(), 1));

    room_vote_store::remove_room_proposal_for_testing(reg.room_votes_mut(), 1);
    rental_store::remove_rental_for_testing(reg.rentals_mut(), 1, &mut client_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_CAPACITY, location = xaisen_contract::rental_store)]
fun order_room_invalid_capacity_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 52);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 53);

    room_governance::order_room(&mut reg, test_fixtures::room(), 0, test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun cast_room_vote_records_vote_without_finalizing() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 54);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 55);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 56);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wc_ctx), &clock, &mut wc_ctx);

    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 3);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 57);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    let mut vote_ctx = test_fixtures::ctx(test_fixtures::owner(), 58);
    room_governance::cast_room_vote(&mut reg, 1, 1, 1, &clock, &mut vote_ctx);

    assert!(!room_vote_store::room_proposal_finalized(reg.room_votes(), 1));

    room_vote_store::remove_room_proposal_for_testing(reg.room_votes_mut(), 1);
    rental_store::remove_rental_for_testing(reg.rentals_mut(), 1, &mut client_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut wb_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 3, &mut wc_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun cast_room_vote_majority_finalizes_assignment() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 60);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 61);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 62);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wc_ctx), &clock, &mut wc_ctx);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 63);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    let mut wb_vote_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 64);
    room_governance::cast_room_vote(&mut reg, 2, 1, 1, &clock, &mut wb_vote_ctx);
    let mut wc_vote_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 65);
    room_governance::cast_room_vote(&mut reg, 3, 1, 1, &clock, &mut wc_vote_ctx);

    assert!(room_vote_store::room_proposal_finalized(reg.room_votes(), 1));
    assert!(rental_store::rental_status(reg.rentals(), 1) == rental_store::rental_active_for_testing());
    assert!(rental_store::rental_worker_node_id(reg.rentals(), 1) == 1);
    assert!(worker_accessors::worker_active_rental_id(reg.workers(), 1) == 1);

    let mut complete_ctx = test_fixtures::ctx(test_fixtures::client(), 66);
    rentals::complete_rental(&mut reg, 1, &clock, &mut complete_ctx);

    room_vote_store::remove_room_proposal_for_testing(reg.room_votes_mut(), 1);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut wb_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 3, &mut wc_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_NODE_OWNER, location = xaisen_contract::worker_store)]
fun cast_room_vote_non_owner_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 70);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 71);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    let mut other_ctx = test_fixtures::ctx(test_fixtures::other(), 72);
    room_governance::cast_room_vote(&mut reg, 1, 1, 1, &clock, &mut other_ctx);

    room_vote_store::remove_room_proposal_for_testing(reg.room_votes_mut(), 1);
    rental_store::remove_rental_for_testing(reg.rentals_mut(), 1, &mut client_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}
