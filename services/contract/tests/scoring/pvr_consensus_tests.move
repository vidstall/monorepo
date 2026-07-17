#[test_only]
module dvconf::pvr_consensus_tests {
    use sui::test_scenario::{Self as ts};
    use sui::test_utils;
    use dvconf::constants;
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::test_helpers;

    const ADMIN: address = @0xAD;

    // ── Test addresses ──
    const CP1_OP: address  = @0xC1;
    const CP2_OP: address  = @0xC2;
    const CP3_OP: address  = @0xC3;
    const RELAY1: address  = @0xA1;
    const RELAY2: address  = @0xA2;
    const VAL1: address    = @0xA3;
    const VAL2: address    = @0xA4;
    // VAL3 + VAL4 added post-ADR-0006 migration (required_validators floor = 4).
    const VAL3: address    = @0xB3;
    const VAL4: address    = @0xB4;
    const SIG1: address    = @0xA5;
    const CP1_ID: address  = @0xA6;
    const CP2_ID: address  = @0xA7;
    const CP3_ID: address  = @0xA8;
    const ROOM1: address   = @0xA9;
    // ── Multi-CP (N=5) additions for the quorum-gate tests (Task A3) ──
    const CP4_OP: address  = @0xC4;
    const CP5_OP: address  = @0xC5;
    const CP4_ID: address  = @0xB5;
    const CP5_ID: address  = @0xB6;

    fun id_from_addr(addr: address): ID {
        object::id_from_address(addr)
    }

