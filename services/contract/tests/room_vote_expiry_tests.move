#[test_only]
module xaisen_contract::room_vote_expiry_tests;

use sui::clock;
use xaisen_contract::registry;
use xaisen_contract::rental_store;
use xaisen_contract::room_governance;
use xaisen_contract::room_vote_store;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const E_ALREADY_VOTED: u64 = 16;
const E_PROPOSAL_EXPIRED: u64 = 18;

#[test]
#[expected_failure(abort_code = E_ALREADY_VOTED, location = xaisen_contract::room_vote_store)]
fun cast_room_vote_duplicate_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 73);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = test_fixtures::ctx(test_fixtures::worker_b(), 74);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = test_fixtures::ctx(test_fixtures::worker_c(), 75);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut wc_ctx), &clock, &mut wc_ctx);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 76);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    let mut vote_ctx1 = test_fixtures::ctx(test_fixtures::owner(), 77);
    room_governance::cast_room_vote(&mut reg, 1, 1, 1, &clock, &mut vote_ctx1);
    let mut vote_ctx2 = test_fixtures::ctx(test_fixtures::owner(), 78);
    room_governance::cast_room_vote(&mut reg, 1, 1, 1, &clock, &mut vote_ctx2);

    room_vote_store::remove_room_proposal_for_testing(reg.room_votes_mut(), 1);
    rental_store::remove_rental_for_testing(reg.rentals_mut(), 1, &mut client_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 2, &mut wb_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 3, &mut wc_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_PROPOSAL_EXPIRED, location = xaisen_contract::room_vote_store)]
fun cast_room_vote_expired_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 80);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 81);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    clock::set_for_testing(&mut clock, room_vote_store::default_vote_deadline_ms_for_testing() + 1);
    let mut vote_ctx = test_fixtures::ctx(test_fixtures::owner(), 82);
    room_governance::cast_room_vote(&mut reg, 1, 1, 1, &clock, &mut vote_ctx);

    room_vote_store::remove_room_proposal_for_testing(reg.room_votes_mut(), 1);
    rental_store::remove_rental_for_testing(reg.rentals_mut(), 1, &mut client_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun cancel_expired_order_refunds_client() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 85);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);

    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 86);
    room_governance::order_room(&mut reg, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    assert!(rental_store::rental_exists(reg.rentals(), 1));

    clock::set_for_testing(&mut clock, room_vote_store::default_vote_deadline_ms_for_testing() + 1);
    room_governance::cancel_expired_order(&mut reg, 1, &clock, &mut client_ctx);

    assert!(!rental_store::rental_exists(reg.rentals(), 1));

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}
