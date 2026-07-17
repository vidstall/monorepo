/// Room-specific capability token — REQ-ADM-001 (RoomCapability struct),
/// REQ-ADM-005 (room-specific events portion), REQ-ADM-019 (room-specific
/// error codes portion), REQ-ADM-014 (late-join entry), REQ-ADM-015
/// (degraded single-CP mode + IssuedDegraded event).
///
/// Phase 2.1 of room-admission-control milestone 1 (F62, Wave W1 P16).
/// Phase 2.3 adds `issue_capability_token_for_peer` (late-join) and
/// `issue_capability_token_degraded` (AdminCap-gated emergency path).
///
/// ## Architecture
///
/// Per Fork 1 Option β (DESIGN.md): the CP-quorum sig primitive (`cp_quorum_sig.move`)
/// is shared; each feature owns its data struct separately. This module owns the
/// `RoomCapability` struct and its struct-level invariant enforcement.
///
/// Phase 2.2 adds the `issue_capability_token` / `verify_capability_token` /
/// `revoke_capability_token` entry functions to this module.
///
/// ## Event design — D-005 Option (b)
///
/// Room-specific emit helpers in this module call the base helpers from
/// `capability_events.move` directly (no wrapper struct). Rationale:
/// the base events (`CapabilityIssued`, `CapabilityRevoked`, `CapabilityRefreshed`)
/// already carry `room_id: ID` and `peer_pubkey: vector<u8>` — all context
/// required by cp-daemon Phase 3.1 to subscribe per-room-per-peer.
/// Introducing a `RoomCapabilityIssued { base: CapabilityIssued }` wrapper would
/// duplicate all fields with zero information gain, increasing LOC without
/// off-chain benefit. Option (b) preserves all required context, minimizes LOC,
/// and does NOT modify the frozen `capability_events.move`.
///
/// See DECISIONS.md § D-005 for full rationale and trade-off.
///
/// ## Error codes
///
/// Struct-level invariant checks use local abort codes defined in this module:
///   E_PUBKEY_WRONG_LENGTH      — peer_pubkey != 32 bytes (ed25519 requirement)
///   E_EXPIRES_NOT_AFTER_ISSUED — expires_epoch <= issued_epoch
///   E_QUORUM_TOO_SMALL         — issuer_cp_quorum.len() < MIN_CP_QUORUM_FOR_TOKEN
///
/// Room-specific runtime codes 909-915 live in `capability_errors_room.move`.
/// Phase 2.2 consumers call those accessors for issue/verify/revoke failures.
///
/// ## Visibility
///
/// `new_room_capability` constructor: `public(package)` — external packages cannot
/// mint RoomCapability objects (Source-of-Truth Rule "Cap constructors are package-private").
/// `new_for_testing` + `destroy_for_testing`: `#[test_only]` — expose only in test context.
/// Emit helpers: `public(package)` — only dvconf-package modules may emit audit events.
/// Field accessor funs: `public` — read-only, safe for external consumers.
///
/// ## BCS layout snapshot (frozen Phase 2.1)
///
/// Field order determines off-chain deserialization. MUST NOT reorder without
/// a BCS-breaking-change ADR and daemon update.
///
/// RoomCapability {
///   id:                UID              (object id, 32 bytes)
///   room_id:           ID              (32 bytes)
///   peer_pubkey:       vector<u8>      (32 bytes, ed25519 per D-OQ-ADM-3)
///   role:              u8              (1 byte; 0=user 1=validator 2=relay 3=CP 4=signaling)
///   issued_epoch:      u64             (8 bytes)
///   expires_epoch:     u64             (8 bytes)
///   issuer_cp_quorum:  vector<address> (variable; each = 32 bytes)
///   aggregate_sig:     vector<u8>      (variable; BCS-serialized QuorumSig payload)
///   revoked:           bool            (1 byte)
///   nonce:             u64             (8 bytes; monotonic per-peer anti-replay; Phase 3.4 enforces)
/// }
module dvconf::room_capability {
    use sui::event;
    use dvconf::capability_events;
    use dvconf::capability_errors;
    use dvconf::constants;
    use dvconf::cp_quorum_sig::{Self, QuorumSig, QuorumConfigState};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::control_plane_registry::ControlPlaneRegistry;

    // ── Struct-level invariant error codes ───────────────────────────────
    // These are NOT in capability_errors_room (runtime codes 909-915) because
    // they fire during construction / struct validation, not during runtime
    // token verification. Kept here for module-local abort locality.

    /// peer_pubkey must be exactly ED25519_PUBKEY_LEN bytes.
    const E_PUBKEY_WRONG_LENGTH: u64 = 916;  // local to room_capability.move

    /// expires_epoch must be strictly greater than issued_epoch.
    const E_EXPIRES_NOT_AFTER_ISSUED: u64 = 917;

    /// issuer_cp_quorum length must be >= constants::min_cp_quorum_for_token().
    const E_QUORUM_TOO_SMALL: u64 = 918;

    /// ed25519 public key length in bytes.
    const ED25519_PUBKEY_LEN: u64 = 32;

    /// Mirrors cp_quorum_sig::E_PAUSED (882). Cannot access private consts across modules.
    /// Used by Phase 2.2 entry functions for consistent paused-flag abort code.
    /// Phase 2.2 entries abort with 882 so callers see the same code as cp_quorum_sig
    /// (rather than a room_capability-specific code). Exported via e_paused() for tests.
    const E_CAP_PAUSED: u64 = 882;

    /// Invalid degraded reason byte. Phase 2.3 `issue_capability_token_degraded` accepts
    /// only reason values 0/1/2 (see IssuedDegraded docstring). reason >= 3 aborts here.
    /// Placed in room_capability.move (not capability_errors_room) because it is a
    /// struct-level invariant on the degraded entry, not a runtime token-verification code.
    /// Value 919 is above the 909-915 room-runtime range (D-005) and above 916-918
    /// struct-invariant range — clear separation per D-007-A rationale.
    const E_INVALID_DEGRADED_REASON: u64 = 919;

    // ══════════════════════════════════════════════════════════
    // PHASE 2.3 EVENTS
    // ══════════════════════════════════════════════════════════

