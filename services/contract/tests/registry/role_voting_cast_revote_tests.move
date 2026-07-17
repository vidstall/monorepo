/// F47 Phase 1.3 — REQ-RV-003 verification: cast_role_vote re-vote guards.
///
/// Guards under test (ADR-0008 Q3/Q4/Q5 cast-side, Guards 1/4 + CP-partial):
///   Guard 1 — re-vote pool membership: a miner whose current_role != USER must be
///             in `revote_eligible` before CPs may re-vote (E_NOT_REVOTE_ELIGIBLE = 708).
///   CP-part — CP↔non-CP transitions deferred (E_CP_REVOTE_REQUIRES_MIGRATION = 714).
///   Guard 4 — pending: miner must not already have a pending assignment (E_PRIOR_ASSIGNMENT_PENDING = 711).
///
/// NOTE: the old cast-side stake guards (Guard 2a binding / Guard 2b surplus) were RELOCATED to
/// registration::apply_voted_role per D-S70-4 / OQ-PH13 — cast_role_vote is CP-signed and cannot
/// reference a miner's owned StakePosition. Their tests now live in
/// registration_apply_voted_role_tests.move (APPLY-10 = 713 threshold, APPLY-11 = 717 binding).
///
/// Coverage (4 tests):
///   RV-CAST-N1: re-vote miner with non-USER role NOT in revote_eligible → 708
///   RV-CAST-N3: miner already has pending assignment → 711
///   RV-CAST-N4: re-vote where old or new role == CP → 714
///   RV-CAST-P1: all guards satisfied → vote recorded; threshold met → miner removed from pool
#[test_only]
module dvconf::role_voting_cast_revote_tests {
    use sui::test_scenario::{Self as ts};
    use sui::coin;
    use sui::sui::SUI;
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{NetworkRegistry};
    use dvconf::miner_store::MinerStore;
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{RelayRegistry};
    use dvconf::validator_registry::{ValidatorRegistry};
    use dvconf::signaling_registry::{SignalingRegistry};
    use dvconf::caps::{Self, ControlPlaneCap, MinerCap};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::role_voting::{Self, RoleVoteBox};

    // ── Test addresses ──
    const CP1_OP: address = @0xC1;
    const CP2_OP: address = @0xC2;
    const CP3_OP: address = @0xC3;
    const CP1_ID: address = @0xA6;
    const CP2_ID: address = @0xA7;
    const CP3_ID: address = @0xA8;
    const MINER1: address = @0xAA;

    fun id_from_addr(addr: address): ID {
        object::id_from_address(addr)
    }

