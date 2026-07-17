/// Role voting tests — verifies cast_role_vote, threshold computation,
/// duplicate rejection, paused guard, invalid role, and threshold-met cleanup.
///
/// Coverage:
///   VOTE-01: RoleVoteBox shared object creation
///   VOTE-03: Dynamic voting threshold based on scarcity
///   VOTE-04: RoleAssigned event emitted + vote record cleaned up on threshold met
#[test_only]
module dvconf::role_voting_tests {
    use sui::test_scenario::{Self as ts};
    use sui::coin;
    use sui::sui::SUI;
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::miner_store::MinerStore;
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
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

    /// Setup scenario with registries + 3 CPs + 1 miner in MinerStore.
    fun setup_voting(): ts::Scenario {
        let mut scenario = h::setup_phase2();

        // Register a miner in MinerStore (via do_register — becomes relay at 0.25 SUI)
        h::do_register(&mut scenario, MINER1, h::relay_stake());

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

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        scenario
    }

    /// Get the miner_id from MinerStore for MINER1.
    fun get_miner_id(scenario: &mut ts::Scenario): ID {
        ts::next_tx(scenario, MINER1);
        let cap = ts::take_from_sender<caps::MinerCap>(scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(scenario, cap);
        miner_id
    }

    /// Cast a vote from a CP operator.
    ///
    /// F47 Phase 1.3: cast_role_vote now requires a `&StakePosition` bound to `miner_id`.
    /// MINER1 is registered as a RELAY (current_role != USER), so positive callers must also
    /// seed MINER1 into the re-vote pool (see `mark_miner1_eligible`) before voting.
    fun do_cast_vote(
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

    /// Build a StakePosition bound to `miner_id` with relay_stake (0.25 SUI) — satisfies the
    /// minimum_for_role of every non-CP target role used in these tests.
    fun make_stake(scenario: &mut ts::Scenario, miner_id: ID, role: u8): StakePosition {
        ts::next_tx(scenario, MINER1);
        let coin = coin::mint_for_testing<SUI>(h::relay_stake(), ts::ctx(scenario));
        staking::create_for_testing(MINER1, miner_id, role, coin, ts::ctx(scenario))
    }

    /// Swap the shared `RoleVoteBox` for a fresh one created at `base` threshold bps (no urgency
    /// decay). Duplicates the destroy-then-share idiom still inlined by the high-threshold tests
    /// (test_single_vote_accumulates / test_duplicate_vote_rejected — those were NOT migrated to
    /// this helper). A base of 10_000 over 3 CPs makes `required` == active_cp_count (3), so a
    /// single vote keeps the record OPEN — exactly what the role-guard tests need (record must
    /// persist past vote 1).
    fun replace_vote_box_with_base(scenario: &mut ts::Scenario, base: u64) {
        ts::next_tx(scenario, h::admin());
        {
            let default_box = ts::take_shared<RoleVoteBox>(scenario);
            role_voting::destroy_vote_box_for_testing(default_box);
        };
        ts::next_tx(scenario, h::admin());
        {
            let new_box = role_voting::create_vote_box_for_testing(base, 0, ts::ctx(scenario));
            role_voting::share_vote_box_for_testing(new_box);
        };
    }

    // ══════════════════════════════════════════════════════════
    // VOTE-01: RoleVoteBox init and accessors
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_vote_box_init() {
        let mut scenario = setup_voting();

        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(role_voting::base_threshold_bps(&vote_box) == 6_667, 0);
            assert!(role_voting::urgency_decay_bps(&vote_box) == 3_000, 1);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // VOTE-03: Single vote accumulates (with high threshold)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_single_vote_accumulates() {
        // Default setup has 3 CPs → threshold always 1, so first vote cleans up.
        // Use a custom vote box with base_threshold_bps=10000 (100%) to require all 3 CPs.
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // Replace the default vote box with a high-threshold one
        ts::next_tx(&mut scenario, h::admin());
        {
            let default_box = ts::take_shared<RoleVoteBox>(&scenario);
            role_voting::destroy_vote_box_for_testing(default_box);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let high_box = role_voting::create_vote_box_for_testing(
                10_000, // base_threshold_bps = 100% → requires 3 of 3 CPs
                0,      // no urgency decay
                ts::ctx(&mut scenario),
            );
            role_voting::share_vote_box_for_testing(high_box);
        };

        // MINER1 is a RELAY → must be in the re-vote pool for a re-vote to be accepted.
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());

        // Cast one vote — should NOT trigger threshold (needs 3)
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());

        // Check vote was recorded (not cleaned up)
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(role_voting::has_votes(&vote_box, miner_id), 0);
            assert!(role_voting::vote_count(&vote_box, miner_id) == 1, 1);
            assert!(role_voting::vote_role(&vote_box, miner_id) == constants::role_validator(), 2);
            ts::return_shared(vote_box);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // VOTE-04: Threshold met — vote record cleaned up
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_threshold_met_cleans_up() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // MINER1 is a RELAY → seed the re-vote pool, then provide a satisfying stake.
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());

