/// Role voting module — CPs collectively vote to assign roles to miners.
///
/// When enough CPs agree on a role for a miner (a flat 2/3-of-active-CP
/// supermajority quorum), the miner is assigned that role. Auto-registration
/// into the appropriate registry is triggered by the vote threshold being met.
///
/// Phase 1.2 additions (F47 REQ-RV-002):
///   - 3 mark_revote_eligible_* entry functions (idle / composition_shift / miner_request)
///   - Shared insert_into_revote_pool helper with cooldown enforcement
///   - RevoteEligibleMarked event struct (reason: 1=IDLE, 2=COMP_SHIFT, 3=MINER_REQUEST)
///   - RoleVoteBox extended with revote_cooldown_epochs + max_idle_epochs (Option A — governance-tunable)
///
/// Error code namespace: 700-719.
module dvconf::role_voting {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use sui::event;
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::caps::{Self, ControlPlaneCap, MinerCap};
    use dvconf::constants;
    use dvconf::cp_quorum_sig::{Self, QuorumSig, QuorumConfigState};

    // ── Errors (700-719) ──
    const E_PAUSED: u64              = 700;
    #[allow(unused_const)]
    const E_NOT_CP: u64              = 701;
    const E_MINER_NOT_FOUND: u64     = 702;
    const E_INVALID_ROLE: u64        = 703;
    const E_ALREADY_VOTED: u64       = 704;
    #[allow(unused_const)]
    const E_MINER_ALREADY_ACTIVE: u64 = 705;
    const E_CP_NOT_REGISTERED: u64   = 706;
    const E_NO_ASSIGNMENT: u64       = 707;
    const E_NOT_REVOTE_ELIGIBLE: u64 = 708;
    const E_COOLDOWN: u64            = 709;
    const E_NOT_IDLE_YET: u64        = 710;
    const E_PRIOR_ASSIGNMENT_PENDING: u64 = 711;
    /// Room guard (Q4) — DEFERRED to a follow-up phase (room_manager has no reverse
    /// miner→room lookup). Const reserved so the namespace stays contiguous.
    #[allow(unused_const)]
    const E_MINER_IN_ACTIVE_ROOM: u64 = 712;
    /// 713 (E_INSUFFICIENT_STAKE_FOR_ROLE) and 717 (E_STAKE_NOT_OWNED_BY_MINER) were the cast-side
    /// stake guards. RELOCATED to registration::apply_voted_role (D-S70-4 / OQ-PH13): cast is
    /// CP-signed and cannot reference a miner's owned StakePosition, so the checks now live on the
    /// MINER-signed apply path. Codes reserved here so the 700-719 namespace stays contiguous.
    const E_CP_REVOTE_REQUIRES_MIGRATION: u64 = 714;
    const E_COMPOSITION_NOT_IMBALANCED: u64 = 715;
    /// Miner self-request: ctx.sender() ≠ profile.owner — cap does not belong to caller.
    const E_INVALID_CAP_OWNER: u64  = 716;
    /// F47 Phase 1.4 (REQ-RV-004): CP-quorum aggregate signature failed to verify for a governance
    /// update (insufficient signers / bad sig / unregistered CP). D-S60-1 direct-gate abort.
    const E_GOVERNANCE_QUORUM_INSUFFICIENT: u64 = 718;
    /// F-MCP: an incoming role-vote whose role differs from the record's first-mover role.
    /// Only same-role votes accumulate toward the quorum ("≥required agree WHICH role").
    const E_ROLE_MISMATCH: u64 = 719;

    // ── Phase 1.2 governance defaults (Option A: stored on RoleVoteBox for CP-quorum mutability) ──
    /// Default idle threshold: 30 epochs (≈30 days on Sui mainnet at ~1 epoch/day).
    /// Matches Q2 decision: operators have 30-epoch recovery window before forced re-vote.
    const DEFAULT_MAX_IDLE_EPOCHS: u64 = 30;
    /// Default cooldown between successive marks: 14 epochs (≈14 days on Sui mainnet).
    /// Matches Q1 decision: 14-day anti-thrashing window.
    const DEFAULT_REVOTE_COOLDOWN_EPOCHS: u64 = 14;

