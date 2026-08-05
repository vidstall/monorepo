/// Role-voting CP-quorum governance — satellite of `role_voting` (F47 Phase 1.4, REQ-RV-004).
///
/// D-S60-1: CP-quorum is the DIRECT authority — there is NO AdminCap shim. Shares the parent's
/// error namespace (700-719) via its public(package) accessors — no new error constants.
module dvconf_role_voting::role_voting_governance {
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::control_plane_registry::ControlPlaneRegistry;
    use dvconf::cp_quorum_sig::{Self, QuorumSig, QuorumConfigState};
    use dvconf_role_voting::role_voting::{Self, RoleVoteBox};
    use dvconf_role_voting::role_voting_events;

    /// Action = mutate revote_cooldown_epochs.
    const ACTION_UPDATE_COOLDOWN: u8 = 1;
    /// Action = mutate max_idle_epochs.
    const ACTION_UPDATE_MAX_IDLE: u8 = 2;

    /// Build the canonical CP-quorum governance message (F47 REQ-RV-004).
    ///
    /// Layout — 25 bytes, little-endian (mirrors room_capability's hand-rolled BCS append style):
    ///   [action: u8] ++ le8(new_value) ++ le8(nonce) ++ le8(epoch)
    ///
    /// `nonce` and `epoch` are signed-binding fields included in the payload now so a future
    /// cp-daemon governance-coordinator (Phase 2.3) can enforce monotonic-nonce / epoch-freshness
    /// WITHOUT a breaking message-format change. The BYTE FORMAT is provisional (OQ-RV-1). On-chain
    /// freshness/replay enforcement is deliberately deferred (OQ-RV-4): until the Phase 2.3 daemon
    /// nonce/freshness check lands, a captured valid quorum signature is replayable on-chain — bounded
    /// because only a registered CP-quorum can produce ANY valid sig, so replay merely re-applies an
    /// already-authorized value (not an attacker-chosen one). This Move layer binds the signature to
    /// the exact (action, new_value, nonce, epoch) tuple.
    public fun build_governance_msg(action: u8, new_value: u64, nonce: u64, epoch: u64): vector<u8> {
        let mut msg = vector::empty<u8>();
        vector::push_back(&mut msg, action);
        vector::append(&mut msg, u64_to_le_bytes(new_value));
        vector::append(&mut msg, u64_to_le_bytes(nonce));
        vector::append(&mut msg, u64_to_le_bytes(epoch));
        msg
    }

    /// Serialize a u64 as 8 little-endian bytes (BCS u64 encoding). Kept inline (no std::bcs dep)
    /// to mirror the sibling room_capability module's hand-rolled style.
    fun u64_to_le_bytes(value: u64): vector<u8> {
        let mut out = vector::empty<u8>();
        let mut v = value;
        let mut i = 0;
        while (i < 8) {
            vector::push_back(&mut out, ((v & 0xFF) as u8));
            v = v >> 8;
            i = i + 1;
        };
        out
    }

    /// Update the per-miner re-vote cooldown window (Q1), gated by a CP-quorum aggregate signature.
    ///
    /// D-S60-1: CP-quorum is the DIRECT authority — there is NO AdminCap shim. The CPs sign
    /// `build_governance_msg(ACTION_UPDATE_COOLDOWN, new_value, nonce, epoch)` off-chain;
    /// `cp_quorum_sig::verify_quorum` enforces M-of-N + ed25519 + CP registration + signer dedup.
    ///
    /// The paused-flag invariant is asserted FIRST so a paused network aborts with THIS module's
    /// E_PAUSED (700) rather than the delegated cp_quorum_sig::E_PAUSED (882), keeping the abort in
    /// the role_voting namespace consistent with every other entry here.
    ///
    /// Aborts: E_PAUSED (700) when paused; E_GOVERNANCE_QUORUM_INSUFFICIENT (718) when quorum fails.
    public fun update_revote_cooldown_epochs(
        net_reg:        &NetworkRegistry,
        vote_box:       &mut RoleVoteBox,
        cp_reg:         &ControlPlaneRegistry,
        quorum_state:   &QuorumConfigState,
        qs:             QuorumSig,
        signer_pubkeys: vector<vector<u8>>,
        new_value:      u64,
        nonce:          u64,
        epoch:          u64,
        ctx:            &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), role_voting::e_paused());

        let msg = build_governance_msg(ACTION_UPDATE_COOLDOWN, new_value, nonce, epoch);
        let quorum_ok = cp_quorum_sig::verify_quorum(
            net_reg, cp_reg, quorum_state, &qs, signer_pubkeys, &msg,
        );
        assert!(quorum_ok, role_voting::e_governance_quorum_insufficient());

        let old_value = role_voting::set_revote_cooldown_epochs(vote_box, new_value);

        role_voting_events::emit_cooldown_config_updated(old_value, new_value, ctx.sender());
    }

    /// Update the idle-epoch threshold (Q2), gated by a CP-quorum aggregate signature.
    /// Same gating contract as update_revote_cooldown_epochs (D-S60-1); action = ACTION_UPDATE_MAX_IDLE.
    ///
    /// Aborts: E_PAUSED (700) when paused; E_GOVERNANCE_QUORUM_INSUFFICIENT (718) when quorum fails.
    public fun update_max_idle_epochs(
        net_reg:        &NetworkRegistry,
        vote_box:       &mut RoleVoteBox,
        cp_reg:         &ControlPlaneRegistry,
        quorum_state:   &QuorumConfigState,
        qs:             QuorumSig,
        signer_pubkeys: vector<vector<u8>>,
        new_value:      u64,
        nonce:          u64,
        epoch:          u64,
        ctx:            &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), role_voting::e_paused());

        let msg = build_governance_msg(ACTION_UPDATE_MAX_IDLE, new_value, nonce, epoch);
        let quorum_ok = cp_quorum_sig::verify_quorum(
            net_reg, cp_reg, quorum_state, &qs, signer_pubkeys, &msg,
        );
        assert!(quorum_ok, role_voting::e_governance_quorum_insufficient());

        let old_value = role_voting::set_max_idle_epochs(vote_box, new_value);

        role_voting_events::emit_max_idle_config_updated(old_value, new_value, ctx.sender());
    }
}
