/// Parametric M-of-N tests for `dvconf::cp_quorum_sig::verify_quorum`.
///
/// REQ-ADM-008 / multi-cp-quorum Leg 8 (TAIL — runs after the live carrier is stable;
/// see plans/multi-cp-quorum/ROADMAP.md § Leg 8 and ADR-0020). These tests sweep the
/// M-of-N parameter matrix (threshold M = 1..5, population N = 3..10) against the SHIPPED,
/// byte-frozen `verify_quorum` predicate. They add NO production code and change NO Move
/// source — `cp_quorum_sig.move` stays byte-identical; this is pure characterization of the
/// already-authoritative on-chain quorum gate across the parameter space the off-chain
/// COLLECTION carrier (ADR-0020) assembles for.
///
/// Method (mirrors QSIG-01): `verify_quorum` counts a quorum by *distinct signer address*
/// (F-01 dedup guard), and each `(signature[i], pubkey[i])` pair only has to ed25519-verify
/// over `msg`. So one RFC 8032 §7.1 valid (pubkey, signature) pair over the empty message is
/// reused under N distinct *registered* operator addresses — this isolates the threshold /
/// shape / registration logic from key material, exactly as the production assembler relies on.
///
/// Matrix coverage (each cell asserts the boundary triple where applicable):
///   - at-threshold        k == M            -> true   (quorum exactly met)
///   - below-threshold     k == M-1          -> false  (one short; for M=1, k=0 empty signers)
///   - above-threshold     k == M+extra      -> true   (monotonic; extra valid sigs never break it)
///   - M == N boundary     k == N == M       -> true,  k == N-1 -> false
///   - quorum floor N < M  register N, set M>N, k == N (all valid) -> false (can't reach M)
///
/// Cells: P-01 (M=1,N=3) · P-02 (M=2,N=3) · P-03 (M=3,N=5) · P-04 (M=4,N=7) ·
///        P-05 (M=5,N=10) · P-06 (M=5,N=5, M==N) · P-07 (M=1,N=10) · P-08 (M=3,N=3, M==N) ·
///        P-09 (M=4,N=4, M==N) · P-10 (quorum floor: N=3, M=5) · P-11 (N=10 wide, M=2).
#[test_only]
module dvconf::cp_quorum_sig_parametric_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{NetworkRegistry, AdminCap};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::cp_quorum_sig::{Self, QuorumConfigState};

    // RFC 8032 §7.1 TEST 1 — empty-message ed25519 vector (same pair as cp_quorum_sig_tests):
    //   pubkey    = d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a
    //   message   = "" (empty)
    //   signature = e5564300...8e7a100b  (valid for the empty message)
    const PUBKEY_1: vector<u8> = x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";
    const SIG_1_VALID_FOR_EMPTY: vector<u8> = x"e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b";

    /// Pool of 10 distinct CP operator addresses (>= max N in the matrix).
    fun op_pool(): vector<address> {
        vector[@0xCA01, @0xCA02, @0xCA03, @0xCA04, @0xCA05,
               @0xCA06, @0xCA07, @0xCA08, @0xCA09, @0xCA0A]
    }

    /// Pool of 10 distinct CP miner-id source addresses (index-aligned with op_pool).
    fun id_pool(): vector<address> {
        vector[@0xDA01, @0xDA02, @0xDA03, @0xDA04, @0xDA05,
               @0xDA06, @0xDA07, @0xDA08, @0xDA09, @0xDA0A]
    }

    /// Bootstrap: registries + N distinct CPs registered + QuorumConfigState shared (default M=2).
    fun setup_n_cps(n: u64): ts::Scenario {
        let mut scenario = h::setup_phase2();
        let ops = op_pool();
        let ids = id_pool();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            let mut i = 0;
            while (i < n) {
                control_plane_registry::add_cp_for_testing(
                    &mut cp_reg,
                    object::id_from_address(*vector::borrow(&ids, i)),
                    *vector::borrow(&ops, i),
                    h::cp_stake(),
                    ctx,
                );
                i = i + 1;
            };
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

    /// AdminCap-set the M-of-N threshold to `m` (verify_quorum reads min_quorum per call).
    fun set_threshold(scenario: &mut ts::Scenario, m: u64) {
        ts::next_tx(scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut state = ts::take_shared<QuorumConfigState>(scenario);
            let cap = ts::take_from_sender<AdminCap>(scenario);
            cp_quorum_sig::update_threshold(&cap, &net_reg, &mut state, m, h::admin());
            ts::return_to_sender(scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(state);
        };
    }

    /// Build a QuorumSig from the first `k` distinct registered operators (each carrying the
    /// valid RFC pair over the empty message) and assert `verify_quorum == expected`.
    /// `code` disambiguates the assertion site when a matrix cell fails.
    fun assert_verify_with_k(scenario: &mut ts::Scenario, k: u64, expected: bool, code: u64) {
        let ops = op_pool();
        ts::next_tx(scenario, h::admin());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(scenario);
            let state = ts::take_shared<QuorumConfigState>(scenario);

            let mut signers = vector::empty<address>();
            let mut signatures = vector::empty<vector<u8>>();
            let mut pubkeys = vector::empty<vector<u8>>();
            let mut i = 0;
            while (i < k) {
                vector::push_back(&mut signers, *vector::borrow(&ops, i));
                vector::push_back(&mut signatures, SIG_1_VALID_FOR_EMPTY);
                vector::push_back(&mut pubkeys, PUBKEY_1);
                i = i + 1;
            };
            let msg = vector[];

            let qsig = cp_quorum_sig::new_quorum_sig(signers, signatures);
            let ok = cp_quorum_sig::verify_quorum(&net_reg, &cp_reg, &state, &qsig, pubkeys, &msg);
            assert!(ok == expected, code);

            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };
    }

    // ── P-01 — M=1, N=3 ─────────────────────────────────────────────────
    #[test]
    fun test_quorum_m1_n3() {
        let mut scenario = setup_n_cps(3);
        set_threshold(&mut scenario, 1);
        assert_verify_with_k(&mut scenario, 1, true, 101);   // at-threshold
        assert_verify_with_k(&mut scenario, 0, false, 102);  // below (empty signers < 1)
        assert_verify_with_k(&mut scenario, 3, true, 103);   // above (3 valid >= 1)
        ts::end(scenario);
    }

    // ── P-02 — M=2, N=3 (default profile) ───────────────────────────────
    #[test]
    fun test_quorum_m2_n3() {
        let mut scenario = setup_n_cps(3);
        set_threshold(&mut scenario, 2);
        assert_verify_with_k(&mut scenario, 2, true, 201);   // at-threshold
        assert_verify_with_k(&mut scenario, 1, false, 202);  // below
        assert_verify_with_k(&mut scenario, 3, true, 203);   // above
        ts::end(scenario);
    }

    // ── P-03 — M=3, N=5 ─────────────────────────────────────────────────
    #[test]
    fun test_quorum_m3_n5() {
        let mut scenario = setup_n_cps(5);
        set_threshold(&mut scenario, 3);
        assert_verify_with_k(&mut scenario, 3, true, 301);
        assert_verify_with_k(&mut scenario, 2, false, 302);
        assert_verify_with_k(&mut scenario, 5, true, 303);
        ts::end(scenario);
    }

    // ── P-04 — M=4, N=7 ─────────────────────────────────────────────────
    #[test]
    fun test_quorum_m4_n7() {
        let mut scenario = setup_n_cps(7);
        set_threshold(&mut scenario, 4);
        assert_verify_with_k(&mut scenario, 4, true, 401);
        assert_verify_with_k(&mut scenario, 3, false, 402);
        assert_verify_with_k(&mut scenario, 7, true, 403);
        ts::end(scenario);
    }

    // ── P-05 — M=5, N=10 (max threshold, max population) ─────────────────
    #[test]
    fun test_quorum_m5_n10() {
        let mut scenario = setup_n_cps(10);
        set_threshold(&mut scenario, 5);
        assert_verify_with_k(&mut scenario, 5, true, 501);
        assert_verify_with_k(&mut scenario, 4, false, 502);
        assert_verify_with_k(&mut scenario, 10, true, 503);
        ts::end(scenario);
    }

    // ── P-06 — M=5, N=5 (M == N boundary) ───────────────────────────────
    #[test]
    fun test_quorum_m5_n5_boundary() {
        let mut scenario = setup_n_cps(5);
        set_threshold(&mut scenario, 5);
        assert_verify_with_k(&mut scenario, 5, true, 601);   // unanimity exactly met
        assert_verify_with_k(&mut scenario, 4, false, 602);  // one short of unanimity
        ts::end(scenario);
    }

    // ── P-07 — M=1, N=10 (min threshold, wide population) ────────────────
    #[test]
    fun test_quorum_m1_n10() {
        let mut scenario = setup_n_cps(10);
        set_threshold(&mut scenario, 1);
        assert_verify_with_k(&mut scenario, 1, true, 701);
        assert_verify_with_k(&mut scenario, 0, false, 702);
        assert_verify_with_k(&mut scenario, 10, true, 703);
        ts::end(scenario);
    }

    // ── P-08 — M=3, N=3 (M == N boundary) ───────────────────────────────
    #[test]
    fun test_quorum_m3_n3_boundary() {
        let mut scenario = setup_n_cps(3);
        set_threshold(&mut scenario, 3);
        assert_verify_with_k(&mut scenario, 3, true, 801);
        assert_verify_with_k(&mut scenario, 2, false, 802);
        ts::end(scenario);
    }

    // ── P-09 — M=4, N=4 (M == N boundary) ───────────────────────────────
    #[test]
    fun test_quorum_m4_n4_boundary() {
        let mut scenario = setup_n_cps(4);
        set_threshold(&mut scenario, 4);
        assert_verify_with_k(&mut scenario, 4, true, 901);
        assert_verify_with_k(&mut scenario, 3, false, 902);
        ts::end(scenario);
    }

    // ── P-10 — quorum floor: N=3 registered, M=5 (N < M) ────────────────
    /// Even with ALL 3 registered CPs signing validly, the quorum can never be reached
    /// because the threshold (5) exceeds the population (3). Proves the M-of-N floor holds
    /// when the off-chain assembler would have nothing to over-count toward.
    #[test]
    fun test_quorum_floor_n3_m5() {
        let mut scenario = setup_n_cps(3);
        set_threshold(&mut scenario, 5);
        assert_verify_with_k(&mut scenario, 3, false, 1001); // 3 valid < required 5 -> false
        ts::end(scenario);
    }

    // ── P-11 — M=2, N=10 (wide population, low threshold) ───────────────
    #[test]
    fun test_quorum_m2_n10() {
        let mut scenario = setup_n_cps(10);
        set_threshold(&mut scenario, 2);
        assert_verify_with_k(&mut scenario, 2, true, 1101);
        assert_verify_with_k(&mut scenario, 1, false, 1102);
        assert_verify_with_k(&mut scenario, 10, true, 1103);
        ts::end(scenario);
    }
}
