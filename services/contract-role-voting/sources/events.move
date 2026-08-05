/// Event structs + emit wrappers for role_voting.move (LOC-budget split).
/// Mirrors the capability_events.move pattern: pure event structs, no field
/// coupling to RoleVoteBox — every emit wrapper takes pre-computed values.
module dvconf_role_voting::role_voting_events {
    use sui::event;

    public struct RoleAssigned has copy, drop {
        miner_id:   ID,
        role:       u8,
        vote_count: u64,
        threshold:  u64,
    }

    public struct RoleVoteCast has copy, drop {
        miner_id: ID,
        role:     u8,
        voter:    address,
        current_votes: u64,
        required:      u64,
    }

    /// Emitted when a miner is inserted into the revote-eligible pool (F47 REQ-RV-007).
    ///
    /// `reason` encoding:
    ///   1 = IDLE — miner's role registry heartbeat stale > max_idle_epochs
    ///   2 = COMPOSITION_SHIFT — miner's role is in surplus (scarcity ratio < SCARCITY_FLOOR_BPS)
    ///   3 = MINER_REQUEST — miner self-requested re-vote via MinerCap
    public struct RevoteEligibleMarked has copy, drop {
        miner_id:     ID,
        reason:       u8,   // 1=IDLE, 2=COMPOSITION_SHIFT, 3=MINER_REQUEST
        current_role: u8,
        marked_at:    u64,  // epoch number when marked
    }

    /// Emitted when the per-miner re-vote cooldown window is changed via CP-quorum (F47 REQ-RV-004).
    public struct CooldownConfigUpdated has copy, drop {
        old_value: u64,
        new_value: u64,
        updater:   address,
    }

    /// Emitted when the idle-epoch threshold is changed via CP-quorum (F47 REQ-RV-004).
    public struct MaxIdleConfigUpdated has copy, drop {
        old_value: u64,
        new_value: u64,
        updater:   address,
    }

    // ══════════════════════════════════════════════════════════
    // EMIT WRAPPERS (public(package) per capability_events.move precedent)
    // ══════════════════════════════════════════════════════════

    public(package) fun emit_role_assigned(miner_id: ID, role: u8, vote_count: u64, threshold: u64) {
        event::emit(RoleAssigned { miner_id, role, vote_count, threshold });
    }

    public(package) fun emit_role_vote_cast(
        miner_id: ID, role: u8, voter: address, current_votes: u64, required: u64,
    ) {
        event::emit(RoleVoteCast { miner_id, role, voter, current_votes, required });
    }

    public(package) fun emit_revote_eligible_marked(
        miner_id: ID, reason: u8, current_role: u8, marked_at: u64,
    ) {
        event::emit(RevoteEligibleMarked { miner_id, reason, current_role, marked_at });
    }

    public(package) fun emit_cooldown_config_updated(old_value: u64, new_value: u64, updater: address) {
        event::emit(CooldownConfigUpdated { old_value, new_value, updater });
    }

    public(package) fun emit_max_idle_config_updated(old_value: u64, new_value: u64, updater: address) {
        event::emit(MaxIdleConfigUpdated { old_value, new_value, updater });
    }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    // ── F47 Phase 1.6 (REQ-RV-007) — RevoteEligibleMarked schema-lock anchor ──
    //
    // Test-only constructor. Names every field so a RENAME or REMOVAL breaks
    // the events-test build before ship (ADR-0008 schema lock); a pure REORDER
    // still compiles (name-bound shorthand) and is caught instead by that
    // test's BCS peel. It also lets the test BCS-serialize the exact wire
    // layout the cp-daemon revote-watcher / F66 viz consumers decode. Not
    // used by any production path.
    #[test_only]
    public fun new_revote_eligible_marked_for_testing(
        miner_id: ID,
        reason: u8,
        current_role: u8,
        marked_at: u64,
    ): RevoteEligibleMarked {
        RevoteEligibleMarked { miner_id, reason, current_role, marked_at }
    }
}
