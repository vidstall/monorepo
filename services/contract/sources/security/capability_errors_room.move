/// Room-specific error-code constants for the capability-token subsystem.
///
/// REQ-ADM-019 (room-specific error codes portion) — Phase 2.1 of
/// room-admission-control M1 (F62, Wave W1 P16).
///
/// ## Namespace layout
///
///   880-889  Phase 1.1 cp_quorum_sig.move (owned by that module)
///   900-908  Phase 1.2 base codes — capability_errors.move (shared, frozen S53)
///   909-915  Phase 2.x room-specific codes (THIS MODULE)
///
/// ## Usage pattern
///
/// Phase 2.x consumers call `capability_errors_room::e_room_cap_not_for_this_room()`
/// instead of embedding the raw integer. This mirrors the Phase 1.2 pattern in
/// capability_errors.move and keeps all room-specific values in one place.
///
/// ## D-005 note
///
/// Codes 909-915 were reserved for Phase 2.x room-specific wrappers per the
/// capability_errors.move module header (docstring line "909-915 Reserved for
/// Phase 2.x room-specific wrappers"). The ROADMAP § Phase 2.1 incorrectly
/// stated "902-907" — that range is already occupied by Phase 1.2 base codes
/// (E_TOKEN_REVOKED=902 through E_TOKEN_QUORUM_INSUFFICIENT=906). Correct range
/// confirmed from capability_errors.move docstring + PIPELINE-STATE.md note.
/// Flagged as ROADMAP discrepancy for correction in subsequent session.
///
/// Reference: ONCHAIN_AGENT_SKILL.md namespace table § (reserved future) 700-1099;
///            DECISIONS.md § D-004 (Phase 1.2 range pins) + § D-005 (room codes).
module dvconf::capability_errors_room {

    // ── Room-specific error constants (909-915) ──────────────────────────
    // All carry #[allow(unused_const)] because each constant is exposed only via
    // its public accessor — the accessor is what callers use at call sites.
    // Phase 2.2 entry functions (issue/verify/revoke) will reference these via
    // accessor calls. This mirrors the Phase 1.2 cp_quorum_sig.move precedent.

    /// Token's room_id does not match the room the caller is trying to join.
    /// More specific than the base E_TOKEN_ROOM_MISMATCH (903); used for
    /// room-capability-specific verification paths in Phase 2.2+.
    #[allow(unused_const)]
    const E_ROOM_CAP_NOT_FOR_THIS_ROOM: u64 = 909;

    /// Token's peer_pubkey does not match the calling peer's ed25519 key.
    /// More specific than the base E_TOKEN_PEER_MISMATCH (904); surfaces the
    /// room-capability context (which room + which peer) in the abort.
    #[allow(unused_const)]
    const E_ROOM_CAP_NOT_FOR_THIS_PEER: u64 = 910;

    /// Token's expires_epoch is in the past for this specific room context.
    /// More specific than the base E_TOKEN_EXPIRED (901); used in Phase 2.2
    /// verify entry to distinguish room-level TTL from general expiry.
    #[allow(unused_const)]
    const E_ROOM_CAP_EXPIRED_FOR_ROOM: u64 = 911;

    /// Token has been explicitly revoked for this room.
    /// More specific than the base E_TOKEN_REVOKED (902). Used in Phase 2.2
    /// verify_capability_token to give callers a room-specific abort code.
    #[allow(unused_const)]
    const E_ROOM_CAP_REVOKED_FOR_ROOM: u64 = 912;

    /// Anti-replay: nonce presented does not match the expected next nonce.
    /// Phase 3.4 signaling daemon enforces nonce monotonicity; this constant
    /// reserves the abort code now so the Phase 3.4 impl picks it up without
    /// a renumber. Reserved: not enforced until Phase 3.4 anti-replay scope.
    #[allow(unused_const)]
    const E_ROOM_CAP_NONCE_MISMATCH: u64 = 913;

    /// CP-quorum signer count provided to issue/revoke is below the configured
    /// minimum threshold (M-of-N not met) in the room-capability context.
    /// Complements the base E_TOKEN_QUORUM_INSUFFICIENT (906) with room scope.
    /// Reserved: activated in Phase 2.2 issue_capability_token entry.
    #[allow(unused_const)]
    const E_ROOM_CAP_QUORUM_BELOW_THRESHOLD: u64 = 914;

    /// Aggregate signature on the RoomCapability failed ed25519 verification
    /// during room-level token verification. Complements base E_TOKEN_SIG_INVALID
    /// (905) with room context for Phase 2.2 verify strict-abort path.
    /// Reserved: activated in Phase 2.2 verify_capability_token entry.
    #[allow(unused_const)]
    const E_ROOM_CAP_SIG_INVALID: u64 = 915;

    // ── Public accessors ─────────────────────────────────────────────────
    // Read-only safe (`public` not `public(package)`) — these are constants,
    // not constructors. Any module may read an error code to use in an assert!.
    // Naming style mirrors Phase 1.2 capability_errors.move `e_snake_case()`.

    /// Token room_id does not match the expected room (room-cap context).
    public fun e_room_cap_not_for_this_room(): u64    { E_ROOM_CAP_NOT_FOR_THIS_ROOM }

    /// Token peer_pubkey does not match the calling peer (room-cap context).
    public fun e_room_cap_not_for_this_peer(): u64    { E_ROOM_CAP_NOT_FOR_THIS_PEER }

    /// Token is expired for this specific room (room-cap context).
    public fun e_room_cap_expired_for_room(): u64     { E_ROOM_CAP_EXPIRED_FOR_ROOM }

    /// Token has been revoked for this room (room-cap context).
    public fun e_room_cap_revoked_for_room(): u64     { E_ROOM_CAP_REVOKED_FOR_ROOM }

    /// Anti-replay nonce mismatch (room-cap context; enforced Phase 3.4).
    public fun e_room_cap_nonce_mismatch(): u64       { E_ROOM_CAP_NONCE_MISMATCH }

    /// CP-quorum count below threshold (room-cap context; enforced Phase 2.2).
    public fun e_room_cap_quorum_below_threshold(): u64 { E_ROOM_CAP_QUORUM_BELOW_THRESHOLD }

    /// Aggregate signature invalid for room-cap verification (Phase 2.2).
    public fun e_room_cap_sig_invalid(): u64          { E_ROOM_CAP_SIG_INVALID }
}
