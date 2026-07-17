/// Tests for `dvconf::cp_quorum_sig` — CP-quorum aggregate signature scheme.
///
/// REQ-ADM-008. Phase 1.1 of room-admission-control milestone 1 (F62).
///
/// Coverage (per ROADMAP § Phase 1.1 + Phase 2.2 F-01 fix):
///   - QSIG-01: Happy path — verify_quorum returns true when M=2 valid sigs from registered CPs
///   - QSIG-02: Insufficient quorum — returns false when only 1 valid sig (M-1)
///   - QSIG-03: Invalid sig — rejects when one signature fails ed25519 verify
///   - QSIG-04: Threshold config update via AdminCap succeeds + emits QuorumConfigUpdated
///   - QSIG-05: Paused — aborts with E_PAUSED when network paused
///   - QSIG-06: Unregistered signer — returns false when a signer address is not a registered CP
///   - QSIG-07: Duplicate signer — returns false when same registered CP appears twice (F-01 fix)
#[test_only]
module dvconf::cp_quorum_sig_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::cp_quorum_sig::{Self, QuorumConfigState};

    // ── CP test fixtures (3 CPs for M=2/N=3 quorum) ──
    const CP1_OP: address = @0xC1;
    const CP2_OP: address = @0xC2;
    const CP3_OP: address = @0xC3;
    const CP1_ID: address = @0xA6;
    const CP2_ID: address = @0xA7;
    const CP3_ID: address = @0xA8;

    // RFC 8032 §7.1 TEST 1 — empty-message ed25519 vector:
    //   pubkey    = d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a
    //   message   = "" (empty)
    //   signature = e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b
    const PUBKEY_1: vector<u8> = x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";
    const SIG_1_VALID_FOR_EMPTY: vector<u8> = x"e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b";

    // Tampered signature (final byte 0b -> ff) — must fail ed25519_verify
    const SIG_1_TAMPERED: vector<u8> = x"e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a10ff";

    fun id_from_addr(addr: address): ID { object::id_from_address(addr) }

    /// Bootstrap: registries + 3 CPs registered + QuorumConfigState shared.
    fun setup_quorum(): ts::Scenario {
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

        scenario
    }

    // ── QSIG-01 ─────────────────────────────────────────────────────────
    #[test]
    fun test_verify_quorum_happy_path_two_valid_sigs() {
        let mut scenario = setup_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // M=2: both signers use the RFC valid pair (PUBKEY_1 / SIG_1) under different CP operator addresses.
            // M-of-N counts by signer-address, so this validates: (a) ≥M sigs, (b) all ed25519 verify, (c) all addrs registered.
            let signers = vector[CP1_OP, CP2_OP];
            let signatures = vector[SIG_1_VALID_FOR_EMPTY, SIG_1_VALID_FOR_EMPTY];
            let pubkeys = vector[PUBKEY_1, PUBKEY_1];
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            let ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);
            assert!(ok, 0);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── QSIG-02 ─────────────────────────────────────────────────────────
    #[test]
    fun test_verify_quorum_insufficient_signers() {
        let mut scenario = setup_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // Only 1 signer — below M=2 threshold — must return false, NO abort
            let signers = vector[CP1_OP];
            let signatures = vector[SIG_1_VALID_FOR_EMPTY];
            let pubkeys = vector[PUBKEY_1];
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            let ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);
            assert!(!ok, 0);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── QSIG-03 ─────────────────────────────────────────────────────────
    #[test]
    fun test_verify_quorum_invalid_signature_rejected() {
        let mut scenario = setup_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // Two signers but second sig is tampered — verify returns false
            let signers = vector[CP1_OP, CP2_OP];
            let signatures = vector[SIG_1_VALID_FOR_EMPTY, SIG_1_TAMPERED];
            let pubkeys = vector[PUBKEY_1, PUBKEY_1];
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            let ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);
            assert!(!ok, 0);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── QSIG-04 ─────────────────────────────────────────────────────────
    #[test]
    fun test_update_threshold_via_admincap() {
        let mut scenario = setup_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut state = ts::take_shared<QuorumConfigState>(&scenario);
            let cap = ts::take_from_sender<AdminCap>(&scenario);

            let old = cp_quorum_sig::min_quorum(&state);
            assert!(old == 2, 0);

            cp_quorum_sig::update_threshold(&cap, &net_reg, &mut state, 3, h::admin());

            let new = cp_quorum_sig::min_quorum(&state);
            assert!(new == 3, 0);

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── QSIG-05 ─────────────────────────────────────────────────────────
    #[test]
    #[expected_failure(abort_code = cp_quorum_sig::E_PAUSED)]
    fun test_verify_quorum_aborts_when_paused() {
        let mut scenario = setup_quorum();

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

            let signers = vector[CP1_OP, CP2_OP];
            let signatures = vector[SIG_1_VALID_FOR_EMPTY, SIG_1_VALID_FOR_EMPTY];
            let pubkeys = vector[PUBKEY_1, PUBKEY_1];
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            // Must abort
            let _ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── QSIG-06 ─────────────────────────────────────────────────────────
    #[test]
    fun test_verify_quorum_rejects_unregistered_signer() {
        let mut scenario = setup_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // Second signer is an unregistered address — returns false
            let signers = vector[CP1_OP, @0xDEAD];
            let signatures = vector[SIG_1_VALID_FOR_EMPTY, SIG_1_VALID_FOR_EMPTY];
            let pubkeys = vector[PUBKEY_1, PUBKEY_1];
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            let ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);
            assert!(!ok, 0);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── QSIG-07 ─────────────────────────────────────────────────────────
    /// F-01 fix (Phase 2.2 hardening, D-004): duplicate-signer guard.
    ///
    /// A single registered CP cannot satisfy M-of-N quorum alone by submitting
    /// `signers: [alice, alice]` with 2 valid alice-key signatures.
    /// The dedup guard detects the duplicate address and returns false
    /// (soft-fail, consistent with all other non-pause failures in verify_quorum).
    ///
    /// Setup: signers = [CP1_OP, CP1_OP] — same registered address twice.
    ///        threshold = 2 (default M=2/N=3 per D-B4).
    ///        Without F-01 fix: would return true (alice counted twice → n=2 >= required=2).
    ///        With F-01 fix: returns false (duplicate detected after first iter).
    #[test]
    fun test_verify_quorum_rejects_duplicate_signer() {
        let mut scenario = setup_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // Same registered CP address appears twice.
            // Both signatures use the valid RFC 8032 test vector over an empty message.
            // The dedup guard should detect CP1_OP at index 1 and return false.
            let signers = vector[CP1_OP, CP1_OP];
            let signatures = vector[SIG_1_VALID_FOR_EMPTY, SIG_1_VALID_FOR_EMPTY];
            let pubkeys = vector[PUBKEY_1, PUBKEY_1];
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            let ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);
            // Must return false — duplicate signer guard rejects [alice, alice]
            assert!(!ok, 0);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }
}
