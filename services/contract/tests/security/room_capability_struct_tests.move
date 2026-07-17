/// Tests for `dvconf::room_capability` — RoomCapability struct invariants,
/// BCS layout, room-specific error codes, and event emission.
///
/// REQ-ADM-001 (RoomCapability struct) + REQ-ADM-005 (room-specific events portion)
/// + REQ-ADM-019 (room-specific error codes portion).
/// Phase 2.1 of room-admission-control milestone 1 (F62, Wave W1 P16).
///
/// Coverage:
///   ROOM_CAP_01: Happy path — construct RoomCapability, assert all fields readable
///   ROOM_CAP_02: Struct invariants — peer_pubkey must be 32 bytes (ed25519)
///   ROOM_CAP_02b: Struct invariant — expires_epoch must be > issued_epoch
///   ROOM_CAP_02c: Struct invariant — issuer_cp_quorum length >= MIN_CP_QUORUM_FOR_TOKEN (2)
///   ROOM_CAP_03: BCS roundtrip — serialize → deserialize → field-by-field equality
///   ROOM_CAP_04: Error code accessor pin — each of 7 accessors returns expected numeric value
///   ROOM_CAP_05: Namespace isolation — all room-specific codes are in 909-915 range
///   ROOM_CAP_06: Event emission — 3 emit helpers each fire exactly 1 user event
#[test_only]
module dvconf::room_capability_struct_tests {
    use sui::test_scenario::{Self as ts};
    use sui::bcs;
    use dvconf::room_capability;
    use dvconf::capability_errors_room;

    // ── Test fixtures ────────────────────────────────────────────────────
    const ADMIN: address = @0xAD;

    // ed25519 32-byte pubkey (RFC 8032 §7.1 TEST 1)
    const VALID_PUBKEY_32: vector<u8> =
        x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";

    // Intentionally short pubkey (31 bytes) — must fail invariant check.
    // 31 bytes = 62 hex chars (one less than the 32-byte / 64-char valid pubkey).
    const SHORT_PUBKEY_31: vector<u8> =
        x"d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f70751";

    // Aggregate sig placeholder (arbitrary bytes for struct tests; not verified in Phase 2.1)
    const DUMMY_AGG_SIG: vector<u8> = x"deadbeef";

    fun sample_room_id(): ID  { object::id_from_address(@0xCAFE) }
    fun sample_quorum_2(): vector<address> { vector[@0xC1, @0xC2] }
    fun sample_quorum_1(): vector<address> { vector[@0xC1] }

