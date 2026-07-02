#[test_only]
module xaisen_contract::rental_tests;

use sui::clock;
use sui::coin;
use xaisen_contract::registry;
use xaisen_contract::rental_store;
use xaisen_contract::rentals;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const E_INVALID_PAYMENT_AMOUNT: u64 = 7;
const E_EMPTY_ROOM_NAME: u64 = 8;
const E_NOT_RENTAL_CLIENT: u64 = 10;
const E_RENTAL_NOT_PENDING: u64 = 11;
const E_WORKER_HAS_ACTIVE_RENTAL: u64 = 12;
const E_WORKER_UNAVAILABLE: u64 = 6;
const E_INVALID_CAPACITY: u64 = 14;

#[test]
fun hire_worker_creates_rental_and_marks_worker_busy() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 9);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 10);

    rentals::hire_worker(
        &mut reg, 1, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx,
    );

    assert!(rental_store::rental_exists(reg.rentals(), 1));
    assert!(rental_store::rental_status(reg.rentals(), 1) == rental_store::rental_pending_for_testing());
    assert!(rental_store::rental_client(reg.rentals(), 1) == test_fixtures::client());
    assert!(rental_store::rental_worker_node_id(reg.rentals(), 1) == 1);
    assert!(rental_store::rental_room_name(reg.rentals(), 1) == test_fixtures::room());
    assert!(rental_store::rental_capacity(reg.rentals(), 1) == test_fixtures::capacity());
    assert!(rental_store::rental_payment_amount(reg.rentals(), 1) == test_fixtures::price());
    assert!(worker_accessors::worker_active_rental_id(reg.workers(), 1) == 1);

    rentals::cancel_rental(&mut reg, 1, &mut client_ctx);
    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_PAYMENT_AMOUNT, location = xaisen_contract::rental_store)]
fun incorrect_payment_amount_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 11);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 12);

    rentals::hire_worker(
        &mut reg, 1, test_fixtures::room(), test_fixtures::capacity(),
        coin::mint_for_testing<TEST_COIN>(test_fixtures::price() - 1, &mut client_ctx), &clock, &mut client_ctx,
    );

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_EMPTY_ROOM_NAME, location = xaisen_contract::rental_store)]
fun empty_room_name_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 13);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 14);

    rentals::hire_worker(
        &mut reg, 1, vector[], test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx,
    );

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_HAS_ACTIVE_RENTAL, location = xaisen_contract::worker_store)]
fun second_rental_for_busy_worker_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 15);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 16);
    let mut other_ctx = test_fixtures::ctx(test_fixtures::other(), 17);

    rentals::hire_worker(&mut reg, 1, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);
    rentals::hire_worker(&mut reg, 1, b"room-two", test_fixtures::capacity(), test_fixtures::payment(&mut other_ctx), &clock, &mut other_ctx);

    rentals::cancel_rental(&mut reg, 1, &mut client_ctx);
    workers::unregister_worker(&mut reg, 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_UNAVAILABLE, location = xaisen_contract::rentals)]
fun inactive_worker_cannot_be_hired() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 18);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 19);

    worker_accessors::set_worker_active_for_testing(reg.workers_mut(), 1, false);
    rentals::hire_worker(&mut reg, 1, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun client_completes_rental_and_worker_gets_reward() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 20);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 21);

    rentals::hire_worker(&mut reg, 1, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);
    clock::set_for_testing(&mut clock, 4000);
    rentals::complete_rental(&mut reg, 1, &clock, &mut client_ctx);

    assert!(!rental_store::rental_exists(reg.rentals(), 1));
    assert!(worker_accessors::worker_active_rental_id(reg.workers(), 1) == worker_accessors::no_active_rental_for_testing());
    assert!(rental_store::total_rewards_paid(reg.rentals()) == test_fixtures::price());

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_RENTAL_CLIENT, location = xaisen_contract::rental_store)]
fun non_client_cannot_complete_rental() {
    rental_store::assert_rental_client_for_testing(test_fixtures::client(), test_fixtures::other());
}

#[test]
fun client_cancels_rental_and_gets_refund() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 25);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 26);

    rentals::hire_worker(&mut reg, 1, test_fixtures::room(), test_fixtures::capacity(), test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);
    rentals::cancel_rental(&mut reg, 1, &mut client_ctx);

    assert!(!rental_store::rental_exists(reg.rentals(), 1));
    assert!(worker_accessors::worker_active_rental_id(reg.workers(), 1) == worker_accessors::no_active_rental_for_testing());
    assert!(rental_store::total_rewards_paid(reg.rentals()) == 0);

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_RENTAL_NOT_PENDING, location = xaisen_contract::rental_store)]
fun completed_rental_cannot_be_canceled() {
    rental_store::assert_rental_pending_for_testing(1);
}

#[test]
#[expected_failure(abort_code = E_INVALID_CAPACITY, location = xaisen_contract::rental_store)]
fun hire_worker_zero_capacity_aborts() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 40);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = test_fixtures::ctx(test_fixtures::client(), 41);

    rentals::hire_worker(&mut reg, 1, test_fixtures::room(), 0, test_fixtures::payment(&mut client_ctx), &clock, &mut client_ctx);

    worker_accessors::remove_worker_for_testing(reg.workers_mut(), 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}
