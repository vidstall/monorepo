/// F47 Phase 1.5 — apply_voted_role signature change + N-caller refactor (REQ-RV-005, RV-006).
///
/// Covers the new 9-object signature: cross-registry cleanup of the OLD role on a
/// genuine transition, the apply-side Q5 CP-migration guard (defensive mirror of the
/// cast-side guard in role_voting.move), and the RoleApplied + RoleTransitioned event
/// contract.
///
/// Coverage:
///   APPLY-01: Relay -> Validator — stale RelayRegistry entry removed, role flips, 2 events
///   APPLY-02: Validator -> Validator (same role) — NO cleanup, NO RoleTransitioned (1 event)
///   APPLY-03: User -> Relay (first application) — no stale registry to clean, role flips, 2 events
///   APPLY-04: Relay -> CP re-vote — aborts E_CP_REVOTE_REQUIRES_MIGRATION (714)
///   APPLY-05: paused protocol — aborts E_PROTOCOL_PAUSED (403)
///   APPLY-10: below-threshold stake — aborts E_INSUFFICIENT_STAKE_FOR_ROLE (713) [relocated RV-CAST-N2, D-S70-4]
///   APPLY-11: stake bound to a different miner — aborts E_STAKE_NOT_OWNED_BY_MINER (717) [relocated RV-CAST-N5, D-S70-4]
#[test_only]
module dvconf::registration_apply_voted_role_tests {
    use sui::test_scenario::{Self as ts};
    use sui::coin;
    use sui::sui::SUI;
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::registration;
    use dvconf::role_voting::{Self, RoleVoteBox};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::control_plane_registry::ControlPlaneRegistry;

    const MINER: address = @0xAA;

    // ── helpers ──────────────────────────────────────────────────────────

