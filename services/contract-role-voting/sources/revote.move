/// Role re-vote eligibility entries — satellite of `role_voting` (F47 Phase 1.2, REQ-RV-002).
///
/// Holds the three permissionless/miner-gated entries that mark a miner eligible for
/// re-vote (idle heartbeat, composition imbalance, self-request). Shares the parent's
/// error namespace (700-719) via its public(package) accessors — no new error constants.
module dvconf_role_voting::role_voting_revote {
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::constants;
    use dvconf_role_voting::role_voting::{Self, RoleVoteBox};
    use dvconf_role_voting::role_voting_events;

    /// Mark a miner as eligible for re-vote due to idle heartbeat.
    ///
    /// Permissionless: anyone can invoke this once the on-chain idle condition is met.
    /// Condition: current_epoch - last_heartbeat(registry[miner.role]) > box.max_idle_epochs
    ///
    /// Reads last_heartbeat from the role-specific registry (Relay/Validator/CP/Signaling).
    /// Aborts with E_NOT_IDLE_YET if idle gap does not exceed threshold.
    /// Aborts with E_COOLDOWN if miner was marked within the cooldown window.
    public fun mark_revote_eligible_idle(
        net_reg:       &NetworkRegistry,
        vote_box:      &mut RoleVoteBox,
        miner_store:   &MinerStore,
        relay_reg:     &RelayRegistry,
        validator_reg: &ValidatorRegistry,
        cp_reg:        &ControlPlaneRegistry,
        signaling_reg: &SignalingRegistry,
        miner_id:      ID,
        ctx:           &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), role_voting::e_paused());
        assert!(miner_store::has_profile(miner_store, miner_id), role_voting::e_miner_not_found());

        let profile = miner_store::borrow_profile(miner_store, miner_id);
        let current_role = miner_store::profile_role(profile);
        let current_epoch = ctx.epoch();
        let max_idle = role_voting::max_idle_epochs(vote_box);

        // Read last_heartbeat from the role-specific registry
        let last_heartbeat = if (current_role == constants::role_relay()) {
            let info = relay_registry::borrow_info(relay_reg, miner_id);
            relay_registry::info_last_heartbeat(info)
        } else if (current_role == constants::role_validator()) {
            let info = validator_registry::borrow_info(validator_reg, miner_id);
            validator_registry::info_last_heartbeat(info)
        } else if (current_role == constants::role_cp()) {
            let info = control_plane_registry::borrow_info(cp_reg, miner_id);
            control_plane_registry::info_last_heartbeat(info)
        } else {
            // ROLE_SIGNALING or ROLE_USER — use signaling registry
            let info = signaling_registry::borrow_info(signaling_reg, miner_id);
            signaling_registry::info_last_heartbeat(info)
        };

        // Enforce idle threshold (integer underflow-safe: check epoch >= last_heartbeat first)
        let idle_gap = if (current_epoch > last_heartbeat) {
            current_epoch - last_heartbeat
        } else {
            0
        };
        // N2 (S63 QC): strict `>` (not `>=`) is deliberate. max_idle is the LAST tolerated idle
        // epoch — a miner becomes eligible only once the gap STRICTLY EXCEEDS it (gap == max_idle
        // is still within the grace window). With default max_idle=30, the first eligible gap is 31.
        assert!(idle_gap > max_idle, role_voting::e_not_idle_yet());

        // Insert into pool (enforces cooldown internally)
        role_voting::insert_into_revote_pool(vote_box, miner_id, current_epoch);

        role_voting_events::emit_revote_eligible_marked(miner_id, 1, current_role, current_epoch);
    }

    /// Mark a miner as eligible for re-vote due to composition imbalance.
    ///
    /// Permissionless: anyone can invoke this when the network role is in surplus.
    /// Condition: scarcity ratio for miner's current role < SCARCITY_FLOOR_BPS (500 bps).
    ///
    /// Scarcity semantics (from economic_layer): LOW ratio = surplus (many nodes of this role).
    /// A role below floor is over-supplied → composition shift needed.
    /// Aborts with E_COMPOSITION_NOT_IMBALANCED if the role is not in surplus.
    public fun mark_revote_eligible_composition_shift(
        net_reg:       &NetworkRegistry,
        vote_box:      &mut RoleVoteBox,
        miner_store:   &MinerStore,
        relay_reg:     &RelayRegistry,
        validator_reg: &ValidatorRegistry,
        cp_reg:        &ControlPlaneRegistry,
        signaling_reg: &SignalingRegistry,
        miner_id:      ID,
        ctx:           &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), role_voting::e_paused());
        assert!(miner_store::has_profile(miner_store, miner_id), role_voting::e_miner_not_found());

        let profile = miner_store::borrow_profile(miner_store, miner_id);
        let current_role = miner_store::profile_role(profile);
        let current_epoch = ctx.epoch();
        let floor = constants::scarcity_floor_bps();

        // Compute pre-clamping scarcity ratio for the miner's current role.
        //
        // We intentionally do NOT use get_scarcity_ratios (which clamps values to floor/ceiling)
        // because surplus roles are pinned exactly to floor after clamping — making `< floor`
        // always false. Instead, compute the raw normalized ratio directly from active counts.
        //
        // raw_weight_i = total / max(count_i, 1)  (inverse scarcity — lower count → higher weight)
        // pre_clamp_ratio_i = raw_weight_i * BASIS_POINTS / raw_total
        // Surplus condition: pre_clamp_ratio < floor → role has too many nodes relative to network.
        let relay_count = relay_registry::active_count(relay_reg);
        let validator_count = validator_registry::active_count(validator_reg);
        let cp_count = control_plane_registry::active_cp_count(cp_reg);
        let sig_count = signaling_registry::active_signaling_count(signaling_reg);
        let total = relay_count + validator_count + cp_count + sig_count;

        let bp = constants::basis_points();
        let role_pre_clamp_bps = if (total == 0) {
            // Empty network: treat as balanced (each role 25%)
            bp / 4
        } else {
            let role_count = if (current_role == constants::role_relay()) {
                relay_count
            } else if (current_role == constants::role_validator()) {
                validator_count
            } else if (current_role == constants::role_cp()) {
                cp_count
            } else {
                sig_count
            };
            let raw_relay = total / if (relay_count > 0) { relay_count } else { 1 };
            let raw_validator = total / if (validator_count > 0) { validator_count } else { 1 };
            let raw_cp = total / if (cp_count > 0) { cp_count } else { 1 };
            let raw_sig = total / if (sig_count > 0) { sig_count } else { 1 };
            let raw_total = raw_relay + raw_validator + raw_cp + raw_sig;

            let role_raw = total / if (role_count > 0) { role_count } else { 1 };
            if (raw_total == 0) { bp / 4 }
            else { role_raw * bp / raw_total }
        };

        // Surplus condition: raw scarcity ratio below floor → role has too many nodes relative to network
        assert!(role_pre_clamp_bps < floor, role_voting::e_composition_not_imbalanced());

        role_voting::insert_into_revote_pool(vote_box, miner_id, current_epoch);

        role_voting_events::emit_revote_eligible_marked(miner_id, 2, current_role, current_epoch);
    }

    /// Mark a miner as eligible for re-vote at the miner's own request.
    ///
    /// MinerCap-gated: only the miner's own operator can invoke this.
    /// No external condition beyond cooldown — miner always controls their own re-vote request.
    /// Aborts with E_INVALID_CAP_OWNER if ctx.sender() ≠ profile.owner (cap forgery check).
    public fun mark_revote_eligible_miner_request(
        net_reg:   &NetworkRegistry,
        vote_box:  &mut RoleVoteBox,
        miner_store: &MinerStore,
        cap:       &MinerCap,
        ctx:       &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), role_voting::e_paused());

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(miner_store::has_profile(miner_store, miner_id), role_voting::e_miner_not_found());

        let profile = miner_store::borrow_profile(miner_store, miner_id);
        let current_role = miner_store::profile_role(profile);
        // N1 (S63 QC): cap-forgery defense. MinerCap carries only `miner_id`, so holding a cap for
        // some miner_id is NOT proof of ownership — a forged/transferred cap could name any miner.
        // The authoritative owner is MinerProfile.owner (set at registration). Asserting
        // ctx.sender() == profile.owner ties the action to the on-chain operator, not cap possession.
        assert!(miner_store::profile_owner(profile) == ctx.sender(), role_voting::e_invalid_cap_owner());

        let current_epoch = ctx.epoch();
        role_voting::insert_into_revote_pool(vote_box, miner_id, current_epoch);

        role_voting_events::emit_revote_eligible_marked(miner_id, 3, current_role, current_epoch);
    }
}
