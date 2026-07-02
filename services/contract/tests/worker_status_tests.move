#[test_only]
module xaisen_contract::worker_status_tests;

use sui::clock;
use xaisen_contract::registry;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const E_NODE_NOT_FOUND: u64 = 2;
const E_NOT_NODE_OWNER: u64 = 3;
const E_WORKER_HAS_ACTIVE_RENTAL: u64 = 12;
const E_WORKER_ACTIVE: u64 = 13;

#[test]
fun owner_can_toggle_active_status() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 8);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut ctx);

    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 1);

    clock::set_for_testing(&mut clock, 3000);
    workers::set_worker_active(&mut reg, 1, false, &clock, &mut ctx);

    assert!(!worker_accessors::worker_active(reg.workers(), 1));
    assert!(!worker_accessors::worker_rentable(reg.workers(), 1));
    assert!(worker_accessors::worker_updated_at_ms(reg.workers(), 1) == 3000);
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 0);

    workers::set_worker_active(&mut reg, 1, true, &clock, &mut ctx);
    assert!(worker_accessors::worker_active(reg.workers(), 1));
    assert!(worker_accessors::worker_rentable(reg.workers(), 1));
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 1);

    workers::unregister_worker(&mut reg, 1, &mut ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun owner_can_heartbeat_worker() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 8_1);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut ctx);

    assert!(worker_accessors::worker_updated_at_ms(reg.workers(), 1) == 0);

    clock::set_for_testing(&mut clock, 4000);
    workers::heartbeat_worker(&mut reg, 1, &clock, &mut ctx);

    assert!(worker_accessors::worker_updated_at_ms(reg.workers(), 1) == 4000);
    assert!(worker_accessors::worker_active(reg.workers(), 1));

    workers::unregister_worker(&mut reg, 1, &mut ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_NODE_OWNER, location = xaisen_contract::worker_store)]
fun non_owner_cannot_heartbeat_worker() {
    let mut owner_ctx = test_fixtures::ctx(test_fixtures::owner(), 8_2);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut owner_ctx);
    let mut other_ctx = test_fixtures::ctx(test_fixtures::other(), 8_3);

    workers::heartbeat_worker(&mut reg, 1, &clock, &mut other_ctx);

    workers::unregister_worker(&mut reg, 1, &mut owner_ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NODE_NOT_FOUND, location = xaisen_contract::worker_store)]
fun heartbeat_unknown_node_aborts() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 8_4);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    workers::heartbeat_worker(&mut reg, 1, &clock, &mut ctx);

    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_ACTIVE, location = xaisen_contract::worker_store)]
fun stake_withdrawal_fails_while_worker_active() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 27);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut ctx);

    workers::withdraw_worker_stake(&mut reg, 1, &mut ctx);

    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_HAS_ACTIVE_RENTAL, location = xaisen_contract::worker_store)]
fun stake_withdrawal_fails_while_worker_rented() {
    worker_accessors::assert_no_active_rental_for_testing(1);
}

#[test]
fun stake_withdrawal_succeeds_when_inactive_and_idle() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 30);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut ctx);

    workers::set_worker_active(&mut reg, 1, false, &clock, &mut ctx);
    workers::withdraw_worker_stake(&mut reg, 1, &mut ctx);

    assert!(worker_accessors::node_count(reg.workers()) == 0);
    assert!(!worker_accessors::node_exists(reg.workers(), 1));

    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NODE_NOT_FOUND, location = xaisen_contract::worker_store)]
fun missing_node_operation_aborts() {
    worker_accessors::assert_node_present_for_testing(false);
}
