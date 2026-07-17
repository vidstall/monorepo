/// UC6 — Governance tests for network_registry.move
#[test_only]
module dvconf::network_registry_tests {
    use sui::test_scenario as ts;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::test_helpers;

    // ── UC6: GOVERNANCE ──────────────────────────────────────────────────

    #[test]
    fun test_governance_update_thresholds() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            network_registry::update_role_thresholds(
                &admin_cap, &mut registry,
                1_000_000_000, // cp
                  500_000_000, // relay
                  100_000_000, // validator
                   50_000_000, // signaling
            );

            let t = network_registry::role_thresholds(&registry);
            assert!(network_registry::cp_threshold(&t)        == 1_000_000_000);
            assert!(network_registry::relay_threshold(&t)     ==   500_000_000);
            assert!(network_registry::validator_threshold(&t) ==   100_000_000);
            assert!(network_registry::signaling_threshold(&t) ==    50_000_000);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 101)] // E_INVALID_THRESHOLD
    fun test_governance_invalid_thresholds() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            // cp < relay → must abort
            network_registry::update_role_thresholds(
                &admin_cap, &mut registry,
                  500_000_000, // cp  (lower than relay)
                1_000_000_000, // relay
                  100_000_000, // validator
                   50_000_000, // signaling
            );

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_governance_update_weights() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            // All equal: 2000 × 5 = 10 000
            network_registry::update_scoring_weights(
                &admin_cap, &mut registry,
                2000, 2000, 2000, 2000, 2000,
            );

            let w = network_registry::scoring_weights(&registry);
            assert!(network_registry::w_reputation(&w) == 2000);
            assert!(network_registry::w_rtt(&w)        == 2000);
            assert!(network_registry::w_load(&w)       == 2000);
            assert!(network_registry::w_stake(&w)      == 2000);
            assert!(network_registry::w_region(&w)     == 2000);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 100)] // E_INVALID_WEIGHT
    fun test_governance_invalid_weights() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            // sum = 9 000, not 10 000 → must abort
            network_registry::update_scoring_weights(
                &admin_cap, &mut registry,
                2000, 2000, 2000, 2000, 1000,
            );

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_governance_update_base_rate() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            network_registry::update_base_rate(&admin_cap, &mut registry, 500);

            assert!(network_registry::base_rate_per_mb(&registry) == 500);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_governance_pause_unpause() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            assert!(!network_registry::is_paused(&registry));

            network_registry::set_paused(&admin_cap, &mut registry, true);
            assert!(network_registry::is_paused(&registry));

            network_registry::set_paused(&admin_cap, &mut registry, false);
            assert!(!network_registry::is_paused(&registry));

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_governance_update_reward_ratios() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            // 6000 + 2500 + 1500 = 10 000
            network_registry::update_reward_ratios(
                &admin_cap, &mut registry,
                6000, 2500, 1500,
            );

            let r = network_registry::reward_ratios(&registry);
            assert!(network_registry::ratio_relay(&r)     == 6000);
            assert!(network_registry::ratio_validator(&r) == 2500);
            assert!(network_registry::ratio_cp(&r)        == 1500);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 102)] // E_INVALID_RATIO
    fun test_governance_invalid_reward_ratios() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            // sum = 9 000, not 10 000 → must abort
            network_registry::update_reward_ratios(
                &admin_cap, &mut registry,
                6000, 2000, 1000,
            );

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 101)] // E_INVALID_THRESHOLD
    fun test_governance_invalid_thresholds_relay_below_validator() {
        let mut scenario = test_helpers::setup();

        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);

            // relay < validator → must abort
            network_registry::update_role_thresholds(
                &admin_cap, &mut registry,
                2_000_000_000, // cp (valid)
                  100_000_000, // relay (lower than validator)
                  500_000_000, // validator
                  250_000_000, // signaling
            );

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::end(scenario);
    }
}
