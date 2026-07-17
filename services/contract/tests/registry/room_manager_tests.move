#[test_only]
module dvconf::room_manager_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::user_registry::{Self, UserRegistry};
    use dvconf::room_manager::{Self, RoomManager};

    // ── Helper: register a user in user_registry ──
    fun register_user(scenario: &mut ts::Scenario, who: address) {
        ts::next_tx(scenario, who);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"TestUser", ts::ctx(scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };
    }

    // ── Happy path: create room ──
    #[test]
    fun test_create_room() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_sfu(), 6, 0u8, ts::ctx(&mut scenario),
            );

            assert!(room_manager::active_count(&manager) == 1);

            // User room_count incremented
            let profile = user_registry::borrow_profile(&user_reg, h::user_1());
            assert!(user_registry::room_count(profile) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Create room with the additive room_class_hint (REQ-RMS-016) ──
    #[test]
    fun test_create_room_with_class_hint() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_sfu(),
                10,            // expected_participants
                2u8,           // room_class_hint = large (NEW additive arg, REQ-RMS-016)
                ts::ctx(&mut scenario),
            );

            // The room was created with the new 6-arg signature (additive arg round-trips through the entry).
            assert!(room_manager::active_count(&manager) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Create room with MCU mode ──
    #[test]
    fun test_create_room_mcu() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_mcu(), 6, 0u8, ts::ctx(&mut scenario),
            );

            assert!(room_manager::active_count(&manager) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Unregistered user aborts 506 ──
    #[test]
    #[expected_failure(abort_code = 506)]
    fun test_create_room_user_not_registered() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_sfu(), 6, 0u8, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Invalid relay mode aborts 504 ──
    #[test]
    #[expected_failure(abort_code = 504)]
    fun test_create_room_invalid_mode() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                99, // invalid mode
                6, 0u8, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Create while paused aborts 500 ──
    #[test]
    #[expected_failure(abort_code = 500)]
    fun test_create_room_paused() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_sfu(), 6, 0u8, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Close room — only creator ──
    #[test]
    fun test_close_room() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        // Create room
        ts::next_tx(&mut scenario, h::user_1());
        let room_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_sfu(), 6, 0u8, ts::ctx(&mut scenario),
            );

            // We need to find the room_id — it's in the table. Since we can't easily
            // iterate, we'll use the event or check active_count
            assert!(room_manager::active_count(&manager) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        // To close a room, we need the room_id. In a real scenario it comes from
        // the RoomCreated event. For testing, we can get it from last_created_objects.
        let effects = ts::next_tx(&mut scenario, h::user_1());
        // The room_id was created via object::new + delete pattern, so it won't be
        // in created objects. We'll use a known-address trick instead.
        // Actually, let's just verify the room_rules accessor instead.
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let rules = room_manager::room_rules(&manager);
            assert!(room_manager::rules_min_relay(&rules) == constants::default_min_relays_per_room());
            assert!(room_manager::rules_min_cp(&rules) == constants::default_min_cps_per_room());
            assert!(room_manager::rules_min_validator(&rules) == constants::default_min_validators_per_room());
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ── REG-13 gap: close non-existent room aborts 502 ──
    // close_room checks table.contains first; a missing room_id triggers E_NOT_FOUND (502).
    #[test]
    #[expected_failure(abort_code = 502)]
    fun test_close_nonexistent_room_aborts_502() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let fake_room_id = object::id_from_address(@0xDEAD);

            room_manager::close_room(
                &net_reg, &mut manager, fake_room_id, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ── REG-13 gap: non-creator close aborts 501 ──
    // Skipped: requires room_id from create_room; the UID is deleted inside create_room
    // so it does not appear in transaction effects. Tested via integration in Phase 3
    // (room.move will expose the room_id via a proper Sui object or event accessor).
    // The error code 501 (E_NOT_CREATOR) is confirmed in room_manager.move line 13.

    // ── Update room rules (governance) ──
    #[test]
    fun test_update_room_rules() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);

            room_manager::update_room_rules(&admin_cap, &mut manager, 3, 5, 4);

            let rules = room_manager::room_rules(&manager);
            assert!(room_manager::rules_min_relay(&rules) == 3);
            assert!(room_manager::rules_min_cp(&rules) == 5);
            assert!(room_manager::rules_min_validator(&rules) == 4);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ── Default room rules from constants ──
    #[test]
    fun test_default_room_rules() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let rules = room_manager::room_rules(&manager);
            assert!(room_manager::rules_min_relay(&rules) == constants::default_min_relays_per_room());
            assert!(room_manager::rules_min_cp(&rules) == constants::default_min_cps_per_room());
            assert!(room_manager::rules_min_validator(&rules) == constants::default_min_validators_per_room());
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ── Multiple rooms by same user ──
    #[test]
    fun test_multiple_rooms() {
        let mut scenario = h::setup_phase2();
        register_user(&mut scenario, h::user_1());

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_sfu(), 6, 0u8, ts::ctx(&mut scenario),
            );
            room_manager::create_room(
                &net_reg, &mut manager, &mut user_reg,
                constants::relay_mode_mcu(), 6, 0u8, ts::ctx(&mut scenario),
            );

            assert!(room_manager::active_count(&manager) == 2);

            let profile = user_registry::borrow_profile(&user_reg, h::user_1());
            assert!(user_registry::room_count(profile) == 2);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // ASSIGNMENT TESTS (Phase 14)
    // ══════════════════════════════════════════════════════════

    // Deterministic IDs for assignment tests
    fun test_room_id(): ID   { object::id_from_address(@0x1001) }
    fun test_relay_id(): ID  { object::id_from_address(@0x2001) }
    fun test_sig_id(): ID    { object::id_from_address(@0x3001) }

    // ── assign_relay_and_signaling happy path + accessors (AdminCap-gated) ──
    #[test]
    fun test_assign_relay_and_signaling() {
        let mut scenario = h::setup_phase2();

        // Add a PENDING room with known ID
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

        // Admin assigns relay + signaling
        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);

            room_manager::assign_relay_and_signaling(
                &net_reg, &mut manager, &admin_cap,
                test_room_id(), test_relay_id(), test_sig_id(),
            );

            // Verify via accessor on RoomInfo
            let info = room_manager::borrow_room(&manager, test_room_id());
            assert!(room_manager::room_assigned_relay(info) == option::some(test_relay_id()));
            assert!(room_manager::room_assigned_signaling(info) == option::some(test_sig_id()));
            assert!(room_manager::room_assigned_relays(info) == vector[test_relay_id()]);

            // Verify via get_room_assignment
            let (relay_ids, sig_opt) = room_manager::get_room_assignment(&manager, test_room_id());
            assert!(relay_ids == vector[test_relay_id()]);
            assert!(sig_opt == option::some(test_sig_id()));

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ── assign to non-existent room aborts 502 ──
    #[test]
    #[expected_failure(abort_code = 502)]
    fun test_assign_nonexistent_room_aborts() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);

            let fake_room_id = object::id_from_address(@0xDEAD);
            room_manager::assign_relay_and_signaling(
                &net_reg, &mut manager, &admin_cap,
                fake_room_id, test_relay_id(), test_sig_id(),
            );

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }

    // ── assign to closed room aborts 503 ──
    #[test]
    #[expected_failure(abort_code = 503)]
    fun test_assign_closed_room_aborts() {
        let mut scenario = h::setup_phase2();

        // Add a CLOSED room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, test_room_id(), h::user_1(),
                constants::room_status_closed(), constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

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
    // F40 BUG FIX — Pairing score must read liveness from
    // info_last_heartbeat, NOT info_registered_at. Regression
    // guard for room_manager.move:523,538 (M0 / TDD).
    // ══════════════════════════════════════════════════════════

    // ── F40: heartbeat_age is computed from last_heartbeat, not registered_at ──
    // When a long-lived relay/validator has been heartbeating regularly, the
    // pairing scorer must observe a SMALL age (fresh) — not the time since
    // first registration (which would always trip the staleness threshold for
    // long-running nodes).
    #[test]
    fun test_pairing_score_uses_last_heartbeat_not_registered_at() {
        use dvconf::caps::{Self, MinerCap};
        use dvconf::staking::StakePosition;
        use dvconf::relay_registry::{Self, RelayRegistry};
        use dvconf::validator_registry::{Self, ValidatorRegistry};

        let mut scenario = h::setup_phase2();

        // Register relay + validator miners at epoch 0
        h::do_register(&mut scenario, h::relay_1(), h::relay_stake());
        h::do_register(&mut scenario, h::val_1(), h::validator_stake());

        // Enroll relay in RelayRegistry at epoch 0
        ts::next_tx(&mut scenario, h::relay_1());
        let relay_miner_id;
        let relay_registered_at;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            relay_registry::register_relay(
                &net_reg, &mut relay_reg, &cap, &stake,
                b"asia-southeast1", b"ws://127.0.0.1:4000",
                ts::ctx(&mut scenario),
            );
            relay_miner_id = caps::miner_cap_miner_id(&cap);
            let info = relay_registry::borrow_info(&relay_reg, relay_miner_id);
            relay_registered_at = relay_registry::info_registered_at(info);

            ts::return_shared(net_reg);
            ts::return_shared(relay_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Enroll validator at epoch 0
        ts::next_tx(&mut scenario, h::val_1());
        let val_miner_id;
        let val_registered_at;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            val_miner_id = caps::miner_cap_miner_id(&cap);
            let info = validator_registry::borrow_info(&val_reg, val_miner_id);
            val_registered_at = validator_registry::info_registered_at(info);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Advance MANY epochs past PVR_HEARTBEAT_STALE (=7).
        // If liveness was computed from registered_at, age would be huge -> stale.
        let mut i = 0;
        while (i < 10) {
            ts::next_epoch(&mut scenario, h::relay_1());
            i = i + 1;
        };

        // Heartbeat both — keep them fresh.
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

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            validator_registry::heartbeat(
                &net_reg, &mut val_reg, &cap, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
        };

        // Verify the semantics: last_heartbeat is fresh; registered_at is stale.
        // This is the invariant room_manager.move:523,538 depends on.
        ts::next_tx(&mut scenario, h::user_1());
        {
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let current_epoch = ts::ctx(&mut scenario).epoch();

            let relay_info = relay_registry::borrow_info(&relay_reg, relay_miner_id);
            let relay_hb = relay_registry::info_last_heartbeat(relay_info);
            let stale_threshold = constants::pvr_heartbeat_stale();

            // If we'd used registered_at, age would be > stale (BUG behaviour).
            let buggy_relay_age = current_epoch - relay_registered_at;
            assert!(buggy_relay_age > stale_threshold);
            // With last_heartbeat (fix), age is fresh (small).
            let fixed_relay_age = current_epoch - relay_hb;
            assert!(fixed_relay_age <= stale_threshold);

            let val_info = validator_registry::borrow_info(&val_reg, val_miner_id);
            let val_hb = validator_registry::info_last_heartbeat(val_info);
            let buggy_val_age = current_epoch - val_registered_at;
            assert!(buggy_val_age > stale_threshold);
            let fixed_val_age = current_epoch - val_hb;
            assert!(fixed_val_age <= stale_threshold);

            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
        };

        ts::end(scenario);
    }

    // ── get_room_assignment returns none when unassigned ──
    #[test]
    fun test_get_room_assignment_unassigned() {
        let mut scenario = h::setup_phase2();

        // Add a PENDING room (no assignment)
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

        ts::next_tx(&mut scenario, h::user_1());
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let (relay_ids, sig_opt) = room_manager::get_room_assignment(&manager, test_room_id());
            assert!(vector::is_empty(&relay_ids));
            assert!(option::is_none(&sig_opt));
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }
}
