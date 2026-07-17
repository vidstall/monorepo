/// Integration tests for PVR (Propose-Verify-Reward) consensus system.
#[test_only]
module dvconf::pvr_integration_tests {
    use sui::test_scenario::{Self as ts};
    use sui::test_utils;
    use dvconf::constants;
    use dvconf::network_registry::{NetworkRegistry, AdminCap};
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::test_helpers;

    // ── Test addresses (valid hex) ──
    const ADMIN: address   = @0xAD;
    const CP1_OP: address  = @0xC1;
    const CP2_OP: address  = @0xC2;
    const CP3_OP: address  = @0xC3;
    // IDs for nodes (used via id_from_addr)
    const RELAY1: address    = @0xA1;
    const RELAY2: address    = @0xA2;
    const VAL1: address      = @0xA3;
    const VAL2: address      = @0xA4;
    // VAL3 + VAL4 added post-ADR-0006 migration (required_validators floor = 4).
    const VAL3: address      = @0xB3;
    const VAL4: address      = @0xB4;
    const SIG1: address      = @0xA5;
    const CP1_ID: address    = @0xA6;
    const CP2_ID: address    = @0xA7;
    const CP3_ID: address    = @0xA8;
    const ROOM1: address     = @0xA9;
    const ROOM2: address     = @0xAA;
    const BAD_NODE: address  = @0xBB;

    fun id_from_addr(addr: address): ID {
        object::id_from_address(addr)
    }

    // ── Setup: 3 CPs, 2 relays, 2 validators, 1 signaling, 1 PENDING room ──
    fun setup_pvr(): ts::Scenario {
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

        // Add PENDING room
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

    fun do_submit_proposal(
        scenario: &mut ts::Scenario,
        cp_addr: address,
        relay_ids: vector<ID>,
        validator_ids: vector<ID>,
        signaling_id: ID,
        room_id: ID,
    ) {
        do_submit_proposal_with_score(scenario, cp_addr, relay_ids, validator_ids, signaling_id, room_id, 8500);
    }

    fun do_submit_proposal_with_score(
        scenario: &mut ts::Scenario,
        cp_addr: address,
        relay_ids: vector<ID>,
        validator_ids: vector<ID>,
        signaling_id: ID,
        room_id: ID,
        submitted_score: u64,
    ) {
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

    // ── Test 1: Quorum of matching proposals finalizes (multi-CP 2/3 gate) ──
    // With the 3-CP setup_pvr fixture, required = ceil(3 * 6667/10000) = 3, so a SINGLE
    // proposal no longer finalizes a room (that only held when active_cp_count == 1). The
    // first two matching submits leave the room PENDING; the 3rd matching submit reaches
    // matching_votes = 3 >= required = 3 → READY. (Renamed from the old
    // `test_single_proposal_finalizes_immediately`, whose name encoded the pre-quorum behavior.)
    #[test]
    fun test_quorum_proposals_finalize() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        // 2 matching submits (8500) are below quorum (matching=2 < required=3) → still PENDING.
        do_submit_proposal_with_score(
            &mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        do_submit_proposal_with_score(
            &mut scenario, CP2_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_pending(), 4);
            ts::return_shared(manager);
        };

        // 3rd matching submit reaches matching=3 >= required=3 → consensus → READY.
        do_submit_proposal_with_score(
            &mut scenario, CP3_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );

        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 0);
            assert!(room_manager::room_verified_score(info) == 8500, 1);
            assert!(room_manager::room_consensus_reached(info) == true, 2);
            // Proposals cleaned up after finalization
            assert!(room_manager::room_proposals_count(&manager, room_id) == 0, 3);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }

    // ── Test 2: Duplicate proposal from the SAME CP rejected (E_DUPLICATE_VOTE) ──
    // Under the multi-CP quorum gate, required = ceil(3 * 6667/10000) = 3, so CP1's first
    // submit leaves the room PENDING (matching=1 < 3). When CP1 submits AGAIN to the still-
    // PENDING room, the per-CP duplicate guard fires → E_DUPLICATE_VOTE. (The old version
    // relied on the first submit finalizing the room and getting E_NOT_PENDING on the second
    // submit — that post-finalization guard is covered by
    // pvr_consensus_tests::test_no_consensus_room_finalized_blocks_further_proposals; here we
    // exercise the genuine duplicate-vote path the test name describes.)
    #[test]
    #[expected_failure(abort_code = room_manager::E_DUPLICATE_VOTE)]
    fun test_duplicate_proposal_rejected() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        // First submit from CP1 — room stays PENDING (matching=1 < required=3).
        do_submit_proposal(&mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id);
        // Second submit from the SAME CP1 to the still-PENDING room → E_DUPLICATE_VOTE.
        do_submit_proposal(&mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id);

