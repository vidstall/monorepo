#[test_only]
module xaisen_contract::worker_tests;

use sui::clock;
use sui::coin;
use xaisen_contract::registry;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const E_EMPTY_METADATA_URI: u64 = 0;
const E_INVALID_METADATA_HASH: u64 = 1;
const E_NOT_NODE_OWNER: u64 = 3;
const E_INVALID_PRICE: u64 = 4;
const E_INSUFFICIENT_STAKE: u64 = 5;

#[test]
fun registry_initializes_empty() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 1);
    let reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    assert!(worker_accessors::node_count(reg.workers()) == 0);
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 0);

    registry::destroy_registry_for_testing(reg);
}

#[test]
fun next_node_id_tracks_registrations_including_gaps() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 1_5);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    assert!(worker_accessors::next_node_id(reg.workers()) == 1);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut ctx), &clock, &mut ctx);
    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(), test_fixtures::stake(&mut ctx), &clock, &mut ctx);
    assert!(worker_accessors::next_node_id(reg.workers()) == 3);

    workers::unregister_worker(&mut reg, 1, &mut ctx);
    assert!(worker_accessors::node_count(reg.workers()) == 1);
    assert!(worker_accessors::next_node_id(reg.workers()) == 3);

    workers::unregister_worker(&mut reg, 2, &mut ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun register_worker_stores_record() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 2);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(), test_fixtures::stake(&mut ctx), &clock, &mut ctx);

    assert!(worker_accessors::node_count(reg.workers()) == 1);
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 1);
    assert!(worker_accessors::worker_owner(reg.workers(), 1) == test_fixtures::owner());
    assert!(worker_accessors::worker_metadata_uri(reg.workers(), 1) == test_fixtures::uri());
    assert!(worker_accessors::worker_metadata_hash(reg.workers(), 1) == test_fixtures::hash(1));
    assert!(worker_accessors::worker_active(reg.workers(), 1));
    assert!(worker_accessors::worker_rentable(reg.workers(), 1));
    assert!(worker_accessors::worker_price_per_rental(reg.workers(), 1) == test_fixtures::price());
    assert!(worker_accessors::worker_stake_value(reg.workers(), 1) == worker_accessors::min_worker_stake_for_testing());
    assert!(worker_accessors::worker_active_rental_id(reg.workers(), 1) == worker_accessors::no_active_rental_for_testing());
    assert!(worker_accessors::worker_created_at_ms(reg.workers(), 1) == 0);
    assert!(worker_accessors::worker_updated_at_ms(reg.workers(), 1) == 0);

    workers::unregister_worker(&mut reg, 1, &mut ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_EMPTY_METADATA_URI, location = xaisen_contract::worker_store)]
fun empty_metadata_uri_aborts() {
    worker_accessors::validate_metadata_for_testing(vector[], test_fixtures::hash(1));
}

#[test]
#[expected_failure(abort_code = E_INVALID_METADATA_HASH, location = xaisen_contract::worker_store)]
fun invalid_metadata_hash_aborts() {
    worker_accessors::validate_metadata_for_testing(test_fixtures::uri(), vector[1]);
}

#[test]
#[expected_failure(abort_code = E_INSUFFICIENT_STAKE, location = xaisen_contract::worker_store)]
fun insufficient_stake_aborts() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 3);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        coin::mint_for_testing<TEST_COIN>(worker_accessors::min_worker_stake_for_testing() - 1, &mut ctx),
        &clock, &mut ctx,
    );

    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_PRICE, location = xaisen_contract::worker_store)]
fun invalid_zero_price_aborts() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 4);
    let clock = clock::create_for_testing(&mut ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    workers::register_worker(&mut reg, test_fixtures::uri(), test_fixtures::hash(1), 0, test_fixtures::stake(&mut ctx), &clock, &mut ctx);

    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun owner_can_update_metadata_and_price() {
    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 5);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut reg = test_fixtures::registered_registry(&clock, &mut ctx);

    clock::set_for_testing(&mut clock, 2000);
    workers::update_worker_metadata(&mut reg, 1, test_fixtures::updated_uri(), test_fixtures::hash(2), &clock, &mut ctx);
    workers::update_worker_price(&mut reg, 1, test_fixtures::price() + 100, &mut ctx);

    assert!(worker_accessors::worker_metadata_uri(reg.workers(), 1) == test_fixtures::updated_uri());
    assert!(worker_accessors::worker_metadata_hash(reg.workers(), 1) == test_fixtures::hash(2));
    assert!(worker_accessors::worker_updated_at_ms(reg.workers(), 1) == 2000);
    assert!(worker_accessors::worker_price_per_rental(reg.workers(), 1) == test_fixtures::price() + 100);

    workers::unregister_worker(&mut reg, 1, &mut ctx);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_NODE_OWNER, location = xaisen_contract::worker_store)]
fun non_owner_cannot_update_metadata() {
    worker_accessors::assert_worker_owner_for_testing(test_fixtures::owner(), test_fixtures::other());
}
