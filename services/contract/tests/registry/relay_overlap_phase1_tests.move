/// Relay Overlap Redundancy — Phase 1 Move tests (REQ-RO-001, RO-002, RO-003)
///
/// TDD:  RED phase written first (before room_manager.move additions).
///       GREEN phase passes after promote_relay + RelayPromoted are added.
///
/// RO-001: verify relay_heartbeat() writes last_heartbeat (F40 canonical path).
/// RO-002: verify submit_pairing_proposal enforces min_relay=2 and assigned_relays
///         slot semantics: [0]=primary, [1]=standby.
/// RO-003: promote_relay emits RelayPromoted on a stale-heartbeat promotion;
///         aborts E_RELAY_NOT_STALE (564) when heartbeat is still fresh.
#[test_only]
module dvconf::relay_overlap_phase1_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::caps::{Self, MinerCap, ControlPlaneCap};
    use dvconf::staking::StakePosition;
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::room_manager::{Self, RoomManager, RelayPromoted};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::user_registry::{Self, UserRegistry};

    // ── Deterministic test IDs ──
    fun room_id(): ID  { object::id_from_address(@0x5001) }

    // ── Addresses for test nodes ──
    const RELAY_A: address = @0xA1;
    const RELAY_B: address = @0xA2;
    const VAL_A:   address = @0xA3;
    const VAL_B:   address = @0xA4;
    const VAL_C:   address = @0xA5;
    const VAL_D:   address = @0xA6;
    const SIG_A:   address = @0xA7;
    const CP_A:    address = @0xA8;
    const CP_A_OP: address = @0xC8;

    fun relay_a_id(): ID { object::id_from_address(RELAY_A) }
    fun relay_b_id(): ID { object::id_from_address(RELAY_B) }
    fun val_a_id():   ID { object::id_from_address(VAL_A) }
    fun val_b_id():   ID { object::id_from_address(VAL_B) }
    fun val_c_id():   ID { object::id_from_address(VAL_C) }
    fun val_d_id():   ID { object::id_from_address(VAL_D) }
    fun sig_a_id():   ID { object::id_from_address(SIG_A) }
    fun cp_a_id():    ID { object::id_from_address(CP_A) }

    /// Setup scenario with two registered relays in RelayRegistry using add_relay_for_testing.
    fun setup_two_relays(): ts::Scenario {
        let mut scenario = h::setup_phase2();
        h::do_register(&mut scenario, h::relay_1(), h::relay_stake());
        h::do_register(&mut scenario, h::relay_2(), h::relay_stake());
        scenario
    }

    // ══════════════════════════════════════════════════════════
    // RO-001 verify — relay_heartbeat writes last_heartbeat (F40 canonical)
    // ══════════════════════════════════════════════════════════

    /// RO-001: relay_heartbeat() updates last_heartbeat on both primary and standby.
    /// Confirms the canonical source that promote_relay reads via borrow_info.
    #[test]
    fun test_ro_001_relay_heartbeat_writes_last_heartbeat_both_slots() {
        let mut scenario = setup_two_relays();

        // Register relay_1 in RelayRegistry at epoch 0
        ts::next_tx(&mut scenario, h::relay_1());
        let primary_miner_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay1:4000", ts::ctx(&mut scenario),
            );
            primary_miner_id = caps::miner_cap_miner_id(&cap);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Register relay_2 in RelayRegistry at epoch 0
        ts::next_tx(&mut scenario, h::relay_2());
        let standby_miner_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay2:4000", ts::ctx(&mut scenario),
            );
            standby_miner_id = caps::miner_cap_miner_id(&cap);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Advance 3 epochs so epoch > 0
        ts::next_epoch(&mut scenario, h::relay_1());
        ts::next_epoch(&mut scenario, h::relay_1());
        ts::next_epoch(&mut scenario, h::relay_1());

        // Primary relay heartbeats → last_heartbeat advances
        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            relay_registry::relay_heartbeat(&net_reg, &mut relay_reg, &cap, ts::ctx(&mut scenario));
            let info = relay_registry::borrow_info(&relay_reg, primary_miner_id);
            let hb = relay_registry::info_last_heartbeat(info);
            // last_heartbeat must advance beyond epoch-0 registration value
            assert!(hb > 0);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        // Standby relay also heartbeats (keep-alive path — RO-001 requirement)
        ts::next_tx(&mut scenario, h::relay_2());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            relay_registry::relay_heartbeat(&net_reg, &mut relay_reg, &cap, ts::ctx(&mut scenario));
            let info = relay_registry::borrow_info(&relay_reg, standby_miner_id);
            let hb = relay_registry::info_last_heartbeat(info);
            assert!(hb > 0);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    /// RO-001: info_last_heartbeat getter returns the F40-shipped field.
    /// Verifies the as-built read path that promote_relay uses.
    #[test]
    fun test_ro_001_info_last_heartbeat_getter_readable() {
        let mut scenario = setup_two_relays();

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay1:4000", ts::ctx(&mut scenario),
            );
            let miner_id = caps::miner_cap_miner_id(&cap);
            let info = relay_registry::borrow_info(&relay_reg, miner_id);
            // getter exists and returns u64 (registered at epoch 0)
            let hb: u64 = relay_registry::info_last_heartbeat(info);
            assert!(hb == 0); // epoch 0 at registration
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RO-002 verify — assigned_relays slot semantics
    // ══════════════════════════════════════════════════════════

    /// RO-002: assigned_relays[0]=primary, [1]=standby after assignment.
    /// Uses set_assigned_relays_for_testing to set up the expected state,
    /// then reads slots to confirm slot semantics are length-driven (not hardcoded).
    #[test]
    fun test_ro_002_assigned_relays_slot_semantics() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), h::user_1(),
                constants::room_status_ready(),
                constants::relay_mode_sfu(),
                1,
                ts::ctx(&mut scenario),
            );
            // Set 2 relays: [0]=primary, [1]=standby
            room_manager::set_assigned_relays_for_testing(
                &mut manager,
                room_id(),
                vector[relay_a_id(), relay_b_id()],
            );
            ts::return_shared(manager);
        };

        // Verify slot semantics
        ts::next_tx(&mut scenario, h::user_1());
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id());
            let relays = room_manager::room_assigned_relays(info);
            // Length >= 2 (K=2 scope, future-proof read)
            assert!(vector::length(&relays) >= 2);
            // slot [0] = primary
            assert!(*vector::borrow(&relays, 0) == relay_a_id());
            // slot [1] = standby
            assert!(*vector::borrow(&relays, 1) == relay_b_id());
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    /// RO-002: submit_pairing_proposal aborts E_INVALID_BALLOT (509) with only 1 relay.
    /// This confirms the on-chain min_relay=2 enforcement (DEFAULT_MIN_RELAYS_PER_ROOM=2).
    #[test]
    #[expected_failure(abort_code = 509)]
    fun test_ro_002_submit_pairing_aborts_on_single_relay() {
        let mut scenario = h::setup_phase2();

        // Use add_*_for_testing helpers (mirrors pvr_integration_tests.move setup pattern)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_a_id(), @0xB1, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_a_id(), @0xD1, 100_000_000, ts::ctx(&mut scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_b_id(), @0xD2, 100_000_000, ts::ctx(&mut scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_c_id(), @0xD3, 100_000_000, ts::ctx(&mut scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_d_id(), @0xD4, 100_000_000, ts::ctx(&mut scenario),
            );
            ts::return_shared(val_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            signaling_registry::add_signaling_for_testing(
                &mut sig_reg, sig_a_id(), @0xF1, ts::ctx(&mut scenario),
            );
            ts::return_shared(sig_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            control_plane_registry::add_cp_for_testing(
                &mut cp_reg, cp_a_id(), CP_A_OP, 500_000_000, ts::ctx(&mut scenario),
            );
            ts::return_shared(cp_reg);
        };

        // Create CP cap for cp_a
        ts::next_tx(&mut scenario, CP_A_OP);
        {
            let cap = caps::new_cp_cap(cp_a_id(), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_A_OP);
        };

        // Add PENDING room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), h::user_1(),
                constants::room_status_pending(),
                constants::relay_mode_sfu(),
                4, // 4 participants → required_validators = ceil(4/3) = 2 → use 4 to be safe
                ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

        // CP submits with only 1 relay — must abort E_INVALID_BALLOT (509)
        ts::next_tx(&mut scenario, CP_A_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            room_manager::submit_pairing_proposal(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                &cap,
                room_id(),
                vector[relay_a_id()], // only 1 relay — ABORT here (min_relay=2)
                vector[val_a_id(), val_b_id(), val_c_id(), val_d_id()],
                sig_a_id(),
                1000,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RO-003 — promote_relay + RelayPromoted event
    // ══════════════════════════════════════════════════════════

    /// RO-003 GREEN: promote_relay succeeds + assigned_relays[0] updated when primary is stale.
    /// Stale = epoch_now - last_heartbeat > MAX_HEARTBEAT_EPOCHS (3).
    /// Primary registered at epoch 0 (last_heartbeat=0); after 4 epoch advances → gap=4 > 3.
    #[test]
    fun test_ro_003_promote_relay_stale_primary_updates_slot() {
        let mut scenario = setup_two_relays();

        // Register relay_1 at epoch 0 → last_heartbeat = 0
        ts::next_tx(&mut scenario, h::relay_1());
        let primary_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay1:4000", ts::ctx(&mut scenario),
            );
            primary_id = caps::miner_cap_miner_id(&cap);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Register relay_2 at epoch 0 → last_heartbeat = 0
        ts::next_tx(&mut scenario, h::relay_2());
        let standby_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay2:4000", ts::ctx(&mut scenario),
            );
            standby_id = caps::miner_cap_miner_id(&cap);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Setup room with primary_id at [0], standby_id at [1]
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), h::user_1(),
                constants::room_status_ready(),
                constants::relay_mode_sfu(),
                1,
                ts::ctx(&mut scenario),
            );
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[primary_id, standby_id],
            );
            ts::return_shared(manager);
        };

        // Advance 4 epochs: current_epoch = 4; primary last_heartbeat = 0; gap = 4 > 3 → STALE
        ts::next_epoch(&mut scenario, h::user_1());
        ts::next_epoch(&mut scenario, h::user_1());
        ts::next_epoch(&mut scenario, h::user_1());
        ts::next_epoch(&mut scenario, h::user_1());

        // Permissionless promotion — any caller (user_1) can trigger
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            room_manager::promote_relay(
                &net_reg, &mut manager, &relay_reg,
                room_id(), standby_id, ts::ctx(&mut scenario),
            );

            // Verify: assigned_relays[0] is now standby_id (promoted to primary)
            let info = room_manager::borrow_room(&manager, room_id());
            let relays = room_manager::room_assigned_relays(info);
            assert!(*vector::borrow(&relays, 0) == standby_id);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    /// RO-003 abort guard: promote_relay aborts E_RELAY_NOT_STALE (564) when primary is fresh.
    /// Primary heartbeats at epoch 2; promote called at epoch 2 → gap = 0 ≤ 3 → NOT stale.
    #[test]
    #[expected_failure(abort_code = 564)]
    fun test_ro_003_promote_relay_fresh_primary_aborts_not_stale() {
        let mut scenario = setup_two_relays();

        // Register both relays
        ts::next_tx(&mut scenario, h::relay_1());
        let primary_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay1:4000", ts::ctx(&mut scenario),
            );
            primary_id = caps::miner_cap_miner_id(&cap);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::next_tx(&mut scenario, h::relay_2());
        let standby_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);
            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://relay2:4000", ts::ctx(&mut scenario),
            );
            standby_id = caps::miner_cap_miner_id(&cap);
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Setup room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), h::user_1(),
                constants::room_status_ready(),
                constants::relay_mode_sfu(),
                1,
                ts::ctx(&mut scenario),
            );
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[primary_id, standby_id],
            );
            ts::return_shared(manager);
        };

        // Advance 2 epochs then primary heartbeats → last_heartbeat = 2
        ts::next_epoch(&mut scenario, h::relay_1());
        ts::next_epoch(&mut scenario, h::relay_1());

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            relay_registry::relay_heartbeat(&net_reg, &mut relay_reg, &cap, ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
        };

        // Immediately promote at same epoch → gap = 0 ≤ 3 → ABORT 564
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            room_manager::promote_relay(
                &net_reg, &mut manager, &relay_reg,
                room_id(), standby_id, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }
}