    // ── Phase 1.4 governance action tags (first byte of the CP-quorum signed message) ──
    /// Action = mutate revote_cooldown_epochs.
    const ACTION_UPDATE_COOLDOWN: u8 = 1;
    /// Action = mutate max_idle_epochs.
    const ACTION_UPDATE_MAX_IDLE: u8 = 2;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    /// Shared object holding all pending role votes.
    public struct RoleVoteBox has key {
        id: UID,
        /// miner_id → RoleVoteRecord
        votes: Table<ID, RoleVoteRecord>,
        /// Quorum threshold in basis points (6667 = ≥2/3-of-active-CP supermajority)
        base_threshold_bps: u64,
        /// DORMANT: formerly the urgency multiplier that decayed the threshold for
        /// scarce roles. Scarcity-decay was removed; this field is retained only for
        /// storage-layout / upgrade compatibility and is no longer read by compute_threshold.
        urgency_decay_bps: u64,
        /// Tracks miner IDs with pending votes for iteration
        pending_miner_ids: VecSet<ID>,
        /// miner_id → assigned role (persists after vote cleanup for daemon consumption)
        assigned_roles: Table<ID, u8>,
        /// Miner IDs marked eligible for role re-vote (F47 REQ-RV-001).
        /// Populated by mark_revote_eligible_{idle,composition_shift,miner_request} entries (Phase 1.2+).
        revote_eligible: VecSet<ID>,
        /// Per-miner epoch when last marked eligible — for cooldown enforcement (F47 REQ-RV-001 + Q1).
        revote_eligible_since: Table<ID, u64>,
        /// Epochs of idle time before a miner is eligible for idle re-vote (F47 Q2, configurable via Phase 1.4).
        /// Default: DEFAULT_MAX_IDLE_EPOCHS (30). Stored here so Phase 1.4 CP-quorum entries can mutate it.
        max_idle_epochs: u64,
        /// Minimum epochs between successive revote marks per miner (F47 Q1, configurable via Phase 1.4).
        /// Default: DEFAULT_REVOTE_COOLDOWN_EPOCHS (14). Stored here for Phase 1.4 governance mutability.
        revote_cooldown_epochs: u64,
    }

    /// Read-only summary of a pending vote for devInspect.
    public struct PendingVoteInfo has store, copy, drop {
        miner_id:   ID,
        target_role: u8,
        vote_count: u64,
    }

    /// Per-miner vote accumulator.
    public struct RoleVoteRecord has store, drop {
        miner_id: ID,
        /// Target role being voted on
        role: u8,
        /// Addresses of CPs that voted for this role
        voters: vector<address>,
        /// Timestamp of first vote
        created_at: u64,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

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
    // INIT
    // ══════════════════════════════════════════════════════════

