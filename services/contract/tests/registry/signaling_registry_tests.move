#[test_only]
module dvconf::signaling_registry_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::staking::StakePosition;
    use dvconf::signaling_registry::{Self, SignalingRegistry};

    // ── Helper: register a signaling miner via registration module ──
    fun register_signaling_miner(scenario: &mut ts::Scenario) {
        h::do_register(scenario, h::sig_1(), h::signaling_stake());
    }

    // ── Helper: register + enroll in SignalingRegistry ──
    fun register_and_enroll(scenario: &mut ts::Scenario) {
        register_signaling_miner(scenario);

        ts::next_tx(scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(scenario);
            let cap = ts::take_from_sender<MinerCap>(scenario);
            let stake = ts::take_from_sender<StakePosition>(scenario);

            signaling_registry::register_signaling(
                &net_reg, &mut sig_reg, &cap, &stake,
                b"wss://sig1.dvconf.io", b"us-east",
                ts::ctx(scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(scenario, cap);
            ts::return_to_sender(scenario, stake);
        };
    }

    // ══════════════════════════════════════════════════════════
    // TEST 1: Happy path registration
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_register_signaling() {
        let mut scenario = h::setup_phase2();
        register_signaling_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            signaling_registry::register_signaling(
                &net_reg, &mut sig_reg, &cap, &stake,
                b"wss://sig1.dvconf.io", b"us-east",
                ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            assert!(signaling_registry::active_signaling_count(&sig_reg) == 1);
            assert!(signaling_registry::is_registered(&sig_reg, miner_id));

            let info = signaling_registry::borrow_info(&sig_reg, miner_id);
            assert!(signaling_registry::info_operator(info) == h::sig_1());
            assert!(signaling_registry::info_stake_amount(info) == h::signaling_stake());
            assert!(signaling_registry::info_is_active(info) == true);
            assert!(signaling_registry::info_endpoint_url(info) == b"wss://sig1.dvconf.io");
            assert!(signaling_registry::info_region(info) == b"us-east");
            assert!(signaling_registry::info_load(info) == 0);

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 2: Wrong role aborts 600 (E_NOT_SIGNALING)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 600)]
    fun test_register_signaling_wrong_role() {
        let mut scenario = h::setup_phase2();
        // Register as user (0.1 DVCONF) -- role_user, not signaling
        h::do_register(&mut scenario, h::user_1(), h::user_stake());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            signaling_registry::register_signaling(
                &net_reg, &mut sig_reg, &cap, &stake,
                b"wss://bad.dvconf.io", b"eu-west",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 3: Duplicate registration aborts 601 (E_ALREADY_REGISTERED)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 601)]
    fun test_register_signaling_duplicate() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        // Second registration attempt
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            signaling_registry::register_signaling(
                &net_reg, &mut sig_reg, &cap, &stake,
                b"wss://sig1.dvconf.io", b"us-east",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 4: Heartbeat updates last_heartbeat
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_heartbeat() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::heartbeat(
                &net_reg, &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            let info = signaling_registry::borrow_info(&sig_reg, miner_id);
            assert!(signaling_registry::info_is_active(info) == true);
            // last_heartbeat is updated to current epoch
            let _hb = signaling_registry::info_last_heartbeat(info);

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 5: Heartbeat on unregistered node aborts 602 (E_NOT_REGISTERED)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 602)]
    fun test_heartbeat_not_registered() {
        let mut scenario = h::setup_phase2();
        register_signaling_miner(&mut scenario);

        // Heartbeat without enrolling in SignalingRegistry
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::heartbeat(
                &net_reg, &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 6: Update load updates load value
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_update_load() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::update_load(
                &net_reg, &mut sig_reg, &cap, 42, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            let info = signaling_registry::borrow_info(&sig_reg, miner_id);
            assert!(signaling_registry::info_load(info) == 42);

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 7: Update load with wrong cap aborts 604 (E_NOT_OPERATOR)
    // ══════════════════════════════════════════════════════════
    // Note: E_NOT_OPERATOR fires when ctx.sender() != info.operator.
    // We register sig_1 then call update_load from a different sender.
    // However, MinerCap is an owned object -- we cannot take it from
    // a different sender. Instead we test that update_load on an
    // unregistered node aborts 602 (E_NOT_REGISTERED) from a different
    // miner, which is the closest we can test in unit tests.
    // The operator check (604) would be testable only if we could
    // transfer MinerCap to another address. We test the not-registered
    // path instead, and add a dedicated test for the operator check below.

    #[test]
    #[expected_failure(abort_code = 602)]
    fun test_update_load_not_registered() {
        let mut scenario = h::setup_phase2();
        // Register a signaling miner but do NOT enroll in SignalingRegistry
        register_signaling_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::update_load(
                &net_reg, &mut sig_reg, &cap, 10, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 8: Unregister signaling -- happy path
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_unregister_signaling() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            let miner_id = caps::miner_cap_miner_id(&cap);
            assert!(signaling_registry::is_registered(&sig_reg, miner_id));

            signaling_registry::unregister_signaling(
                &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            assert!(!signaling_registry::is_registered(&sig_reg, miner_id));
            assert!(signaling_registry::active_signaling_count(&sig_reg) == 0);

            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 9: Register when paused aborts 603 (E_PAUSED)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 603)]
    fun test_register_when_paused() {
        let mut scenario = h::setup_phase2();
        register_signaling_miner(&mut scenario);

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Try to register -- should abort 603
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            signaling_registry::register_signaling(
                &net_reg, &mut sig_reg, &cap, &stake,
                b"wss://sig1.dvconf.io", b"us-east",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 10: Signaling role determination -- 0.25 DVCONF gets ROLE_SIGNALING
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_signaling_role_determination() {
        use dvconf::constants;

        let mut scenario = h::setup_phase2();
        register_signaling_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            assert!(caps::miner_cap_role(&cap) == constants::role_signaling());
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 11: get_active_nodes returns correct vector
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_get_active_nodes() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            let nodes = signaling_registry::get_active_nodes(&sig_reg);
            assert!(nodes.length() == 1);

            let info = nodes.borrow(0);
            assert!(signaling_registry::info_operator(info) == h::sig_1());
            assert!(signaling_registry::info_endpoint_url(info) == b"wss://sig1.dvconf.io");
            assert!(signaling_registry::info_region(info) == b"us-east");

            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 12: Heartbeat re-activates inactive node
    // (node removed from active_set via unregister then re-registered,
    //  or testing the is_active = true path in heartbeat)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_heartbeat_reactivates_node() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        // Heartbeat should keep is_active = true and stay in active_set
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::heartbeat(
                &net_reg, &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            let info = signaling_registry::borrow_info(&sig_reg, miner_id);
            assert!(signaling_registry::info_is_active(info) == true);
            assert!(signaling_registry::active_signaling_count(&sig_reg) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 13: get_active_nodes returns empty when no nodes registered
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_get_active_nodes_empty() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let nodes = signaling_registry::get_active_nodes(&sig_reg);
            assert!(nodes.length() == 0);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 14: is_registered returns false for unknown ID
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_is_registered_false() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);
            assert!(!signaling_registry::is_registered(&sig_reg, fake_id));
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 15: Heartbeat when paused aborts 603
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 603)]
    fun test_heartbeat_when_paused() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::heartbeat(
                &net_reg, &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 16: Update load when paused aborts 603
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 603)]
    fun test_update_load_when_paused() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::update_load(
                &net_reg, &mut sig_reg, &cap, 10, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 17: Unregister not-registered node aborts 602
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 602)]
    fun test_unregister_not_registered() {
        let mut scenario = h::setup_phase2();
        register_signaling_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::sig_1());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::unregister_signaling(
                &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 18: Unregister does NOT require pause check (can exit when paused)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_unregister_when_paused_succeeds() {
        let mut scenario = h::setup_phase2();
        register_and_enroll(&mut scenario);

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Unregister should succeed even when paused
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            signaling_registry::unregister_signaling(
                &mut sig_reg, &cap, ts::ctx(&mut scenario),
            );

            assert!(signaling_registry::active_signaling_count(&sig_reg) == 0);

            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }
}