    /// Setup: registries + 3 CPs + MINER1 registered as a RELAY (current_role != USER).
    /// RoleVoteBox initialized. Mirrors role_voting_tests::setup_voting.
    fun setup_voting(): ts::Scenario {
        let mut scenario = h::setup_phase2();

        // Register MINER1 as a relay miner (current_role = RELAY → re-vote path).
        h::do_register_with_role(&mut scenario, MINER1, h::relay_stake(), constants::role_relay());

        // Register 3 CPs in ControlPlaneRegistry
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP1_ID), CP1_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP2_ID), CP2_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP3_ID), CP3_OP, h::cp_stake(), ctx);
            ts::return_shared(cp_reg);
        };

        // Create CP caps
        ts::next_tx(&mut scenario, CP1_OP);
        { let cap = caps::new_cp_cap(id_from_addr(CP1_ID), ts::ctx(&mut scenario)); transfer::public_transfer(cap, CP1_OP); };
        ts::next_tx(&mut scenario, CP2_OP);
        { let cap = caps::new_cp_cap(id_from_addr(CP2_ID), ts::ctx(&mut scenario)); transfer::public_transfer(cap, CP2_OP); };
        ts::next_tx(&mut scenario, CP3_OP);
        { let cap = caps::new_cp_cap(id_from_addr(CP3_ID), ts::ctx(&mut scenario)); transfer::public_transfer(cap, CP3_OP); };

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        { role_voting::init_for_testing(ts::ctx(&mut scenario)); };

        scenario
    }

    /// Setup variant for INITIAL votes: identical to `setup_voting` but MINER1 is registered
    /// with role == USER (constants::role_user() == 0). The profile lives in MinerStore only —
    /// it is NOT added to any role registry and NOT seeded into revote_eligible/assigned_roles —
    /// so cast_role_vote sees current_role == USER and the re-vote-only guards (708 / 714) must
    /// short-circuit. Mirrors `setup_voting` for the CP set and RoleVoteBox init.
    fun setup_voting_initial(): ts::Scenario {
        let mut scenario = h::setup_phase2();

        // Register MINER1 as a USER-role miner (current_role == USER → initial-vote path).
        h::do_register_with_role(&mut scenario, MINER1, h::relay_stake(), constants::role_user());

        // Register 3 CPs in ControlPlaneRegistry
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP1_ID), CP1_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP2_ID), CP2_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP3_ID), CP3_OP, h::cp_stake(), ctx);
            ts::return_shared(cp_reg);
        };

        // Create CP caps
        ts::next_tx(&mut scenario, CP1_OP);
        { let cap = caps::new_cp_cap(id_from_addr(CP1_ID), ts::ctx(&mut scenario)); transfer::public_transfer(cap, CP1_OP); };
        ts::next_tx(&mut scenario, CP2_OP);
        { let cap = caps::new_cp_cap(id_from_addr(CP2_ID), ts::ctx(&mut scenario)); transfer::public_transfer(cap, CP2_OP); };
        ts::next_tx(&mut scenario, CP3_OP);
        { let cap = caps::new_cp_cap(id_from_addr(CP3_ID), ts::ctx(&mut scenario)); transfer::public_transfer(cap, CP3_OP); };

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        { role_voting::init_for_testing(ts::ctx(&mut scenario)); };

        scenario
    }

    /// Get MINER1's miner_id from its MinerCap.
    fun get_miner_id(scenario: &mut ts::Scenario): ID {
        ts::next_tx(scenario, MINER1);
        let cap = ts::take_from_sender<MinerCap>(scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(scenario, cap);
        miner_id
    }

    /// Seed MINER1 into the revote_eligible pool via miner self-request (sender = cap owner).
    fun mark_miner1_eligible(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, MINER1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(scenario);
            let store = ts::take_shared<MinerStore>(scenario);
            let cap = ts::take_from_sender<MinerCap>(scenario);

            role_voting::mark_revote_eligible_miner_request(
                &net_reg, &mut vote_box, &store, &cap, ts::ctx(scenario),
            );

            ts::return_to_sender(scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
        };
    }

    /// Build a StakePosition for `miner_id` with `amount` MIST and `role`, owned by MINER1.
    fun make_stake(scenario: &mut ts::Scenario, miner_id: ID, amount: u64, role: u8): StakePosition {
        ts::next_tx(scenario, MINER1);
        let coin = coin::mint_for_testing<SUI>(amount, ts::ctx(scenario));
        staking::create_for_testing(MINER1, miner_id, role, coin, ts::ctx(scenario))
    }

    /// Cast a vote from a CP operator. `_stake` is retained for call-site compatibility but no
    /// longer forwarded: the stake guards moved to apply_voted_role (D-S70-4 / OQ-PH13).
    fun do_cast_vote_with_stake(
        scenario: &mut ts::Scenario,
        cp_addr: address,
        _stake: &StakePosition,
        miner_id: ID,
        role: u8,
    ) {
        ts::next_tx(scenario, cp_addr);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(scenario);
            let store = ts::take_shared<MinerStore>(scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(scenario);

            role_voting::cast_role_vote(
                &net_reg, &mut vote_box, &store,
                &cp_reg, &relay_reg, &val_reg, &sig_reg,
                &cap, miner_id, role,
                ts::ctx(scenario),
            );

            ts::return_to_sender(scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };
    }

    // ══════════════════════════════════════════════════════════
    // RV-CAST-N1: re-vote miner NOT in revote_eligible → E_NOT_REVOTE_ELIGIBLE (708)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_NOT_REVOTE_ELIGIBLE)]
    fun test_revote_not_eligible_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // MINER1 is RELAY (current_role != USER) and NOT in revote_eligible → Guard 1 aborts.
        // Stake satisfies the target-role minimum so we isolate Guard 1.
        let stake = make_stake(&mut scenario, miner_id, h::relay_stake(), constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // RV-CAST-N2 (stake surplus) + RV-CAST-N5 (stake binding) RELOCATED to
    // registration_apply_voted_role_tests.move (APPLY-10 / APPLY-11) per D-S70-4 / OQ-PH13:
    // the stake guards moved from the CP-signed cast path to the MINER-signed apply path, so
    // they can no longer be exercised here.

    // ══════════════════════════════════════════════════════════
    // RV-CAST-N3: miner already has a pending assignment → E_PRIOR_ASSIGNMENT_PENDING (711)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_PRIOR_ASSIGNMENT_PENDING)]
    fun test_revote_prior_assignment_pending_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // First eligible re-vote campaign reaches the multi-CP quorum
        // (required = ceil(3 * 6667/10000) = 3): the 3rd matching vote finalizes, so
        // assigned_roles[miner_id] is populated AND the miner is removed from the pool —
        // the finalize cleanup also clears its revote_eligible + revote_eligible_since entries.
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, h::relay_stake(), constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP2_OP, &stake, miner_id, constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP3_OP, &stake, miner_id, constants::role_validator());

        // Re-mark eligible. Because the finalize cleanup above REMOVED the prior
        // revote_eligible_since entry, insert_into_revote_pool creates a FRESH timestamp and the
        // cooldown guard (E_COOLDOWN = 709) is NOT reached — so Guard 1 (708) passes cleanly.
        // The campaign's assignment is still UNCONSUMED (no apply_voted_role here), so the next
        // vote must abort on the pending-assignment guard (E_PRIOR_ASSIGNMENT_PENDING = 711).
        mark_miner1_eligible(&mut scenario);
        let stake2 = make_stake(&mut scenario, miner_id, h::relay_stake(), constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake2, miner_id, constants::role_validator());

        staking::destroy_for_testing(stake);
        staking::destroy_for_testing(stake2);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-CAST-N4: re-vote into CP (new role == CP) → E_CP_REVOTE_REQUIRES_MIGRATION (714)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_CP_REVOTE_REQUIRES_MIGRATION)]
    fun test_revote_cp_transition_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // MINER1 is RELAY (current_role != USER) and eligible; voting INTO CP is a
        // CP↔non-CP transition → CP-partial aborts. Stake satisfies CP minimum so we
        // isolate the CP-partial guard from Guard 2b.
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, h::cp_stake(), constants::role_cp());
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake, miner_id, constants::role_cp());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // RV-CAST-N5 relocated — see the note above RV-CAST-N3 (now APPLY-11).

    // ══════════════════════════════════════════════════════════
    // RV-CAST-P1: all guards satisfied → vote recorded; threshold met → removed from pool
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_revote_eligible_succeeds_and_clears_pool() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // Make eligible, then cast an eligible re-vote with a satisfying stake.
        mark_miner1_eligible(&mut scenario);

        // Sanity: miner is in the pool before the vote.
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(role_voting::is_revote_eligible(&vote_box, miner_id), 0);
            ts::return_shared(vote_box);
        };

        let stake = make_stake(&mut scenario, miner_id, h::relay_stake(), constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP2_OP, &stake, miner_id, constants::role_validator());
        do_cast_vote_with_stake(&mut scenario, CP3_OP, &stake, miner_id, constants::role_validator());

        // Multi-CP quorum: required = ceil(3 * 6667/10000) = 3 votes. The miner stays in the pool
        // across votes 1 and 2 (so Guard 1 keeps passing); the 3rd matching vote meets threshold,
        // so the assignment is persisted AND the miner is removed from the re-vote pool.
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            // Threshold met → vote record cleaned up.
            assert!(!role_voting::has_votes(&vote_box, miner_id), 1);
            // Threshold-met cleanup also removed the miner from the re-vote pool.
            assert!(!role_voting::is_revote_eligible(&vote_box, miner_id), 2);
            // Assignment persisted for the daemon to consume.
            assert!(role_voting::get_assigned_role(&vote_box, miner_id) == option::some(constants::role_validator()), 3);
            ts::return_shared(vote_box);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-CAST-P2 (initial-vote coverage): miner with current_role == USER voting into a
    // NON-CP role (RELAY). The re-vote-only guards must NOT fire on an initial vote:
    //   - Guard 1 (708) is gated on current_role != USER → skipped (miner need NOT be in
    //     revote_eligible).
    //   - CP-partial (714) requires current_role != USER → short-circuits false.
    // Guard 2a/2b/4 still apply and are satisfied (stake bound to miner_id, amount >= relay
    // minimum, no pending assignment). The multi-CP quorum required = ceil(3 * 6667/10000) = 3,
    // so the 3rd matching vote meets threshold → RoleAssigned + assignment persisted.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_initial_vote_into_noncp_succeeds() {
        let mut scenario = setup_voting_initial();
        let miner_id = get_miner_id(&mut scenario);

        // Sanity: USER-role miner is NOT in the re-vote pool and has NO pending assignment.
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(!role_voting::is_revote_eligible(&vote_box, miner_id), 0);
            ts::return_shared(vote_box);
        };

        // Stake bound to miner_id, amount (0.25 SUI) >= relay minimum → Guard 2 satisfied.
        let stake = make_stake(&mut scenario, miner_id, h::relay_stake(), constants::role_relay());

        // INITIAL votes into RELAY. current_role == USER, so each vote skips Guard 1 (708) and
        // the CP-partial guard (714) — neither may abort an initial vote.
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake, miner_id, constants::role_relay());
        do_cast_vote_with_stake(&mut scenario, CP2_OP, &stake, miner_id, constants::role_relay());
        do_cast_vote_with_stake(&mut scenario, CP3_OP, &stake, miner_id, constants::role_relay());

        // Multi-CP quorum: required = ceil(3 * 6667/10000) = 3 → the 3rd vote meets threshold,
        // so the assignment is persisted and the vote record is cleaned up.
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(!role_voting::has_votes(&vote_box, miner_id), 1);
            assert!(role_voting::get_assigned_role(&vote_box, miner_id) == option::some(constants::role_relay()), 2);
            ts::return_shared(vote_box);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-CAST-P3 (initial-vote coverage — CP-partial regression): miner with current_role
    // == USER voting INTO CP. The CP-partial guard (714) is gated on current_role != USER,
    // so an initial vote into CP must short-circuit false and NOT abort. This is the
    // most-likely-bug regression guard for the new CP-partial condition.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_initial_vote_into_cp_succeeds() {
        let mut scenario = setup_voting_initial();
        let miner_id = get_miner_id(&mut scenario);

        // Stake bound to miner_id, amount (0.5 SUI) >= CP minimum → Guard 2 satisfied.
        let stake = make_stake(&mut scenario, miner_id, h::cp_stake(), constants::role_cp());

        // INITIAL votes into CP. current_role == USER makes the CP-partial condition
        // (current_role != USER && (current_role==CP || role==CP)) short-circuit false on EACH
        // vote → must NOT abort with 714 (nor 708).
        do_cast_vote_with_stake(&mut scenario, CP1_OP, &stake, miner_id, constants::role_cp());
        do_cast_vote_with_stake(&mut scenario, CP2_OP, &stake, miner_id, constants::role_cp());
        do_cast_vote_with_stake(&mut scenario, CP3_OP, &stake, miner_id, constants::role_cp());

        // Multi-CP quorum: required = ceil(3 * 6667/10000) = 3 → the 3rd vote meets threshold;
        // assignment persisted with the CP role.
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(role_voting::get_assigned_role(&vote_box, miner_id) == option::some(constants::role_cp()), 1);
            ts::return_shared(vote_box);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }
}