    fun init(ctx: &mut TxContext) {
        let vote_box = RoleVoteBox {
            id: object::new(ctx),
            votes: table::new(ctx),
            base_threshold_bps: 6_667,   // 2/3-of-active-CP quorum (honest flat threshold)
            urgency_decay_bps: 3_000,    // dormant: scarcity-decay removed, retained for storage-layout compat
            pending_miner_ids: vec_set::empty(),
            assigned_roles: table::new(ctx),
            revote_eligible: vec_set::empty(),
            revote_eligible_since: table::new(ctx),
            // Phase 1.2 — governance-tunable defaults (Q1 + Q2 decisions)
            max_idle_epochs: DEFAULT_MAX_IDLE_EPOCHS,
            revote_cooldown_epochs: DEFAULT_REVOTE_COOLDOWN_EPOCHS,
        };
        transfer::share_object(vote_box);
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// CP casts a vote for a miner to become a specific role.
    ///
    /// When the vote count meets the flat 2/3-of-active-CP quorum,
    /// a RoleAssigned event is emitted. The off-chain daemon then triggers
    /// actual registry enrollment via the miner's own transaction.
    public fun cast_role_vote(
        net_reg:       &NetworkRegistry,
        vote_box:      &mut RoleVoteBox,
        miner_store:   &MinerStore,
        cp_reg:        &ControlPlaneRegistry,
        // ABI-preserved: relay/validator/signaling registries are no longer read by the
        // flat 2/3-of-active-CP threshold, but the param list is kept intact (count/types/order)
        // because daemon PTB builders pass these objects positionally. Renaming is ABI-safe.
        _relay_reg:     &RelayRegistry,
        _validator_reg: &ValidatorRegistry,
        _signaling_reg: &SignalingRegistry,
        cap:           &ControlPlaneCap,
        miner_id:      ID,
        role:          u8,
        ctx:           &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        // Verify caller is a registered CP
        let cp_miner_id = caps::cp_cap_miner_id(cap);
        assert!(
            control_plane_registry::is_registered(cp_reg, cp_miner_id),
            E_CP_NOT_REGISTERED,
        );

        // Verify miner exists
        assert!(miner_store::has_profile(miner_store, miner_id), E_MINER_NOT_FOUND);

        // Verify role is valid (relay=2, validator=1, cp=3, signaling=4)
        assert!(
            role == constants::role_relay() ||
            role == constants::role_validator() ||
            role == constants::role_cp() ||
            role == constants::role_signaling(),
            E_INVALID_ROLE,
        );

        // ── F47 Phase 1.3 — REQ-RV-003 re-vote guards (ADR-0008 Q3/Q5 cast-side) ──
        // Snapshot the miner's current on-chain role. Initial votes have current_role == USER;
        // re-votes have a non-USER role and must satisfy the re-vote pool + transition guards.
        let current_role = miner_store::profile_role(miner_store::borrow_profile(miner_store, miner_id));

        // Guard 1 — re-vote pool membership: a non-USER miner may only be re-voted if it has
        // been marked eligible (idle / composition shift / self-request). Initial votes skip this.
        if (current_role != constants::role_user()) {
            assert!(vec_set::contains(&vote_box.revote_eligible, &miner_id), E_NOT_REVOTE_ELIGIBLE);
        };

        // CP-partial (ADR-0008 Q5, cast-side): CP↔non-CP transitions are deferred to the
        // canonical unregister+register migration path. Only fires on RE-votes (current_role
        // != USER); an initial vote INTO CP (current_role == USER) is unaffected.
        if (current_role != constants::role_user()
            && (current_role == constants::role_cp() || role == constants::role_cp())) {
            abort E_CP_REVOTE_REQUIRES_MIGRATION
        };

        // ── Stake guards relocated to apply_voted_role (D-S70-4 / OQ-PH13) ──
        // The cast-side stake binding + surplus checks were MOVED to registration::apply_voted_role.
        // Rationale: cast_role_vote is CP-signed (cap: &ControlPlaneCap), but on Sui a CP-signed TX
        // CANNOT reference a miner's OWNED StakePosition ("Object owned by A, but signer is B").
        // So a `stake: &StakePosition` param here was un-callable on a real network. apply_voted_role
        // is MINER-signed and already takes &mut StakePosition, so the binding (E_STAKE_NOT_OWNED_BY_MINER
        // = 717) + threshold (E_INSUFFICIENT_STAKE_FOR_ROLE = 713) guards live there now.

        // Guard 4 — pending: a miner with an unconsumed assignment cannot start a new campaign.
        assert!(!table::contains(&vote_box.assigned_roles, miner_id), E_PRIOR_ASSIGNMENT_PENDING);

        let voter = ctx.sender();

        // Snapshot active-CP count before mutable borrow of votes table.
        // Threshold is now a flat 2/3-of-active-CP quorum (no scarcity inputs).
        let cp_count = control_plane_registry::active_cp_count(cp_reg);

        let required = compute_threshold(vote_box, cp_count);

        // Create vote record if first vote for this miner
        if (!table::contains(&vote_box.votes, miner_id)) {
            table::add(&mut vote_box.votes, miner_id, RoleVoteRecord {
                miner_id,
                role,
                voters: vector::empty(),
                created_at: ctx.epoch(),
            });
            vec_set::insert(&mut vote_box.pending_miner_ids, miner_id);
        };

        let record = table::borrow_mut(&mut vote_box.votes, miner_id);

        // Outcome guard: only votes matching the record's (first-mover) role count.
        // First vote trivially matches (record.role was just set to `role`); later
        // off-role votes abort so they cannot be silently tallied into another role.
        assert!(role == record.role, E_ROLE_MISMATCH);

        // Check no duplicate vote from this CP
        let num_voters = record.voters.length();
        let mut i = 0;
        while (i < num_voters) {
            assert!(record.voters[i] != voter, E_ALREADY_VOTED);
            i = i + 1;
        };

        // Add vote
        record.voters.push_back(voter);
        let current_votes = record.voters.length();

        event::emit(RoleVoteCast {
            miner_id,
            role,
            voter,
            current_votes,
            required,
        });

        // Check if threshold met — drop mutable borrow first
        if (current_votes >= required) {
            event::emit(RoleAssigned {
                miner_id,
                role,
                vote_count: current_votes,
                threshold: required,
            });
        };

        // Clean up vote record if threshold met (separate borrow scope)
        if (current_votes >= required) {
            let _removed = table::remove(&mut vote_box.votes, miner_id);
            if (vec_set::contains(&vote_box.pending_miner_ids, &miner_id)) {
                vec_set::remove(&mut vote_box.pending_miner_ids, &miner_id);
            };
            // F47 Phase 1.3 — the campaign succeeded, so the miner exits the re-vote pool.
            // Removing the eligibility mark + its cooldown timestamp keeps the pool consistent
            // (it was either seeded by a mark_* entry on a re-vote, or absent on an initial vote).
            if (vec_set::contains(&vote_box.revote_eligible, &miner_id)) {
                vec_set::remove(&mut vote_box.revote_eligible, &miner_id);
            };
            if (table::contains(&vote_box.revote_eligible_since, miner_id)) {
                table::remove(&mut vote_box.revote_eligible_since, miner_id);
            };
            // Persist assignment for daemon consumption via apply_voted_role
            table::add(&mut vote_box.assigned_roles, miner_id, role);
        };
    }

    // ── F47 Phase 1.2 — REQ-RV-002: mark_revote_eligible_* entries ──

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
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(miner_store::has_profile(miner_store, miner_id), E_MINER_NOT_FOUND);

        let profile = miner_store::borrow_profile(miner_store, miner_id);
        let current_role = miner_store::profile_role(profile);
        let current_epoch = ctx.epoch();
        let max_idle = vote_box.max_idle_epochs;

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
        assert!(idle_gap > max_idle, E_NOT_IDLE_YET);

        // Insert into pool (enforces cooldown internally)
        insert_into_revote_pool(vote_box, miner_id, current_epoch);

        event::emit(RevoteEligibleMarked {
            miner_id,
            reason: 1, // IDLE
            current_role,
            marked_at: current_epoch,
        });
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
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(miner_store::has_profile(miner_store, miner_id), E_MINER_NOT_FOUND);

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
        assert!(role_pre_clamp_bps < floor, E_COMPOSITION_NOT_IMBALANCED);

        insert_into_revote_pool(vote_box, miner_id, current_epoch);

        event::emit(RevoteEligibleMarked {
            miner_id,
            reason: 2, // COMPOSITION_SHIFT
            current_role,
            marked_at: current_epoch,
        });
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
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(miner_store::has_profile(miner_store, miner_id), E_MINER_NOT_FOUND);

        let profile = miner_store::borrow_profile(miner_store, miner_id);
        let current_role = miner_store::profile_role(profile);
        // N1 (S63 QC): cap-forgery defense. MinerCap carries only `miner_id`, so holding a cap for
        // some miner_id is NOT proof of ownership — a forged/transferred cap could name any miner.
        // The authoritative owner is MinerProfile.owner (set at registration). Asserting
        // ctx.sender() == profile.owner ties the action to the on-chain operator, not cap possession.
        assert!(miner_store::profile_owner(profile) == ctx.sender(), E_INVALID_CAP_OWNER);

        let current_epoch = ctx.epoch();
        insert_into_revote_pool(vote_box, miner_id, current_epoch);

        event::emit(RevoteEligibleMarked {
            miner_id,
            reason: 3, // MINER_REQUEST
            current_role,
            marked_at: current_epoch,
        });
    }

