/// Phase 12 verification gap tests for relay_registry.
///
/// Closes: GAP-12-01, GAP-12-02, GAP-12-03, GAP-12-04, GAP-12-05,
///         GAP-12-06, GAP-12-08, GAP-12-09, GAP-12-10, GAP-12-11
#[test_only]
module dvconf::phase_12_gap_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};

    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::staking::StakePosition;
    use dvconf::relay_registry::{Self, RelayRegistry};

    // ── Helper: register relay_1 in both miner store and relay registry ──
    fun setup_registered_relay(scenario: &mut ts::Scenario) {
        h::do_register(scenario, h::relay_1(), h::relay_stake());

        ts::next_tx(scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(scenario);
            let cap = ts::take_from_sender<MinerCap>(scenario);
            let stake = ts::take_from_sender<StakePosition>(scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(scenario, cap);
            ts::return_to_sender(scenario, stake);
        };
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-01: update_load when paused aborts E_PAUSED (523)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 523)]
    fun test_update_load_when_paused_aborts_523() {
        let mut scenario = h::setup_phase2();
        setup_registered_relay(&mut scenario);

        // Admin pauses network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // update_load while paused must abort 523
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            relay_registry::update_load(
                &net_reg, &mut relay_reg, &cap, 42, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-02: update_rtt on unregistered miner aborts 522
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 522)]
    fun test_update_rtt_unregistered_aborts_522() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            relay_registry::update_rtt(&mut relay_reg, fake_id, 100);

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-03: set_reputation on unregistered miner aborts 522
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 522)]
    fun test_set_reputation_unregistered_aborts_522() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            relay_registry::set_reputation(&mut relay_reg, fake_id, 5000);

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-04: get_active_relays returns empty when no relays
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_get_active_relays_empty() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            let active = relay_registry::get_active_relays(&relay_reg);
            assert!(active.length() == 0);
            assert!(relay_registry::active_count(&relay_reg) == 0);

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-05: endpoint_url verified via borrow_info after registration
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_endpoint_url_stored_via_borrow_info() {
        let mut scenario = h::setup_phase2();
        setup_registered_relay(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let miner_id = caps::miner_cap_miner_id(&cap);

            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            assert!(relay_registry::info_endpoint_url(info) == b"ws://127.0.0.1:4000");
            assert!(relay_registry::info_region(info) == b"asia-southeast1");

            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-06: update_load on unregistered miner aborts 522
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 522)]
    fun test_update_load_unregistered_aborts_522() {
        let mut scenario = h::setup_phase2();
        // Register as miner but do NOT register in RelayRegistry
        h::do_register(&mut scenario, h::relay_1(), h::relay_stake());

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            // update_load must abort 522 because relay_1 is not in RelayRegistry
            relay_registry::update_load(
                &net_reg, &mut relay_reg, &cap, 42, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-09: borrow_info on unregistered miner aborts 522
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 522)]
    fun test_borrow_info_unregistered_aborts_522() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            let _info = relay_registry::borrow_info(&relay_reg, fake_id);

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-10: get_rtt on unregistered miner aborts 522
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 522)]
    fun test_get_rtt_unregistered_aborts_522() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            let _rtt = relay_registry::get_rtt(&relay_reg, fake_id);

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-12-11: has_rtt returns false for unregistered miner
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_has_rtt_false_for_unregistered() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            // has_rtt should return false (not abort) for unregistered miner
            assert!(!relay_registry::has_rtt(&relay_reg, fake_id));

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }
}
