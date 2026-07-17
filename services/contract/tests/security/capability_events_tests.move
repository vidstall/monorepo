/// Tests for `dvconf::capability_events` and `dvconf::capability_errors` —
/// Base capability events + error code constants.
///
/// REQ-ADM-005 (base events portion) + REQ-ADM-019 (base error codes portion).
/// Phase 1.2 of room-admission-control milestone 1 (F62, Wave W1 P16).
///
/// Coverage:
///   CAP_EVT_01: emit_capability_issued fires exactly 1 user event
///   CAP_EVT_02: emit_capability_revoked fires exactly 1 user event
///   CAP_EVT_03: emit_capability_refreshed fires exactly 1 user event
///   CAP_EVT_04: error-code accessor batch — e_token_not_found (900) through
///               e_replay_nonce_used (908) pinned to exact numeric values
///   CAP_EVT_05: error-code namespace isolation — all Phase 1.2 codes > 889
///               (no collision with Phase 1.1 range 880-889)
///
/// Event-assertion pattern: emit in the initial transaction (ts::begin starts
/// tx-0 implicitly), then call ts::next_tx which returns tx-0's
/// TransactionEffects. ts::num_user_events(effects) counts events from tx-0.
#[test_only]
module dvconf::capability_events_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::capability_events;
    use dvconf::capability_errors;

    // ── Test fixtures ────────────────────────────────────────────────────
    const ADMIN: address = @0xAD;

    fun sample_token_id(): ID { object::id_from_address(@0xBEEF) }
    fun sample_room_id(): ID  { object::id_from_address(@0xCAFE) }
    fun sample_peer_pubkey(): vector<u8> {
        x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    }
    fun sample_quorum(): vector<address> { vector[@0xC1, @0xC2] }

    // ── CAP_EVT_01 ───────────────────────────────────────────────────────
    /// emit_capability_issued must fire exactly 1 Sui user event.
    #[test]
    fun test_emit_capability_issued_fires_event() {
        // tx-0: emit the event
        let mut scenario = ts::begin(ADMIN);
        capability_events::emit_capability_issued(
            sample_token_id(),
            sample_room_id(),
            sample_peer_pubkey(),
            1u8,     // role
            sample_quorum(),
            100u64,  // expires_epoch
        );
        // end tx-0, get its effects
        let effects = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&effects) == 1, 0);

        ts::end(scenario);
    }

    // ── CAP_EVT_02 ───────────────────────────────────────────────────────
    /// emit_capability_revoked must fire exactly 1 Sui user event.
    #[test]
    fun test_emit_capability_revoked_fires_event() {
        // tx-0: emit the event
        let mut scenario = ts::begin(ADMIN);
        capability_events::emit_capability_revoked(
            sample_token_id(),
            sample_room_id(),
            sample_quorum(),
            0u8,  // reason: 0 = normal revocation
        );
        // end tx-0, get its effects
        let effects = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&effects) == 1, 0);

        ts::end(scenario);
    }

    // ── CAP_EVT_03 ───────────────────────────────────────────────────────
    /// emit_capability_refreshed must fire exactly 1 Sui user event.
    #[test]
    fun test_emit_capability_refreshed_fires_event() {
        // tx-0: emit the event
        let mut scenario = ts::begin(ADMIN);
        capability_events::emit_capability_refreshed(
            sample_token_id(),
            sample_room_id(),
            sample_peer_pubkey(),
            50u64,   // old_expires_epoch
            150u64,  // new_expires_epoch
            sample_quorum(),
        );
        // end tx-0, get its effects
        let effects = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&effects) == 1, 0);

        ts::end(scenario);
    }

    // ── CAP_EVT_04 ───────────────────────────────────────────────────────
    /// Compile-time pin: each accessor must return the documented numeric value.
    /// If any future edit renumbers a constant this test fails before the change ships.
    #[test]
    fun test_error_code_accessor_values_pinned() {
        assert!(capability_errors::e_token_not_found()           == 900, 900);
        assert!(capability_errors::e_token_expired()             == 901, 901);
        assert!(capability_errors::e_token_revoked()             == 902, 902);
        assert!(capability_errors::e_token_room_mismatch()       == 903, 903);
        assert!(capability_errors::e_token_peer_mismatch()       == 904, 904);
        assert!(capability_errors::e_token_sig_invalid()         == 905, 905);
        assert!(capability_errors::e_token_quorum_insufficient() == 906, 906);
        assert!(capability_errors::e_token_already_revoked()     == 907, 907);
        assert!(capability_errors::e_replay_nonce_used()         == 908, 908);
    }

    // ── CAP_EVT_05 ───────────────────────────────────────────────────────
    /// Namespace isolation: Phase 1.2 codes 900-908 must be strictly above the
    /// Phase 1.1 ceiling of 889. No abort-code collision possible.
    #[test]
    fun test_error_codes_isolated_from_phase_1_1_namespace() {
        assert!(capability_errors::e_token_not_found()           > 889, 0);
        assert!(capability_errors::e_token_expired()             > 889, 0);
        assert!(capability_errors::e_token_revoked()             > 889, 0);
        assert!(capability_errors::e_token_room_mismatch()       > 889, 0);
        assert!(capability_errors::e_token_peer_mismatch()       > 889, 0);
        assert!(capability_errors::e_token_sig_invalid()         > 889, 0);
        assert!(capability_errors::e_token_quorum_insufficient() > 889, 0);
        assert!(capability_errors::e_token_already_revoked()     > 889, 0);
        assert!(capability_errors::e_replay_nonce_used()         > 889, 0);
    }
}
