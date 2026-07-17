/// Shared error-code constants for the capability-token subsystem.
///
/// REQ-ADM-019 (base error codes portion) — Phase 1.2 of room-admission-control M1 (F62).
///
/// Namespace layout:
///   900-908  Base codes (this module) — shared across all capability-token consumers.
///   909-915  Reserved for Phase 2.x room-specific wrappers (room_capability.move et al.).
///
/// Phase 1.1 (cp_quorum_sig.move) owns 880-889. No collision is possible because all
/// Phase 1.2 codes start at 900. CAP_EVT_05 test in capability_events_tests.move pins
/// this invariant at compile time.
///
/// Usage: Phase 2.x consumers call `capability_errors::e_token_not_found()` instead of
/// embedding the raw integer. This keeps the numeric values in one place so a future
/// renumber is caught by CAP_EVT_04 before it ships.
///
/// Reference: ONCHAIN_AGENT_SKILL.md namespace table § (reserved future) 700-1099;
///            DECISIONS.md § D-001 (Phase 1.1 range) + § D-002 (Phase 1.2 range).
module dvconf::capability_errors {

    // ── Base error constants (900-908) ───────────────────────────────────
    // Each constant carries #[allow(unused_const)] because the constant itself
    // is only referenced through its public accessor. Downstream Phase 2.x
    // callers use the accessor so the numeric value stays in one place.
    // This mirrors the Phase 1.1 cp_quorum_sig.move precedent for reserved codes.

    #[allow(unused_const)]
    const E_TOKEN_NOT_FOUND: u64         = 900;
    #[allow(unused_const)]
    const E_TOKEN_EXPIRED: u64           = 901;
    #[allow(unused_const)]
    const E_TOKEN_REVOKED: u64           = 902;
    #[allow(unused_const)]
    const E_TOKEN_ROOM_MISMATCH: u64     = 903;
    #[allow(unused_const)]
    const E_TOKEN_PEER_MISMATCH: u64     = 904;
    #[allow(unused_const)]
    const E_TOKEN_SIG_INVALID: u64       = 905;
    #[allow(unused_const)]
    const E_TOKEN_QUORUM_INSUFFICIENT: u64 = 906;
    #[allow(unused_const)]
    const E_TOKEN_ALREADY_REVOKED: u64   = 907;
    // Reserved for Phase 2.x anti-replay enforcement (Phase 3.4 signaling daemon scope).
    // Phase 1.2 does not enforce nonces; the constant locks the namespace value at 908.
    #[allow(unused_const)]
    const E_REPLAY_NONCE_USED: u64       = 908;

    // ── Public accessors ─────────────────────────────────────────────────
    // Read-only safe (`public` not `public(package)`) — these are constants,
    // not constructors. Any module may read an error code to use in an assert!.

    /// Capability token with the given ID was not found in the on-chain registry.
    public fun e_token_not_found(): u64         { E_TOKEN_NOT_FOUND }

    /// Capability token's `expires_epoch` is in the past; re-issue required.
    public fun e_token_expired(): u64           { E_TOKEN_EXPIRED }

    /// Capability token has been explicitly revoked (revoked == true).
    public fun e_token_revoked(): u64           { E_TOKEN_REVOKED }

    /// Token's `room_id` does not match the room the caller is trying to join.
    public fun e_token_room_mismatch(): u64     { E_TOKEN_ROOM_MISMATCH }

    /// Token's `peer_pubkey` does not match the calling peer's ed25519 key.
    public fun e_token_peer_mismatch(): u64     { E_TOKEN_PEER_MISMATCH }

    /// Aggregate signature attached to the token failed ed25519 verification.
    public fun e_token_sig_invalid(): u64       { E_TOKEN_SIG_INVALID }

    /// CP-quorum signer count < configured minimum threshold (M-of-N not met).
    public fun e_token_quorum_insufficient(): u64 { E_TOKEN_QUORUM_INSUFFICIENT }

    /// Token revocation was attempted but the token is already revoked (idempotency guard).
    public fun e_token_already_revoked(): u64   { E_TOKEN_ALREADY_REVOKED }

    /// Anti-replay: a nonce that was already consumed is being presented again.
    public fun e_replay_nonce_used(): u64       { E_REPLAY_NONCE_USED }
}
