/// Role voting module — CPs collectively vote to assign roles to miners.
///
/// When enough CPs agree on a role for a miner (a flat 2/3-of-active-CP
/// supermajority quorum), the miner is assigned that role. Auto-registration
/// into the appropriate registry is triggered by the vote threshold being met.
///
/// Re-vote eligibility entries and CP-quorum governance entries live in the
/// `role_voting_revote` / `role_voting_governance` satellites (RoleVoteBox field access is
/// declaring-module-only in Move, so satellites call back into this module's
/// public(package) mutators/accessors — see insert_into_revote_pool, set_*_epochs, e_*()).
///
/// Package split (dvconf_role_voting, depends on dvconf_contracts): `apply_voted_role`
/// (dvconf::registration, package A) can no longer call `consume_assignment` directly
/// (public(package) does not cross a package boundary) -- callers now issue a 2-command
/// PTB: `consume_voted_assignment` here first, then `registration::apply_voted_role(new_role, ...)`
/// with the returned u8 chained in as an argument. Both commands still execute atomically
/// within the same Sui transaction.
///
/// Error code namespace: 700-719.
module dvconf_role_voting::role_voting {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use dvconf_role_voting::role_voting_events;
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::RelayRegistry;
    use dvconf::validator_registry::ValidatorRegistry;
    use dvconf::signaling_registry::SignalingRegistry;
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::caps::{Self, ControlPlaneCap, MinerCap};
    use dvconf::constants;

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
    /// Room guard (Q4) — DEFERRED (room_manager has no reverse miner→room lookup).
    #[allow(unused_const)]
    const E_MINER_IN_ACTIVE_ROOM: u64 = 712;
    /// 713/717 were cast-side stake guards, RELOCATED to registration::apply_voted_role
    /// (D-S70-4 / OQ-PH13): cast is CP-signed and cannot reference a miner's owned StakePosition.
    const E_CP_REVOTE_REQUIRES_MIGRATION: u64 = 714;
    const E_COMPOSITION_NOT_IMBALANCED: u64 = 715;
    /// Miner self-request: ctx.sender() ≠ profile.owner — cap does not belong to caller.
    const E_INVALID_CAP_OWNER: u64  = 716;
    /// F47 REQ-RV-004: CP-quorum aggregate signature failed to verify for a governance update.
    const E_GOVERNANCE_QUORUM_INSUFFICIENT: u64 = 718;
    /// F-MCP: an incoming role-vote whose role differs from the record's first-mover role.
    const E_ROLE_MISMATCH: u64 = 719;

    // ── Phase 1.2 governance defaults (stored on RoleVoteBox for CP-quorum mutability) ──
    /// Default idle threshold: 30 epochs (Q2: 30-epoch recovery window before forced re-vote).
    const DEFAULT_MAX_IDLE_EPOCHS: u64 = 30;
    /// Default cooldown between successive marks: 14 epochs (Q1: anti-thrashing window).
    const DEFAULT_REVOTE_COOLDOWN_EPOCHS: u64 = 14;

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
        /// DORMANT: scarcity-decay was removed; retained only for storage-layout compat.
        urgency_decay_bps: u64,
        /// Tracks miner IDs with pending votes for iteration
        pending_miner_ids: VecSet<ID>,
        /// miner_id → assigned role (persists after vote cleanup for daemon consumption)
        assigned_roles: Table<ID, u8>,
        /// Miner IDs marked eligible for role re-vote (F47 REQ-RV-001).
        revote_eligible: VecSet<ID>,
        /// Per-miner epoch when last marked eligible — for cooldown enforcement (F47 Q1).
        revote_eligible_since: Table<ID, u64>,
        /// Idle-epoch threshold before re-vote eligible (F47 Q2, governance-tunable via Phase 1.4).
        max_idle_epochs: u64,
        /// Minimum epochs between successive revote marks (F47 Q1, governance-tunable via Phase 1.4).
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
        // ABI-preserved (unread by the flat threshold; daemon PTB builders pass these positionally).
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

        // F47 REQ-RV-003 re-vote guards (ADR-0008 Q3/Q5). Initial votes have current_role == USER.
        let current_role = miner_store::profile_role(miner_store::borrow_profile(miner_store, miner_id));

        // Guard 1 — re-vote pool membership: a non-USER miner may only be re-voted if marked eligible.
        if (current_role != constants::role_user()) {
            assert!(vec_set::contains(&vote_box.revote_eligible, &miner_id), E_NOT_REVOTE_ELIGIBLE);
        };

        // CP-partial (ADR-0008 Q5): CP<->non-CP transitions defer to unregister+register migration.
        if (current_role != constants::role_user()
            && (current_role == constants::role_cp() || role == constants::role_cp())) {
            abort E_CP_REVOTE_REQUIRES_MIGRATION
        };

        // Stake guards (D-S70-4 / OQ-PH13): relocated to registration::apply_voted_role, since
        // cast_role_vote is CP-signed and cannot reference a miner's owned StakePosition.

        // Guard 4 — pending: a miner with an unconsumed assignment cannot start a new campaign.
        assert!(!table::contains(&vote_box.assigned_roles, miner_id), E_PRIOR_ASSIGNMENT_PENDING);

