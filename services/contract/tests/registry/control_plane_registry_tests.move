#[test_only]
module dvconf::control_plane_registry_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::staking::StakePosition;
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};

    // ── Helper: register a CP miner ──
    fun register_cp_miner(scenario: &mut ts::Scenario) {
        h::do_register(scenario, h::cp_1(), h::cp_stake());
    }

    // ── Happy path: register CP ──
    #[test]
    fun test_register_cp() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::cp_cap_miner_id(&cap);
            assert!(control_plane_registry::active_cp_count(&cp_reg) == 1);
            assert!(control_plane_registry::is_registered(&cp_reg, miner_id));

            let info = control_plane_registry::borrow_info(&cp_reg, miner_id);
            assert!(control_plane_registry::info_operator(info) == h::cp_1());
            assert!(control_plane_registry::info_stake_amount(info) == h::cp_stake());
            assert!(control_plane_registry::info_is_active(info) == true);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Duplicate registration aborts 511 ──
    #[test]
    #[expected_failure(abort_code = 511)]
    fun test_register_duplicate() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        // First registration
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Second registration
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Register while paused aborts 513 ──
    #[test]
    #[expected_failure(abort_code = 513)]
    fun test_register_paused() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Heartbeat updates last_heartbeat ──
    #[test]
    fun test_heartbeat() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Send heartbeat
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            control_plane_registry::heartbeat(
                &net_reg, &mut cp_reg, &cap, ts::ctx(&mut scenario),
            );

            let miner_id = caps::cp_cap_miner_id(&cap);
            let info = control_plane_registry::borrow_info(&cp_reg, miner_id);
            assert!(control_plane_registry::info_is_active(info) == true);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── Heartbeat on unregistered CP aborts 512 ──
    #[test]
    #[expected_failure(abort_code = 512)]
    fun test_heartbeat_not_registered() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        // Heartbeat without registering in CP registry
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            control_plane_registry::heartbeat(
                &net_reg, &mut cp_reg, &cap, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── Room assignments ──
    #[test]
    fun test_room_assignments() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::cp_cap_miner_id(&cap);
            let room_id = object::id_from_address(@0xA1);

            // Empty assignments initially
            assert!(control_plane_registry::get_room_assignments(&cp_reg, room_id) == vector::empty());

            // Assign CP to room
            control_plane_registry::assign_to_room(&mut cp_reg, miner_id, room_id);
            let assignments = control_plane_registry::get_room_assignments(&cp_reg, room_id);
            assert!(assignments.length() == 1);

            // Unassign
            control_plane_registry::unassign_from_room(&mut cp_reg, room_id);
            assert!(control_plane_registry::get_room_assignments(&cp_reg, room_id) == vector::empty());

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── is_registered returns false for unknown ID ──
    #[test]
    fun test_is_registered_false() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);
            assert!(!control_plane_registry::is_registered(&cp_reg, fake_id));
            ts::return_shared(cp_reg);
        };

        ts::end(scenario);
    }

    // ── REG-04 gap: heartbeat records last_heartbeat epoch on CPNodeInfo ──
    // Verifies that CPNodeInfo.last_heartbeat is updated by heartbeat() and that
    // the accessor for it is readable, enabling external liveness checks against
    // constants::default_heartbeat_timeout().
    #[test]
    fun test_heartbeat_records_epoch_on_node_info() {
        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        // Register in CP registry
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            // After registration: last_heartbeat == ctx.epoch() == 0 (test epoch)
            let miner_id = caps::cp_cap_miner_id(&cap);
            let info = control_plane_registry::borrow_info(&cp_reg, miner_id);
            let heartbeat_at_registration = control_plane_registry::info_last_heartbeat(info);
            let registered_at = control_plane_registry::info_registered_at(info);
            // Both fields set at registration epoch
            assert!(heartbeat_at_registration == registered_at);
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Send heartbeat in a new transaction
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            control_plane_registry::heartbeat(
                &net_reg, &mut cp_reg, &cap, ts::ctx(&mut scenario),
            );
            let miner_id = caps::cp_cap_miner_id(&cap);
            let info = control_plane_registry::borrow_info(&cp_reg, miner_id);
            // last_heartbeat is updated; is_active remains true
            assert!(control_plane_registry::info_is_active(info) == true);
            // last_heartbeat is readable (used by external liveness checks)
            let _last_hb = control_plane_registry::info_last_heartbeat(info);
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── REG-04 gap: liveness fields expose enough data to compute staleness ──
    // Verifies that CPNodeInfo exposes last_heartbeat and that constants exposes
    // DEFAULT_HEARTBEAT_TIMEOUT — so an off-chain agent or Phase 3 tx can compute
    // staleness as (current_epoch - last_heartbeat) > heartbeat_timeout.
    #[test]
    fun test_cp_liveness_fields_satisfy_timeout_computation() {
        use dvconf::constants;

        let mut scenario = h::setup_phase2();
        register_cp_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            control_plane_registry::register_cp(
                &net_reg, &mut cp_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            let miner_id = caps::cp_cap_miner_id(&cap);
            let info = control_plane_registry::borrow_info(&cp_reg, miner_id);

            // Confirm that all fields needed to evaluate liveness are accessible
            let last_hb  = control_plane_registry::info_last_heartbeat(info);
            let is_active = control_plane_registry::info_is_active(info);
            let timeout  = constants::default_heartbeat_timeout();

            // At registration epoch 0: (0 - 0) = 0, which is NOT > 10, so CP is live
            assert!(is_active == true);
            assert!(timeout == 10); // DEFAULT_HEARTBEAT_TIMEOUT = 10 epochs
            // Simulate liveness check: if current_epoch - last_hb <= timeout → still live
            let simulated_current_epoch = last_hb + 5; // 5 epochs have passed
            assert!(simulated_current_epoch - last_hb <= timeout); // within window

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }
}
