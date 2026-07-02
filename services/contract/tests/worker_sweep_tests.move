#[test_only]
module xaisen_contract::worker_sweep_tests;

use sui::clock;
use xaisen_contract::registry;
use xaisen_contract::test_fixtures::{Self, TEST_COIN};
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

const STALE_THRESHOLD_MS: u64 = 1_800_000; // 30 minutes, mirrors worker_store::STALE_THRESHOLD_MS

#[test]
fun stale_worker_deactivated_on_new_registration() {
    let mut ctx1 = test_fixtures::ctx(test_fixtures::owner(), 900);
    let mut clock = clock::create_for_testing(&mut ctx1);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx1);

    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        test_fixtures::stake(&mut ctx1), &clock, &mut ctx1,
    );

    clock::set_for_testing(&mut clock, STALE_THRESHOLD_MS + 1);
    let mut ctx2 = test_fixtures::ctx(test_fixtures::other(), 901);
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(),
        test_fixtures::stake(&mut ctx2), &clock, &mut ctx2,
    );

    assert!(!worker_accessors::worker_active(reg.workers(), 1));
    assert!(worker_accessors::worker_active(reg.workers(), 2));
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 1);

    let mut cleanup_ctx1 = test_fixtures::ctx(test_fixtures::owner(), 902);
    workers::unregister_worker(&mut reg, 1, &mut cleanup_ctx1);
    let mut cleanup_ctx2 = test_fixtures::ctx(test_fixtures::other(), 903);
    workers::unregister_worker(&mut reg, 2, &mut cleanup_ctx2);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun non_stale_worker_untouched() {
    let mut ctx1 = test_fixtures::ctx(test_fixtures::owner(), 910);
    let mut clock = clock::create_for_testing(&mut ctx1);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx1);

    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        test_fixtures::stake(&mut ctx1), &clock, &mut ctx1,
    );

    clock::set_for_testing(&mut clock, STALE_THRESHOLD_MS - 1);
    let mut ctx2 = test_fixtures::ctx(test_fixtures::other(), 911);
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(),
        test_fixtures::stake(&mut ctx2), &clock, &mut ctx2,
    );

    assert!(worker_accessors::worker_active(reg.workers(), 1));
    assert!(worker_accessors::worker_active(reg.workers(), 2));
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 2);

    let mut cleanup_ctx1 = test_fixtures::ctx(test_fixtures::owner(), 912);
    workers::unregister_worker(&mut reg, 1, &mut cleanup_ctx1);
    let mut cleanup_ctx2 = test_fixtures::ctx(test_fixtures::other(), 913);
    workers::unregister_worker(&mut reg, 2, &mut cleanup_ctx2);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun newly_registered_worker_never_swept_by_its_own_call() {
    let mut ctx1 = test_fixtures::ctx(test_fixtures::owner(), 920);
    let mut clock = clock::create_for_testing(&mut ctx1);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx1);

    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        test_fixtures::stake(&mut ctx1), &clock, &mut ctx1,
    );

    clock::set_for_testing(&mut clock, STALE_THRESHOLD_MS * 10);
    let mut ctx2 = test_fixtures::ctx(test_fixtures::other(), 921);
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(),
        test_fixtures::stake(&mut ctx2), &clock, &mut ctx2,
    );

    assert!(worker_accessors::worker_active(reg.workers(), 2));
    assert!(worker_accessors::worker_updated_at_ms(reg.workers(), 2) == STALE_THRESHOLD_MS * 10);

    let mut cleanup_ctx1 = test_fixtures::ctx(test_fixtures::owner(), 922);
    workers::unregister_worker(&mut reg, 1, &mut cleanup_ctx1);
    let mut cleanup_ctx2 = test_fixtures::ctx(test_fixtures::other(), 923);
    workers::unregister_worker(&mut reg, 2, &mut cleanup_ctx2);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun heartbeat_worker_prevents_sweep() {
    let mut ctx1 = test_fixtures::ctx(test_fixtures::owner(), 930);
    let mut clock = clock::create_for_testing(&mut ctx1);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx1);

    // Registered at t=0.
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        test_fixtures::stake(&mut ctx1), &clock, &mut ctx1,
    );

    // Heartbeat at t=1_000_000 resets updated_at_ms.
    clock::set_for_testing(&mut clock, 1_000_000);
    workers::heartbeat_worker(&mut reg, 1, &clock, &mut ctx1);

    // t=2_000_000: elapsed since original registration (2_000_000) exceeds the
    // threshold, but elapsed since the heartbeat (1_000_000) does not.
    clock::set_for_testing(&mut clock, 2_000_000);
    let mut ctx2 = test_fixtures::ctx(test_fixtures::other(), 931);
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(2), test_fixtures::price(),
        test_fixtures::stake(&mut ctx2), &clock, &mut ctx2,
    );

    assert!(worker_accessors::worker_active(reg.workers(), 1));
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == 2);

    let mut cleanup_ctx1 = test_fixtures::ctx(test_fixtures::owner(), 932);
    workers::unregister_worker(&mut reg, 1, &mut cleanup_ctx1);
    let mut cleanup_ctx2 = test_fixtures::ctx(test_fixtures::other(), 933);
    workers::unregister_worker(&mut reg, 2, &mut cleanup_ctx2);
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}

#[test]
fun sweep_cap_bounds_a_single_call_safely() {
    let cap = worker_accessors::sweep_cap_for_testing();
    let extra = 5;
    let total_before_trigger = cap + extra; // 205 with cap=200

    let mut ctx = test_fixtures::ctx(test_fixtures::owner(), 940);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    let mut i = 0;
    while (i < total_before_trigger) {
        workers::register_worker(
            &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
            test_fixtures::stake(&mut ctx), &clock, &mut ctx,
        );
        i = i + 1;
    };
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == total_before_trigger);

    clock::set_for_testing(&mut clock, STALE_THRESHOLD_MS + 1);

    // Registration (total_before_trigger + 1) triggers a sweep capped at `cap` ids.
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        test_fixtures::stake(&mut ctx), &clock, &mut ctx,
    );
    let after_first_sweep = total_before_trigger + 1 - cap; // 205 + 1 - 200 = 6
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == after_first_sweep);
    assert!(!worker_accessors::worker_active(reg.workers(), 1));
    assert!(!worker_accessors::worker_active(reg.workers(), cap));
    assert!(worker_accessors::worker_active(reg.workers(), cap + 1));

    // A second registration re-sweeps ids 1..cap (already inactive, safe no-op)
    // rather than continuing past the cap, since there is no persisted cursor.
    workers::register_worker(
        &mut reg, test_fixtures::uri(), test_fixtures::hash(1), test_fixtures::price(),
        test_fixtures::stake(&mut ctx), &clock, &mut ctx,
    );
    assert!(worker_accessors::active_worker_count_for_testing(reg.workers()) == after_first_sweep + 1);

    let total_registered = total_before_trigger + 2;
    let mut node_id = 1;
    while (node_id <= total_registered) {
        workers::unregister_worker(&mut reg, node_id, &mut ctx);
        node_id = node_id + 1;
    };
    registry::destroy_registry_for_testing(reg);
    clock::destroy_for_testing(clock);
}