    // ══════════════════════════════════════════════════════════
    // GOVERNANCE (F47 Phase 1.4 — REQ-RV-004, D-S60-1: CP-quorum direct gate, no AdminCap shim)
    // ══════════════════════════════════════════════════════════

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
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let msg = build_governance_msg(ACTION_UPDATE_COOLDOWN, new_value, nonce, epoch);
        let quorum_ok = cp_quorum_sig::verify_quorum(
            net_reg, cp_reg, quorum_state, &qs, signer_pubkeys, &msg,
        );
        assert!(quorum_ok, E_GOVERNANCE_QUORUM_INSUFFICIENT);

        let old_value = vote_box.revote_cooldown_epochs;
        vote_box.revote_cooldown_epochs = new_value;

        event::emit(CooldownConfigUpdated { old_value, new_value, updater: ctx.sender() });
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
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let msg = build_governance_msg(ACTION_UPDATE_MAX_IDLE, new_value, nonce, epoch);
        let quorum_ok = cp_quorum_sig::verify_quorum(
            net_reg, cp_reg, quorum_state, &qs, signer_pubkeys, &msg,
        );
        assert!(quorum_ok, E_GOVERNANCE_QUORUM_INSUFFICIENT);

        let old_value = vote_box.max_idle_epochs;
        vote_box.max_idle_epochs = new_value;