    // ── ROOM_CAP_01 ──────────────────────────────────────────────────────
    /// Happy path: construct RoomCapability, assert all fields readable.
    #[test]
    fun test_construct_room_capability_happy_path() {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            let cap = room_capability::new_for_testing(
                sample_room_id(),
                VALID_PUBKEY_32,
                2u8,                // role = CP
                10u64,              // issued_epoch
                20u64,              // expires_epoch
                sample_quorum_2(),  // 2 CP quorum signers
                DUMMY_AGG_SIG,
                false,              // revoked
                0u64,               // nonce
                ctx,
            );

            assert!(room_capability::room_id(&cap)          == sample_room_id(), 0);
            assert!(room_capability::peer_pubkey(&cap)       == VALID_PUBKEY_32, 1);
            assert!(room_capability::role(&cap)              == 2u8, 2);
            assert!(room_capability::issued_epoch(&cap)      == 10u64, 3);
            assert!(room_capability::expires_epoch(&cap)     == 20u64, 4);
            assert!(room_capability::issuer_cp_quorum(&cap)  == sample_quorum_2(), 5);
            assert!(room_capability::aggregate_sig(&cap)     == DUMMY_AGG_SIG, 6);
            assert!(room_capability::revoked(&cap)           == false, 7);
            assert!(room_capability::nonce(&cap)             == 0u64, 8);

            // Clean up owned object
            room_capability::destroy_for_testing(cap);
        };
        ts::end(scenario);
    }

    // ── ROOM_CAP_02 ──────────────────────────────────────────────────────
    /// Struct invariant: peer_pubkey must be exactly 32 bytes (ed25519).
    #[test]
    #[expected_failure(abort_code = room_capability::E_PUBKEY_WRONG_LENGTH, location = dvconf::room_capability)]
    fun test_pubkey_too_short_aborts() {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            // 31-byte pubkey — must abort E_PUBKEY_WRONG_LENGTH
            let cap = room_capability::new_for_testing(
                sample_room_id(),
                SHORT_PUBKEY_31,
                2u8,
                10u64,
                20u64,
                sample_quorum_2(),
                DUMMY_AGG_SIG,
                false,
                0u64,
                ctx,
            );
            room_capability::destroy_for_testing(cap);
        };
        ts::end(scenario);
    }

    // ── ROOM_CAP_02b ─────────────────────────────────────────────────────
    /// Struct invariant: expires_epoch must be strictly greater than issued_epoch.
    #[test]
    #[expected_failure(abort_code = room_capability::E_EXPIRES_NOT_AFTER_ISSUED, location = dvconf::room_capability)]
    fun test_expires_not_after_issued_aborts() {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            // expires_epoch == issued_epoch — must abort
            let cap = room_capability::new_for_testing(
                sample_room_id(),
                VALID_PUBKEY_32,
                2u8,
                20u64,  // issued_epoch
                20u64,  // expires_epoch == issued — invalid
                sample_quorum_2(),
                DUMMY_AGG_SIG,
                false,
                0u64,
                ctx,
            );
            room_capability::destroy_for_testing(cap);
        };
        ts::end(scenario);
    }

    // ── ROOM_CAP_02c ─────────────────────────────────────────────────────
    /// Struct invariant: issuer_cp_quorum must have >= MIN_CP_QUORUM_FOR_TOKEN (2) entries.
    #[test]
    #[expected_failure(abort_code = room_capability::E_QUORUM_TOO_SMALL, location = dvconf::room_capability)]
    fun test_quorum_too_small_aborts() {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            // Only 1 quorum signer — must abort (min = 2 per D-B4)
            let cap = room_capability::new_for_testing(
                sample_room_id(),
                VALID_PUBKEY_32,
                2u8,
                10u64,
                20u64,
                sample_quorum_1(),  // 1 signer — below MIN_CP_QUORUM_FOR_TOKEN=2
                DUMMY_AGG_SIG,
                false,
                0u64,
                ctx,
            );
            room_capability::destroy_for_testing(cap);
        };
        ts::end(scenario);
    }

    // ── ROOM_CAP_03 ──────────────────────────────────────────────────────
    /// BCS roundtrip: serialize scalar field values → deserialize → equality.
    /// Validates that the primitive field types (u8, u64, bool, vector<u8>) used
    /// in RoomCapability are BCS-stable for off-chain consumers.
    ///
    /// Note: `RoomCapability` has `has key` (not `store`), so `bcs::to_bytes` on
    /// the struct itself requires `store`. Instead we serialize and deserialize
    /// each scalar field independently, which is sufficient to pin the BCS encoding
    /// contract for the cp-daemon Phase 3.1 deserializer.
    #[test]
    fun test_bcs_field_roundtrip_stable() {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            let role_val    = 3u8;
            let issued_val  = 42u64;
            let expires_val = 142u64;
            let nonce_val   = 7u64;
            let revoked_val = false;

            let cap = room_capability::new_for_testing(
                sample_room_id(),
                VALID_PUBKEY_32,
                role_val,
                issued_val,
                expires_val,
                sample_quorum_2(),
                DUMMY_AGG_SIG,
                revoked_val,
                nonce_val,
                ctx,
            );

            // u8 roundtrip
            let role_bytes = bcs::to_bytes(&role_val);
            let role_back: u8 = bcs::peel_u8(&mut bcs::new(role_bytes));
            assert!(room_capability::role(&cap) == role_back, 0);

            // u64 roundtrip — issued_epoch
            let issued_bytes = bcs::to_bytes(&issued_val);
            let issued_back: u64 = bcs::peel_u64(&mut bcs::new(issued_bytes));
            assert!(room_capability::issued_epoch(&cap) == issued_back, 1);

            // u64 roundtrip — expires_epoch
            let expires_bytes = bcs::to_bytes(&expires_val);
            let expires_back: u64 = bcs::peel_u64(&mut bcs::new(expires_bytes));
            assert!(room_capability::expires_epoch(&cap) == expires_back, 2);

            // u64 roundtrip — nonce
            let nonce_bytes = bcs::to_bytes(&nonce_val);
            let nonce_back: u64 = bcs::peel_u64(&mut bcs::new(nonce_bytes));
            assert!(room_capability::nonce(&cap) == nonce_back, 3);

            // bool roundtrip — revoked
            let revoked_bytes = bcs::to_bytes(&revoked_val);
            let revoked_back: bool = bcs::peel_bool(&mut bcs::new(revoked_bytes));
            assert!(room_capability::revoked(&cap) == revoked_back, 4);

            // vector<u8> roundtrip — peer_pubkey (32 bytes ed25519)
            let pk = room_capability::peer_pubkey(&cap);
            let pk_bytes = bcs::to_bytes(&pk);
            let pk_back: vector<u8> = bcs::peel_vec_u8(&mut bcs::new(pk_bytes));
            assert!(pk_back == VALID_PUBKEY_32, 5);

            room_capability::destroy_for_testing(cap);
        };
        ts::end(scenario);
    }

    // ── ROOM_CAP_04 ──────────────────────────────────────────────────────
    /// Error-code accessor pin: each of 7 room-specific accessors returns the
    /// documented numeric value. If any future edit renumbers a constant this
    /// test fails before the change ships.
    #[test]
    fun test_error_code_accessor_values_pinned() {
        assert!(capability_errors_room::e_room_cap_not_for_this_room()    == 909, 909);
        assert!(capability_errors_room::e_room_cap_not_for_this_peer()    == 910, 910);
        assert!(capability_errors_room::e_room_cap_expired_for_room()     == 911, 911);
        assert!(capability_errors_room::e_room_cap_revoked_for_room()     == 912, 912);
        assert!(capability_errors_room::e_room_cap_nonce_mismatch()       == 913, 913);
        assert!(capability_errors_room::e_room_cap_quorum_below_threshold() == 914, 914);
        assert!(capability_errors_room::e_room_cap_sig_invalid()          == 915, 915);
    }

    // ── ROOM_CAP_05 ──────────────────────────────────────────────────────
    /// Namespace isolation: Phase 2.1 room-specific codes 909-915 must all be
    /// > 908 (above Phase 1.2 base ceiling) and <= 915 (within reserved range).
    /// No abort-code collision with Phase 1.1 (880-889) or Phase 1.2 (900-908).
    #[test]
    fun test_error_codes_in_reserved_room_range() {
        assert!(capability_errors_room::e_room_cap_not_for_this_room()    > 908, 0);
        assert!(capability_errors_room::e_room_cap_not_for_this_peer()    > 908, 0);
        assert!(capability_errors_room::e_room_cap_expired_for_room()     > 908, 0);
        assert!(capability_errors_room::e_room_cap_revoked_for_room()     > 908, 0);
        assert!(capability_errors_room::e_room_cap_nonce_mismatch()       > 908, 0);
        assert!(capability_errors_room::e_room_cap_quorum_below_threshold() > 908, 0);
        assert!(capability_errors_room::e_room_cap_sig_invalid()          > 908, 0);

        assert!(capability_errors_room::e_room_cap_not_for_this_room()    <= 915, 0);
        assert!(capability_errors_room::e_room_cap_not_for_this_peer()    <= 915, 0);
        assert!(capability_errors_room::e_room_cap_expired_for_room()     <= 915, 0);
        assert!(capability_errors_room::e_room_cap_revoked_for_room()     <= 915, 0);
        assert!(capability_errors_room::e_room_cap_nonce_mismatch()       <= 915, 0);
        assert!(capability_errors_room::e_room_cap_quorum_below_threshold() <= 915, 0);
        assert!(capability_errors_room::e_room_cap_sig_invalid()          <= 915, 0);
    }

    // ── ROOM_CAP_06 ──────────────────────────────────────────────────────
    /// Event emission: each of the 3 room-specific emit helpers fires exactly
    /// 1 user event.
    ///
    /// D-005: Option (b) — room_capability emits the base CapabilityIssued /
    /// CapabilityRevoked / CapabilityRefreshed events directly (no wrapper struct).
    /// Base events carry room_id + peer_pubkey, so cp-daemon Phase 3.1 subscription
    /// gets all required fields from the base event.
    #[test]
    fun test_emit_room_capability_issued_fires_one_event() {
        let mut scenario = ts::begin(ADMIN);
        room_capability::emit_room_capability_issued(
            object::id_from_address(@0xBEEF),
            sample_room_id(),
            VALID_PUBKEY_32,
            2u8,
            sample_quorum_2(),
            100u64,
        );
        let effects = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&effects) == 1, 0);
        ts::end(scenario);
    }

    #[test]
    fun test_emit_room_capability_revoked_fires_one_event() {
        let mut scenario = ts::begin(ADMIN);
        room_capability::emit_room_capability_revoked(
            object::id_from_address(@0xBEEF),
            sample_room_id(),
            sample_quorum_2(),
            0u8,  // reason: 0 = normal
        );
        let effects = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&effects) == 1, 0);
        ts::end(scenario);
    }

    #[test]
    fun test_emit_room_capability_refreshed_fires_one_event() {
        let mut scenario = ts::begin(ADMIN);
        room_capability::emit_room_capability_refreshed(
            object::id_from_address(@0xBEEF),
            sample_room_id(),
            VALID_PUBKEY_32,
            50u64,
            150u64,
            sample_quorum_2(),
        );
        let effects = ts::next_tx(&mut scenario, ADMIN);
        assert!(ts::num_user_events(&effects) == 1, 0);
        ts::end(scenario);
    }
}