    /// Forensic audit event emitted by the degraded (single-CP / admin-override)
    /// issuance path. Off-chain consumers MUST subscribe to BOTH `CapabilityIssued`
    /// AND `IssuedDegraded` to reconstruct the full token lifecycle. When a token
    /// appears in `CapabilityIssued` without a paired `IssuedDegraded`, it was
    /// issued via the normal CP-quorum path. When both appear for the same
    /// `token_id`, it was issued via the degraded path.
    ///
    /// D-007-B: This struct lives in `room_capability.move` (NOT the frozen
    /// `capability_events.move`) per D-005 Option (b). cp-daemon Phase 3.1 must
    /// subscribe to this event source separately from the base `CapabilityIssued`.
    ///
    /// `reason` u8 enum (per D-OQ-2.3-2, mirrors D-002 CapabilityRevoked.reason):
    ///   0 = cp-partition    — CP set unreachable; single-CP fallback activated
    ///   1 = quorum-disabled — QuorumConfigState misconfigured; AdminCap recovery
    ///   2 = admin-override  — AdminCap holder explicit emergency issuance
    ///
    /// Valid range: 0..=2. reason >= 3 aborts with E_INVALID_DEGRADED_REASON (919).
    /// The enum is informational only — not enforced on-chain beyond the range guard.
    ///
    /// `aggregate_sig` in the paired RoomCapability is `vector::empty<u8>()` on the
    /// degraded path (marker for "no CP-quorum signature"). `issuer_cp_quorum` is
    /// also empty on the degraded path. Downstream consumers should treat an empty
    /// aggregate_sig as a signal to cross-check IssuedDegraded event presence.
    public struct IssuedDegraded has copy, drop {
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        reason: u8,
        issuer: address,   // AdminCap-bearing wallet that authorized the degraded issuance
    }

    // ══════════════════════════════════════════════════════════
    // DATA TYPE
    // ══════════════════════════════════════════════════════════

    /// Room-specific capability token issued by a CP-quorum.
    ///
    /// A `RoomCapability` grants the peer identified by `peer_pubkey` the role
    /// `role` within the room `room_id`, valid from `issued_epoch` to
    /// `expires_epoch`. The CP quorum that issued it is recorded in
    /// `issuer_cp_quorum` (operator addresses per D-001). `aggregate_sig`
    /// carries the BCS-serialized QuorumSig payload for off-chain audit.
    ///
    /// `revoked: bool` is set to `true` by `revoke_capability_token` (Phase 2.2).
    /// `nonce: u64` is a monotonic per-peer counter; Phase 3.4 signaling daemon
    /// enforces nonce strictly-increasing to prevent replay attacks.
    public struct RoomCapability has key {
        id: UID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        issued_epoch: u64,
        expires_epoch: u64,
        issuer_cp_quorum: vector<address>,
        aggregate_sig: vector<u8>,
        revoked: bool,
        nonce: u64,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR (package-private)
    // ══════════════════════════════════════════════════════════

    /// Create a new `RoomCapability` and transfer it to `recipient`.
    ///
    /// Enforces struct-level invariants:
    ///   1. `peer_pubkey` must be exactly 32 bytes (ed25519).
    ///   2. `expires_epoch` must be strictly > `issued_epoch`.
    ///   3. `issuer_cp_quorum` length must be >= MIN_CP_QUORUM_FOR_TOKEN.
    ///
    /// Called by Phase 2.2 `issue_capability_token` entry function.
    /// NOT callable from outside the dvconf package.
    public(package) fun new_room_capability(
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        issued_epoch: u64,
        expires_epoch: u64,
        issuer_cp_quorum: vector<address>,
        aggregate_sig: vector<u8>,
        revoked: bool,
        nonce: u64,
        recipient: address,
        ctx: &mut TxContext,
    ) {
        assert!(
            vector::length(&peer_pubkey) == ED25519_PUBKEY_LEN,
            E_PUBKEY_WRONG_LENGTH,
        );
        assert!(expires_epoch > issued_epoch, E_EXPIRES_NOT_AFTER_ISSUED);
        assert!(
            vector::length(&issuer_cp_quorum) >= constants::min_cp_quorum_for_token(),
            E_QUORUM_TOO_SMALL,
        );

        let cap = RoomCapability {
            id: object::new(ctx),
            room_id,
            peer_pubkey,
            role,
            issued_epoch,
            expires_epoch,
            issuer_cp_quorum,
            aggregate_sig,
            revoked,
            nonce,
        };
        transfer::transfer(cap, recipient);
    }

    // ══════════════════════════════════════════════════════════
    // TEST-ONLY CONSTRUCTOR + DESTRUCTOR
    // ══════════════════════════════════════════════════════════

    /// Test-only constructor that RETURNS the capability (not transfers it).
    /// Allows struct-level tests to inspect fields and call destroy_for_testing.
    #[test_only]
    public fun new_for_testing(
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        issued_epoch: u64,
        expires_epoch: u64,
        issuer_cp_quorum: vector<address>,
        aggregate_sig: vector<u8>,
        revoked: bool,
        nonce: u64,
        ctx: &mut TxContext,
    ): RoomCapability {
        assert!(
            vector::length(&peer_pubkey) == ED25519_PUBKEY_LEN,
            E_PUBKEY_WRONG_LENGTH,
        );
        assert!(expires_epoch > issued_epoch, E_EXPIRES_NOT_AFTER_ISSUED);
        assert!(
            vector::length(&issuer_cp_quorum) >= constants::min_cp_quorum_for_token(),
            E_QUORUM_TOO_SMALL,
        );

        RoomCapability {
            id: object::new(ctx),
            room_id,
            peer_pubkey,
            role,
            issued_epoch,
            expires_epoch,
            issuer_cp_quorum,
            aggregate_sig,
            revoked,
            nonce,
        }
    }

