#[test_only]
module dvconf::relay_registry_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::staking::StakePosition;
    use dvconf::relay_registry::{Self, RelayRegistry};

    // ── Helper: register a relay miner ──
    fun register_relay_miner(scenario: &mut ts::Scenario) {
        h::do_register(scenario, h::relay_1(), h::relay_stake());
    }

    // ── Happy path: register relay ──
    #[test]
    fun test_register_relay() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            assert!(relay_registry::active_count(&relay_reg) == 1);
            assert!(relay_registry::is_registered(&relay_reg, miner_id));

            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            assert!(relay_registry::info_operator(info) == h::relay_1());
            assert!(relay_registry::info_stake_amount(info) == h::relay_stake());
            assert!(relay_registry::info_region(info) == b"asia-southeast1");
            assert!(relay_registry::info_reputation(info) == constants::default_initial_reputation());

            // Load starts at 0
            assert!(relay_registry::get_load(&relay_reg, miner_id) == 0);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Wrong role aborts 520 ──
    #[test]
    #[expected_failure(abort_code = 520)]
    fun test_register_wrong_role() {
        let mut scenario = h::setup_phase2();
        h::do_register(&mut scenario, h::val_1(), h::validator_stake());

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"us-east1",
                b"ws://127.0.0.1:4001",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Duplicate registration aborts 521 ──
    #[test]
    #[expected_failure(abort_code = 521)]
    fun test_register_duplicate() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Second registration
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"us-east1",
                b"ws://127.0.0.1:4001",
                ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Register while paused aborts 523 ──
    #[test]
    #[expected_failure(abort_code = 523)]
    fun test_register_paused() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Update load ──
    #[test]
    fun test_update_load() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        // Register in relay registry
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Update load
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            relay_registry::update_load(
                &net_reg, &mut relay_reg, &cap, 42, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            assert!(relay_registry::get_load(&relay_reg, miner_id) == 42);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── RTT update (package-only) ──
    #[test]
    fun test_update_rtt() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);

            // No RTT yet
            assert!(!relay_registry::has_rtt(&relay_reg, miner_id));

            // Set RTT (package-gated)
            relay_registry::update_rtt(&mut relay_reg, miner_id, 150);
            assert!(relay_registry::has_rtt(&relay_reg, miner_id));
            assert!(relay_registry::get_rtt(&relay_reg, miner_id) == 150);

            // Update RTT again
            relay_registry::update_rtt(&mut relay_reg, miner_id, 200);
            assert!(relay_registry::get_rtt(&relay_reg, miner_id) == 200);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── GAP-003: get_load on unregistered relay aborts 522 ──
    #[test]
    #[expected_failure(abort_code = 522)]
    fun test_get_load_unregistered_aborts_522() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            let _load = relay_registry::get_load(&relay_reg, fake_id);

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ── BUG-RR-01: update_load with wrong operator aborts 524 ──
    #[test]
    #[expected_failure(abort_code = 524)]
    fun test_update_load_wrong_operator() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        // Register relay_1 in relay registry
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, stake);

            // Transfer MinerCap to relay_2 so they possess relay_1's cap
            transfer::public_transfer(cap, h::relay_2());
        };

        // relay_2 calls update_load with relay_1's cap — sender != operator => abort 524
        ts::next_tx(&mut scenario, h::relay_2());
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

    // ── get_active_relays returns registered nodes ──
    #[test]
    fun test_get_active_relays() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            // Verify get_active_relays returns the registered node
            let active = relay_registry::get_active_relays(&relay_reg);
            assert!(active.length() == 1);

            let info = &active[0];
            assert!(relay_registry::info_operator(info) == h::relay_1());
            assert!(relay_registry::info_endpoint_url(info) == b"ws://127.0.0.1:4000");
            assert!(relay_registry::info_region(info) == b"asia-southeast1");

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Report degradation (happy path) ──
    #[test]
    fun test_report_degradation() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        // Register relay in relay registry
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Report degradation — should succeed (relay is registered)
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let miner_id = caps::miner_cap_miner_id(&cap);
            let room_id = object::id_from_address(@0xB00B);

            relay_registry::report_degradation(
                &relay_reg, room_id, miner_id, 350, 85, ts::ctx(&mut scenario),
            );

            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── Report degradation with unregistered relay aborts 525 ──
    #[test]
    #[expected_failure(abort_code = 525)]
    fun test_report_degradation_unregistered_relay() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let fake_miner_id = object::id_from_address(@0xDEAD);
            let room_id = object::id_from_address(@0xB00B);

            relay_registry::report_degradation(
                &relay_reg, room_id, fake_miner_id, 500, 90, ts::ctx(&mut scenario),
            );

            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // F40 BUG FIX — last_heartbeat field, getter, and refactored
    // relay_heartbeat() that writes on-chain state (M0 / TDD).
    // ══════════════════════════════════════════════════════════

    // ── F40: register_relay initialises info_last_heartbeat to current epoch ──
    #[test]
    fun test_register_relay_initializes_last_heartbeat() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            let registered_at = relay_registry::info_registered_at(info);
            let last_hb = relay_registry::info_last_heartbeat(info);
            // On registration, last_heartbeat == registered_at (both = ctx.epoch())
            assert!(last_hb == registered_at);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── F40: relay_heartbeat() updates on-chain last_heartbeat field ──
    #[test]
    fun test_relay_heartbeat_updates_last_heartbeat() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        // Register relay at epoch 0
        ts::next_tx(&mut scenario, h::relay_1());
        let initial_hb;
        let miner_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            miner_id = caps::miner_cap_miner_id(&cap);
            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            initial_hb = relay_registry::info_last_heartbeat(info);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Advance epochs
        ts::next_epoch(&mut scenario, h::relay_1());
        ts::next_epoch(&mut scenario, h::relay_1());
        ts::next_epoch(&mut scenario, h::relay_1());

        // Heartbeat at later epoch — last_heartbeat must update
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            relay_registry::relay_heartbeat(
                &net_reg, &mut relay_reg, &cap, ts::ctx(&mut scenario),
            );

            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            let new_hb = relay_registry::info_last_heartbeat(info);
            // Heartbeat must advance the stored epoch.
            assert!(new_hb > initial_hb);
            // registered_at must remain unchanged (separate field).
            assert!(relay_registry::info_registered_at(info) == initial_hb);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── F40: relay_heartbeat aborts 523 when network is paused ──
    #[test]
    #[expected_failure(abort_code = 523)]
    fun test_relay_heartbeat_fails_when_paused() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        // Register relay
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Pause network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Heartbeat must abort with E_PAUSED (523)
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            relay_registry::relay_heartbeat(
                &net_reg, &mut relay_reg, &cap, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── Reputation set ──
    #[test]
    fun test_set_reputation() {
        let mut scenario = h::setup_phase2();
        register_relay_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1",
                b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            relay_registry::set_reputation(&mut relay_reg, miner_id, 9_000);

            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            assert!(relay_registry::info_reputation(info) == 9_000);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }
}