    /// setup_phase2 (all 5 registries) + register MINER at `stake` (role derived from
    /// the stake bracket) + share a fresh RoleVoteBox.
    fun setup_apply(stake: u64): ts::Scenario {
        let mut scenario = h::setup_phase2();
        h::do_register(&mut scenario, MINER, stake);
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };
        scenario
    }

    /// Like `setup_apply` but registers MINER with an EXPLICIT old role while keeping the
    /// StakePosition funded at `stake`. Needed after D-S70-4 / OQ-PH13: apply_voted_role now
    /// asserts `stake.amount >= minimum_for_role(new_role)`, so positive transitions need a
    /// funded stake that does NOT necessarily match the stake-bracket role (e.g. a USER-role
    /// miner holding enough stake to be voted into RELAY/CP).
    fun setup_apply_role(stake: u64, role: u8): ts::Scenario {
        let mut scenario = h::setup_phase2();
        h::do_register_with_role(&mut scenario, MINER, stake, role);
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };
        scenario
    }

    /// Seed an assignment (miner_id -> role) into the shared RoleVoteBox.
    fun inject(scenario: &mut ts::Scenario, miner_id: ID, role: u8) {
        ts::next_tx(scenario, h::admin());
        {
            let mut box = ts::take_shared<RoleVoteBox>(scenario);
            role_voting::add_assignment_for_testing(&mut box, miner_id, role);
            ts::return_shared(box);
        };
    }

    // ── APPLY-01 ─────────────────────────────────────────────────────────
    #[test]
    fun apply_01_relay_to_validator_cleans_old_and_transitions() {
        let mut scenario = setup_apply(h::relay_stake()); // role = relay
        let miner_id = object::id_from_address(MINER);

        // Seed the RelayRegistry so cleanup has a real stale entry to drop.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, miner_id, MINER, ts::ctx(&mut scenario));
            assert!(relay_registry::is_registered(&relay_reg, miner_id), 0);
            ts::return_shared(relay_reg);
        };

        inject(&mut scenario, miner_id, miner_store::role_validator());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            // role flipped to validator
            assert!(caps::miner_cap_role(&cap) == miner_store::role_validator(), 1);
            // stale relay entry cleaned up
            assert!(!relay_registry::is_registered(&relay_reg, miner_id), 2);
            // assignment actually consumed (removed from assigned_roles), not just read
            assert!(option::is_none(&role_voting::get_assigned_role(&box, miner_id)), 4);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // apply tx emitted RoleApplied + RoleTransitioned = 2 events
        let effects = ts::next_tx(&mut scenario, MINER);
        assert!(ts::num_user_events(&effects) == 2, 3);

        ts::end(scenario);
    }

    // ── APPLY-02 ─────────────────────────────────────────────────────────
    #[test]
    fun apply_02_same_role_no_cleanup_no_transition_event() {
        let mut scenario = setup_apply(h::validator_stake()); // role = validator
        let miner_id = object::id_from_address(MINER);

        // Seed ValidatorRegistry; a same-role apply must NOT remove it.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, miner_id, MINER, h::validator_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(val_reg);
        };

        inject(&mut scenario, miner_id, miner_store::role_validator());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            assert!(caps::miner_cap_role(&cap) == miner_store::role_validator(), 1);
            // same-role: entry must remain (no cleanup)
            assert!(validator_registry::is_registered(&val_reg, miner_id), 2);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // same-role: only RoleApplied fires (no RoleTransitioned) = 1 event
        let effects = ts::next_tx(&mut scenario, MINER);
        assert!(ts::num_user_events(&effects) == 1, 3);

        ts::end(scenario);
    }

    // ── APPLY-03 ─────────────────────────────────────────────────────────
    #[test]
    fun apply_03_user_to_relay_no_cleanup_transitions() {
        // D-S70-4: USER old-role but funded at relay_stake (0.25 SUI) so the new RELAY threshold
        // guard (min 0.25 SUI) passes. Stake bracket would call this RELAY, hence the explicit role.
        let mut scenario = setup_apply_role(h::relay_stake(), miner_store::role_user());
        let miner_id = object::id_from_address(MINER);

        inject(&mut scenario, miner_id, miner_store::role_relay());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            assert!(caps::miner_cap_role(&cap) == miner_store::role_relay(), 1);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // user -> relay is a genuine transition: RoleApplied + RoleTransitioned = 2 events
        let effects = ts::next_tx(&mut scenario, MINER);
        assert!(ts::num_user_events(&effects) == 2, 2);

        ts::end(scenario);
    }

    // ── APPLY-04 ─────────────────────────────────────────────────────────
    #[test]
    #[expected_failure(abort_code = 714, location = dvconf::registration)] // E_CP_REVOTE_REQUIRES_MIGRATION
    fun apply_04_cp_revote_aborts_requires_migration() {
        let mut scenario = setup_apply(h::relay_stake()); // old_role = relay (!= USER)
        let miner_id = object::id_from_address(MINER);

        inject(&mut scenario, miner_id, miner_store::role_cp()); // new_role = CP

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── APPLY-05 ─────────────────────────────────────────────────────────
    #[test]
    #[expected_failure(abort_code = 403, location = dvconf::registration)] // E_PROTOCOL_PAUSED
    fun apply_05_paused_aborts() {
        let mut scenario = setup_apply(h::relay_stake());
        let miner_id = object::id_from_address(MINER);

        inject(&mut scenario, miner_id, miner_store::role_validator());

        // Admin pauses the protocol.
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut registry, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── APPLY-06 ─────────────────────────────────────────────────────────
    // Initial application INTO CP (old_role == USER) is ALLOWED — the Q5 guard's
    // USER carve-out, mirroring the cast-side. This is the one cell where the impl
    // intentionally diverges from the ADR-0008 literal sketch (which would abort it).
    #[test]
    fun apply_06_user_to_cp_initial_is_allowed() {
        // D-S70-4: USER old-role but funded at cp_stake (0.5 SUI) so the new CP threshold guard
        // (min 0.5 SUI) passes on this initial USER -> CP application.
        let mut scenario = setup_apply_role(h::cp_stake(), miner_store::role_user());
        let miner_id = object::id_from_address(MINER);

        inject(&mut scenario, miner_id, miner_store::role_cp());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            assert!(caps::miner_cap_role(&cap) == miner_store::role_cp(), 1);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // user -> CP is a genuine transition: RoleApplied + RoleTransitioned = 2 events
        let effects = ts::next_tx(&mut scenario, MINER);
        assert!(ts::num_user_events(&effects) == 2, 2);

        ts::end(scenario);
    }

    // ── APPLY-07 ─────────────────────────────────────────────────────────
    // CP as the OLD role (the `old_role != CP` half of the Q5 boolean). A miner that
    // became CP via an initial apply (APPLY-06 path) cannot then be re-voted OUT of CP
    // through the apply fast-path — it must migrate via unregister+register.
    #[test]
    #[expected_failure(abort_code = 714, location = dvconf::registration)] // E_CP_REVOTE_REQUIRES_MIGRATION
    fun apply_07_cp_source_revote_aborts() {
        // D-S70-4: USER old-role funded at cp_stake (0.5 SUI) so Step 1's USER -> CP apply clears
        // the new CP threshold guard. Step 2 (CP -> relay) aborts at the Q5 migration guard, which
        // runs BEFORE the threshold guard, so the 0.5-SUI stake is irrelevant to the Step 2 abort.
        let mut scenario = setup_apply_role(h::cp_stake(), miner_store::role_user());
        let miner_id = object::id_from_address(MINER);

        // Step 1: User -> CP (allowed) — leaves the MinerCap at role = CP.
        inject(&mut scenario, miner_id, miner_store::role_cp());
        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);
            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );
            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Step 2: CP -> Relay re-vote must abort E_CP_REVOTE_REQUIRES_MIGRATION.
        inject(&mut scenario, miner_id, miner_store::role_relay());
        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);
            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );
            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── APPLY-08 ─────────────────────────────────────────────────────────
    // SIGNALING old-role cleanup branch (previously zero coverage).
    #[test]
    fun apply_08_signaling_to_relay_cleans_signaling_registry() {
        // D-S70-4: SIGNALING old-role but funded at relay_stake (0.25 SUI) so the new RELAY
        // threshold guard (min 0.25 SUI) passes on the signaling -> relay transition.
        let mut scenario = setup_apply_role(h::relay_stake(), miner_store::role_signaling());
        let miner_id = object::id_from_address(MINER);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            signaling_registry::add_signaling_for_testing(&mut sig_reg, miner_id, MINER, ts::ctx(&mut scenario));
            assert!(signaling_registry::is_registered(&sig_reg, miner_id), 0);
            ts::return_shared(sig_reg);
        };

        inject(&mut scenario, miner_id, miner_store::role_relay());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            assert!(caps::miner_cap_role(&cap) == miner_store::role_relay(), 1);
            // signaling old-role entry cleaned up
            assert!(!signaling_registry::is_registered(&sig_reg, miner_id), 2);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── APPLY-09 ─────────────────────────────────────────────────────────
    // VALIDATOR old-role REMOVAL on a genuine transition (APPLY-02 only proved the
    // same-role NO-OP; this proves the validator entry is actually removed).
    #[test]
    fun apply_09_validator_to_relay_cleans_validator_registry() {
        // D-S70-4: VALIDATOR old-role but funded at relay_stake (0.25 SUI) so the new RELAY
        // threshold guard (min 0.25 SUI) passes on the validator -> relay transition.
        let mut scenario = setup_apply_role(h::relay_stake(), miner_store::role_validator());
        let miner_id = object::id_from_address(MINER);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, miner_id, MINER, h::validator_stake(), ts::ctx(&mut scenario),
            );
            assert!(validator_registry::is_registered(&val_reg, miner_id), 0);
            ts::return_shared(val_reg);
        };

        inject(&mut scenario, miner_id, miner_store::role_relay());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            assert!(caps::miner_cap_role(&cap) == miner_store::role_relay(), 1);
            // validator old-role entry removed on the transition
            assert!(!validator_registry::is_registered(&val_reg, miner_id), 2);

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── APPLY-10 ─────────────────────────────────────────────────────────
    // RELOCATED from role_voting_cast_revote_tests::test_revote_insufficient_stake_rejected
    // (RV-CAST-N2) per D-S70-4 / OQ-PH13. The stake-surplus guard moved from the CP-signed
    // cast path to this MINER-signed apply path. A miner voted into a role it cannot yet
    // afford → apply aborts E_INSUFFICIENT_STAKE_FOR_ROLE (713) and the assignment stays
    // pending until the miner tops up its stake.
    #[test]
    #[expected_failure(abort_code = 713, location = dvconf::registration)] // E_INSUFFICIENT_STAKE_FOR_ROLE
    fun apply_10_below_threshold_stake_aborts() {
        // USER old-role funded at only user_stake (0.01 SUI). Q5 carve-out allows the USER
        // transition; binding passes (stake is bound to MINER); but 0.01 SUI < the VALIDATOR
        // minimum (0.1 SUI) so the threshold guard aborts with 713.
        let mut scenario = setup_apply_role(h::user_stake(), miner_store::role_user());
        let miner_id = object::id_from_address(MINER);

        inject(&mut scenario, miner_id, miner_store::role_validator());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);
            let mut stake = ts::take_from_sender<StakePosition>(&scenario);

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── APPLY-11 ─────────────────────────────────────────────────────────
    // RELOCATED from role_voting_cast_revote_tests::test_revote_stake_not_owned_rejected
    // (RV-CAST-N5) per D-S70-4 / OQ-PH13. The stake-binding guard moved to this apply path:
    // the supplied StakePosition must belong to the miner whose cap drives the apply, so a node
    // cannot apply a voted role using some OTHER miner's stake. Stake bound to a different
    // miner_id → apply aborts E_STAKE_NOT_OWNED_BY_MINER (717).
    #[test]
    #[expected_failure(abort_code = 717, location = dvconf::registration)] // E_STAKE_NOT_OWNED_BY_MINER
    fun apply_11_stake_not_owned_aborts() {
        // MINER is a relay (old_role = relay); voted into VALIDATOR. The wrong_stake is funded
        // above the validator minimum (so the threshold guard would pass) BUT bound to a DIFFERENT
        // miner_id → the binding guard (717) fires first.
        let mut scenario = setup_apply_role(h::relay_stake(), miner_store::role_relay());
        let miner_id = object::id_from_address(MINER);
        let other_miner_id = object::id_from_address(@0xDEAD);

        inject(&mut scenario, miner_id, miner_store::role_validator());

        ts::next_tx(&mut scenario, MINER);
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut box = ts::take_shared<RoleVoteBox>(&scenario);
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let mut cap = ts::take_from_sender<MinerCap>(&scenario);

            // Build a stake bound to OTHER miner_id, funded above the validator minimum so the
            // threshold guard cannot be what aborts — isolating the 717 binding guard.
            let coin = coin::mint_for_testing<SUI>(h::validator_stake(), ts::ctx(&mut scenario));
            let mut wrong_stake = staking::create_for_testing(
                MINER, other_miner_id, miner_store::role_validator(), coin, ts::ctx(&mut scenario),
            );

            registration::apply_voted_role(
                &registry, &mut store, &mut box,
                &mut sig_reg, &mut relay_reg, &mut val_reg, &mut cp_reg,
                &mut cap, &mut wrong_stake, ts::ctx(&mut scenario),
            );

            // Never reached (apply aborts 717); present so the value is consumed + the block type-checks.
            staking::destroy_for_testing(wrong_stake);
            ts::return_shared(registry);
            ts::return_shared(store);
            ts::return_shared(box);
            ts::return_shared(sig_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }
}