        let voter = ctx.sender();

        // Snapshot active-CP count before mutable borrow of votes table.
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

        role_voting_events::emit_role_vote_cast(miner_id, role, voter, current_votes, required);

        // Check if threshold met — drop mutable borrow first
        if (current_votes >= required) {
            role_voting_events::emit_role_assigned(miner_id, role, current_votes, required);
        };

        // Clean up vote record if threshold met (separate borrow scope)
        if (current_votes >= required) {
            let _removed = table::remove(&mut vote_box.votes, miner_id);
            if (vec_set::contains(&vote_box.pending_miner_ids, &miner_id)) {
                vec_set::remove(&mut vote_box.pending_miner_ids, &miner_id);
            };
            // Campaign succeeded — miner exits the re-vote pool (mark + cooldown timestamp cleared).
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
    ///
    /// public(package): called from the role_voting_revote satellite's mark_revote_eligible_*
    /// entries, which cannot mutate RoleVoteBox fields directly (Move field-access is
    /// declaring-module-only). Shares the parent's error namespace — see E_COOLDOWN (709).
    public(package) fun insert_into_revote_pool(
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

    /// Consume a voted role assignment. Removes the assignment so it can only be consumed once.
    /// Package-private -- used internally by `consume_voted_assignment` below. Kept distinct
    /// (not just inlined) since it's still the natural extension point for any future in-package
    /// caller that already holds a `&mut RoleVoteBox` and a miner_id without a MinerCap in hand.
    public(package) fun consume_assignment(vote_box: &mut RoleVoteBox, miner_id: ID): u8 {
        assert!(table::contains(&vote_box.assigned_roles, miner_id), E_NO_ASSIGNMENT);
        table::remove(&mut vote_box.assigned_roles, miner_id)
    }

    /// Externally-callable variant of `consume_assignment`, for the daemon to invoke as the FIRST
    /// command of a 2-command PTB whose second command is `registration::apply_voted_role(new_role, ...)`
    /// (package A) -- `consume_assignment` itself stays `public(package)` (this package only);
    /// `registration.move` can no longer call it directly post-split, so callers chain these two
    /// ordinary moveCalls in one PTB instead. Still one atomic Sui transaction, same as before.
    public fun consume_voted_assignment(vote_box: &mut RoleVoteBox, cap: &MinerCap): u8 {
        consume_assignment(vote_box, caps::miner_cap_miner_id(cap))
    }

    /// Set the re-vote cooldown window; returns the old value. Called by the
    /// role_voting_governance satellite AFTER its own CP-quorum-signature check passes —
    /// this function performs no gating itself, so callers must not expose it unguarded.
    public(package) fun set_revote_cooldown_epochs(vb: &mut RoleVoteBox, new_value: u64): u64 {
        let old_value = vb.revote_cooldown_epochs;
        vb.revote_cooldown_epochs = new_value;
        old_value
    }

    /// Set the idle-epoch threshold; returns the old value. Same gating contract as
    /// set_revote_cooldown_epochs — caller (role_voting_governance) must have already
    /// verified the CP-quorum signature before invoking this.
    public(package) fun set_max_idle_epochs(vb: &mut RoleVoteBox, new_value: u64): u64 {
        let old_value = vb.max_idle_epochs;
        vb.max_idle_epochs = new_value;
        old_value
    }

    // ── Error accessors (shared parent namespace — satellites call these, never mint new consts) ──
    public(package) fun e_paused(): u64 { E_PAUSED }
    public(package) fun e_miner_not_found(): u64 { E_MINER_NOT_FOUND }
    public(package) fun e_not_idle_yet(): u64 { E_NOT_IDLE_YET }
    public(package) fun e_composition_not_imbalanced(): u64 { E_COMPOSITION_NOT_IMBALANCED }
    public(package) fun e_invalid_cap_owner(): u64 { E_INVALID_CAP_OWNER }
    public(package) fun e_governance_quorum_insufficient(): u64 { E_GOVERNANCE_QUORUM_INSUFFICIENT }

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

    // ── F47 REQ-RV-001/002 verification helpers ──

    #[test_only]
    public fun revote_eligible_is_empty(box: &RoleVoteBox): bool {
        vec_set::is_empty(&box.revote_eligible)
    }

    #[test_only]
    public fun revote_eligible_since_is_empty(box: &RoleVoteBox): bool {
        table::is_empty(&box.revote_eligible_since)
    }

    #[test_only]
    public fun is_revote_eligible(box: &RoleVoteBox, miner_id: ID): bool {
        vec_set::contains(&box.revote_eligible, &miner_id)
    }

    /// Aborts if miner_id has never been marked (use is_revote_eligible check first).
    #[test_only]
    public fun revote_eligible_since_epoch(box: &RoleVoteBox, miner_id: ID): u64 {
        *table::borrow(&box.revote_eligible_since, miner_id)
    }

    /// Directly seed a role assignment so apply_voted_role tests can exercise the consume
    /// path without driving a full cast_role_vote quorum to threshold.
    #[test_only]
    public fun add_assignment_for_testing(box: &mut RoleVoteBox, miner_id: ID, role: u8) {
        table::add(&mut box.assigned_roles, miner_id, role);
    }
}
