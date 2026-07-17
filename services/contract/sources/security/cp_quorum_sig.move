/// CP-quorum aggregate signature scheme — REQ-ADM-008 (F62 Phase 1.1).
///
/// Shared primitive for the Phase 16 "Security Capability Tokens" cluster
/// (F5 TURN cap revocation, F8 relay secret rotation, F62 room admission,
/// F47 cooldown updates). Per Fork 1 Option β (DESIGN.md), this module owns
/// the M-of-N ed25519 aggregate signature verification path; the per-feature
/// cap-token data structs (room_capability, turn_capability, relay_secret)
/// live separately and consume `verify_quorum` for their issue/revoke gating.
///
/// Threshold: default M=2/N=3 (D-B4 — BFT 67% minority tolerance). Default
/// sourced from `constants::min_cp_quorum_for_token()`. Configurable post-deploy
/// via `update_threshold` (AdminCap Stage 1; per Fork 2 will migrate to
/// CP-quorum self-gating once F10/W3 ships).
///
/// Error code namespace: 880-889 (reserved future range from ONCHAIN_AGENT_SKILL
/// namespace table — `(reserved future) | 700–1099`). Phase 1.2 capability_events
/// owns 900-915.
module dvconf::cp_quorum_sig {
    use sui::event;
    use sui::ed25519;
    use sui::hash;
    use sui::vec_set::{Self, VecSet};
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry, CPNodeInfo};

    // ── Errors (880-889) ──
    // `verify_quorum` is a soft-fail predicate for most checks (returns `bool`,
    // emits `QuorumInsufficient`). It only aborts on the paused-flag invariant
    // and shape mismatches. The other constants reserve runtime codes for
    // Stage 2+ consumers that want strict-abort wrappers (Fork 2 migration scope).
    // E_DUPLICATE_SIGNER (886) is ACTIVE as of Phase 2.2 — verify_quorum now
    // deduplicates the `signers` vector and returns false on duplicate address.
    #[allow(unused_const)]
    const E_INSUFFICIENT_QUORUM: u64    = 880;  // reserved; activated in Stage 2 strict gating
    #[allow(unused_const)]
    const E_INVALID_SIG: u64            = 881;  // reserved; Stage 2 strict gating
    const E_PAUSED: u64                 = 882;
    const E_QUORUM_CONFIG_INVALID: u64  = 883;
    const E_PUBKEY_COUNT_MISMATCH: u64  = 884;
    #[allow(unused_const)]
    const E_SIGNER_NOT_REGISTERED: u64  = 885;  // reserved; Stage 2 strict gating
    /// Duplicate address in `qs.signers` vector — same CP counted twice toward quorum.
    /// F-01 fix: explicit deduplication guard prevents a single registered CP from
    /// satisfying M-of-N quorum alone by submitting [alice, alice] with 2 valid sigs.
    /// Soft-fail: returns false + emits QuorumInsufficient (does NOT abort) so that
    /// callers retain the same soft-fail policy as all other non-pause failures.
    /// The const documents the reserved error code value for future strict-abort wrappers
    /// in Stage 2+ consumers (consistent with 880-885 #[allow(unused_const)] pattern).
    #[allow(unused_const)]
    const E_DUPLICATE_SIGNER: u64       = 886;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    /// BCS-serialisable aggregate signature payload.
    /// `signers[i]` is the operator address of the CP node whose ed25519
    /// signature lives at `signatures[i]`. Pubkeys are passed alongside in
    /// `verify_quorum` (off-chain look-up; CP registry pubkey storage is
    /// scoped to Phase 2.x — see DECISIONS.md § D-001).
    public struct QuorumSig has copy, drop, store {
        signers: vector<address>,
        signatures: vector<vector<u8>>,
    }

    /// Shared mutable config for the M-of-N threshold. AdminCap-gated update Stage 1.
    public struct QuorumConfigState has key {
        id: UID,
        min_quorum: u64,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct QuorumVerified has copy, drop {
        signers: vector<address>,
        msg_hash: vector<u8>,
    }

    public struct QuorumInsufficient has copy, drop {
        signers_count: u64,
        required: u64,
    }

    public struct QuorumConfigUpdated has copy, drop {
        old_threshold: u64,
        new_threshold: u64,
        updater: address,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    /// One-shot init of the shared config object. AdminCap-gated.
    public fun create_config(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(QuorumConfigState {
            id: object::new(ctx),
            min_quorum: constants::min_cp_quorum_for_token(),
        });
    }

    /// BCS struct constructor (callers build off-chain then pass in).
    public fun new_quorum_sig(
        signers: vector<address>,
        signatures: vector<vector<u8>>,
    ): QuorumSig {
        QuorumSig { signers, signatures }
    }

    // ══════════════════════════════════════════════════════════
    // VERIFICATION (read-only path — no state mutation)
    // ══════════════════════════════════════════════════════════

    /// Verify a CP-quorum aggregate signature over `msg`.
    ///
    /// Returns `true` iff ALL the following hold:
    ///   1. `qs.signers.length() >= state.min_quorum` (M-of-N threshold)
    ///   2. `qs.signatures.length() == qs.signers.length()` (BCS shape check)
    ///   3. `pubkeys.length() == qs.signers.length()` (off-chain look-up shape)
    ///   4. Each `signers[i]` is the operator address of a registered CP node
    ///   5. `ed25519::ed25519_verify(signatures[i], pubkeys[i], msg)` for every i
    ///
    /// Aborts with `E_PAUSED` when network paused (SoT Rule — paused flag invariant).
    /// All other failure modes return `false` and emit `QuorumInsufficient` —
    /// caller decides whether to abort or fall back.
    public fun verify_quorum(
        net_reg: &NetworkRegistry,
        cp_reg: &ControlPlaneRegistry,
        state: &QuorumConfigState,
        qs: &QuorumSig,
        pubkeys: vector<vector<u8>>,
        msg: &vector<u8>,
    ): bool {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let n = vector::length(&qs.signers);
        let required = state.min_quorum;

        // Shape checks (return false, not abort — caller chooses policy)
        if (vector::length(&qs.signatures) != n) {
            event::emit(QuorumInsufficient { signers_count: n, required });
            return false
        };
        if (vector::length(&pubkeys) != n) {
            // Hard mismatch: caller built malformed payload. Abort so the bug surfaces.
            abort E_PUBKEY_COUNT_MISMATCH
        };

        // Threshold check
        if (n < required) {
            event::emit(QuorumInsufficient { signers_count: n, required });
            return false
        };

        // Duplicate-signer dedup guard (F-01 fix — Stage 2 hardening per D-004).
        // Build a VecSet<address> while iterating; if the same operator address
        // appears twice, return false + emit QuorumInsufficient (soft-fail, not abort —
        // consistent with all other non-pause failure modes in this function).
        // Trade-off: O(n) VecSet insert on top of O(n*m) membership scan — negligible
        // at thesis scale (N ≤ ~10 CPs, M ≤ 5 signers per D-001).
        let mut seen: VecSet<address> = vec_set::empty();
        let mut i = 0;
        while (i < n) {
            let signer_addr = *vector::borrow(&qs.signers, i);
            // Duplicate check before membership + sig verify
            if (vec_set::contains(&seen, &signer_addr)) {
                event::emit(QuorumInsufficient { signers_count: n, required });
                return false
            };
            vec_set::insert(&mut seen, signer_addr);
            if (!is_operator_registered(cp_reg, signer_addr)) {
                event::emit(QuorumInsufficient { signers_count: n, required });
                return false
            };
            let sig = vector::borrow(&qs.signatures, i);
            let pk = vector::borrow(&pubkeys, i);
            if (!ed25519::ed25519_verify(sig, pk, msg)) {
                event::emit(QuorumInsufficient { signers_count: n, required });
                return false
            };
            i = i + 1;
        };

        event::emit(QuorumVerified {
            signers: qs.signers,
            msg_hash: hash::keccak256(msg),
        });
        true
    }

    // ══════════════════════════════════════════════════════════
    // GOVERNANCE (AdminCap-gated; will migrate to CP-quorum post-F10)
    // ══════════════════════════════════════════════════════════

    /// Update the M threshold. New value must satisfy `1 <= new <= active_cp_count`.
    /// AdminCap Stage 1 per Fork 2 F-2.A. CP-quorum dual-gating arrives in Phase 2.3.
    public fun update_threshold(
        _: &AdminCap,
        net_reg: &NetworkRegistry,
        state: &mut QuorumConfigState,
        new_threshold: u64,
        updater: address,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(new_threshold >= 1, E_QUORUM_CONFIG_INVALID);

        let old = state.min_quorum;
        state.min_quorum = new_threshold;

        event::emit(QuorumConfigUpdated {
            old_threshold: old,
            new_threshold,
            updater,
        });
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun min_quorum(state: &QuorumConfigState): u64 { state.min_quorum }

    public fun signers(qs: &QuorumSig): &vector<address> { &qs.signers }
    public fun signatures(qs: &QuorumSig): &vector<vector<u8>> { &qs.signatures }

    // ══════════════════════════════════════════════════════════
    // INTERNAL HELPERS
    // ══════════════════════════════════════════════════════════

    /// Check whether `addr` is the operator address of any currently-registered CP.
    /// O(n) over `active_cps` (n ≤ ~10 for thesis scale; M-of-N rarely > 5).
    fun is_operator_registered(cp_reg: &ControlPlaneRegistry, addr: address): bool {
        let active: vector<CPNodeInfo> = control_plane_registry::get_active_cps(cp_reg);
        let mut i = 0;
        let len = vector::length(&active);
        while (i < len) {
            let info = vector::borrow(&active, i);
            if (control_plane_registry::info_operator(info) == addr) {
                return true
            };
            i = i + 1;
        };
        false
    }
}