    /// Test-only destructor — consumes the capability object and deletes the UID.
    /// Prevents "unused resource" Move VM errors in tests that don't transfer the cap.
    #[test_only]
    public fun destroy_for_testing(cap: RoomCapability) {
        let RoomCapability {
            id,
            room_id: _,
            peer_pubkey: _,
            role: _,
            issued_epoch: _,
            expires_epoch: _,
            issuer_cp_quorum: _,
            aggregate_sig: _,
            revoked: _,
            nonce: _,
        } = cap;
        object::delete(id);
    }

    // ══════════════════════════════════════════════════════════
    // EMIT HELPERS (D-005 Option b — emit base events directly)
    // ══════════════════════════════════════════════════════════
    //
    // These thin wrappers delegate to `capability_events.move` emit helpers.
    // They exist so Phase 2.2 entry functions call a single named helper
    // with a descriptive name (`emit_room_capability_issued`) rather than
    // calling `capability_events::emit_capability_issued` directly, keeping
    // the call site readable and the event source identifiable in code review.
    //
    // `public(package)` per Source-of-Truth Rule "Cap constructors are
    // package-private" (emitting a fake audit event from an external package
    // is prevented at the Move type system level).

    /// Emit a `CapabilityIssued` event for a room capability token issuance.
    /// cp-daemon Phase 3.1 subscribes to `CapabilityIssued` events with
    /// `room_id` + `peer_pubkey` fields to populate its LRU token cache.
    public(package) fun emit_room_capability_issued(
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        role: u8,
        issuer_quorum: vector<address>,
        expires_epoch: u64,
    ) {
        capability_events::emit_capability_issued(
            token_id,
            room_id,
            peer_pubkey,
            role,
            issuer_quorum,
            expires_epoch,
        );
    }

    /// Emit a `CapabilityRevoked` event for a room capability token revocation.
    /// `reason` encoding: 0=normal / 1=slash / 2=admin (per D-002).
    public(package) fun emit_room_capability_revoked(
        token_id: ID,
        room_id: ID,
        revoker_quorum: vector<address>,
        reason: u8,
    ) {
        capability_events::emit_capability_revoked(
            token_id,
            room_id,
            revoker_quorum,
            reason,
        );
    }