        event::emit(MaxIdleConfigUpdated { old_value, new_value, updater: ctx.sender() });
    }

    // ══════════════════════════════════════════════════════════
    // INTERNAL FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Insert a miner into the revote-eligible pool, enforcing the cooldown window.
    ///
    /// Cooldown enforcement: if the miner already has a `revote_eligible_since` entry,
    /// the current epoch must be >= last_marked + revote_cooldown_epochs. This prevents
    /// thrashing (Q1: 14-day cooldown between successive marks).
    ///
    /// Idempotent pool insert: if the miner is already in `revote_eligible`, the epoch
    /// is updated but no duplicate VecSet insert is attempted.
    fun insert_into_revote_pool(
        box:           &mut RoleVoteBox,
        miner_id:      ID,
        current_epoch: u64,
    ) {
        // Cooldown check: if previously marked, enforce minimum gap
        if (table::contains(&box.revote_eligible_since, miner_id)) {
            let last_marked = *table::borrow(&box.revote_eligible_since, miner_id);
            assert!(
                current_epoch >= last_marked + box.revote_cooldown_epochs,
                E_COOLDOWN,
            );
            // Update the epoch timestamp to the new mark time
            *table::borrow_mut(&mut box.revote_eligible_since, miner_id) = current_epoch;
        } else {
            // First mark: create a fresh entry
            table::add(&mut box.revote_eligible_since, miner_id, current_epoch);
        };

        // Idempotent insert into the eligible set
        if (!vec_set::contains(&box.revote_eligible, &miner_id)) {
            vec_set::insert(&mut box.revote_eligible, miner_id);
        };
    }

