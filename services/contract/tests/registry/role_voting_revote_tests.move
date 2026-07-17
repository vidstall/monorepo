/// F47 Phase 3 — REQ-RV-012 revote integration / gap tests.
///
/// This file fills the GENUINE RV-012 coverage gaps (full mark→cast→apply E2E,
/// scenario 3.2.9) without duplicating the per-guard unit coverage already shipped
/// in Phase 1. The 9 ADR-0008 revote scenarios map to their existing homes as follows:
///
/// ── Already covered (DO NOT duplicate) ──
///   3.1.1 idle mark              → role_voting_mark_tests::test_mark_idle_succeeds_after_threshold
///   3.1.2 composition-shift mark → role_voting_mark_tests::test_mark_composition_shift_succeeds_on_surplus_role
///   3.1.3 self-request mark      → role_voting_mark_tests::test_mark_miner_request_succeeds_with_cap
///   3.1.4 cooldown               → role_voting_mark_tests::test_mark_cooldown_blocks_re_mark
///   3.2.5 pool-membership (708)  → role_voting_cast_revote_tests::test_revote_not_eligible_rejected
///   3.2.7 stake-threshold (713)  → role_voting_cast_revote_tests::test_revote_insufficient_stake_rejected
///
/// ── 3.2.8 CP-migration (E_CP_REVOTE_REQUIRES_MIGRATION = 714) ──
///   CAST-SIDE (the only public-API-reachable 714): role_voting_cast_revote_tests::
///   test_revote_cp_transition_rejected drives cast_role_vote on a RELAY miner voting
///   INTO CP and observes 714 at role_voting.move:247-250.
///
///   APPLY-SIDE (registration.move:163-167) is DEFENSE-IN-DEPTH, NOT independently
///   reachable through the public API, so NO new test is written for it here:
///     • The apply guard fires when `old_role != USER && (old_role==CP || new_role==CP)`.
///     • `old_role` is `caps::miner_cap_role(cap)` and equals the miner's profile role
///       (cap.role and profile.role only ever change together, atomically, inside
///       apply_voted_role itself — see registration.move:180-182).
///     • The ONLY public route that creates an entry in `assigned_roles` (which apply
///       then consumes) is cast_role_vote reaching threshold (role_voting.move:335).
///     • cast_role_vote's OWN guard (role_voting.move:247-250) uses the IDENTICAL
///       predicate over the SAME (current_role, role) pair and aborts 714 BEFORE the
///       assignment is ever persisted. So no public sequence can persist an assignment
///       that would later trip the apply guard — cast pre-empts every such route.
///     • The existing apply_04 / apply_07 (registration_apply_voted_role_tests) only
///       reach the apply guard via the TEST-ONLY backdoor
///       role_voting::add_assignment_for_testing (bypassing cast), which is not a
///       public-API path. Faking a "public-path" apply-side 714 test here would be
///       dishonest, so it is intentionally omitted.
///   ⇒ Effective public-path 714 coverage = the cast-side test above.
///
/// ── 3.2.6 mid-room (E_MINER_IN_ACTIVE_ROOM = 712) — DEFERRED, NO TEST ──
///   The 712 const is `#[allow(unused_const)]` (role_voting.move:46-47) and the guard
///   is NOT wired into cast_role_vote because room_manager has no reverse miner→room
///   lookup (RV-003 PARTIAL). The guard cannot be triggered, so no passing test can be
///   written. Tracked as deferred follow-up; documented here only.
///
/// ── What THIS file adds ──
///   test_3_2_9_full_e2e_relay_to_validator (REQ-RV-012, positive E2E): the complete
///   revote lifecycle across tx boundaries — register a RELAY miner, drive it idle
///   (epoch gap > max_idle_epochs=30), mark it revote-eligible (idle path), have a CP
///   cast a VALIDATOR vote to threshold (RELAY→VALIDATOR is non-CP↔non-CP so 714 does
///   not fire; 708 passes because the miner is in revote_eligible; the StakePosition is
///   bound to the miner and ≥ validator minimum), then apply_voted_role and assert the
///   end state.
///
///   END-STATE ASSERTED (= exactly what apply_voted_role does, verified against
///   registration.move:135-192): the assignment is consumed; MinerCap.role and
///   MinerProfile.role both flip RELAY→VALIDATOR; and the stale RELAY entry is removed
///   from RelayRegistry (cleanup_old_registry, registration.move:198-213); and a
///   RoleTransitioned event fires (2 user events = RoleApplied + RoleTransitioned).
///   NOTE — apply_voted_role does NOT enroll the miner into the NEW (validator)
///   registry: it only CLEANS the OLD registry. New-registry enrollment is a separate
///   daemon-side step outside this fast-path, so this test deliberately does NOT assert
///   ValidatorRegistry membership (asserting it would fail against real code). This
///   matches the existing apply_01_relay_to_validator unit test's scope.
///   This is the only scenario exercising the mark→cast→apply chain as one flow; every
///   guard above is a unit slice of it.
#[test_only]
module dvconf::role_voting_revote_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::staking::StakePosition;
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::ValidatorRegistry;
    use dvconf::signaling_registry::SignalingRegistry;
    use dvconf::caps::{Self, ControlPlaneCap, MinerCap};
    use dvconf::registration;
    use dvconf::role_voting::{Self, RoleVoteBox};

    // ── Test addresses ──
    const MINER: address  = @0xA1;   // the relay miner being re-voted to validator
    const CP1_OP: address = @0xC1;   // CP operator (the voter)
    const CP1_ID: address = @0xA6;   // CP node id

    fun id_from_addr(addr: address): ID { object::id_from_address(addr) }

    // ══════════════════════════════════════════════════════════
    // 3.2.9 — FULL E2E: idle mark → CP cast → apply (RELAY → VALIDATOR)
    // ══════════════════════════════════════════════════════════
    //
    // Network: 1 RELAY (the miner) + 1 CP (the voter), 0 validators/signaling.
    //   • validator is scarce (count 0) → compute_threshold collapses to its 1-vote
    //     floor, so the single CP vote meets threshold on the first cast.
    //   • RELAY → VALIDATOR is non-CP↔non-CP, so neither the cast-side nor the
    //     apply-side 714 guard fires.
    //
    #[test]
    fun test_3_2_9_full_e2e_relay_to_validator() {
        let mut scenario = h::setup_phase2();

        // ── Register MINER as a RELAY (stake = 0.25 SUI ≥ validator min 0.1 SUI) ──
        // register_with_role transfers a MinerCap (role=RELAY) and a StakePosition
        // (bound to miner_id, owned by MINER) to MINER.
        h::do_register_with_role(&mut scenario, MINER, h::relay_stake(), constants::role_relay());

        // Retrieve the miner_id from the MinerCap.
        ts::next_tx(&mut scenario, MINER);
        let miner_id = {
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let mid = caps::miner_cap_miner_id(&cap);
            ts::return_to_sender(&scenario, cap);
            mid
        };

        // ── Seed RelayRegistry so (a) idle heartbeat can go stale and (b) apply has a
        //    real stale entry to clean up. last_heartbeat = current epoch (0). ──
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            if (!relay_registry::is_registered(&relay_reg, miner_id)) {
                relay_registry::add_relay_for_testing(&mut relay_reg, miner_id, MINER, ts::ctx(&mut scenario));
            };
            ts::return_shared(relay_reg);
        };

        // ── Register one CP (the voter) + mint its ControlPlaneCap ──
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            control_plane_registry::add_cp_for_testing(
                &mut cp_reg, id_from_addr(CP1_ID), CP1_OP, h::cp_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(cp_reg);
        };
        ts::next_tx(&mut scenario, CP1_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP1_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP1_OP);
        };

        // ── Initialize the RoleVoteBox ──
        ts::next_tx(&mut scenario, h::admin());
        { role_voting::init_for_testing(ts::ctx(&mut scenario)); };

        // ── Drive the relay idle: advance 31 epochs so gap (31) > max_idle_epochs (30). ──
        let mut i = 0u8;
        while (i < 31) {
            ts::next_epoch(&mut scenario, h::admin());
            i = i + 1;
        };

        // ── STEP 1: mark the miner revote-eligible via the IDLE path. ──
        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            role_voting::mark_revote_eligible_idle(
                &net_reg, &mut vote_box, &store,
                &relay_reg, &val_reg, &cp_reg, &sig_reg,
                miner_id, ts::ctx(&mut scenario),
            );

            assert!(role_voting::is_revote_eligible(&vote_box, miner_id), 0);

            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        // ── STEP 2: the CP casts a VALIDATOR vote. The miner's own StakePosition is
        //    bound to miner_id and its 0.25 SUI ≥ validator minimum (0.1 SUI), so the
        //    stake-binding + surplus guards pass. validator is scarce → 1 vote meets
        //    threshold → assignment persisted + miner removed from the revote pool. ──
        ts::next_tx(&mut scenario, MINER);
        let stake = ts::take_from_sender<StakePosition>(&scenario);

        ts::next_tx(&mut scenario, CP1_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            role_voting::cast_role_vote(
                &net_reg, &mut vote_box, &store,
                &cp_reg, &relay_reg, &val_reg, &sig_reg,
                &cp_cap, miner_id, constants::role_validator(),
                ts::ctx(&mut scenario),
            );

            // Threshold met → assignment persisted, miner left the revote pool.
            assert!(role_voting::get_assigned_role(&vote_box, miner_id) == option::some(constants::role_validator()), 1);
            assert!(!role_voting::is_revote_eligible(&vote_box, miner_id), 2);

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        // Return the stake to MINER so apply can re-take it as &mut from the owner.
        ts::next_tx(&mut scenario, CP1_OP);
        { ts::return_to_address(MINER, stake); };

        // ── STEP 3: the miner applies the voted role (RELAY → VALIDATOR). ──
        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut vote_box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            // Cap role flipped to validator.
            assert!(caps::miner_cap_role(&cap) == constants::role_validator(), 3);
            // Profile role also flipped (change_role mutated the store).
            assert!(miner_store::profile_role(miner_store::borrow_profile(&store, miner_id)) == constants::role_validator(), 4);
            // Stale RELAY entry cleaned up (apply removes the OLD-role registry entry).
            assert!(!relay_registry::is_registered(&relay_reg, miner_id), 5);
            // Assignment consumed (removed from assigned_roles).
            assert!(option::is_none(&role_voting::get_assigned_role(&vote_box, miner_id)), 6);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(vote_box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // ── Assert the apply tx emitted RoleApplied + RoleTransitioned = 2 user events. ──
        let effects = ts::next_tx(&mut scenario, MINER);
        assert!(ts::num_user_events(&effects) == 2, 7);

        ts::end(scenario);
    }
}