    /// Emit a `CapabilityRefreshed` event for a room capability TTL extension.
    /// Covers both routine 60s sliding-TTL refresh and role-change grace window
    /// (REQ-ADM-013). cp-daemon Phase 3.1 listens to update its LRU cache TTL.
    public(package) fun emit_room_capability_refreshed(
        token_id: ID,
        room_id: ID,
        peer_pubkey: vector<u8>,
        old_expires_epoch: u64,
        new_expires_epoch: u64,
        refresher_quorum: vector<address>,
    ) {
        capability_events::emit_capability_refreshed(
            token_id,
            room_id,
            peer_pubkey,
            old_expires_epoch,
            new_expires_epoch,
            refresher_quorum,
        );
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS (public — read-only, safe for external consumers)
    // ══════════════════════════════════════════════════════════

    /// The room this capability grants access to.
    public fun room_id(cap: &RoomCapability): ID { cap.room_id }

    /// ed25519 public key of the peer this capability was issued to (32 bytes).
    public fun peer_pubkey(cap: &RoomCapability): vector<u8> { cap.peer_pubkey }

    /// Role granted by this capability (0=user 1=validator 2=relay 3=CP 4=signaling).
    public fun role(cap: &RoomCapability): u8 { cap.role }

    /// Epoch at which this capability was issued.
    public fun issued_epoch(cap: &RoomCapability): u64 { cap.issued_epoch }

    /// Epoch at which this capability expires (sliding TTL boundary).
    public fun expires_epoch(cap: &RoomCapability): u64 { cap.expires_epoch }

    /// CP operator addresses that co-signed this capability (M-of-N per D-001).
    public fun issuer_cp_quorum(cap: &RoomCapability): vector<address> { cap.issuer_cp_quorum }

    /// BCS-serialized QuorumSig payload carried for off-chain audit.
    public fun aggregate_sig(cap: &RoomCapability): vector<u8> { cap.aggregate_sig }

    /// Whether this capability has been explicitly revoked.
    public fun revoked(cap: &RoomCapability): bool { cap.revoked }

    /// Monotonic per-peer nonce for anti-replay enforcement (Phase 3.4).
    public fun nonce(cap: &RoomCapability): u64 { cap.nonce }

    // ── Exported invariant abort codes (for use in #[expected_failure] tests) ──

    /// Abort code when peer_pubkey is not 32 bytes.
    public fun e_pubkey_wrong_length(): u64    { E_PUBKEY_WRONG_LENGTH }

    /// Abort code when expires_epoch <= issued_epoch.
    public fun e_expires_not_after_issued(): u64 { E_EXPIRES_NOT_AFTER_ISSUED }

    /// Abort code when issuer_cp_quorum is too small.
    public fun e_quorum_too_small(): u64       { E_QUORUM_TOO_SMALL }

    /// Abort code when network is paused (882 = cp_quorum_sig::E_PAUSED).
    /// Used by Phase 2.2 entry functions. Exported for #[expected_failure] in tests.
    public fun e_cap_paused(): u64             { E_CAP_PAUSED }

    /// Abort code when degraded issuance reason byte is out of range (>= 3).
    /// Phase 2.3 `issue_capability_token_degraded` only.
    public fun e_invalid_degraded_reason(): u64 { E_INVALID_DEGRADED_REASON }

    // ══════════════════════════════════════════════════════════
    // PHASE 2.2 — ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════
    //
    // REQ-ADM-002: issue_capability_token
    // REQ-ADM-003: verify_capability_token (public fun — devInspect callable)
    // REQ-ADM-004: revoke_capability_token (dual gating: quorum OR admin)
    //
    // All state-mutating entries check !is_paused(registry) first per
    // Source-of-Truth Rule "paused flag always checked". Even verify_capability_token
    // checks the paused flag to respect security intent of the circuit breaker.
    //
    // Canonical signed payload for issue: BCS-serialize {room_id, peer_pubkey, role,
    // expires_epoch, nonce}. This binds the CP-quorum signature to the specific token
    // being issued, preventing signature reuse across rooms/peers (partial anti-replay
    // at the Move layer; full nonce enforcement is Phase 3.4 daemon scope per D-004/F-02).
    //
    // Nonce: Phase 2.2 stores the nonce in the token (from caller) but does NOT enforce
    // monotonic ordering on-chain. The `E_REPLAY_NONCE_USED` constant (908) is reserved
    // for Phase 3.4 signaling daemon enforcement. The Move layer trusts that the CP-quorum
    // signed the payload including the nonce, which provides BCS-level binding.

    /// Issue a room capability token gated by a CP-quorum aggregate signature.
    ///
    /// REQ-ADM-002. Paused-flag checked first (Source-of-Truth Rule).
    /// The canonical signed message is the BCS serialization of
    /// `{room_id, peer_pubkey, role, expires_epoch, nonce}` — callers must sign
    /// this exact payload off-chain. `aggregate_sig` carries the BCS-serialized
    /// QuorumSig for off-chain audit storage in the token object.
    ///
    /// Aborts with:
    ///   E_PAUSED (882)                 — network circuit breaker
    ///   E_TOKEN_QUORUM_INSUFFICIENT (906) — CP-quorum verify_quorum returned false
    ///   E_TOKEN_EXPIRED (901)          — expires_epoch <= current epoch
    ///   E_PUBKEY_WRONG_LENGTH (916)    — peer_pubkey not 32 bytes (caught by constructor)
    ///   E_EXPIRES_NOT_AFTER_ISSUED (917) — expires_epoch <= issued_epoch (constructor)
    ///   E_QUORUM_TOO_SMALL (918)       — issuer_cp_quorum < MIN_CP_QUORUM (constructor)
    public entry fun issue_capability_token(
        registry:       &NetworkRegistry,
        cp_reg:         &ControlPlaneRegistry,
        quorum_state:   &QuorumConfigState,
        room_id:        address,           // passed as address; converted to ID internally
        peer_pubkey:    vector<u8>,
        role:           u8,
        expires_epoch:  u64,
        nonce:          u64,
        qs:             QuorumSig,
        signer_pubkeys: vector<vector<u8>>,
        aggregate_sig:  vector<u8>,        // BCS-serialized QuorumSig for audit storage
        ctx:            &mut TxContext,
    ) {
        // ① Source-of-Truth paused-flag invariant
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        let room_id_typed: ID = object::id_from_address(room_id);
        let issued_epoch_val: u64 = tx_context::epoch(ctx);

        // ② expires_epoch must be in the future relative to current epoch
        assert!(
            expires_epoch > issued_epoch_val,
            capability_errors::e_token_expired(),
        );

        // ③ Build canonical signed message: BCS(room_id || peer_pubkey || role || expires_epoch || nonce)
        // Using vector concatenation of BCS-encoded fields.
        // This must match exactly what the CP-daemon signs off-chain.
        let mut canonical_msg = vector::empty<u8>();
        let room_id_bytes = object::id_to_bytes(&room_id_typed);
        vector::append(&mut canonical_msg, room_id_bytes);
        vector::append(&mut canonical_msg, peer_pubkey);
        vector::push_back(&mut canonical_msg, role);
        // Encode expires_epoch and nonce as little-endian u64 (BCS convention)
        let exp_bytes = bcs_u64_le(expires_epoch);
        vector::append(&mut canonical_msg, exp_bytes);
        let nonce_bytes = bcs_u64_le(nonce);
        vector::append(&mut canonical_msg, nonce_bytes);

        // ④ CP-quorum aggregate signature verification
        let quorum_ok = cp_quorum_sig::verify_quorum(
            registry,
            cp_reg,
            quorum_state,
            &qs,
            signer_pubkeys,
            &canonical_msg,
        );
        assert!(quorum_ok, capability_errors::e_token_quorum_insufficient());

        // ⑤ Capture issuer CP addresses for audit storage in the token
        let issuer_quorum_addrs: vector<address> = *cp_quorum_sig::signers(&qs);

        // ⑥ Construct RoomCapability inline (instead of via new_room_capability) so we can
        //    capture the UID before transferring. new_room_capability calls transfer::transfer
        //    internally which consumes the object — we need the ID for the event first.
        //    Invariants checked here mirror those in new_room_capability exactly.
        assert!(
            vector::length(&peer_pubkey) == ED25519_PUBKEY_LEN,
            E_PUBKEY_WRONG_LENGTH,
        );
        // expires_epoch > issued_epoch_val already asserted above (step ②).
        // issued_epoch_val is the current epoch. issuer_quorum_addrs length check:
        // ADR-0013: read the CONFIGURABLE quorum floor (mirrors verify_quorum's
        // QuorumConfigState.min_quorum) instead of the compile-time constant, so a
        // post-deploy update_threshold(1) lets a single-CP quorum mint.
        assert!(
            vector::length(&issuer_quorum_addrs) >= cp_quorum_sig::min_quorum(quorum_state),
            E_QUORUM_TOO_SMALL,
        );

        let uid = object::new(ctx);
        let token_id: ID = object::uid_to_inner(&uid);

        let cap = RoomCapability {
            id: uid,
            room_id: room_id_typed,
            peer_pubkey,
            role,
            issued_epoch: issued_epoch_val,
            expires_epoch,
            issuer_cp_quorum: issuer_quorum_addrs,
            aggregate_sig,
            revoked: false,
            nonce,
        };

        // ⑦ Emit CapabilityIssued event BEFORE transfer (object still accessible)
        emit_room_capability_issued(
            token_id,
            room_id_typed,
            cap.peer_pubkey,
            role,
            cap.issuer_cp_quorum,
            expires_epoch,
        );

        // ⑧ Transfer to sender (the peer's wallet receives the token)
        transfer::transfer(cap, tx_context::sender(ctx));
    }

    /// Verify a room capability token. Public fun (not entry) so it returns bool.
    /// Daemons call this via devInspect RPC (read-only, no gas cost).
    ///
    /// REQ-ADM-003. Returns true iff ALL of:
    ///   1. Network is not paused (abort E_PAUSED if paused — circuit breaker)
    ///   2. cap.revoked == false
    ///   3. cap.room_id == expected_room_id
    ///   4. cap.peer_pubkey == expected_peer_pubkey
    ///   5. cap.expires_epoch > current epoch
    ///
    /// All failure modes except paused return false (not abort) — daemons use
    /// the bool to decide admission without a transaction error path.
    public fun verify_capability_token(
        registry:             &NetworkRegistry,
        cap:                  &RoomCapability,
        expected_room_id:     address,
        expected_peer_pubkey: vector<u8>,
        ctx:                  &TxContext,
    ): bool {
        // ① Paused-flag: even read-only verify respects circuit breaker
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        // ② Revoked check
        if (cap.revoked) { return false };

        // ③ Room match
        let expected_id: ID = object::id_from_address(expected_room_id);
        if (cap.room_id != expected_id) { return false };

        // ④ Peer pubkey match
        if (cap.peer_pubkey != expected_peer_pubkey) { return false };

        // ⑤ Expiry check
        if (cap.expires_epoch <= tx_context::epoch(ctx)) { return false };

        true
    }

    /// Revoke a room capability token via CP-quorum aggregate signature.
    ///
    /// REQ-ADM-004 (quorum path). Dual-gating: CP-quorum or AdminCap.
    /// Aborts with E_TOKEN_ALREADY_REVOKED (907) if already revoked (idempotency guard).
    /// Aborts with E_TOKEN_QUORUM_INSUFFICIENT (906) if quorum verify fails.
    public entry fun revoke_capability_token_via_quorum(
        registry:       &NetworkRegistry,
        cp_reg:         &ControlPlaneRegistry,
        quorum_state:   &QuorumConfigState,
        cap:            &mut RoomCapability,
        reason:         u8,
        qs:             QuorumSig,
        signer_pubkeys: vector<vector<u8>>,
    ) {
        // ① Paused-flag
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        // ② Idempotency guard
        assert!(!cap.revoked, capability_errors::e_token_already_revoked());

        // ③ Canonical revoke message: BCS(cap_object_id || reason)
        let cap_id_bytes = object::id_to_bytes(&object::uid_to_inner(&cap.id));
        let mut canonical_msg = vector::empty<u8>();
        vector::append(&mut canonical_msg, cap_id_bytes);
        vector::push_back(&mut canonical_msg, reason);

        // ④ CP-quorum signature verification
        let quorum_ok = cp_quorum_sig::verify_quorum(
            registry,
            cp_reg,
            quorum_state,
            &qs,
            signer_pubkeys,
            &canonical_msg,
        );
        assert!(quorum_ok, capability_errors::e_token_quorum_insufficient());

        // ⑤ Apply revocation
        cap.revoked = true;

        // ⑥ Emit CapabilityRevoked event
        let revoker_addrs: vector<address> = *cp_quorum_sig::signers(&qs);
        emit_room_capability_revoked(
            object::uid_to_inner(&cap.id),
            cap.room_id,
            revoker_addrs,
            reason,
        );
    }

    /// Revoke a room capability token via AdminCap (emergency override).
    ///
    /// REQ-ADM-004 (admin path). Dual-gating: CP-quorum or AdminCap.
    /// Aborts with E_TOKEN_ALREADY_REVOKED (907) if already revoked.
    /// `reason` should be 2 (=admin) per the informational enum in D-002.
    public entry fun revoke_capability_token_via_admin(
        _:        &AdminCap,
        registry: &NetworkRegistry,
        cap:      &mut RoomCapability,
        reason:   u8,
    ) {
        // ① Paused-flag
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        // ② Idempotency guard
        assert!(!cap.revoked, capability_errors::e_token_already_revoked());

        // ③ Apply revocation
        cap.revoked = true;

        // ④ Emit CapabilityRevoked event — revoker_quorum is empty for AdminCap path
        emit_room_capability_revoked(
            object::uid_to_inner(&cap.id),
            cap.room_id,
            vector::empty<address>(),
            reason,
        );
    }

    // ── Internal BCS encoding helper ─────────────────────────────────────

    /// Encode a u64 as 8 little-endian bytes (BCS convention).
    /// Used to build canonical signed messages for issue/revoke.
    /// In Move, the >> shift amount must be u8.
    fun bcs_u64_le(v: u64): vector<u8> {
        let mut bytes = vector::empty<u8>();
        let mut shift: u8 = 0;
        while (shift < 64) {
            vector::push_back(&mut bytes, (((v >> shift) & 0xFF) as u8));
            shift = shift + 8;
        };
        bytes
    }

    // ══════════════════════════════════════════════════════════
    // PHASE 2.3 — LATE-JOIN + DEGRADED ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════
    //
    // REQ-ADM-014: issue_capability_token_for_peer (late-join)
    // REQ-ADM-015: issue_capability_token_degraded (degraded single-CP mode)
    //
    // D-007-A: Late-join window abort reuses E_TOKEN_EXPIRED (901) with semantic
    // stretch — "not enough time remains on existing cap" maps cleanly to the
    // concept of "token is too-close-to-expired for safe issuance". Introducing a
    // new room code (916+) would consume from the 916-918 struct-invariant range
    // and create a third expiry-related code (901 + 911 + new) confusing for daemons.
    // Reusing 901 keeps the signal unambiguous: the existing cap's TTL is
    // insufficient. See D-007 for full rationale.

    /// Issue a room capability token for a late-joining peer, anchored to an
    /// already-active `existing_cap` in the same room.
    ///
    /// REQ-ADM-014. Paused-flag checked first (Source-of-Truth Rule).
    ///
    /// The `existing_cap` proves the room is live and provides the `room_id`.
    /// The late-join window guard (`MIN_REMAINING_EPOCHS`) ensures the new token
    /// is not minted when the room session is nearly over, preventing trivially
    /// short-lived tokens from being issued.
    ///
    /// Canonical signed payload for this entry:
    ///   BCS({room_id, new_peer_pubkey, new_role, new_nonce, new_expires_epoch})
    /// This is identical in shape to `issue_capability_token` but uses the
    /// `room_id` extracted from `existing_cap` rather than a caller-supplied address.
    ///
    /// Aborts with:
    ///   E_CAP_PAUSED (882)                 — network circuit breaker
    ///   E_TOKEN_REVOKED (902)              — existing_cap has been revoked
    ///   E_TOKEN_EXPIRED (901)              — existing_cap expired OR remaining
    ///                                        epochs < MIN_REMAINING_EPOCHS (D-007-A)
    ///   E_PUBKEY_WRONG_LENGTH (916)        — new_peer_pubkey not 32 bytes
    ///   E_TOKEN_QUORUM_INSUFFICIENT (906)  — verify_quorum returned false
    public entry fun issue_capability_token_for_peer(
        registry:          &NetworkRegistry,
        cp_reg:            &ControlPlaneRegistry,
        quorum_state:      &QuorumConfigState,
        existing_cap:      &RoomCapability,        // proves room is active; room_id sourced here
        new_peer_pubkey:   vector<u8>,             // 32-byte ed25519 for the joining peer
        new_role:          u8,
        new_nonce:         u64,                    // monotonic per-peer; Phase 3.4 daemon enforces
        new_expires_epoch: u64,                    // typically inherited from existing_cap or shorter
        cp_quorum_sig:     QuorumSig,              // BCS struct per D-001
        signer_pubkeys:    vector<vector<u8>>,     // pubkeys-as-parameter per D-001
        aggregate_sig:     vector<u8>,             // stored for off-chain audit
        ctx:               &mut TxContext,
    ) {
        // ① Source-of-Truth paused-flag invariant
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        // ② Existing cap must not be revoked (room is still active)
        assert!(!existing_cap.revoked, capability_errors::e_token_revoked());

        let current_epoch = tx_context::epoch(ctx);

        // ③ Existing cap must not be expired
        assert!(
            existing_cap.expires_epoch > current_epoch,
            capability_errors::e_token_expired(),
        );

        // ④ Late-join window guard: sufficient epochs must remain before the
        //    existing cap expires. Reuses E_TOKEN_EXPIRED (901) per D-007-A.
        //    Semantics: "the existing cap is too close to expiry to safely admit
        //    a new peer" — equivalent to "token expired for this admission purpose".
        assert!(
            existing_cap.expires_epoch - current_epoch >= constants::min_remaining_epochs(),
            capability_errors::e_token_expired(),
        );

        // ⑤ Validate new_peer_pubkey length (ed25519 = 32 bytes)
        assert!(
            vector::length(&new_peer_pubkey) == ED25519_PUBKEY_LEN,
            E_PUBKEY_WRONG_LENGTH,
        );

        // ⑥ Extract room_id from the existing cap (caller cannot forge a different room)
        let room_id_typed: ID = existing_cap.room_id;

        // ⑦ Build canonical signed message:
        //    BCS({room_id, new_peer_pubkey, new_role, new_nonce, new_expires_epoch})
        //    Shape matches issue_capability_token canonical msg (D-001 carryover).
        let mut canonical_msg = vector::empty<u8>();
        let room_id_bytes = object::id_to_bytes(&room_id_typed);
        vector::append(&mut canonical_msg, room_id_bytes);
        vector::append(&mut canonical_msg, new_peer_pubkey);
        vector::push_back(&mut canonical_msg, new_role);
        let nonce_bytes = bcs_u64_le(new_nonce);
        vector::append(&mut canonical_msg, nonce_bytes);
        let exp_bytes = bcs_u64_le(new_expires_epoch);
        vector::append(&mut canonical_msg, exp_bytes);

        // ⑧ CP-quorum aggregate signature verification (inherits F-01 VecSet dedup)
        let quorum_ok = cp_quorum_sig::verify_quorum(
            registry,
            cp_reg,
            quorum_state,
            &cp_quorum_sig,
            signer_pubkeys,
            &canonical_msg,
        );
        assert!(quorum_ok, capability_errors::e_token_quorum_insufficient());

        // ⑨ Capture issuer CP addresses for audit storage
        let issuer_quorum_addrs: vector<address> = *cp_quorum_sig::signers(&cp_quorum_sig);

        // ⑩ Validate issuer_quorum length (mirrors issue_capability_token step ⑥)
        // ADR-0013: configurable floor via cp_quorum_sig::min_quorum (see issue_capability_token).
        assert!(
            vector::length(&issuer_quorum_addrs) >= cp_quorum_sig::min_quorum(quorum_state),
            E_QUORUM_TOO_SMALL,
        );

        // ⑪ Mint new RoomCapability (issued_epoch = current; expires = caller-supplied)
        assert!(new_expires_epoch > current_epoch, capability_errors::e_token_expired());

        let uid = object::new(ctx);
        let token_id: ID = object::uid_to_inner(&uid);

        let new_cap = RoomCapability {
            id: uid,
            room_id: room_id_typed,
            peer_pubkey: new_peer_pubkey,
            role: new_role,
            issued_epoch: current_epoch,
            expires_epoch: new_expires_epoch,
            issuer_cp_quorum: issuer_quorum_addrs,
            aggregate_sig,
            revoked: false,
            nonce: new_nonce,
        };

        // ⑫ Emit CapabilityIssued (D-005 Option b — base event, consistent subscription)
        emit_room_capability_issued(
            token_id,
            room_id_typed,
            new_cap.peer_pubkey,
            new_role,
            new_cap.issuer_cp_quorum,
            new_expires_epoch,
        );

        // ⑬ Transfer to sender (the joining peer's wallet)
        transfer::transfer(new_cap, tx_context::sender(ctx));
    }

    /// Issue a room capability token via the degraded path (AdminCap-gated).
    ///
    /// REQ-ADM-015. Used when the CP-quorum is unreachable (partition, misconfiguration,
    /// or emergency). NO `verify_quorum` call — that is the degraded path's purpose.
    ///
    /// The minted RoomCapability carries:
    ///   - `aggregate_sig = vector::empty<u8>()` — degraded-path marker (no CP sig)
    ///   - `issuer_cp_quorum = vector::empty<address>()` — no CP-quorum signers
    ///
    /// Downstream consumers MUST check `IssuedDegraded` event to distinguish
    /// degraded-path tokens from normal quorum-issued tokens. An empty aggregate_sig
    /// in the token object is a secondary signal.
    ///
    /// D-007-C: AdminCap-gating (NOT CP-quorum-of-1) — degraded path's entire point
    /// is bypassing quorum. AdminCap is the only authorization source pre-F10/W3.
    ///
    /// Aborts with:
    ///   E_CAP_PAUSED (882)              — network circuit breaker (applies to ALL
    ///                                     state-mutating entries, even AdminCap-gated)
    ///   E_INVALID_DEGRADED_REASON (919) — reason >= 3 (only 0/1/2 valid per D-007-E)
    ///   E_PUBKEY_WRONG_LENGTH (916)     — peer_pubkey not 32 bytes
    ///   E_TOKEN_EXPIRED (901)           — expires_epoch <= current epoch
    public entry fun issue_capability_token_degraded(
        _:             &AdminCap,           // AdminCap-gated degraded path
        registry:      &NetworkRegistry,
        _quorum_state: &QuorumConfigState,  // reserved: future CP-quorum-of-1 migration
        room_id:       address,
        peer_pubkey:   vector<u8>,
        role:          u8,
        nonce:         u64,
        expires_epoch: u64,
        reason:        u8,                  // 0=cp-partition / 1=quorum-disabled / 2=admin-override
        ctx:           &mut TxContext,
    ) {
        // ① Source-of-Truth paused-flag — applies to ALL state-mutating entries
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        // ② Reason range guard — only 0/1/2 are valid per D-OQ-2.3-2
        assert!(reason <= 2, E_INVALID_DEGRADED_REASON);

        // ③ Validate peer_pubkey length (ed25519 = 32 bytes)
        assert!(
            vector::length(&peer_pubkey) == ED25519_PUBKEY_LEN,
            E_PUBKEY_WRONG_LENGTH,
        );

        let current_epoch = tx_context::epoch(ctx);

        // ④ expires_epoch must be in the future
        assert!(expires_epoch > current_epoch, capability_errors::e_token_expired());

        let room_id_typed: ID = object::id_from_address(room_id);
        let issuer_addr = tx_context::sender(ctx);

        // ⑤ Mint RoomCapability — no CP-quorum sig on degraded path
        //    aggregate_sig = empty (degraded marker); issuer_cp_quorum = empty
        let uid = object::new(ctx);
        let token_id: ID = object::uid_to_inner(&uid);

        let deg_cap = RoomCapability {
            id: uid,
            room_id: room_id_typed,
            peer_pubkey,
            role,
            issued_epoch: current_epoch,
            expires_epoch,
            issuer_cp_quorum: vector::empty<address>(),  // no CP-quorum signers
            aggregate_sig: vector::empty<u8>(),           // degraded-path marker
            revoked: false,
            nonce,
        };

        // ⑥ Emit CapabilityIssued (D-005 Option b — off-chain consumers subscribe normally)
        emit_room_capability_issued(
            token_id,
            room_id_typed,
            deg_cap.peer_pubkey,
            role,
            deg_cap.issuer_cp_quorum,
            expires_epoch,
        );

        // ⑦ Emit IssuedDegraded for forensic audit (D-007-B: lives here, NOT in
        //    capability_events.move which is frozen). cp-daemon Phase 3.1 must
        //    subscribe to BOTH event sources for full degraded-path visibility.
        event::emit(IssuedDegraded {
            token_id,
            room_id: room_id_typed,
            peer_pubkey: deg_cap.peer_pubkey,
            role,
            reason,
            issuer: issuer_addr,
        });

        // ⑧ Transfer to sender (joining peer's wallet or admin-controlled wallet)
        transfer::transfer(deg_cap, tx_context::sender(ctx));
    }

    // ══════════════════════════════════════════════════════════
    // PHASE 2.4-RETRO — ATOMIC REFRESH ENTRY (D-009 / D-010-B)
    // ══════════════════════════════════════════════════════════
    //
    // REQ-ADM-002: atomic refresh capability (single-TX validate + revoke + mint + emit)
    // REQ-ADM-013: monotonic refresh_nonce = old.nonce + 1 (per D-010-B)
    //
    // The refresh entry replaces an active RoomCapability with a new one carrying
    // the same room_id + peer_pubkey but a new role and/or new expires_epoch.
    // It is the on-chain primitive for the F47 role-change grace flow + future
    // F8 emergency rotation flow. Per D-009, this is "Option A" — a single
    // atomic Move entry — chosen over daemon-orchestrated issue+revoke because:
    //   1. Preserves chain-as-SOT (one state transition + one audit event)
    //   2. Avoids state-inconsistency window between two daemon TXs
    //   3. Makes the frozen `CapabilityRefreshed` event live as designed
    //
    // Refresh-nonce derivation: `new.nonce = old.nonce + 1` (D-010-B). Strict
    // monotonic per-token chain — aligns Phase 3.4 daemon nonce enforcement.
    //
    // Canonical signed payload (cp-daemon off-chain signing must match):
    //   BCS({old_token_id, new_role, new_expires_epoch, refresh_nonce})
    // where refresh_nonce = old.nonce + 1. Field order locked.

    /// Atomically refresh a room capability token. Replaces an active token with
    /// a new one carrying the same room_id + peer_pubkey but a new role and/or
    /// new expires_epoch.
    ///
    /// REQ-ADM-002 (refresh primitive), REQ-ADM-013 (nonce monotonicity).
    ///
    /// Atomic semantics: a single TX validates the old token + verifies CP-quorum +
    /// marks old `revoked = true` + mints a new RoomCapability (new UID) with
    /// `nonce = old.nonce + 1` + emits frozen `CapabilityRefreshed`. Daemon failure
    /// mid-flow cannot leave inconsistent state because the entry is one Sui
    /// object-locked transaction. (D-009 defense: preserves chain-as-SOT.)
    ///
    /// Canonical signed payload (for cp-daemon off-chain signing):
    ///   BCS({old_token_id, new_role, new_expires_epoch, refresh_nonce})
    /// where refresh_nonce = `old.nonce + 1`. The CP quorum signs this exact
    /// payload off-chain. Field order locked (do NOT reorder without ADR + daemon update).
    ///
    /// Aborts with:
    ///   E_CAP_PAUSED (882)                — network circuit breaker (paused-flag invariant)
    ///   E_TOKEN_REVOKED (902)             — old_token already revoked
    ///   E_TOKEN_EXPIRED (901)             — new_expires_epoch <= current + MIN_REMAINING_EPOCHS (5)
    ///                                       NOTE: reuses 901 per D-007-A precedent; no new code
    ///   E_TOKEN_QUORUM_INSUFFICIENT (906) — verify_quorum returned false (M-of-N not met or duplicate)
    ///   E_PUBKEY_WRONG_LENGTH (916)       — peer_pubkey != 32 bytes (inherited from old, checked at mint)
    ///
    /// No new error codes introduced — all reuse existing 900-908 / 880-889 namespace.
    ///
    /// Transfers the new RoomCapability to `tx_context::sender(ctx)`. The sender is
    /// typically the cp-daemon multisig wallet OR the peer's wallet — Phase 3.4
    /// daemon design picks based on flow (see DECISIONS.md D-009).
    public entry fun refresh_capability_token(
        registry:          &NetworkRegistry,
        cp_reg:            &ControlPlaneRegistry,
        quorum_state:      &QuorumConfigState,
        old_token:         &mut RoomCapability,
        new_role:          u8,
        new_expires_epoch: u64,
        cp_quorum_proof:   QuorumSig,
        signer_pubkeys:    vector<vector<u8>>,
        aggregate_sig:     vector<u8>,             // BCS-serialized QuorumSig for audit
        ctx:               &mut TxContext,
    ) {
        // ① Source-of-Truth paused-flag invariant — fires FIRST
        assert!(!network_registry::is_paused(registry), E_CAP_PAUSED);

        // ② Old-token state check: must not be revoked
        assert!(!old_token.revoked, capability_errors::e_token_revoked());

        // ③ New-expiry window check — must be > current + MIN_REMAINING_EPOCHS.
        //    D-007-A: reuses E_TOKEN_EXPIRED (901) — semantically "the requested
        //    new TTL is too small for safe refresh". Same precedent as the
        //    late-join window guard in issue_capability_token_for_peer.
        let current_epoch = tx_context::epoch(ctx);
        assert!(
            new_expires_epoch > current_epoch + constants::min_remaining_epochs(),
            capability_errors::e_token_expired(),
        );

        // ④ Build canonical signed message:
        //    BCS({old_token_id, new_role, new_expires_epoch, refresh_nonce})
        //    where refresh_nonce = old.nonce + 1 (D-010-B monotonic).
        let old_token_id: ID = object::uid_to_inner(&old_token.id);
        let refresh_nonce: u64 = old_token.nonce + 1;

        let mut canonical_msg = vector::empty<u8>();
        let old_id_bytes = object::id_to_bytes(&old_token_id);
        vector::append(&mut canonical_msg, old_id_bytes);
        vector::push_back(&mut canonical_msg, new_role);
        let exp_bytes = bcs_u64_le(new_expires_epoch);
        vector::append(&mut canonical_msg, exp_bytes);
        let nonce_bytes = bcs_u64_le(refresh_nonce);
        vector::append(&mut canonical_msg, nonce_bytes);

        // ⑤ CP-quorum aggregate signature verification
        let quorum_ok = cp_quorum_sig::verify_quorum(
            registry,
            cp_reg,
            quorum_state,
            &cp_quorum_proof,
            signer_pubkeys,
            &canonical_msg,
        );
        assert!(quorum_ok, capability_errors::e_token_quorum_insufficient());

        // ⑥ Capture refresher CP addresses for audit storage in new token
        let refresher_addrs: vector<address> = *cp_quorum_sig::signers(&cp_quorum_proof);

        // ⑦ Capture old fields BEFORE state mutation (need for event + new cap)
        let inherited_room_id: ID = old_token.room_id;
        let inherited_peer_pubkey: vector<u8> = old_token.peer_pubkey;
        let old_expires_epoch: u64 = old_token.expires_epoch;

        // ⑧ Atomic mutation: mark old.revoked = true BEFORE minting new
        //    (per CONTRACTS § 4.1 step 7 — atomic ordering inside one TX).
        old_token.revoked = true;

        // ⑨ Mint new RoomCapability (new UID, inherited room + peer, new role +
        //    expires + monotonic nonce). Constructor invariants checked inline
        //    to match Phase 2.2 / 2.3 entry function pattern.
        assert!(
            vector::length(&inherited_peer_pubkey) == ED25519_PUBKEY_LEN,
            E_PUBKEY_WRONG_LENGTH,
        );
        // ADR-0013: configurable floor via cp_quorum_sig::min_quorum (see issue_capability_token).
        assert!(
            vector::length(&refresher_addrs) >= cp_quorum_sig::min_quorum(quorum_state),
            E_QUORUM_TOO_SMALL,
        );

        let new_uid = object::new(ctx);
        let new_token_id: ID = object::uid_to_inner(&new_uid);

        let new_cap = RoomCapability {
            id: new_uid,
            room_id: inherited_room_id,
            peer_pubkey: inherited_peer_pubkey,
            role: new_role,
            issued_epoch: current_epoch,
            expires_epoch: new_expires_epoch,
            issuer_cp_quorum: refresher_addrs,
            aggregate_sig,
            revoked: false,
            nonce: refresh_nonce,
        };

        // ⑩ Emit frozen CapabilityRefreshed event (capability_events.move S53).
        //    Carries old_expires_epoch + new_expires_epoch + refresher_quorum for
        //    off-chain TTL refresh tracking (cp-daemon Phase 3.1 + cache Phase 3.3).
        emit_room_capability_refreshed(
            new_token_id,
            inherited_room_id,
            new_cap.peer_pubkey,
            old_expires_epoch,
            new_expires_epoch,
            new_cap.issuer_cp_quorum,
        );

        // ⑪ Transfer new token to sender (typically cp-daemon multisig OR peer wallet)
        transfer::transfer(new_cap, tx_context::sender(ctx));
    }
}