    /// Serialize a u64 as 8 little-endian bytes (BCS u64 encoding). Used by build_governance_msg
    /// to construct the canonical CP-quorum message; kept inline (no std::bcs dep) to mirror the
    /// sibling room_capability module's hand-rolled style and keep the byte layout self-evident.
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

    /// Required votes = ceil(active_cp_count * base_threshold_bps / 10000), floor 1.
    /// Honest 2/3-of-active-CP quorum (base init'd to 6667). N1->1, N3->3, N4->3, N5->4.
    /// Because base=6667 rounds UP via ceil, this is a STRICT >2/3 supermajority:
    /// N=3 => 3 (unanimous), N=4 => 3, N=5 => 4 (matches test_threshold_flat_two_thirds_n5).
    /// `urgency_decay_bps` is retained on the struct for storage-layout/test compatibility
    /// but is NO LONGER read here (scarcity-decay removed -- it floored the threshold to 1).
    fun compute_threshold(vote_box: &RoleVoteBox, active_cp_count: u64): u64 {
        let bp = constants::basis_points();
        let required = (active_cp_count * vote_box.base_threshold_bps + bp - 1) / bp;
        if (required < 1) { 1 } else { required }
    }

    #[test_only]
    public fun compute_threshold_for_testing(vb: &RoleVoteBox, active_cp_count: u64): u64 {
        compute_threshold(vb, active_cp_count)
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Consume a voted role assignment. Called by registration::apply_voted_role.
    /// Removes the assignment so it can only be consumed once.
    public(package) fun consume_assignment(vote_box: &mut RoleVoteBox, miner_id: ID): u8 {
        assert!(table::contains(&vote_box.assigned_roles, miner_id), E_NO_ASSIGNMENT);
        table::remove(&mut vote_box.assigned_roles, miner_id)
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun base_threshold_bps(vb: &RoleVoteBox): u64 { vb.base_threshold_bps }
    public fun urgency_decay_bps(vb: &RoleVoteBox): u64  { vb.urgency_decay_bps }

    /// F47 Phase 1.4 — current governance-tunable thresholds (mutated by the CP-quorum entries).
    public fun max_idle_epochs(vb: &RoleVoteBox): u64 { vb.max_idle_epochs }
    public fun revote_cooldown_epochs(vb: &RoleVoteBox): u64 { vb.revote_cooldown_epochs }

    public fun has_votes(vb: &RoleVoteBox, miner_id: ID): bool {
        table::contains(&vb.votes, miner_id)
    }

    public fun vote_count(vb: &RoleVoteBox, miner_id: ID): u64 {
        if (!table::contains(&vb.votes, miner_id)) return 0;
        let record = table::borrow(&vb.votes, miner_id);
        record.voters.length()
    }

    public fun vote_role(vb: &RoleVoteBox, miner_id: ID): u8 {
        let record = table::borrow(&vb.votes, miner_id);
        record.role
    }

    /// Check if a miner has a voted role assignment ready to consume.
    public fun get_assigned_role(vote_box: &RoleVoteBox, miner_id: ID): Option<u8> {
        if (table::contains(&vote_box.assigned_roles, miner_id)) {
            option::some(*table::borrow(&vote_box.assigned_roles, miner_id))
        } else {
            option::none()
        }
    }

    /// Returns all pending votes for devInspect batch-fetch.
    /// Cost: O(n) where n = pending vote count. Acceptable for < 100 pending.
    public fun get_pending_votes(vb: &RoleVoteBox): vector<PendingVoteInfo> {
        let ids = vec_set::keys(&vb.pending_miner_ids);
        let mut result = vector::empty<PendingVoteInfo>();
        let mut i = 0;
        let len = ids.length();
        while (i < len) {
            let id = *ids.borrow(i);
            if (table::contains(&vb.votes, id)) {
                let record = table::borrow(&vb.votes, id);
                result.push_back(PendingVoteInfo {
                    miner_id: record.miner_id,
                    target_role: record.role,
                    vote_count: record.voters.length(),
                });
            };
            i = i + 1;
        };
        result
    }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        init(ctx);
    }

    #[test_only]
    public fun create_vote_box_for_testing(
        base_threshold_bps: u64,
        urgency_decay_bps: u64,
        ctx: &mut TxContext,
    ): RoleVoteBox {
        RoleVoteBox {
            id: object::new(ctx),
            votes: table::new(ctx),
            base_threshold_bps,
            urgency_decay_bps,
            pending_miner_ids: vec_set::empty(),
            assigned_roles: table::new(ctx),
            revote_eligible: vec_set::empty(),
            revote_eligible_since: table::new(ctx),
            // Phase 1.2: include governance defaults in test box
            max_idle_epochs: DEFAULT_MAX_IDLE_EPOCHS,
            revote_cooldown_epochs: DEFAULT_REVOTE_COOLDOWN_EPOCHS,
        }
    }

    #[test_only]
    public fun share_vote_box_for_testing(vb: RoleVoteBox) {
        transfer::share_object(vb);
    }

    #[test_only]
    public fun destroy_vote_box_for_testing(vb: RoleVoteBox) {
        let RoleVoteBox {
            id,
            votes,
            base_threshold_bps: _,
            urgency_decay_bps: _,
            pending_miner_ids: _,
            assigned_roles,
            revote_eligible: _,
            revote_eligible_since,
            max_idle_epochs: _,
            revote_cooldown_epochs: _,
        } = vb;
        table::destroy_empty(votes);
        table::destroy_empty(assigned_roles);
        table::destroy_empty(revote_eligible_since);
        object::delete(id);
    }

    // ── F47 Phase 1.1 helpers — REQ-RV-001 verification ──

    #[test_only]
    public fun revote_eligible_is_empty(box: &RoleVoteBox): bool {
        vec_set::is_empty(&box.revote_eligible)
    }

    #[test_only]
    public fun revote_eligible_since_is_empty(box: &RoleVoteBox): bool {
        table::is_empty(&box.revote_eligible_since)
    }

    // ── F47 Phase 1.2 helpers — REQ-RV-002 verification ──

    /// Returns true if `miner_id` is currently in the revote-eligible pool.
    #[test_only]
    public fun is_revote_eligible(box: &RoleVoteBox, miner_id: ID): bool {
        vec_set::contains(&box.revote_eligible, &miner_id)
    }

    /// Returns the epoch when `miner_id` was last marked eligible.
    /// Aborts if miner_id has never been marked (use is_revote_eligible check first).
    #[test_only]
    public fun revote_eligible_since_epoch(box: &RoleVoteBox, miner_id: ID): u64 {
        *table::borrow(&box.revote_eligible_since, miner_id)
    }

    // ── F47 Phase 1.5 helper — REQ-RV-005 apply_voted_role test scaffolding ──

    /// Directly seed a role assignment so apply_voted_role tests can exercise the
    /// consume path in isolation, without driving a full cast_role_vote quorum to
    /// threshold. Mirrors the threshold-met `assigned_roles` insert (see line ~335).
    #[test_only]
    public fun add_assignment_for_testing(box: &mut RoleVoteBox, miner_id: ID, role: u8) {
        table::add(&mut box.assigned_roles, miner_id, role);
    }

    // ── F47 Phase 1.6 (REQ-RV-007) — RevoteEligibleMarked schema-lock anchor ──
    //
    // Test-only constructor (mirrors add_assignment_for_testing's intent). Names
    // every field so a RENAME or REMOVAL breaks the events-test build before ship
    // (ADR-0008 schema lock); a pure REORDER still compiles (name-bound shorthand)
    // and is caught instead by that test's BCS peel. It also lets the test
    // BCS-serialize the exact wire layout the cp-daemon revote-watcher / F66 viz
    // consumers decode. Not used by any production path.
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