        test_utils::destroy(scenario);
    }

    // ── Test 3: Inactive (unregistered) node rejected ──
    #[test]
    #[expected_failure(abort_code = 700)]
    fun test_inactive_node_rejected() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(BAD_NODE)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        do_submit_proposal(&mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id);

        test_utils::destroy(scenario);
    }

    // ── Test 4: Insufficient validators rejected ──
    #[test]
    #[expected_failure(abort_code = room_manager::E_INVALID_BALLOT)]
    fun test_insufficient_validators_rejected() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        // Only 1 validator but required_validators(6) = max(4, 6/3=2) = 4 (post-ADR-0006)
        let validator_ids = vector[id_from_addr(VAL1)];
        let signaling_id = id_from_addr(SIG1);

        do_submit_proposal(&mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id);

        test_utils::destroy(scenario);
    }

    // ── Test 5: Consensus-first finalization with matching scores ──
    #[test]
    fun test_consensus_finalization_with_matching_scores() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        // All 3 CPs submit the same score — quorum required = ceil(3 * 6667/10000) = 3, so the
        // 3rd matching submit reaches matching_votes = 3 >= required = 3 → consensus finalizes.
        do_submit_proposal_with_score(
            &mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        do_submit_proposal_with_score(
            &mut scenario, CP2_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        do_submit_proposal_with_score(
            &mut scenario, CP3_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );

        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let info = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 0);
            assert!(vector::length(&room_manager::room_assigned_relays(info)) == 2, 1);
            assert!(option::is_some(&room_manager::room_assigned_signaling(info)), 2);
            assert!(vector::length(&room_manager::room_assigned_validators(info)) == 4, 3);
            assert!(room_manager::room_verified_score(info) == 8500, 4);
            assert!(room_manager::room_consensus_reached(info) == true, 5);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }

    // ── Test 6: First submitter of winning score gets reputation ──
    #[test]
    fun test_first_submitter_gets_reputation() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        // 3 matching submits reach quorum (required=3); CP1 is the FIRST submitter of the
        // winning score, so only CP1 earns the first-submitter reputation bonus.
        do_submit_proposal_with_score(
            &mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        do_submit_proposal_with_score(
            &mut scenario, CP2_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        do_submit_proposal_with_score(
            &mut scenario, CP3_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );

        // CP1 (first submitter of the winning score) reputation = 1
        ts::next_tx(&mut scenario, ADMIN);
        {
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cp1_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP1_ID));
            assert!(control_plane_registry::info_reputation(cp1_info) == 1, 0);
            // CP2 matched the winning score but was NOT first → no reputation bonus.
            let cp2_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP2_ID));
            assert!(control_plane_registry::info_reputation(cp2_info) == 0, 1);
            // CP3 matched the winning score but was NOT first → no reputation bonus.
            let cp3_info = control_plane_registry::borrow_info(&cp_reg, id_from_addr(CP3_ID));
            assert!(control_plane_registry::info_reputation(cp3_info) == 0, 2);
            ts::return_shared(cp_reg);
        };

        test_utils::destroy(scenario);
    }

    // ── Test 7: ProposerRewarded event fires ONLY at consensus finalization ──
    // Distinct from Test 6 (which asserts the reputation STATE distribution across CPs): this test
    // proves the reward MECHANISM — that submit_pairing_proposal emits ProposerRewarded — using the
    // only event signal the Move VM exposes. The test VM can COUNT user events per tx
    // (`num_user_events`) but cannot DECODE an event payload (`take_events<T>` is SDK-only), and
    // ProposerRewarded has no #[test_only] constructor to BCS-peel — adding one would be a
    // forbidden sources/** change. So we assert the per-submit event COUNT: a sub-quorum submit
    // emits exactly 1 user event (ProposalSubmitted); the finalizing submit emits 3
    // (ProposalSubmitted + RoomAssigned + ProposerRewarded). The +2 delta on the 3rd submit is
    // precisely the finalization pair, so ProposerRewarded is emitted iff consensus is reached.
    #[test]
    fun test_proposer_rewarded_event_emitted_on_finalization() {
        let mut scenario = setup_pvr();
        let room_id = id_from_addr(ROOM1);
        let relay_ids = vector[id_from_addr(RELAY1), id_from_addr(RELAY2)];
        let validator_ids = vector[id_from_addr(VAL1), id_from_addr(VAL2), id_from_addr(VAL3), id_from_addr(VAL4)];
        let signaling_id = id_from_addr(SIG1);

        // Submit 1 (CP1) — sub-quorum (matching=1 < required=3): only ProposalSubmitted fires.
        do_submit_proposal_with_score(
            &mut scenario, CP1_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        let e1 = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&e1) == 1, 0); // no reward emitted yet

        // Submit 2 (CP2) — sub-quorum (matching=2 < required=3): still only ProposalSubmitted.
        do_submit_proposal_with_score(
            &mut scenario, CP2_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        let e2 = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&e2) == 1, 1); // still no reward emitted

        // Submit 3 (CP3) — finalizing (matching=3 >= required=3): ProposalSubmitted + RoomAssigned
        // + ProposerRewarded = 3 user events. The +2 over a sub-quorum submit IS the reward path.
        do_submit_proposal_with_score(
            &mut scenario, CP3_OP, relay_ids, validator_ids, signaling_id, room_id, 8500,
        );
        let e3 = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&e3) == 3, 2); // ProposerRewarded fired alongside RoomAssigned

        test_utils::destroy(scenario);
    }

    // ── Test 8: Fallback assign_relay_and_signaling still works ──
    #[test]
    fun test_fallback_assign_still_works() {
        let mut scenario = setup_pvr();

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            room_manager::add_room_for_testing(
                &mut manager, id_from_addr(ROOM2), @0xE1,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                2, ctx,
            );
            ts::return_shared(manager);
        };

        // AdminCap-gated fallback assignment (PAIR-04)
        ts::next_tx(&mut scenario, ADMIN);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);

            room_manager::assign_relay_and_signaling(
                &net_reg, &mut manager, &admin_cap,
                id_from_addr(ROOM2), id_from_addr(RELAY1), id_from_addr(SIG1),
            );

            let info = room_manager::borrow_room(&manager, id_from_addr(ROOM2));
            assert!(room_manager::room_status(info) == constants::room_status_ready(), 0);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
        };

        test_utils::destroy(scenario);
    }
}
