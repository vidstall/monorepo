/// Phase 14 verification gap tests.
///
/// Closes coverage gaps identified by the Verification Agent RTM:
///   GAP-14-01: assign_relay_and_signaling when paused aborts E_PAUSED (500)
///   GAP-14-02: get_room_assignment on non-existent room aborts E_NOT_FOUND (502)
///   GAP-14-03: remove_if_registered cross-registry cleanup on unregister
///   GAP-14-04: assign_relay_and_signaling on ACTIVE room succeeds (failover)
///   GAP-14-05: assign_relay_and_signaling on READY room succeeds
#[test_only]
module dvconf::phase_14_gap_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::relay_registry::RelayRegistry;
    use dvconf::validator_registry::ValidatorRegistry;
    use dvconf::control_plane_registry::ControlPlaneRegistry;
    use dvconf::miner_store::MinerStore;
    use dvconf::registration;

    // Deterministic IDs for assignment tests
    fun test_room_id(): ID   { object::id_from_address(@0x1001) }
    fun test_relay_id(): ID  { object::id_from_address(@0x2001) }
    fun test_sig_id(): ID    { object::id_from_address(@0x3001) }

    // ══════════════════════════════════════════════════════════
    // GAP-14-01: assign_relay_and_signaling when paused aborts 500
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 500)]
    fun test_assign_when_paused_aborts_500() {
        let mut scenario = h::setup_phase2();

        // Add a PENDING room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, test_room_id(), h::user_1(),
                constants::room_status_pending(), constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
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

        // Assignment while paused must abort 500 (AdminCap-gated)
        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);

            room_manager::assign_relay_and_signaling(
                &net_reg, &mut manager, &admin_cap,
                test_room_id(), test_relay_id(), test_sig_id(),
            );

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-14-02: get_room_assignment on non-existent room aborts 502
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 502)]
    fun test_get_assignment_nonexistent_room_aborts_502() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::user_1());
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let fake_room_id = object::id_from_address(@0xDEAD);

            let (_relay_opt, _sig_opt) = room_manager::get_room_assignment(
                &manager, fake_room_id,
            );

            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-14-03: remove_if_registered cross-registry cleanup
    // When a signaling miner unregisters via registration::unregister,
    // the SignalingRegistry entry is silently removed.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_unregister_cleans_signaling_registry() {
        let mut scenario = h::setup_phase2();

        // Register a signaling miner
        h::do_register(&mut scenario, h::sig_1(), h::signaling_stake());

        // Enroll in SignalingRegistry
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
            assert!(signaling_registry::is_registered(&sig_reg, miner_id));
            assert!(signaling_registry::active_signaling_count(&sig_reg) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Unregister via registration::unregister (consumes StakePosition)
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            let miner_id = staking::miner_id(&pos);

            registration::unregister(
                &mut store, &mut sig_reg,
                &mut relay_reg, &mut val_reg, &mut cp_reg,
                pos, ts::ctx(&mut scenario),
            );

            // Verify signaling entry was cleaned up (TD-P11-04)
            assert!(!signaling_registry::is_registered(&sig_reg, miner_id));
            assert!(signaling_registry::active_signaling_count(&sig_reg) == 0);

            ts::return_shared(store);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-14-04: assign_relay_and_signaling on ACTIVE room succeeds
    // Proves failover reassignment is supported (IMP-3). AdminCap-gated.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_assign_active_room_succeeds() {
        let mut scenario = h::setup_phase2();

        // Add an ACTIVE room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, test_room_id(), h::user_1(),
                constants::room_status_active(), constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

        // Assignment on ACTIVE room should succeed (AdminCap-gated)
        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);

            room_manager::assign_relay_and_signaling(
                &net_reg, &mut manager, &admin_cap,
                test_room_id(), test_relay_id(), test_sig_id(),
            );

            let (relay_ids, sig_opt) = room_manager::get_room_assignment(
                &manager, test_room_id(),
            );
            assert!(relay_ids == vector[test_relay_id()]);
            assert!(sig_opt == option::some(test_sig_id()));

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // GAP-14-05: assign_relay_and_signaling on READY room succeeds
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_assign_ready_room_succeeds() {
        let mut scenario = h::setup_phase2();

        // Add a READY room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, test_room_id(), h::user_1(),
                constants::room_status_ready(), constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

        // Assignment on READY room should succeed (AdminCap-gated)
        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);

            room_manager::assign_relay_and_signaling(
                &net_reg, &mut manager, &admin_cap,
                test_room_id(), test_relay_id(), test_sig_id(),
            );

            let info = room_manager::borrow_room(&manager, test_room_id());
            assert!(room_manager::room_assigned_relay(info) == option::some(test_relay_id()));
            assert!(room_manager::room_assigned_signaling(info) == option::some(test_sig_id()));

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }
}
