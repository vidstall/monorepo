/// Tests for `dvconf::role_voting` — F47 Phase 1.4 governance CP-quorum gated entries.
///
/// REQ-RV-004 (D-S60-1: CP-quorum direct gate, no AdminCap shim). The two governance
/// entries `update_revote_cooldown_epochs` + `update_max_idle_epochs` mutate the
/// RoleVoteBox governance fields (revote_cooldown_epochs / max_idle_epochs) only when a
/// CP-quorum aggregate signature over the canonical `build_governance_msg` payload verifies.
///
/// GOLD-STANDARD positive path: Move cannot sign ed25519 in-VM, so the valid (pubkey, sig)
/// pairs below are generated off-chain by `dvconf-daemons/scripts/governance/
/// gen-governance-sig-fixture.ts` (@mysten/sui Ed25519Keypair over the EXACT
/// build_governance_msg byte layout) and self-verified there twice (@mysten + Node crypto).
/// `test_build_governance_msg_byte_layout_matches_fixture` locks the Move<->TS byte layout.
///
/// Coverage:
///   GOV-00: build_governance_msg byte layout == off-chain fixture (drift lock)
///   GOV-01: update_revote_cooldown_epochs happy — 2-of-2 valid quorum -> field 14->21 + event
///   GOV-02: update_max_idle_epochs happy — 2-of-2 valid quorum -> field 30->45 + event
///   GOV-03: cooldown insufficient quorum (1 signer) -> abort E_GOVERNANCE_QUORUM_INSUFFICIENT (718)
///   GOV-04: cooldown tampered sig -> verify_quorum false -> abort 718
///   GOV-05: cooldown when paused -> abort E_PAUSED (700) before quorum check
///   GOV-06: max_idle insufficient quorum (1 signer) -> abort 718 (symmetric negative)
#[test_only]
module dvconf::role_voting_governance_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::cp_quorum_sig::{Self, QuorumConfigState};
    use dvconf::role_voting::{Self, RoleVoteBox};

    // ── CP fixtures (3 CPs for default M=2/N=3 quorum) ──
    const CP1_OP: address = @0xC1;
    const CP2_OP: address = @0xC2;
    const CP3_OP: address = @0xC3;
    const CP1_ID: address = @0xA6;
    const CP2_ID: address = @0xA7;
    const CP3_ID: address = @0xA8;

    // ── Off-chain fixture (gen-governance-sig-fixture.ts; seed 0x01..0x20; self-verified) ──
    // Pubkey (32B) of the deterministic TEST-ONLY keypair.
    const PK: vector<u8> = x"79b5562e8fe654f94078b112e8a98ba7901f853ae695bed7e0e3910bad049664";

    // COOLDOWN canonical message + signature: action=1, new_value=21, nonce=0, epoch=0.
    const MSG_COOLDOWN: vector<u8> = x"01150000000000000000000000000000000000000000000000";
    const SIG_COOLDOWN: vector<u8> = x"082879c6446ddf9e7d6a6649ab2835e6c865a4ae3b2f0f471768caccd66fe8dec9f005d5e85791c268bacac27a39f781e5a58054c6c8eea8cb7510c505150505";
    // Same sig with the final byte flipped (05 -> ff) — must fail ed25519_verify.
    const SIG_COOLDOWN_TAMPERED: vector<u8> = x"082879c6446ddf9e7d6a6649ab2835e6c865a4ae3b2f0f471768caccd66fe8dec9f005d5e85791c268bacac27a39f781e5a58054c6c8eea8cb7510c5051505ff";

    // MAX_IDLE canonical message + signature: action=2, new_value=45, nonce=0, epoch=0.
    const MSG_MAX_IDLE: vector<u8> = x"022d0000000000000000000000000000000000000000000000";
    const SIG_MAX_IDLE: vector<u8> = x"82e4c1e07c972ecbb708240ebf3ad4b2bf9ed1608bb819fb5346ccb04c05f018f6e7dc21c532a6f343bb9759699ac1542046393a23808a2b3b58bd2017491603";

    fun id_from_addr(addr: address): ID { object::id_from_address(addr) }

    /// Bootstrap: registries + 3 CPs registered + QuorumConfigState (default M=2) + RoleVoteBox.
    fun setup_governance(): ts::Scenario {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP1_ID), CP1_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP2_ID), CP2_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_from_addr(CP3_ID), CP3_OP, h::cp_stake(), ctx);
            ts::return_shared(cp_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let cap = ts::take_from_sender<AdminCap>(&scenario);
            cp_quorum_sig::create_config(&cap, ts::ctx(&mut scenario));
            ts::return_to_sender(&scenario, cap);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        scenario
    }

    // ── GOV-00 — byte layout drift lock ───────────────────────────────────
    #[test]
    fun test_build_governance_msg_byte_layout_matches_fixture() {
        let msg_cd = role_voting::build_governance_msg(1, 21, 0, 0);
        assert!(msg_cd == MSG_COOLDOWN, 0);
        let msg_mi = role_voting::build_governance_msg(2, 45, 0, 0);
        assert!(msg_mi == MSG_MAX_IDLE, 1);
    }

    // ── GOV-01 — cooldown happy path ──────────────────────────────────────
    #[test]
    fun test_update_cooldown_via_quorum_happy() {
        let mut scenario = setup_governance();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            // Default before update (DEFAULT_REVOTE_COOLDOWN_EPOCHS = 14)
            assert!(role_voting::revote_cooldown_epochs(&vote_box) == 14, 0);

            // 2-of-2: same valid (PK, SIG) under two distinct registered CP addresses.
            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_COOLDOWN, SIG_COOLDOWN],
            );
            role_voting::update_revote_cooldown_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK, PK], 21, 0, 0,
                ts::ctx(&mut scenario),
            );

            assert!(role_voting::revote_cooldown_epochs(&vote_box) == 21, 1);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        // QuorumVerified (verify_quorum) + CooldownConfigUpdated (entry) = 2 events
        let effects = ts::next_tx(&mut scenario, h::admin());
        assert!(ts::num_user_events(&effects) == 2, 2);

        ts::end(scenario);
    }

    // ── GOV-02 — max_idle happy path ──────────────────────────────────────
    #[test]
    fun test_update_max_idle_via_quorum_happy() {
        let mut scenario = setup_governance();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            // Default before update (DEFAULT_MAX_IDLE_EPOCHS = 30)
            assert!(role_voting::max_idle_epochs(&vote_box) == 30, 0);

            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_MAX_IDLE, SIG_MAX_IDLE],
            );
            role_voting::update_max_idle_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK, PK], 45, 0, 0,
                ts::ctx(&mut scenario),
            );

            assert!(role_voting::max_idle_epochs(&vote_box) == 45, 1);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        let effects = ts::next_tx(&mut scenario, h::admin());
        assert!(ts::num_user_events(&effects) == 2, 2);

        ts::end(scenario);
    }

    // ── GOV-03 — cooldown insufficient quorum ─────────────────────────────
    #[test]
    #[expected_failure(abort_code = 718, location = dvconf::role_voting)]
    fun test_update_cooldown_insufficient_quorum_aborts() {
        let mut scenario = setup_governance();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            // Only 1 signer — below M=2 → verify_quorum false → abort 718
            let qs = cp_quorum_sig::new_quorum_sig(vector[CP1_OP], vector[SIG_COOLDOWN]);
            role_voting::update_revote_cooldown_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK], 21, 0, 0,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }

    // ── GOV-04 — cooldown tampered signature ──────────────────────────────
    #[test]
    #[expected_failure(abort_code = 718, location = dvconf::role_voting)]
    fun test_update_cooldown_tampered_sig_aborts() {
        let mut scenario = setup_governance();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            // 2 signers but second sig tampered → ed25519_verify false → abort 718
            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_COOLDOWN, SIG_COOLDOWN_TAMPERED],
            );
            role_voting::update_revote_cooldown_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK, PK], 21, 0, 0,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }

    // ── GOV-05 — cooldown when paused ─────────────────────────────────────
    #[test]
    #[expected_failure(abort_code = 700, location = dvconf::role_voting)]
    fun test_update_cooldown_when_paused_aborts() {
        let mut scenario = setup_governance();

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = ts::take_from_sender<AdminCap>(&scenario);
            network_registry::set_paused(&cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            // Valid 2-of-2 quorum, but paused-flag is checked FIRST → abort 700
            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_COOLDOWN, SIG_COOLDOWN],
            );
            role_voting::update_revote_cooldown_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK, PK], 21, 0, 0,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }

    // ── GOV-06 — max_idle insufficient quorum (symmetric negative) ────────
    #[test]
    #[expected_failure(abort_code = 718, location = dvconf::role_voting)]
    fun test_update_max_idle_insufficient_quorum_aborts() {
        let mut scenario = setup_governance();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            let qs = cp_quorum_sig::new_quorum_sig(vector[CP1_OP], vector[SIG_MAX_IDLE]);
            role_voting::update_max_idle_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK], 45, 0, 0,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }

    // ── GOV-07 — cross-action signature rejected (anti cross-action replay) ─
    /// A COOLDOWN signature (signed over action=1, value=21) must NOT authorize
    /// update_max_idle_epochs, which builds an action=2 message. Passing new_value=21 isolates the
    /// ACTION byte as the sole differing field: ed25519_verify fails over the action=2 message ->
    /// abort 718. This is the exact binding the action byte exists to provide; no new fixture needed.
    #[test]
    #[expected_failure(abort_code = 718, location = dvconf::role_voting)]
    fun test_update_max_idle_rejects_cooldown_action_sig() {
        let mut scenario = setup_governance();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);

            // SIG_COOLDOWN signed action=1; update_max_idle_epochs builds action=2 (same value/nonce/epoch)
            // -> only the action byte differs -> verify_quorum false -> abort 718.
            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_COOLDOWN, SIG_COOLDOWN],
            );
            role_voting::update_max_idle_epochs(
                &net_reg, &mut vote_box, &cp_reg, &state,
                qs, vector[PK, PK], 21, 0, 0,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }
}