    // ── Setup: 3 CPs, 2 relays, 2 validators, 1 signaling, 1 PENDING room ──
    fun setup_consensus(): ts::Scenario {
        let mut scenario = test_helpers::setup_phase2();

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_from_addr(RELAY1), @0xB1, ctx);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_from_addr(RELAY2), @0xB2, ctx);
            ts::return_shared(relay_reg);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL1), @0xD1, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL2), @0xD2, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL3), @0xD3, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL4), @0xD4, 100_000_000, ctx);
            ts::return_shared(val_reg);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            signaling_registry::add_signaling_for_testing(&mut sig_reg, id_from_addr(SIG1), @0xF1, ctx);
            ts::return_shared(sig_reg);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP1_ID), CP1_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP2_ID), CP2_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP3_ID), CP3_OP, 500_000_000, ctx);
            ts::return_shared(cp_reg);
        };

        // Create CP caps
        ts::next_tx(&mut scenario, CP1_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP1_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP1_OP);
        };
        ts::next_tx(&mut scenario, CP2_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP2_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP2_OP);
        };
        ts::next_tx(&mut scenario, CP3_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP3_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP3_OP);
        };

        // Add PENDING room with 6 expected participants
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            room_manager::add_room_for_testing(
                &mut manager, id_from_addr(ROOM1), @0xE1,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                6, ctx,
            );
            ts::return_shared(manager);
        };

        scenario
    }

    fun do_submit_with_score(
        scenario: &mut ts::Scenario,
        cp_addr: address,
        room_id: ID,
        submitted_score: u64,
    ) {
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        ts::next_tx(scenario, cp_addr);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut manager = ts::take_shared<RoomManager>(scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(scenario);

            room_manager::submit_pairing_proposal(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                &cap, room_id,
                relay_ids, validator_ids, signaling_id,
                submitted_score,
                ts::ctx(scenario),
            );

            ts::return_to_sender(scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };
    }

    // ══════════════════════════════════════════════════════════
    // CONSTANT TESTS (from Task 2)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_dispute_cooldown_constant() {
        assert!(constants::pvr_dispute_cooldown() == 2, 0);
    }

    #[test]
    fun test_consensus_threshold_constant() {
        assert!(constants::pvr_consensus_threshold_bps() == 6_667, 0);
    }

    // ── Test: new RoomInfo fields default to zero/false ──
    #[test]
    fun test_room_info_has_consensus_fields() {
        let mut scenario = test_helpers::setup_phase2();

        let room_id = object::id_from_address(@0xBEEF);

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id, ADMIN,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                4, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_verified_score(info) == 0, 0);
            assert!(room_manager::room_consensus_reached(info) == false, 1);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // CONSENSUS-FIRST TESTS (Task 3)
    // ══════════════════════════════════════════════════════════

    /// Test 1: Happy-path consensus. With the 3-CP `setup_consensus` fixture,
    /// `required = ceil(active_cp_count * 6667/10000) = ceil(3 * 0.6667) = 3`,
    /// i.e. the 2/3 threshold rounds UP to 3-of-3 unanimity at N=3. A single
    /// submit no longer finalizes (post-A3 quorum gate): the first two matching
    /// submits leave the room PENDING, and only the 3rd matching submit reaches
    /// `matching_votes = 3 >= required = 3` → READY.
    #[test]
    fun test_consensus_happy_path_3_of_3_agree() {
        let mut scenario = setup_consensus();
        let room_id = id_from_addr(ROOM1);

        // 2 matching submits (8500) are below quorum (matching=2 < required=3) → still PENDING.
        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 8500);
        assert_room_pending(&mut scenario, room_id);

        // 3rd matching submit reaches matching=3 >= required=3 → READY (locks the N=3 unanimity boundary).
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 8500);

        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            // 3-of-3 agreement = consensus
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 0);
            assert!(room_manager::room_verified_score(info) == 8500, 1);
            assert!(room_manager::room_consensus_reached(info) == true, 2);
            // Proposals cleaned up
            assert!(room_manager::room_proposals_count(&manager, room_id) == 0, 3);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }

    /// Test 2: Once a room finalizes (READY), further proposals are blocked.
    /// With the 3-CP fixture `required = 3`, so three matching submits (8500)
    /// finalize the room. A subsequent submit then hits the PENDING guard
    /// (the room is no longer PENDING) and aborts E_NOT_PENDING — the guard
    /// fires before the duplicate-vote check, so even a previously-voted CP
    /// is rejected with E_NOT_PENDING here.
    #[test]
    #[expected_failure(abort_code = room_manager::E_NOT_PENDING)]
    fun test_no_consensus_room_finalized_blocks_further_proposals() {
        let mut scenario = setup_consensus();
        let room_id = id_from_addr(ROOM1);

        // 3 matching submits → matching=3 >= required=3 → room finalizes (READY).
        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 8500);

        // Room is READY now → any further proposal hits the PENDING guard → E_NOT_PENDING.
        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8200);

        test_utils::destroy(scenario);
    }

    /// Test 3: Only the FIRST submitter of the winning score is rewarded.
    /// `required = 3` (3-CP fixture), so CP1, CP2, CP3 all submit 8500. The
    /// winner is the first matching submitter (CP1) → CP1 reputation = 1; the
    /// later matching submitters (CP2, CP3) get NO first-submitter bonus.
    #[test]
    fun test_consensus_first_submitter_gets_reputation() {
        let mut scenario = setup_consensus();
        let room_id = id_from_addr(ROOM1);

        // 3 matching submits on 8500; CP1 is the FIRST submitter of the winning score.
        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 8500);

        ts::next_tx(&mut scenario, ADMIN);
        {
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            // CP1 = first submitter of winning score, reputation incremented
            let cp1_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP1_ID));
            assert!(control_plane_registry::info_reputation(cp1_info) == 1, 0);
            // CP2 matched but was not first → no reputation bonus
            let cp2_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP2_ID));
            assert!(control_plane_registry::info_reputation(cp2_info) == 0, 1);
            // CP3 matched but was not first → no reputation bonus
            let cp3_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP3_ID));
            assert!(control_plane_registry::info_reputation(cp3_info) == 0, 2);
            ts::return_shared(cp_reg);
        };

        test_utils::destroy(scenario);
    }

    /// Test 4: The agreed score is stored in the room's verified_score field
    /// once consensus finalizes (3 matching submits on the 3-CP fixture).
    #[test]
    fun test_submitted_score_stored_in_room() {
        let mut scenario = setup_consensus();
        let room_id = id_from_addr(ROOM1);

        do_submit_with_score(&mut scenario, CP1_OP, room_id, 7777);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 7777);
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 7777);

        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_verified_score(info) == 7777, 0);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }

    /// Test 5: Room assigned_cp is set to the winning CP's ID — the FIRST
    /// submitter of the agreed score. 3 matching submits → winner = CP1.
    #[test]
    fun test_winning_cp_assigned_to_room() {
        let mut scenario = setup_consensus();
        let room_id = id_from_addr(ROOM1);

        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 8500);

        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            let assigned_cp = room_manager::room_assigned_cp(info);
            assert!(option::is_some(&assigned_cp), 0);
            assert!(*option::borrow(&assigned_cp) == id_from_addr(CP1_ID), 1);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // DISPUTE FALLBACK TESTS (Task 4)
    // ══════════════════════════════════════════════════════════

    const CREATOR: address = @0xE1;

    /// Helper: set up a PENDING room with 3 proposals (different scores) but
    /// NO consensus triggered. Uses add_proposal_for_testing to bypass the
    /// automatic consensus check in submit_pairing_proposal.
    fun setup_dispute(): ts::Scenario {
        let mut scenario = test_helpers::setup_phase2();
        let room_id = id_from_addr(ROOM1);

        // Register nodes
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_from_addr(RELAY1), @0xB1, ctx);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_from_addr(RELAY2), @0xB2, ctx);
            ts::return_shared(relay_reg);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL1), @0xD1, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL2), @0xD2, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL3), @0xD3, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, id_from_addr(VAL4), @0xD4, 100_000_000, ctx);
            ts::return_shared(val_reg);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            signaling_registry::add_signaling_for_testing(&mut sig_reg, id_from_addr(SIG1), @0xF1, ctx);
            ts::return_shared(sig_reg);
        };

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP1_ID), CP1_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP2_ID), CP2_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP3_ID), CP3_OP, 500_000_000, ctx);
            ts::return_shared(cp_reg);
        };

        // Create PENDING room owned by CREATOR
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id, CREATOR,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                6, ctx,
            );
            ts::return_shared(manager);
        };

        // Add 3 proposals with different scores directly (bypass consensus)
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
            let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
            let signaling_id = id_from_addr(SIG1);

            room_manager::add_proposal_for_testing(
                &mut manager, room_id, id_from_addr(CP1_ID),
                relay_ids, validator_ids, signaling_id, 8500,
            );
            room_manager::add_proposal_for_testing(
                &mut manager, room_id, id_from_addr(CP2_ID),
                relay_ids, validator_ids, signaling_id, 8200,
            );
            room_manager::add_proposal_for_testing(
                &mut manager, room_id, id_from_addr(CP3_ID),
                relay_ids, validator_ids, signaling_id, 7900,
            );

            // Verify 3 proposals stored
            assert!(room_manager::room_proposals_count(&manager, room_id) == 3, 0);
            ts::return_shared(manager);
        };

        scenario
    }

    /// Test 6: Happy path — dispute fallback picks best proposal after cooldown.
    #[test]
    fun test_finalize_room_dispute_fallback() {
        let mut scenario = setup_dispute();
        let room_id = id_from_addr(ROOM1);

        // Advance 2 epochs for cooldown (room created at epoch 0, need epoch >= 2)
        ts::next_epoch(&mut scenario, ADMIN);
        ts::next_epoch(&mut scenario, ADMIN);

        // Creator calls finalize_room
        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            room_manager::finalize_room(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                room_id,
                ts::ctx(&mut scenario),
            );

            // Verify room is READY
            let info = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 0);
            assert!(room_manager::room_consensus_reached(info) == false, 1);
            assert!(room_manager::room_verified_score(info) > 0, 2);

            // Proposals cleaned up
            assert!(room_manager::room_proposals_count(&manager, room_id) == 0, 3);

            // Assigned fields populated
            let relays = room_manager::room_assigned_relays(info);
            assert!(vector::length(&relays) == 2, 4);
            let validators = room_manager::room_assigned_validators(info);
            assert!(vector::length(&validators) == 4, 5);
            assert!(option::is_some(&room_manager::room_assigned_signaling(info)), 6);
            assert!(option::is_some(&room_manager::room_assigned_cp(info)), 7);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        // Verify no reputation incremented for any CP (dispute = no reward)
        ts::next_tx(&mut scenario, ADMIN);
        {
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cp1_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP1_ID));
            assert!(control_plane_registry::info_reputation(cp1_info) == 0, 8);
            let cp2_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP2_ID));
            assert!(control_plane_registry::info_reputation(cp2_info) == 0, 9);
            ts::return_shared(cp_reg);
        };

        test_utils::destroy(scenario);
    }

    /// Test 7: Non-creator cannot call finalize_room.
    #[test]
    #[expected_failure(abort_code = room_manager::E_NOT_ROOM_CREATOR)]
    fun test_finalize_room_non_creator_fails() {
        let mut scenario = setup_dispute();
        let room_id = id_from_addr(ROOM1);

        // Advance cooldown
        ts::next_epoch(&mut scenario, ADMIN);
        ts::next_epoch(&mut scenario, ADMIN);

        // Non-creator calls finalize_room
        ts::next_tx(&mut scenario, @0xBAD);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            room_manager::finalize_room(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                room_id,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        test_utils::destroy(scenario);
    }

    /// Test 8: finalize_room before cooldown fails.
    #[test]
    #[expected_failure(abort_code = room_manager::E_COOLDOWN_NOT_MET)]
    fun test_finalize_room_before_cooldown_fails() {
        let mut scenario = setup_dispute();
        let room_id = id_from_addr(ROOM1);

        // Do NOT advance epochs — cooldown not met

        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            room_manager::finalize_room(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                room_id,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        test_utils::destroy(scenario);
    }

    /// Test 9: finalize_room with insufficient proposals fails.
    #[test]
    #[expected_failure(abort_code = room_manager::E_INSUFFICIENT_PROPOSALS)]
    fun test_finalize_room_insufficient_proposals_fails() {
        let mut scenario = test_helpers::setup_phase2();
        let room_id = id_from_addr(ROOM1);

        // Register minimal nodes
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_from_addr(RELAY1), @0xB1, ctx);
            ts::return_shared(relay_reg);
        };

        // Create PENDING room
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id, CREATOR,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                6, ctx,
            );

            // Add only 1 proposal
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx2 = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP1_ID), CP1_OP, 500_000_000, ctx2);

            room_manager::add_proposal_for_testing(
                &mut manager, room_id, id_from_addr(CP1_ID),
                vector[id_from_addr(RELAY1)], vector[], id_from_addr(SIG1),
                8000,
            );

            ts::return_shared(cp_reg);
            ts::return_shared(manager);
        };

        // Advance cooldown
        ts::next_epoch(&mut scenario, ADMIN);
        ts::next_epoch(&mut scenario, ADMIN);

        // Creator tries finalize with only 1 proposal → E_INSUFFICIENT_PROPOSALS
        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            room_manager::finalize_room(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                room_id,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        test_utils::destroy(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // MULTI-CP QUORUM GATE TESTS (Task A3 — matching_votes >= ceil(2/3 * active_cp))
    // ══════════════════════════════════════════════════════════

    /// 5-CP variant of `setup_consensus`: reuses the 3-CP fixture (relays,
    /// validators, signaling, PENDING room) then registers CP4 + CP5 (active
    /// CP count = 5) and mints their caps. Mirrors the existing 3-CP idiom.
    fun setup_consensus_5cp(): ts::Scenario {
        let mut scenario = setup_consensus();

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP4_ID), CP4_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP5_ID), CP5_OP, 500_000_000, ctx);
            ts::return_shared(cp_reg);
        };

        ts::next_tx(&mut scenario, CP4_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP4_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP4_OP);
        };
        ts::next_tx(&mut scenario, CP5_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP5_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP5_OP);
        };

        scenario
    }

    /// Assert the room is still PENDING (quorum not yet reached).
    fun assert_room_pending(scenario: &mut ts::Scenario, room_id: ID) {
        ts::next_tx(scenario, ADMIN);
        {
            let m = ts::take_shared<RoomManager>(scenario);
            let info = room_manager::borrow_room(&m, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_pending(), 0);
            ts::return_shared(m);
        };
    }

    /// Assert the room finalized READY via consensus on `expected_score`.
    fun assert_room_ready_score(scenario: &mut ts::Scenario, room_id: ID, expected_score: u64) {
        ts::next_tx(scenario, ADMIN);
        {
            let m = ts::take_shared<RoomManager>(scenario);
            let info = room_manager::borrow_room(&m, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 0);
            assert!(room_manager::room_consensus_reached(info) == true, 1);
            assert!(room_manager::room_verified_score(info) == expected_score, 2);
            ts::return_shared(m);
        };
    }

    #[test]
    fun test_pairing_requires_4_of_5() {
        let mut scenario = setup_consensus_5cp(); // 5 CPs registered; 1 PENDING room
        let room_id = id_from_addr(ROOM1);

        // 3 of 5 agree on score 8500 → matching=3 < required=ceil(5*6667/10000)=4 → still PENDING.
        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 8500);
        ts::next_tx(&mut scenario, ADMIN);
        {
            let m = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&m, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_pending(), 0);
            ts::return_shared(m);
        };

        // 4th agreeing CP → matching=4 >= 4 → READY with 4 distinct cp_id.
        do_submit_with_score(&mut scenario, CP4_OP, room_id, 8500);
        ts::next_tx(&mut scenario, ADMIN);
        {
            let m = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&m, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 1);
            assert!(room_manager::room_consensus_reached(info) == true, 2);
            ts::return_shared(m);
        };
        test_utils::destroy(scenario);
    }

    #[test]
    fun test_pairing_divergent_minority_does_not_skew() {
        let mut scenario = setup_consensus_5cp();
        let room_id = id_from_addr(ROOM1);
        do_submit_with_score(&mut scenario, CP1_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP2_OP, room_id, 9999); // dissenter score
        do_submit_with_score(&mut scenario, CP3_OP, room_id, 8500);
        do_submit_with_score(&mut scenario, CP4_OP, room_id, 8500);
        // matching(8500)=3 < 4 → still PENDING despite 4 total proposals.
        assert_room_pending(&mut scenario, room_id);
        do_submit_with_score(&mut scenario, CP5_OP, room_id, 8500); // 4th agreeing → READY
        assert_room_ready_score(&mut scenario, room_id, 8500);
        test_utils::destroy(scenario);
    }
}