        // Flat 2/3 threshold over 3 registered CPs → required = ceil(3*6667/10000) = 3.
        // Cast 3 distinct CP votes for the SAME role to reach the threshold and clean up.
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());
        do_cast_vote(&mut scenario, CP2_OP, &stake, miner_id, constants::role_validator());
        do_cast_vote(&mut scenario, CP3_OP, &stake, miner_id, constants::role_validator());

        // Check vote record was cleaned up (threshold met with 3 votes)
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(!role_voting::has_votes(&vote_box, miner_id), 0);
            ts::return_shared(vote_box);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // Duplicate vote rejected (E_ALREADY_VOTED = 704)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_ALREADY_VOTED)]
    fun test_duplicate_vote_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // Replace default vote box with high-threshold one so first vote doesn't clean up
        ts::next_tx(&mut scenario, h::admin());
        {
            let default_box = ts::take_shared<RoleVoteBox>(&scenario);
            role_voting::destroy_vote_box_for_testing(default_box);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let high_box = role_voting::create_vote_box_for_testing(
                10_000, // 100% threshold → requires all 3 CPs
                0,      // no urgency decay
                ts::ctx(&mut scenario),
            );
            role_voting::share_vote_box_for_testing(high_box);
        };

        // MINER1 is a RELAY → seed the re-vote pool on the high-threshold box; build a stake.
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());

        // First vote from CP1 — stays (threshold not met)
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());

        // Duplicate vote from CP1 — should abort E_ALREADY_VOTED (guards pass; duplicate caught after)
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // Invalid role rejected (E_INVALID_ROLE = 703)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_INVALID_ROLE)]
    fun test_invalid_role_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // Role 0 (USER) is not a valid vote target — aborts at E_INVALID_ROLE before the guards.
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_user());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // Miner not found rejected (E_MINER_NOT_FOUND = 702)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_MINER_NOT_FOUND)]
    fun test_miner_not_found_rejected() {
        let mut scenario = setup_voting();
        let fake_miner_id = object::id_from_address(@0xDEAD);

        // Aborts at E_MINER_NOT_FOUND before the guards inspect the stake.
        let stake = make_stake(&mut scenario, fake_miner_id, constants::role_validator());
        do_cast_vote(&mut scenario, CP1_OP, &stake, fake_miner_id, constants::role_validator());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // Paused network rejected (E_PAUSED = 700)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 700)]
    fun test_vote_when_paused_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // Pause network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Aborts at E_PAUSED (first assert) before the guards inspect the stake.
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // Unregistered CP rejected (E_CP_NOT_REGISTERED = 706)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_CP_NOT_REGISTERED)]
    fun test_unregistered_cp_rejected() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // Create a CP cap for an unregistered CP
        let fake_cp_addr: address = @0xFF;
        let fake_cp_id = object::id_from_address(@0xFE);
        ts::next_tx(&mut scenario, fake_cp_addr);
        {
            let cap = caps::new_cp_cap(fake_cp_id, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, fake_cp_addr);
        };

        // Build a stake for the signature (aborts at E_CP_NOT_REGISTERED before the guards).
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());

        // Try to vote with unregistered CP
        ts::next_tx(&mut scenario, fake_cp_addr);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            role_voting::cast_role_vote(
                &net_reg, &mut vote_box, &store,
                &cp_reg, &relay_reg, &val_reg, &sig_reg,
                &cap, miner_id, constants::role_validator(),
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // VOTE-03: Multiple votes from different CPs
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_multiple_cp_votes() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);

        // MINER1 is a RELAY → seed the re-vote pool; signaling minimum (0.05 SUI) < relay_stake.
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, constants::role_signaling());

        // Flat 2/3 threshold over 3 registered CPs → required = ceil(3*6667/10000) = 3.
        // Cast 3 distinct CP votes for the SAME role to reach the threshold.
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_signaling());
        do_cast_vote(&mut scenario, CP2_OP, &stake, miner_id, constants::role_signaling());
        do_cast_vote(&mut scenario, CP3_OP, &stake, miner_id, constants::role_signaling());

        // After threshold met, record is cleaned up
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(!role_voting::has_votes(&vote_box, miner_id), 0);
            assert!(role_voting::vote_count(&vote_box, miner_id) == 0, 1);
            ts::return_shared(vote_box);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // VOTE-01: vote_count returns 0 for unknown miner
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_vote_count_unknown_miner() {
        let mut scenario = setup_voting();
        let unknown = object::id_from_address(@0xBEEF);

        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(!role_voting::has_votes(&vote_box, unknown), 0);
            assert!(role_voting::vote_count(&vote_box, unknown) == 0, 1);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // MCV-A1: Flat 2/3-of-active-CP threshold (scarcity-decay removed)
    // ══════════════════════════════════════════════════════════

    // N=5 -> ceil(5*6667/10000)=4. A custom box with base=6667 mirrors the new init.
    #[test]
    fun test_threshold_flat_two_thirds_n5_requires_4() {
        let mut scenario = setup_voting();
        ts::next_tx(&mut scenario, h::admin());
        {
            let vb = role_voting::create_vote_box_for_testing(6_667, 0, ts::ctx(&mut scenario));
            // required(active_cp_count) ignores role/scarcity now.
            assert!(role_voting::compute_threshold_for_testing(&vb, 5) == 4, 0);
            assert!(role_voting::compute_threshold_for_testing(&vb, 1) == 1, 1);
            assert!(role_voting::compute_threshold_for_testing(&vb, 3) == 3, 2);
            assert!(role_voting::compute_threshold_for_testing(&vb, 4) == 3, 3);
            role_voting::share_vote_box_for_testing(vb);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // MCV-A2: Role-outcome guard — only same-role votes accumulate (E_ROLE_MISMATCH = 719)
    // ══════════════════════════════════════════════════════════

    /// A 2nd CP voting a DIFFERENT role for the same miner, while the record is still open, must
    /// abort with E_ROLE_MISMATCH. base=10_000 over 3 CPs -> required=3, so vote 1 keeps the
    /// record OPEN (1 < 3). MINER1 is a RELAY (current_role != USER), so it must be seeded into
    /// the re-vote pool first — otherwise the off-role vote would abort earlier on
    /// E_NOT_REVOTE_ELIGIBLE (708) instead of reaching the role-guard (719).
    #[test]
    #[expected_failure(abort_code = role_voting::E_ROLE_MISMATCH)]
    fun test_role_guard_rejects_off_role_vote() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);
        replace_vote_box_with_base(&mut scenario, 10_000);
        mark_miner1_eligible(&mut scenario);
        // do_cast_vote ignores its &StakePosition arg (the stake guards live on apply_voted_role),
        // but the signature still requires one. StakePosition has only `key` (no `drop`), so it is
        // a local that must be explicitly destroyed — it cannot be passed as an inline temporary.
        let stake = make_stake(&mut scenario, miner_id, constants::role_validator());

        // CP1 opens the record at role=Validator (1 < 3 -> stays open).
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_validator());
        // CP2 votes a DIFFERENT role (Relay) for the SAME miner -> E_ROLE_MISMATCH.
        do_cast_vote(&mut scenario, CP2_OP, &stake, miner_id, constants::role_relay());

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }

    /// Documents the KISS limitation: a minority first-mover's record is unrecoverable. base=10_000
    /// over 3 CPs -> required=3, so the first mover (CP1) opens a Relay record that sits at 1 < 3
    /// with NO on-chain recovery path. This test asserts ONLY that single fact — the record PERSISTS
    /// in the stuck state (has_votes == true after one sub-threshold vote).
    ///
    /// It does NOT exercise the 719 role-guard: it casts no off-role challenger, so the assertion
    /// would hold with or without the guard. The guard is what GUARANTEES such a minority record can
    /// never be finalized by off-role votes — that behavior is exercised by
    /// `test_role_guard_rejects_off_role_vote`. The two tests are complementary: this one pins the
    /// "stuck, unrecovered" outcome; that one pins the "off-role challenger aborts (719)" mechanism.
    #[test]
    fun test_minority_first_mover_record_persists_unrecovered() {
        let mut scenario = setup_voting();
        let miner_id = get_miner_id(&mut scenario);
        replace_vote_box_with_base(&mut scenario, 10_000);
        mark_miner1_eligible(&mut scenario);
        let stake = make_stake(&mut scenario, miner_id, constants::role_relay());

        // First-mover (CP1) opens the record at Relay (1 < 3 -> stays open).
        do_cast_vote(&mut scenario, CP1_OP, &stake, miner_id, constants::role_relay());

        ts::next_tx(&mut scenario, h::admin());
        {
            let vb = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(role_voting::has_votes(&vb, miner_id), 0); // record persists, unrecovered
            ts::return_shared(vb);
        };

        staking::destroy_for_testing(stake);
        ts::end(scenario);
    }
}
