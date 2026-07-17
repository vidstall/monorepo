/// F47 Phase 1.2 — REQ-RV-002 verification: 3 mark_revote_eligible_* entries +
/// shared insert_into_revote_pool helper.
///
/// Coverage (7 tests):
///   RV-MARK-01: mark_revote_eligible_idle succeeds after threshold (positive)
///   RV-MARK-02: mark_revote_eligible_composition_shift succeeds on surplus role (positive)
///   RV-MARK-03: mark_revote_eligible_miner_request succeeds with valid MinerCap (positive)
///   RV-MARK-04: mark_revote_eligible_idle aborts when not idle yet (negative, E_NOT_IDLE_YET)
///   RV-MARK-05: mark_revote_eligible_composition_shift aborts when balanced (negative, E_COMPOSITION_NOT_IMBALANCED)
///   RV-MARK-06: mark_revote_eligible_miner_request aborts with wrong cap owner (negative, E_INVALID_CAP_OWNER)
///   RV-MARK-07: cooldown blocks re-mark within window (negative, E_COOLDOWN)
#[test_only]
module dvconf::role_voting_mark_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::{NetworkRegistry};
    use dvconf::miner_store::MinerStore;
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::role_voting::{Self, RoleVoteBox};

    // ── Test addresses ──
    const MINER_RELAY: address  = @0xA1;
    const MINER_VAL: address    = @0xA2;
    const WRONG_SENDER: address = @0xBB;

    // ── Extra node IDs for counting (fixed, no arithmetic on addresses) ──
    const EXTRA_VAL_ID_1: address = @0xD01;
    const EXTRA_VAL_ID_2: address = @0xD02;
    const EXTRA_VAL_ID_3: address = @0xD03;
    const EXTRA_VAL_ID_4: address = @0xD04;
    const EXTRA_VAL_ID_5: address = @0xD05;
    const EXTRA_VAL_ID_6: address = @0xD06;
    const EXTRA_VAL_ID_7: address = @0xD07;
    const EXTRA_VAL_ID_8: address = @0xD08;
    const EXTRA_VAL_ID_9: address = @0xD09;
    const EXTRA_RELAY_ID: address = @0xB90;
    const EXTRA_CP_ID:    address = @0xC90;
    const EXTRA_SIG_ID:   address = @0xF90;
    const BAL_RELAY_ID:   address = @0xB50;
    const BAL_VAL_ID:     address = @0xD50;
    const BAL_CP_ID:      address = @0xC50;
    const BAL_SIG_ID:     address = @0xF50;

    // ══════════════════════════════════════════════════════════
    // SETUP HELPERS
    // ══════════════════════════════════════════════════════════

    /// Setup: all registries + role_voting initialized.
    /// Registers MINER_RELAY as a relay miner in MinerStore + RelayRegistry.
    /// RelayRegistry entry has last_heartbeat = epoch 0 (test start).
    /// Caller must advance epochs before calling mark_revote_eligible_idle.
    fun setup_with_relay_miner(): (ts::Scenario, ID) {
        let mut scenario = h::setup_phase2();

        // Register relay miner in MinerStore (receives MinerCap with role=RELAY)
        h::do_register_with_role(&mut scenario, MINER_RELAY, h::relay_stake(), constants::role_relay());

        // Retrieve miner_id from MinerCap
        ts::next_tx(&mut scenario, MINER_RELAY);
        let cap = ts::take_from_sender<MinerCap>(&scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(&scenario, cap);

        // Add miner to RelayRegistry with last_heartbeat = current epoch (0)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            if (!relay_registry::is_registered(&relay_reg, miner_id)) {
                relay_registry::add_relay_for_testing(&mut relay_reg, miner_id, MINER_RELAY, ts::ctx(&mut scenario));
            };
            ts::return_shared(relay_reg);
        };

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        (scenario, miner_id)
    }

    /// Setup: validator miner in surplus (many validators, zero of other roles).
    ///
    /// Network state: 10 validators (miner_id + 9 extras), 0 relay, 0 CP, 0 signaling.
    ///   total = 10; raw_val = 10/10 = 1, raw_relay = 10/1 = 10, raw_cp = 10/1 = 10, raw_sig = 10/1 = 10
    ///   raw_total = 31; n_validator = 1*10000/31 = 322 bps < floor (500) → SURPLUS ✓
    fun setup_with_validator_miner_surplus(): (ts::Scenario, ID) {
        let mut scenario = h::setup_phase2();

        // Register the validator miner in MinerStore
        h::do_register_with_role(&mut scenario, MINER_VAL, h::validator_stake(), constants::role_validator());

        // Retrieve miner_id
        ts::next_tx(&mut scenario, MINER_VAL);
        let cap = ts::take_from_sender<MinerCap>(&scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(&scenario, cap);

        // Add to ValidatorRegistry (miner_id = 1st validator)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            if (!validator_registry::is_registered(&val_reg, miner_id)) {
                validator_registry::add_validator_for_testing(&mut val_reg, miner_id, MINER_VAL, h::validator_stake(), ts::ctx(&mut scenario));
            };
            ts::return_shared(val_reg);
        };

        // Add 9 more validators (10 total). With 0 relay/cp/sig:
        //   total=10; raw_val=10/10=1, raw_relay/cp/sig=10/1=10 each; raw_total=31
        //   n_validator = 1*10000/31 = 322 bps < floor=500 → validator is SURPLUS ✓
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_1), @0xDE1, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_2), @0xDE2, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_3), @0xDE3, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_4), @0xDE4, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_5), @0xDE5, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_6), @0xDE6, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_7), @0xDE7, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_8), @0xDE8, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(EXTRA_VAL_ID_9), @0xDE9, 100_000_000, ctx);
            ts::return_shared(val_reg);
        };

        // Initialize RoleVoteBox (no relay/cp/sig nodes — pure validator surplus)
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        (scenario, miner_id)
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-01: mark_revote_eligible_idle succeeds after threshold
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_mark_idle_succeeds_after_threshold() {
        let (mut scenario, miner_id) = setup_with_relay_miner();

        // Advance 31 epochs so relay miner's last_heartbeat (epoch=0) is stale:
        // gap = 31 > MAX_IDLE_EPOCHS=30. Use next_epoch to move epoch counter.
        let mut i = 0u8;
        while (i < 31) {
            ts::next_epoch(&mut scenario, h::admin());
            i = i + 1;
        };

        // Call mark_revote_eligible_idle — miner has role=RELAY, gap > MAX_IDLE_EPOCHS
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
                &net_reg,
                &mut vote_box,
                &store,
                &relay_reg,
                &val_reg,
                &cp_reg,
                &sig_reg,
                miner_id,
                ts::ctx(&mut scenario),
            );

            // Verify: miner is now in revote_eligible pool
            assert!(role_voting::is_revote_eligible(&vote_box, miner_id), 0);
            // Verify: revote_eligible_since was recorded at current epoch (>0)
            assert!(role_voting::revote_eligible_since_epoch(&vote_box, miner_id) > 0, 1);

            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-02: mark_revote_eligible_composition_shift succeeds on surplus role
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_mark_composition_shift_succeeds_on_surplus_role() {
        let (mut scenario, miner_id) = setup_with_validator_miner_surplus();

        // Validators are surplus: 10 validators total, 0 relay/CP/signaling.
        // raw_val = 10/10 = 1; raw_relay = raw_cp = raw_sig = 10/1 = 10; raw_total = 31.
        // n_validator = 1*10000/31 = 322 bps < SCARCITY_FLOOR_BPS (500) → SURPLUS.
        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            role_voting::mark_revote_eligible_composition_shift(
                &net_reg,
                &mut vote_box,
                &store,
                &relay_reg,
                &val_reg,
                &cp_reg,
                &sig_reg,
                miner_id,
                ts::ctx(&mut scenario),
            );

            // Verify: miner is in revote_eligible pool
            assert!(role_voting::is_revote_eligible(&vote_box, miner_id), 0);

            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-03: mark_revote_eligible_miner_request succeeds with valid MinerCap
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_mark_miner_request_succeeds_with_cap() {
        let mut scenario = h::setup_phase2();

        // Register miner with relay role (MINER_RELAY gets MinerCap where owner = MINER_RELAY)
        h::do_register_with_role(&mut scenario, MINER_RELAY, h::relay_stake(), constants::role_relay());

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        // Get miner_id from MinerCap
        ts::next_tx(&mut scenario, MINER_RELAY);
        let cap = ts::take_from_sender<MinerCap>(&scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(&scenario, cap);

        // Call mark_revote_eligible_miner_request — signed by MINER_RELAY (cap owner)
        ts::next_tx(&mut scenario, MINER_RELAY);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            role_voting::mark_revote_eligible_miner_request(
                &net_reg,
                &mut vote_box,
                &store,
                &cap,
                ts::ctx(&mut scenario),
            );

            // Verify: miner is in revote_eligible pool
            assert!(role_voting::is_revote_eligible(&vote_box, miner_id), 0);

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-04: mark_revote_eligible_idle aborts when not idle yet (E_NOT_IDLE_YET)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_NOT_IDLE_YET)]
    fun test_mark_idle_aborts_when_not_idle_yet() {
        let (mut scenario, miner_id) = setup_with_relay_miner();

        // Advance only 10 epochs — NOT enough (10 < MAX_IDLE_EPOCHS=30)
        let mut i = 0u8;
        while (i < 10) {
            ts::next_epoch(&mut scenario, h::admin());
            i = i + 1;
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            // Should abort E_NOT_IDLE_YET (epoch gap = 10, threshold = 30)
            role_voting::mark_revote_eligible_idle(
                &net_reg,
                &mut vote_box,
                &store,
                &relay_reg,
                &val_reg,
                &cp_reg,
                &sig_reg,
                miner_id,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-05: mark_revote_eligible_composition_shift aborts when balanced
    //             (E_COMPOSITION_NOT_IMBALANCED)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_COMPOSITION_NOT_IMBALANCED)]
    fun test_mark_composition_shift_aborts_when_balanced() {
        let mut scenario = h::setup_phase2();

        // Register a relay miner
        h::do_register_with_role(&mut scenario, MINER_RELAY, h::relay_stake(), constants::role_relay());

        // Get relay miner_id
        ts::next_tx(&mut scenario, MINER_RELAY);
        let cap = ts::take_from_sender<MinerCap>(&scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(&scenario, cap);

        // Balanced: 2 relays (miner + BAL_RELAY_ID), 1 each validator/CP/sig
        // total=5; raw_relay=5/2=2, raw_val=5/1=5, raw_cp=5/1=5, raw_sig=5/1=5
        // raw_total=17; n_relay=2*10000/17=1176 bps > floor(500) and < ceiling(8000)
        // → relay is NOT surplus → E_COMPOSITION_NOT_IMBALANCED
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, object::id_from_address(BAL_RELAY_ID), @0xB5, ts::ctx(&mut scenario));
            ts::return_shared(relay_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(&mut val_reg, object::id_from_address(BAL_VAL_ID), @0xD5, h::validator_stake(), ts::ctx(&mut scenario));
            ts::return_shared(val_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, object::id_from_address(BAL_CP_ID), @0xC5, h::cp_stake(), ts::ctx(&mut scenario));
            ts::return_shared(cp_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            signaling_registry::add_signaling_for_testing(&mut sig_reg, object::id_from_address(BAL_SIG_ID), @0xF5, ts::ctx(&mut scenario));
            ts::return_shared(sig_reg);
        };

        // Also add relay miner to RelayRegistry so it's counted
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            if (!relay_registry::is_registered(&relay_reg, miner_id)) {
                relay_registry::add_relay_for_testing(&mut relay_reg, miner_id, MINER_RELAY, ts::ctx(&mut scenario));
            };
            ts::return_shared(relay_reg);
        };

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            // Relay scarcity ratio ~1176 bps > floor(500) → relay is NOT in surplus
            // Should abort E_COMPOSITION_NOT_IMBALANCED
            role_voting::mark_revote_eligible_composition_shift(
                &net_reg,
                &mut vote_box,
                &store,
                &relay_reg,
                &val_reg,
                &cp_reg,
                &sig_reg,
                miner_id,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-06: mark_revote_eligible_miner_request aborts with wrong cap owner
    //             (E_INVALID_CAP_OWNER: ctx.sender() ≠ profile.owner)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_INVALID_CAP_OWNER)]
    fun test_mark_miner_request_aborts_with_wrong_cap_owner() {
        let mut scenario = h::setup_phase2();

        // Register miner MINER_RELAY — owner becomes MINER_RELAY in MinerProfile
        h::do_register_with_role(&mut scenario, MINER_RELAY, h::relay_stake(), constants::role_relay());

        // Get MINER_RELAY's miner_id
        ts::next_tx(&mut scenario, MINER_RELAY);
        let real_cap = ts::take_from_sender<MinerCap>(&scenario);
        let miner_id = caps::miner_cap_miner_id(&real_cap);
        ts::return_to_sender(&scenario, real_cap);

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        // WRONG_SENDER creates a fake MinerCap pointing to MINER_RELAY's miner_id.
        // The ownership check: ctx.sender() == miner_store::profile_owner(profile)
        // will see WRONG_SENDER ≠ MINER_RELAY → abort E_INVALID_CAP_OWNER.
        ts::next_tx(&mut scenario, WRONG_SENDER);
        {
            let fake_cap = caps::new_miner_cap(miner_id, constants::role_relay(), ts::ctx(&mut scenario));
            transfer::public_transfer(fake_cap, WRONG_SENDER);
        };

        // Attempt mark with WRONG_SENDER holding a cap for MINER_RELAY's miner_id
        ts::next_tx(&mut scenario, WRONG_SENDER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let fake_cap = ts::take_from_sender<MinerCap>(&scenario);

            // ctx.sender() = WRONG_SENDER, but profile.owner = MINER_RELAY → abort
            role_voting::mark_revote_eligible_miner_request(
                &net_reg,
                &mut vote_box,
                &store,
                &fake_cap,
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, fake_cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // RV-MARK-07: cooldown blocks re-mark within 14-epoch window (E_COOLDOWN)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = role_voting::E_COOLDOWN)]
    fun test_mark_cooldown_blocks_re_mark() {
        let mut scenario = h::setup_phase2();

        // Register miner
        h::do_register_with_role(&mut scenario, MINER_RELAY, h::relay_stake(), constants::role_relay());

        // Initialize RoleVoteBox
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        // Get miner_id
        ts::next_tx(&mut scenario, MINER_RELAY);
        let cap = ts::take_from_sender<MinerCap>(&scenario);
        let miner_id = caps::miner_cap_miner_id(&cap);
        ts::return_to_sender(&scenario, cap);

        // First mark (miner_request) — succeeds (no prior cooldown entry)
        ts::next_tx(&mut scenario, MINER_RELAY);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            role_voting::mark_revote_eligible_miner_request(
                &net_reg,
                &mut vote_box,
                &store,
                &cap,
                ts::ctx(&mut scenario),
            );
            assert!(role_voting::is_revote_eligible(&vote_box, miner_id), 0);

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
        };

        // Advance only 5 epochs (< COOLDOWN_EPOCHS=14) — cooldown still active
        let mut i = 0u8;
        while (i < 5) {
            ts::next_epoch(&mut scenario, h::admin());
            i = i + 1;
        };

        // Second mark attempt within cooldown — should abort E_COOLDOWN
        ts::next_tx(&mut scenario, MINER_RELAY);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            role_voting::mark_revote_eligible_miner_request(
                &net_reg,
                &mut vote_box,
                &store,
                &cap,
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }
}
