/// L2 contract test snapshot — interface lock for Stage 2 consumers.
///
/// DO NOT change the snapshot comments below without coordinating with:
///   - F62 admission (Stage 2, this milestone — room_capability.move)
///   - F47 cooldown updates (Stage 3 lane B — separate ROADMAP)
///   - F10 AdminCap migration (W3 — replaces AdminCap with CP-quorum self-gating)
///   - F5 TURN cap revocation + F8 relay secret rotation (pending brainstorm, post-Stage 1 ship)
///
/// This module compiles into the package but contains no callable code; it
/// exists purely as a reviewer-visible snapshot of the public surface of
/// `dvconf::cp_quorum_sig` at Phase 1.1 SHIP gate (S53 2026-05-25).
/// Any change to the signatures below MUST be paired with an update to all
/// listed consumers + a fresh L2 snapshot revision.
#[allow(unused_field)]
module dvconf::cp_quorum_sig_spec {
    // ── Public function signatures (frozen S53) ──
    //
    // public fun create_config(_: &AdminCap, ctx: &mut TxContext)
    //
    // public fun new_quorum_sig(
    //     signers: vector<address>,
    //     signatures: vector<vector<u8>>,
    // ): QuorumSig
    //
    // public fun verify_quorum(
    //     net_reg:  &NetworkRegistry,
    //     cp_reg:   &ControlPlaneRegistry,
    //     state:    &QuorumConfigState,
    //     qs:       &QuorumSig,
    //     pubkeys:  vector<vector<u8>>,
    //     msg:      &vector<u8>,
    // ): bool
    //
    // public fun update_threshold(
    //     _:             &AdminCap,
    //     net_reg:       &NetworkRegistry,
    //     state:         &mut QuorumConfigState,
    //     new_threshold: u64,
    //     updater:       address,
    // )
    //
    // public fun min_quorum(state: &QuorumConfigState): u64
    // public fun signers(qs: &QuorumSig): &vector<address>
    // public fun signatures(qs: &QuorumSig): &vector<vector<u8>>

    // ── BCS struct layouts (frozen S53) ──
    //
    // struct QuorumSig has copy, drop, store {
    //     signers:    vector<address>,
    //     signatures: vector<vector<u8>>,
    // }
    //
    // struct QuorumConfigState has key {
    //     id:         UID,
    //     min_quorum: u64,
    // }

    // ── Event schemas (frozen S53; Fork 6 additive-only convention) ──
    //
    // struct QuorumVerified      has copy, drop { signers: vector<address>, msg_hash: vector<u8> }
    // struct QuorumInsufficient  has copy, drop { signers_count: u64, required: u64 }
    // struct QuorumConfigUpdated has copy, drop { old_threshold: u64, new_threshold: u64, updater: address }

    // ── Error namespace (880-889 reserved-future range) ──
    // Frozen S53 PLUS Phase 2.2 addition: E_DUPLICATE_SIGNER (886) is now ACTIVE.
    // verify_quorum deduplicates the `signers` vector as of Phase 2.2 (F-01 fix).
    //
    // const E_INSUFFICIENT_QUORUM:   u64 = 880;
    // const E_INVALID_SIG:           u64 = 881;
    // const E_PAUSED:                u64 = 882;
    // const E_QUORUM_CONFIG_INVALID: u64 = 883;
    // const E_PUBKEY_COUNT_MISMATCH: u64 = 884;
    // const E_SIGNER_NOT_REGISTERED: u64 = 885;
    // const E_DUPLICATE_SIGNER:      u64 = 886;  // ACTIVE Phase 2.2 — soft-fail dedup

    /// Stub struct so the module file is not empty.
    public struct CpQuorumSigSpecMarker has drop {
        version: u64,
    }
}
