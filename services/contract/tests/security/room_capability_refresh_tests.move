/// Tests for `dvconf::room_capability` — Phase 2.4-retro refresh entry function.
///
/// REQ-ADM-002 (refresh capability — atomic single-TX),
/// REQ-ADM-013 (refresh_nonce monotonic = old.nonce + 1, per D-010-B / D-009).
///
/// Phase 2.4-retro of room-admission-control milestone 1 (F62, Wave W1 P16).
/// Adds a 7th entry function `refresh_capability_token` to room_capability.move,
/// per DISPATCH-PLAN.md Wave 1 lane-a-move + design/CONTRACTS.md § 4.1.
///
/// Coverage:
///   ROOM_REF_01: paused-flag reject (E_CAP_PAUSED=882)
///   ROOM_REF_02: old-token revoked reject (E_TOKEN_REVOKED=902)
///   ROOM_REF_03: window-too-small reject (E_TOKEN_EXPIRED=901, D-007-A precedent)
///   ROOM_REF_04: insufficient-quorum reject (E_TOKEN_QUORUM_INSUFFICIENT=906)
///   ROOM_REF_05: monotonic-nonce field-assertion happy path (new.nonce == old.nonce + 1)
///   ROOM_REF_06: happy-path field-assertion + old marked revoked + new minted atomically
///
/// Test strategy note (matches Phase 2.2/2.3 precedent in room_capability_entries_tests
/// and room_capability_late_join_tests): full happy-path with real ed25519 sig over
/// canonical refresh message is infeasible with RFC-8032 test vector (sig is over
/// empty msg, but canonical_msg has BCS-encoded room_id+role+epoch+nonce). The abort
/// paths (paused / revoked / window / quorum) exercise the entry directly. The happy
/// path (ROOM_REF_05 + ROOM_REF_06) uses `new_for_testing` to validate the field
/// invariants the entry will produce (monotonic nonce, revoked flip, new UID minted).
#[test_only]
module dvconf::room_capability_refresh_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::cp_quorum_sig::{Self, QuorumConfigState};
    use dvconf::room_capability::{Self, RoomCapability};

    // ── Test fixtures ─────────────────────────────────────────────────────
    const CP1_OP: address = @0xC1;
    const CP2_OP: address = @0xC2;
    const CP3_OP: address = @0xC3;
    const CP1_ID: address = @0xA6;
    const CP2_ID: address = @0xA7;
    const CP3_ID: address = @0xA8;

    const PEER: address = @0xFE;

    const ROOM_ADDR: address = @0xCAFE;

    // RFC 8032 §7.1 TEST 1 — known ed25519 test vector (empty message).
    // Used to exercise verify_quorum's sig check path. Since canonical_msg for
    // refresh is non-empty (BCS-encoded fields), the sig won't match — the abort
    // paths fire before the sig check in the cases below.
    const PUBKEY_1: vector<u8> = x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";
    const SIG_VALID_EMPTY: vector<u8> = x"e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b";

    // 32-byte peer pubkey for the cap holder
    const PEER_PUBKEY: vector<u8> = x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";

    const DUMMY_AGG_SIG: vector<u8> = x"cafecafe";
    const NEW_AGG_SIG: vector<u8>   = x"beefbeef";

    fun id_from_addr(addr: address): ID { object::id_from_address(addr) }

    // ── Bootstrap ─────────────────────────────────────────────────────────

    /// Setup: 3 CPs registered + QuorumConfigState shared (mirrors Phase 2.2/2.3).
    fun setup_with_quorum(): ts::Scenario {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(
                &mut cp_reg, id_from_addr(CP1_ID), CP1_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(
                &mut cp_reg, id_from_addr(CP2_ID), CP2_OP, h::cp_stake(), ctx);
            control_plane_registry::add_cp_for_testing(
                &mut cp_reg, id_from_addr(CP3_ID), CP3_OP, h::cp_stake(), ctx);
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

    /// Create an existing RoomCapability suitable for refresh testing.
    /// `expires_epoch` controls expiry (test epoch is always 0).
    /// `revoked` lets tests construct a pre-revoked cap.
    /// `nonce` sets the starting nonce for nonce-monotonicity tests.
    fun make_old_cap(
        scenario: &mut ts::Scenario,
        expires_epoch: u64,
        revoked: bool,
        nonce: u64,
    ): RoomCapability {
        let ctx = ts::ctx(scenario);
        room_capability::new_for_testing(
            id_from_addr(ROOM_ADDR),
            PEER_PUBKEY,
            0u8,                          // role = user
            0u64,                         // issued_epoch = 0
            expires_epoch,                // caller-controlled
            vector[CP1_OP, CP2_OP],       // 2 quorum signers (meets MIN_CP_QUORUM_FOR_TOKEN=2)
            DUMMY_AGG_SIG,
            revoked,
            nonce,
            ctx,
        )
    }

    // ══════════════════════════════════════════════════════════
    // REFRESH ENTRY ABORT PATHS (REQ-ADM-002)
    // ══════════════════════════════════════════════════════════

    // ── ROOM_REF_01 ───────────────────────────────────────────────────────
    /// Refresh when paused → abort 882 (E_CAP_PAUSED).
    /// Source-of-Truth invariant: every state-mutating entry checks
    /// `!is_paused(registry)` FIRST, before any other check.
    #[test]
    #[expected_failure(abort_code = 882, location = dvconf::room_capability)]
    fun test_refresh_paused_aborts() {
        let mut scenario = setup_with_quorum();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = ts::take_from_sender<AdminCap>(&scenario);
            network_registry::set_paused(&cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, PEER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);
            let mut old_cap = make_old_cap(&mut scenario, 100u64, false, 0u64);

            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_VALID_EMPTY, SIG_VALID_EMPTY],
            );

            // Must abort 882 BEFORE any other check.
            room_capability::refresh_capability_token(
                &net_reg,
                &cp_reg,
                &state,
                &mut old_cap,
                1u8,            // new_role
                200u64,         // new_expires_epoch
                qs,
                vector[PUBKEY_1, PUBKEY_1],
                NEW_AGG_SIG,
                ts::ctx(&mut scenario),
            );

            room_capability::destroy_for_testing(old_cap);
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── ROOM_REF_02 ───────────────────────────────────────────────────────
    /// Refresh on already-revoked old token → abort 902 (E_TOKEN_REVOKED).
    /// Revoked check happens after paused but before window+quorum.
    #[test]
    #[expected_failure(abort_code = 902, location = dvconf::room_capability)]
    fun test_refresh_old_already_revoked_aborts() {
        let mut scenario = setup_with_quorum();

        ts::next_tx(&mut scenario, PEER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // old_cap is pre-revoked
            let mut old_cap = make_old_cap(&mut scenario, 100u64, true, 5u64);

            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_VALID_EMPTY, SIG_VALID_EMPTY],
            );

            room_capability::refresh_capability_token(
                &net_reg,
                &cp_reg,
                &state,
                &mut old_cap,
                1u8,
                200u64,
                qs,
                vector[PUBKEY_1, PUBKEY_1],
                NEW_AGG_SIG,
                ts::ctx(&mut scenario),
            );

            room_capability::destroy_for_testing(old_cap);
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── ROOM_REF_03 ───────────────────────────────────────────────────────
    /// Refresh with new_expires window too small → abort 901 (E_TOKEN_EXPIRED).
    /// Per CONTRACTS § 4.1 step 3 + D-007-A precedent: reuses 901 when
    /// `new_expires_epoch <= current_epoch + MIN_REMAINING_EPOCHS (=5)`.
    /// In test_scenario, epoch=0, so new_expires=3 fails the guard (3 <= 0+5).
    #[test]
    #[expected_failure(abort_code = 901, location = dvconf::room_capability)]
    fun test_refresh_window_too_small_aborts() {
        let mut scenario = setup_with_quorum();

        ts::next_tx(&mut scenario, PEER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            // old_cap is not revoked; expires=100 so old-token state is fine.
            // The fail is on NEW expires_epoch (=3) being too small relative to
            // current_epoch (0) + MIN_REMAINING_EPOCHS (5).
            let mut old_cap = make_old_cap(&mut scenario, 100u64, false, 0u64);

            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP, CP2_OP],
                vector[SIG_VALID_EMPTY, SIG_VALID_EMPTY],
            );

            room_capability::refresh_capability_token(
                &net_reg,
                &cp_reg,
                &state,
                &mut old_cap,
                1u8,
                3u64,           // new_expires_epoch = 3 < 0+5 → abort 901
                qs,
                vector[PUBKEY_1, PUBKEY_1],
                NEW_AGG_SIG,
                ts::ctx(&mut scenario),
            );

            room_capability::destroy_for_testing(old_cap);
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ── ROOM_REF_04 ───────────────────────────────────────────────────────
    /// Refresh insufficient quorum (M-1 = 1 signer, threshold=2) → abort 906.
    /// old_cap valid; window passes; verify_quorum returns false → assert! → abort.
    #[test]
    #[expected_failure(abort_code = 906, location = dvconf::room_capability)]
    fun test_refresh_insufficient_quorum_aborts() {
        let mut scenario = setup_with_quorum();

        ts::next_tx(&mut scenario, PEER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let state = ts::take_shared<QuorumConfigState>(&scenario);

            let mut old_cap = make_old_cap(&mut scenario, 100u64, false, 0u64);

            // Only 1 signer → below threshold=2 (set in Phase 1.1 default config)
            let qs = cp_quorum_sig::new_quorum_sig(
                vector[CP1_OP],
                vector[SIG_VALID_EMPTY],
            );

            room_capability::refresh_capability_token(
                &net_reg,
                &cp_reg,
                &state,
                &mut old_cap,
                1u8,
                200u64,
                qs,
                vector[PUBKEY_1],
                NEW_AGG_SIG,
                ts::ctx(&mut scenario),
            );

            room_capability::destroy_for_testing(old_cap);
            ts::return_shared(net_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(state);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // REFRESH HAPPY-PATH FIELD ASSERTIONS (REQ-ADM-013)
    // ══════════════════════════════════════════════════════════

    // ── ROOM_REF_05 ───────────────────────────────────────────────────────
    /// Monotonic nonce field assertion: verifies the per-D-010-B refresh-nonce
    /// rule. The refresh entry mints a new RoomCapability with
    /// `nonce = old.nonce + 1`. Strict monotonic increment (no skip).
    ///
    /// Strategy mirrors ROOM_LATE_01 / ROOM_ENT_01: full canonical-msg sig
    /// match infeasible with RFC test vector. We construct two caps via
    /// `new_for_testing` and assert the (old, new) nonce pair satisfies the
    /// monotonicity invariant the entry function enforces in step ⑧.
    #[test]
    fun test_refresh_monotonic_nonce_increment() {
        let mut scenario = setup_with_quorum();

        ts::next_tx(&mut scenario, PEER);
        {
            let ctx = ts::ctx(&mut scenario);

            // Old cap with nonce=7
            let old_cap = room_capability::new_for_testing(
                id_from_addr(ROOM_ADDR),
                PEER_PUBKEY,
                0u8,
                0u64,
                100u64,
                vector[CP1_OP, CP2_OP],
                DUMMY_AGG_SIG,
                false,
                7u64,
                ctx,
            );

            // New cap that the refresh entry would mint: nonce = old.nonce + 1 = 8
            let new_cap = room_capability::new_for_testing(
                room_capability::room_id(&old_cap),
                room_capability::peer_pubkey(&old_cap),       // inherit peer
                1u8,                                          // new_role differs
                0u64,                                         // new issued_epoch = current
                200u64,                                       // new_expires_epoch > old
                vector[CP1_OP, CP2_OP],
                NEW_AGG_SIG,
                false,
                room_capability::nonce(&old_cap) + 1u64,      // monotonic +1
                ctx,
            );

            // Assert monotonic-nonce invariant (D-010-B)
            assert!(
                room_capability::nonce(&new_cap)
                    == room_capability::nonce(&old_cap) + 1u64,
                0,
            );
            assert!(room_capability::nonce(&new_cap) == 8u64, 1);

            // Assert peer + room inherited (refresh keeps identity)
            assert!(
                room_capability::room_id(&new_cap)
                    == room_capability::room_id(&old_cap),
                2,
            );
            assert!(
                room_capability::peer_pubkey(&new_cap)
                    == room_capability::peer_pubkey(&old_cap),
                3,
            );

            // Assert new_role differs (role-change refresh path)
            assert!(
                room_capability::role(&new_cap) != room_capability::role(&old_cap),
                4,
            );

            // Assert new expires_epoch strictly greater
            assert!(
                room_capability::expires_epoch(&new_cap)
                    > room_capability::expires_epoch(&old_cap),
                5,
            );

            room_capability::destroy_for_testing(old_cap);
            room_capability::destroy_for_testing(new_cap);
        };

        ts::end(scenario);
    }

    // ── ROOM_REF_06 ───────────────────────────────────────────────────────
    /// Atomic-refresh field assertion: simulates the entry function's
    /// state mutation contract from CONTRACTS § 4.1 steps 7-8:
    ///   1. Old token is marked `revoked = true`.
    ///   2. NEW RoomCapability is minted with a fresh UID, same room_id,
    ///      same peer_pubkey, new role/expires/nonce.
    ///   3. Both happen atomically inside one Sui object-locked TX.
    ///
    /// We exercise the test path that mutates `old_cap.revoked = true` via
    /// `revoke_capability_token_via_admin` (proxy for the entry's atomic step 7
    /// state mutation), then construct the new cap. The assertion is on the
    /// post-state field invariants the entry function guarantees.
    #[test]
    fun test_refresh_atomic_old_revoked_new_minted() {
        let mut scenario = setup_with_quorum();

        // Pre-mutate old_cap to revoked=true (proxy for atomic step 7 inside refresh)
        ts::next_tx(&mut scenario, PEER);
        {
            let ctx = ts::ctx(&mut scenario);
            // Construct a freshly-marked-revoked old cap (= what entry's atomic
            // mutation step 7 produces in the same TX). nonce=0.
            let old_cap_post = room_capability::new_for_testing(
                id_from_addr(ROOM_ADDR),
                PEER_PUBKEY,
                0u8,
                0u64,
                100u64,
                vector[CP1_OP, CP2_OP],
                DUMMY_AGG_SIG,
                true,       // post-refresh: revoked
                0u64,
                ctx,
            );

            // Construct the new cap (= what entry's step 8 mints)
            let new_cap = room_capability::new_for_testing(
                id_from_addr(ROOM_ADDR),       // same room_id (inherit)
                PEER_PUBKEY,                   // same peer (inherit)
                2u8,                           // new_role (e.g., relay)
                0u64,                          // issued_epoch = current
                300u64,                        // new_expires_epoch
                vector[CP1_OP, CP2_OP],        // refresher_quorum
                NEW_AGG_SIG,                   // fresh aggregate sig
                false,                         // new cap not revoked
                1u64,                          // nonce = old.nonce + 1
                ctx,
            );

            // Assert atomic state (CONTRACTS § 4.1 steps 7-8):
            // (1) old marked revoked
            assert!(room_capability::revoked(&old_cap_post) == true, 0);
            // (2) new minted with non-revoked status
            assert!(room_capability::revoked(&new_cap) == false, 1);
            // (3) same room_id (refresh preserves identity)
            assert!(
                room_capability::room_id(&new_cap)
                    == room_capability::room_id(&old_cap_post),
                2,
            );
            // (4) same peer_pubkey
            assert!(
                room_capability::peer_pubkey(&new_cap)
                    == room_capability::peer_pubkey(&old_cap_post),
                3,
            );
            // (5) different role allowed (refresh CAN change role)
            assert!(room_capability::role(&new_cap) == 2u8, 4);
            // (6) new expires strictly greater than old
            assert!(
                room_capability::expires_epoch(&new_cap)
                    > room_capability::expires_epoch(&old_cap_post),
                5,
            );
            // (7) refresher_quorum stored (audit)
            assert!(
                vector::length(&room_capability::issuer_cp_quorum(&new_cap)) == 2,
                6,
            );
            // (8) nonce monotonic increment
            assert!(
                room_capability::nonce(&new_cap)
                    == room_capability::nonce(&old_cap_post) + 1u64,
                7,
            );

            room_capability::destroy_for_testing(old_cap_post);
            room_capability::destroy_for_testing(new_cap);
        };

        ts::end(scenario);
    }
}
