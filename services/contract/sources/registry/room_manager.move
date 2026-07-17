/// Room manager — creates and manages conference rooms.
///
/// Room creators must be registered users. Rooms have a lifecycle status
/// (PENDING → READY → ACTIVE → CLOSED) managed by package functions in Phase 3.
///
/// CP Voting (Phase 17): CPs submit relay ballots; contract uses appearance-count
/// consensus to assign multiple relays per room.
module dvconf::room_manager {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use sui::event;
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::user_registry::{Self, UserRegistry};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::pairing_score;

    // ── Errors (500-509) ──
    const E_PAUSED: u64              = 500;
    const E_NOT_CREATOR: u64         = 501;
    const E_NOT_FOUND: u64           = 502;
    const E_ALREADY_CLOSED: u64      = 503;
    const E_INVALID_MODE: u64        = 504;
    const E_INVALID_MIN: u64         = 505;
    const E_USER_NOT_REGISTERED: u64 = 506;
    const E_DUPLICATE_VOTE: u64      = 507;
    const E_NOT_PENDING: u64         = 508;
    const E_INVALID_BALLOT: u64      = 509;

    const E_NOT_ROOM_CREATOR: u64       = 550;
    const E_COOLDOWN_NOT_MET: u64       = 551;
    const E_INSUFFICIENT_PROPOSALS: u64 = 552;

    // ── Failover errors (560-569, ADR-0004) ──
    const E_NO_STANDBY: u64              = 560;
    const E_STANDBY_NOT_REGISTERED: u64  = 561;
    const E_PRIMARY_NOT_ASSIGNED: u64    = 562;
    const E_SAME_RELAY: u64              = 563;

    // ── Relay overlap errors (564-569, ADR-0009 / RO-003) ──
    const E_RELAY_NOT_STALE: u64         = 564; // primary's last_heartbeat gap <= MAX_HEARTBEAT_EPOCHS

    // ── Relay-mesh-scaling spill-authorization errors (565-567, REQ-RMS-009) ──
    // FRESH codes — do NOT reuse 561 E_STANDBY_NOT_REGISTERED (that names the F1
    // STANDBY-relay check; a spill relay is a distinct concept, so it gets its own).
    const E_CP_NOT_REGISTERED: u64        = 565; // ControlPlaneCap's cp_id not in ControlPlaneRegistry
    const E_RELAY_ALREADY_ASSIGNED: u64   = 566; // spill relay already in assigned_relays (no dup)
    const E_SPILL_RELAY_NOT_REGISTERED: u64 = 567; // spill relay not in RelayRegistry

    // ── Relay overlap constants (ADR-0009) ──
    /// Epochs of missed heartbeat after which a primary is considered stale.
    /// Matches Layer C threshold in RelayHeartbeatWatcher (cp-daemon).
    const MAX_HEARTBEAT_EPOCHS: u64      = 3;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    public struct RoomInfo has store, copy, drop {
        creator:                address,
        status:                 u8,
        relay_mode:             u8,
        created_at:             u64,
        closed_at:              u64,  // 0 if not closed
        assigned_relays:        vector<ID>,
        assigned_signaling:     Option<ID>,
        assigned_cp:            Option<ID>,
        expected_participants:  u64,
        assigned_validators:    vector<ID>,
        verified_score:         u64,  // NEW: score from winning PVR proposal (0 = not yet assigned)
        consensus_reached:      bool, // NEW: true if assigned via PVR consensus, false if admin fallback
        standby_relay_id:       Option<ID>, // ADR-0004: pre-selected warm standby (N=1), none until set_standby_relay
    }

    public struct RoomRules has store, copy, drop {
        min_relay:     u64,
        min_cp:        u64,
        min_validator: u64,
    }

    public struct PairingProposal has store, copy, drop {
        cp_id:           ID,
        relay_ids:       vector<ID>,
        validator_ids:   vector<ID>,
        signaling_id:    ID,
        submitted_score: u64,  // renamed from verified_score; score computed at submission time
    }

    public struct RoomManager has key {
        id: UID,
        rooms:          Table<ID, RoomInfo>,
        active_count:   u64,
        room_rules:     RoomRules,
        room_proposals: Table<ID, vector<PairingProposal>>,
        active_room_ids: VecSet<ID>,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct RoomCreated has copy, drop {
        room_id:         ID,
        creator:         address,
        relay_mode:      u8,
        room_class_hint: u8,  // NEW (REQ-RMS-016): 0=small,1=webinar,2=large — creator hint for L_r seeding, off-chain consumed
    }

    public struct RoomClosed has copy, drop {
        room_id:   ID,
        closed_by: address,
        epoch:     u64,
    }

    public struct RoomRulesUpdated has copy, drop {
        min_relay:     u64,
        min_cp:        u64,
        min_validator: u64,
    }

    public struct RoomAssigned has copy, drop {
        room_id:           ID,
        relay_ids:         vector<ID>,
        signaling_id:      ID,
        relay_mode:        u8,
        verified_score:    u64,   // NEW: score of winning proposal (0 for admin fallback)
        consensus_reached: bool,  // NEW: true if via PVR, false if admin fallback
        winning_cp:        ID,    // NEW: CP that won the PVR vote (zero ID for admin fallback)
        validator_ids:     vector<ID>,
    }

    #[allow(unused_field)]
    public struct VoteSubmitted has copy, drop {
        room_id:     ID,
        cp_id:       ID,
        relay_count: u64,
    }

    #[allow(unused_field)]
    public struct VoteReset has copy, drop {
        room_id: ID,
    }

    public struct ProposalSubmitted has copy, drop {
        room_id:         ID,
        cp_id:           ID,
        verified_score:  u64,
        relay_count:     u64,
        validator_count: u64,
    }

    public struct ProposerRewarded has copy, drop {
        room_id: ID,
        cp_id:   ID,
        reward:  u64,
    }

    // ── Failover events (ADR-0004) ──

    /// Bootstrap record of warm-standby binding for a room.
    public struct RoomCreatedWithStandby has copy, drop {
        room_id:           ID,
        primary_relay:     ID,
        standby_relay:     ID,
        rtp_params_hash:   vector<u8>,
        mcu_config_hash:   vector<u8>,
        epoch:             u64,
    }

    /// Failover trigger record. `trigger` is one of: 0=chain-slash, 1=heartbeat-miss, 2=performance-degraded.
    public struct RelayFailoverInitiated has copy, drop {
        room_id:        ID,
        primary_relay:  ID,
        standby_relay:  ID,
        trigger:        u8,
        epoch:          u64,
    }

    /// Post-swap canonical record — primary has been replaced; clients hard-cut.
    public struct RelaySwapped has copy, drop {
        room_id:                  ID,
        old_relay:                ID,
        new_relay:                ID,
        new_turn_creds_required:  bool,
        epoch:                    u64,
    }

    /// Emitted when a pre-selected standby is itself unavailable and the CP picks a fresh one.
    public struct StandbyRelayReplaced has copy, drop {
        room_id:      ID,
        old_standby:  ID,
        new_standby:  ID,
        epoch:        u64,
    }

    // ── Relay overlap events (ADR-0009 / RO-003) ──

    /// Emitted when CP-daemon detects relay heartbeat miss and promotes standby to primary.
    /// Schema locked under ADR-0009. Additive — no existing event is modified.
    /// Co-located with RoomAssigned (room_id context) and assigned_relays (role tracking).
    /// Owner: room_manager.move (D-RO-2).
    public struct RelayPromoted has copy, drop {
        room_id:     ID,  // ID of the room whose primary relay changed
        old_primary: ID,  // relay node ID that was primary (now replaced)
        new_primary: ID,  // relay node ID that was standby (now promoted to primary)
        epoch:       u64, // Sui epoch at time of promotion (ctx.epoch())
    }

    /// REQ-RMS-009 — emitted when CP-quorum authorizes a spill relay APPENDED to a
    /// room's assigned_relays (additive cascade growth; NOT a primary swap).
    public struct RelaySpillAuthorized has copy, drop {
        room_id:     ID,
        spill_relay: ID,  // relay node ID appended to assigned_relays
        authorized_by: ID, // cp_id of the authorizing ControlPlaneCap
        relay_count: u64,  // assigned_relays length AFTER the append
        epoch:       u64,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    public fun create(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(RoomManager {
            id: object::new(ctx),
            rooms: table::new(ctx),
            active_count: 0,
            room_rules: RoomRules {
                min_relay: constants::default_min_relays_per_room(),
                min_cp: constants::default_min_cps_per_room(),
                min_validator: constants::default_min_validators_per_room(),
            },
            room_proposals: table::new(ctx),
            active_room_ids: vec_set::empty(),
        });
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Create a new room. Creator must be a registered user.
    public fun create_room(
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        user_reg: &mut UserRegistry,
        relay_mode: u8,
        expected_participants: u64,
        room_class_hint: u8,     // NEW additive arg (REQ-RMS-016)
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(
            relay_mode == constants::relay_mode_sfu() || relay_mode == constants::relay_mode_mcu(),
            E_INVALID_MODE,
        );

        let sender = ctx.sender();
        assert!(user_registry::is_registered(user_reg, sender), E_USER_NOT_REGISTERED);

        let room_uid = object::new(ctx);
        let room_id = object::uid_to_inner(&room_uid);
        object::delete(room_uid);

        let info = RoomInfo {
            creator: sender,
            status: constants::room_status_pending(),
            relay_mode,
            created_at: ctx.epoch(),
            closed_at: 0,
            assigned_relays: vector::empty(),
            assigned_signaling: option::none(),
            assigned_cp: option::none(),
            expected_participants,
            assigned_validators: vector::empty(),
            verified_score: 0,
            consensus_reached: false,
            standby_relay_id: option::none(),
        };

        table::add(&mut manager.rooms, room_id, info);
        manager.active_count = manager.active_count + 1;
        vec_set::insert(&mut manager.active_room_ids, room_id);

        // Increment user's room count
        user_registry::increment_room_count(user_reg, sender);

        event::emit(RoomCreated { room_id, creator: sender, relay_mode, room_class_hint });
    }

    /// Close a room. Only the creator can close it.
    public fun close_room(
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        room_id: ID,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);

        let info = table::borrow_mut(&mut manager.rooms, room_id);
        assert!(info.creator == ctx.sender(), E_NOT_CREATOR);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);

        info.status = constants::room_status_closed();
        info.closed_at = ctx.epoch();
        manager.active_count = manager.active_count - 1;
        if (vec_set::contains(&manager.active_room_ids, &room_id)) {
            vec_set::remove(&mut manager.active_room_ids, &room_id);
        };

        // Clean up any pending proposals
        if (table::contains(&manager.room_proposals, room_id)) {
            table::remove(&mut manager.room_proposals, room_id);
        };

        event::emit(RoomClosed {
            room_id,
            closed_by: ctx.sender(),
            epoch: ctx.epoch(),
        });
    }

    /// Update room rules (governance — AdminCap required).
    public fun update_room_rules(
        _: &AdminCap,
        manager: &mut RoomManager,
        min_relay: u64,
        min_cp: u64,
        min_validator: u64,
    ) {
        // ONCHAIN-4 (REQ-RMS-009 fold): governance floor — min_relay must keep the
        // REQ-RMS-004 ballot-size invariant (>= 2). Without this an AdminCap could
        // lower min_relay to 0/1, letting a length-1/empty create_room ballot pass.
        assert!(min_relay >= 2, E_INVALID_MIN);

        manager.room_rules = RoomRules { min_relay, min_cp, min_validator };

        event::emit(RoomRulesUpdated { min_relay, min_cp, min_validator });
    }

    /// Submit a pairing proposal for a PENDING room. ControlPlaneCap-gated.
    ///
    /// Consensus-first model: each CP submits relay_ids, validator_ids,
    /// signaling_id, and a pre-computed `submitted_score`. The contract
    /// does NOT recompute scores on-chain. Instead, proposals are grouped
    /// by score equality — the room finalizes once `matching_votes >=
    /// ceil(active_cp_count * 2/3)`, i.e. enough CPs agree on ONE score.
    /// The denominator is the ACTIVE CP SET, not the proposals submitted so
    /// far (so a lone first proposal no longer finalizes unless it is the
    /// whole active set). The first submitter of the winning score gets
    /// reputation.
    public fun submit_pairing_proposal(
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        cp_reg: &mut ControlPlaneRegistry,
        relay_reg: &RelayRegistry,
        validator_reg: &ValidatorRegistry,
        signaling_reg: &SignalingRegistry,
        cap: &ControlPlaneCap,
        room_id: ID,
        relay_ids: vector<ID>,
        validator_ids: vector<ID>,
        signaling_id: ID,
        submitted_score: u64,
        ctx: &TxContext,
    ) {
        // 1. Guards: paused, room exists, PENDING, CP registered
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);

        let expected_participants = table::borrow(&manager.rooms, room_id).expected_participants;
        let room_status = table::borrow(&manager.rooms, room_id).status;
        assert!(room_status == constants::room_status_pending(), E_NOT_PENDING);

        let cp_id = caps::cp_cap_miner_id(cap);
        assert!(control_plane_registry::is_registered(cp_reg, cp_id), E_NOT_FOUND);

        // 2. Duplicate check: CP hasn't already proposed for this room
        if (!table::contains(&manager.room_proposals, room_id)) {
            table::add(&mut manager.room_proposals, room_id, vector::empty<PairingProposal>());
        };

        let proposals = table::borrow(&manager.room_proposals, room_id);
        let mut j = 0;
        let proposal_count = vector::length(proposals);
        while (j < proposal_count) {
            assert!(vector::borrow(proposals, j).cp_id != cp_id, E_DUPLICATE_VOTE);
            j = j + 1;
        };

        // 3. Ballot size: relay_ids >= min_relay, validator_ids >= required_validators
        let min_relays = manager.room_rules.min_relay;
        assert!(vector::length(&relay_ids) >= min_relays, E_INVALID_BALLOT);

        let req_validators = pairing_score::required_validators(expected_participants);
        assert!(vector::length(&validator_ids) >= req_validators, E_INVALID_BALLOT);

        // 4. Liveness check: all proposed nodes must be registered
        let mut i = 0;
        while (i < vector::length(&relay_ids)) {
            assert!(
                relay_registry::is_registered(relay_reg, *vector::borrow(&relay_ids, i)),
                pairing_score::e_node_not_active(),
            );
            i = i + 1;
        };
        i = 0;
        while (i < vector::length(&validator_ids)) {
            assert!(
                validator_registry::is_registered(validator_reg, *vector::borrow(&validator_ids, i)),
                pairing_score::e_node_not_active(),
            );
            i = i + 1;
        };
        assert!(
            signaling_registry::is_registered(signaling_reg, signaling_id),
            pairing_score::e_node_not_active(),
        );

        // 5. Store proposal with submitted_score (NO on-chain score computation)
        let proposal = PairingProposal {
            cp_id,
            relay_ids,
            validator_ids,
            signaling_id,
            submitted_score,
        };
        let relay_count = vector::length(&proposal.relay_ids);
        let validator_count = vector::length(&proposal.validator_ids);
        table::borrow_mut(&mut manager.room_proposals, room_id).push_back(proposal);

        // 6. Emit ProposalSubmitted event (verified_score field carries submitted_score)
        event::emit(ProposalSubmitted {
            room_id,
            cp_id,
            verified_score: submitted_score,
            relay_count,
            validator_count,
        });

        // 7. Genuine multi-CP quorum: require ceil(active_cp_count * 2/3) CPs to agree
        //    on ONE score. (The first proposal no longer finalizes a room alone — unless
        //    a single CP is the entire active set → required = 1, backward-compatible.)
        let bp = constants::basis_points();
        let active_cps = control_plane_registry::active_cp_count(cp_reg);
        let required = {
            // ceil(2/3): N5->4, N1->1; rounds up at N3 -> 3-of-3 (unanimity)
            let r = (active_cps * constants::pvr_consensus_threshold_bps() + bp - 1) / bp;
            if (r < 1) { 1 } else { r }
        };

        // 8. Count proposals matching this submitted_score (the winning group).
        let all_proposals = table::borrow(&manager.room_proposals, room_id);
        let total_proposals = vector::length(all_proposals);
        let mut matching_votes: u64 = 0;
        let mut first_matching_idx: u64 = 0;
        let mut found_first = false;
        let mut k: u64 = 0;
        while (k < total_proposals) {
            if (vector::borrow(all_proposals, k).submitted_score == submitted_score) {
                matching_votes = matching_votes + 1;
                if (!found_first) {
                    first_matching_idx = k;
                    found_first = true;
                };
            };
            k = k + 1;
        };

        // 9. Not enough CPs agree on one score yet → wait for more proposals.
        if (matching_votes < required) {
            return
        };

        // Consensus reached — finalize with the first submitter of the winning score
        let winner = *vector::borrow(all_proposals, first_matching_idx);

        // Assign to room: PENDING -> READY
        let room_info = table::borrow_mut(&mut manager.rooms, room_id);
        room_info.assigned_relays = winner.relay_ids;
        room_info.assigned_validators = winner.validator_ids;
        room_info.assigned_signaling = option::some(winner.signaling_id);
        room_info.assigned_cp = option::some(winner.cp_id);
        room_info.status = constants::room_status_ready();
        room_info.verified_score = submitted_score;
        room_info.consensus_reached = true;

        // Increment first submitter's reputation
        control_plane_registry::increment_reputation(cp_reg, winner.cp_id);

        // Clean up proposals
        table::remove(&mut manager.room_proposals, room_id);

        let room_mode = room_info.relay_mode;
        event::emit(RoomAssigned {
            room_id,
            relay_ids: winner.relay_ids,
            signaling_id: winner.signaling_id,
            relay_mode: room_mode,
            verified_score: submitted_score,
            consensus_reached: true,
            winning_cp: winner.cp_id,
            validator_ids: winner.validator_ids,
        });

        event::emit(ProposerRewarded {
            room_id,
            cp_id: winner.cp_id,
            reward: constants::pvr_proposer_reward(),
        });
    }

    /// Dispute fallback: when no CP consensus is reached, the room creator
    /// can trigger on-chain scoring after a cooldown period. The contract
    /// reads node metrics from registries, computes verified scores, and
    /// picks the best proposal.
    public fun finalize_room(
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        _cp_reg: &mut ControlPlaneRegistry,
        relay_reg: &RelayRegistry,
        validator_reg: &ValidatorRegistry,
        signaling_reg: &SignalingRegistry,
        room_id: ID,
        ctx: &TxContext,
    ) {
        // 1. Paused check
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        // 2. Room exists
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        // 3. Room is PENDING
        let room_status = table::borrow(&manager.rooms, room_id).status;
        assert!(room_status == constants::room_status_pending(), E_NOT_PENDING);
        // 4. Only room creator
        let room_creator = table::borrow(&manager.rooms, room_id).creator;
        assert!(room_creator == ctx.sender(), E_NOT_ROOM_CREATOR);
        // 5. Cooldown check
        let room_created_at = table::borrow(&manager.rooms, room_id).created_at;
        assert!(
            ctx.epoch() >= room_created_at + constants::pvr_dispute_cooldown(),
            E_COOLDOWN_NOT_MET,
        );
        // 6. Sufficient proposals (>= 2)
        assert!(table::contains(&manager.room_proposals, room_id), E_INSUFFICIENT_PROPOSALS);
        let proposals = table::borrow(&manager.room_proposals, room_id);
        let proposal_count = vector::length(proposals);
        assert!(proposal_count >= 2, E_INSUFFICIENT_PROPOSALS);

        // 7-8. Compute verified score for each proposal, pick highest
        let current_epoch = ctx.epoch();
        let default_history = constants::pvr_default_history();

        let mut best_idx: u64 = 0;
        let mut best_score: u64 = 0;
        let mut i: u64 = 0;
        while (i < proposal_count) {
            let p = vector::borrow(proposals, i);
            let mut node_scores = vector::empty<u64>();

            // Score relays
            let mut r = 0;
            let relay_count = vector::length(&p.relay_ids);
            while (r < relay_count) {
                let rid = *vector::borrow(&p.relay_ids, r);
                let relay_info = relay_registry::borrow_info(relay_reg, rid);
                let rtt = if (relay_registry::has_rtt(relay_reg, rid)) {
                    relay_registry::get_rtt(relay_reg, rid)
                } else {
                    0
                };
                let load = relay_registry::get_load(relay_reg, rid);
                let stake = relay_registry::info_stake_amount(relay_info);
                let heartbeat_age = current_epoch - relay_registry::info_last_heartbeat(relay_info);

                node_scores.push_back(
                    pairing_score::compute_node_score(rtt, load, stake, heartbeat_age, false, default_history),
                );
                r = r + 1;
            };

            // Score validators
            let mut v = 0;
            let val_count = vector::length(&p.validator_ids);
            while (v < val_count) {
                let vid = *vector::borrow(&p.validator_ids, v);
                let val_info = validator_registry::borrow_info(validator_reg, vid);
                let stake = validator_registry::info_stake_amount(val_info);
                let heartbeat_age = current_epoch - validator_registry::info_last_heartbeat(val_info);

                node_scores.push_back(
                    pairing_score::compute_node_score(0, 0, stake, heartbeat_age, false, default_history),
                );
                v = v + 1;
            };

            // Score signaling
            let sig_info = signaling_registry::borrow_info(signaling_reg, p.signaling_id);
            let sig_load = signaling_registry::info_load(sig_info);
            let sig_stake = signaling_registry::info_stake_amount(sig_info);
            let sig_heartbeat_age = current_epoch - signaling_registry::info_last_heartbeat(sig_info);

            node_scores.push_back(
                pairing_score::compute_node_score(0, sig_load, sig_stake, sig_heartbeat_age, false, default_history),
            );

            let score = pairing_score::compute_pairing_score(&node_scores);
            if (score > best_score) {
                best_score = score;
                best_idx = i;
            };

            i = i + 1;
        };

        // 9. Assign room with best proposal
        let winner = *vector::borrow(proposals, best_idx);

        let room_info = table::borrow_mut(&mut manager.rooms, room_id);
        room_info.assigned_relays = winner.relay_ids;
        room_info.assigned_validators = winner.validator_ids;
        room_info.assigned_signaling = option::some(winner.signaling_id);
        room_info.assigned_cp = option::some(winner.cp_id);
        room_info.verified_score = best_score;
        room_info.consensus_reached = false;
        room_info.status = constants::room_status_ready();

        // 10. No reputation increment (dispute path)

        // 11. Clean up proposals
        let room_mode = room_info.relay_mode;
        table::remove(&mut manager.room_proposals, room_id);

        // 12. Emit RoomAssigned with consensus_reached = false
        event::emit(RoomAssigned {
            room_id,
            relay_ids: winner.relay_ids,
            signaling_id: winner.signaling_id,
            relay_mode: room_mode,
            verified_score: best_score,
            consensus_reached: false,
            winning_cp: winner.cp_id,
            validator_ids: winner.validator_ids,
        });
    }

    /// Direct assignment (bypasses voting). AdminCap-gated (PAIR-04).
    /// Kept for testing and admin-only fallback scenarios.
    /// Normal flow uses submit_pairing_proposal.
    /// Room must exist and not be CLOSED.
    public fun assign_relay_and_signaling(
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        _admin: &AdminCap,
        room_id: ID,
        relay_id: ID,
        signaling_id: ID,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);

        let info = table::borrow_mut(&mut manager.rooms, room_id);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);

        info.assigned_relays = vector[relay_id];
        info.assigned_signaling = option::some(signaling_id);
        // Transition PENDING → READY once infrastructure is assigned
        if (info.status == constants::room_status_pending()) {
            info.status = constants::room_status_ready();
        };

        event::emit(RoomAssigned {
            room_id,
            relay_ids: vector[relay_id],
            signaling_id,
            relay_mode: info.relay_mode,
            verified_score: 0,
            consensus_reached: false,
            winning_cp: object::id_from_address(@0x0),
            validator_ids: vector::empty(),
        });
    }

    /// Returns (assigned_relays, assigned_signaling) for devInspect.
    public fun get_room_assignment(
        manager: &RoomManager,
        room_id: ID,
    ): (vector<ID>, Option<ID>) {
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        let info = table::borrow(&manager.rooms, room_id);
        (info.assigned_relays, info.assigned_signaling)
    }

    // ══════════════════════════════════════════════════════════
    // FAILOVER (ADR-0004)
    // ══════════════════════════════════════════════════════════

    /// Bind a warm standby relay to a room. AdminCap-gated for scope-B (CP-cap path
    /// is a follow-up). Emits `RoomCreatedWithStandby` as the canonical bootstrap
    /// record — `rtp_params_hash` + `mcu_config_hash` anchor the off-chain payload
    /// the standby will receive via the signaling node.
    public fun set_standby_relay(
        _admin: &AdminCap,
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        relay_reg: &RelayRegistry,
        room_id: ID,
        standby_relay: ID,
        rtp_params_hash: vector<u8>,
        mcu_config_hash: vector<u8>,
        ctx: &TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        assert!(relay_registry::is_registered(relay_reg, standby_relay), E_STANDBY_NOT_REGISTERED);

        let info = table::borrow_mut(&mut manager.rooms, room_id);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);
        assert!(!vector::is_empty(&info.assigned_relays), E_PRIMARY_NOT_ASSIGNED);

        let primary = *vector::borrow(&info.assigned_relays, 0);
        assert!(primary != standby_relay, E_SAME_RELAY);

        info.standby_relay_id = option::some(standby_relay);

        event::emit(RoomCreatedWithStandby {
            room_id,
            primary_relay: primary,
            standby_relay,
            rtp_params_hash,
            mcu_config_hash,
            epoch: ctx.epoch(),
        });
    }

    /// Swap primary → standby. Emits the failover-initiated record AND the post-swap
    /// canonical record; the manuscript framing for the validator-signature gap is
    /// "bounded and chain-witnessed, not silent" (ADR-0004 § MCU composite continuity).
    /// AdminCap-gated for scope-B.
    public fun swap_relay(
        _admin: &AdminCap,
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        relay_reg: &RelayRegistry,
        room_id: ID,
        trigger: u8,
        ctx: &TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);

        let info = table::borrow_mut(&mut manager.rooms, room_id);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);
        assert!(!vector::is_empty(&info.assigned_relays), E_PRIMARY_NOT_ASSIGNED);
        assert!(option::is_some(&info.standby_relay_id), E_NO_STANDBY);

        let old_relay = *vector::borrow(&info.assigned_relays, 0);
        let new_relay = *option::borrow(&info.standby_relay_id);

        // Standby must still be a registered relay at swap time
        assert!(relay_registry::is_registered(relay_reg, new_relay), E_STANDBY_NOT_REGISTERED);

        // Replace primary slot 0; preserve any additional entries past index 0
        *vector::borrow_mut(&mut info.assigned_relays, 0) = new_relay;
        info.standby_relay_id = option::none();

        let current_epoch = ctx.epoch();
        event::emit(RelayFailoverInitiated {
            room_id,
            primary_relay: old_relay,
            standby_relay: new_relay,
            trigger,
            epoch: current_epoch,
        });
        event::emit(RelaySwapped {
            room_id,
            old_relay,
            new_relay,
            new_turn_creds_required: true,
            epoch: current_epoch,
        });
    }

    /// Replace a no-longer-available standby with a fresh one (no swap of primary).
    /// AdminCap-gated for scope-B.
    public fun replace_standby(
        _admin: &AdminCap,
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        relay_reg: &RelayRegistry,
        room_id: ID,
        new_standby: ID,
        ctx: &TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        assert!(relay_registry::is_registered(relay_reg, new_standby), E_STANDBY_NOT_REGISTERED);

        let info = table::borrow_mut(&mut manager.rooms, room_id);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);
        assert!(option::is_some(&info.standby_relay_id), E_NO_STANDBY);

        let old_standby = *option::borrow(&info.standby_relay_id);
        assert!(old_standby != new_standby, E_SAME_RELAY);

        // Ensure new standby is not the current primary
        if (!vector::is_empty(&info.assigned_relays)) {
            let primary = *vector::borrow(&info.assigned_relays, 0);
            assert!(primary != new_standby, E_SAME_RELAY);
        };

        info.standby_relay_id = option::some(new_standby);

        event::emit(StandbyRelayReplaced {
            room_id,
            old_standby,
            new_standby,
            epoch: ctx.epoch(),
        });
    }

    // ── Relay overlap promotion (ADR-0009 / RO-003) ──

    /// Permissionless promotion of a stale primary relay to its standby.
    ///
    /// Access control: NONE (permissionless + on-chain staleness assert, D-RO-1).
    /// Any caller may submit — the on-chain heartbeat age is the authority, not a cap.
    /// Mirrors the `mark_revote_eligible_*` permissionless-but-advisory pattern (F47).
    ///
    /// Preconditions:
    ///   - System must not be paused.
    ///   - Room must exist and not be CLOSED.
    ///   - `assigned_relays` must have at least 2 slots (primary at [0]).
    ///   - `new_primary` must be in `assigned_relays` (not the current primary at [0]).
    ///   - Current primary's `last_heartbeat` age must exceed MAX_HEARTBEAT_EPOCHS.
    ///
    /// Effect: replaces `assigned_relays[0]` with `new_primary`; emits `RelayPromoted`.
    /// Does NOT touch `standby_relay_id` (ADR-0004 N=1 legacy field — D-RO-4).
    public entry fun promote_relay(
        net_reg:  &NetworkRegistry,
        manager:  &mut RoomManager,
        relay_reg: &RelayRegistry,
        room_id:  ID,
        new_primary: ID,
        ctx:      &mut TxContext,
    ) {
        // 1. Paused guard
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        // 2. Room exists and is not closed
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        let info = table::borrow(&manager.rooms, room_id);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);

        // 3. Must have at least 2 assigned relays (primary at [0])
        assert!(!vector::is_empty(&info.assigned_relays), E_PRIMARY_NOT_ASSIGNED);
        let relay_count = vector::length(&info.assigned_relays);
        assert!(relay_count >= 2, E_PRIMARY_NOT_ASSIGNED);

        // 4. new_primary must be in assigned_relays and must differ from current primary
        let old_primary = *vector::borrow(&info.assigned_relays, 0);
        assert!(old_primary != new_primary, E_SAME_RELAY);

        // Verify new_primary is in assigned_relays[1..]
        let mut found = false;
        let mut i: u64 = 1;
        while (i < relay_count) {
            if (*vector::borrow(&info.assigned_relays, i) == new_primary) {
                found = true;
                break
            };
            i = i + 1;
        };
        assert!(found, E_NOT_FOUND);

        // 5. On-chain staleness assert — reads F40 last_heartbeat (RO-001 canonical source)
        let relay_info = relay_registry::borrow_info(relay_reg, old_primary);
        let last_hb = relay_registry::info_last_heartbeat(relay_info);
        let current_epoch = ctx.epoch();
        assert!(current_epoch - last_hb > MAX_HEARTBEAT_EPOCHS, E_RELAY_NOT_STALE);

        // 6. Mutate: replace primary slot [0] with new_primary
        let info_mut = table::borrow_mut(&mut manager.rooms, room_id);
        *vector::borrow_mut(&mut info_mut.assigned_relays, 0) = new_primary;

        // 7. Emit RelayPromoted event (schema locked under ADR-0009)
        event::emit(RelayPromoted {
            room_id,
            old_primary,
            new_primary,
            epoch: current_epoch,
        });
    }

    /// REQ-RMS-009 — CP-quorum-gated spill authorization. APPENDS `spill_relay` to a
    /// room's assigned_relays so a too-big room can cascade across K_r relays. Guard
    /// provenance (verified vs room_manager.move):
    ///   • paused / room-exists / not-closed  → reused from promote_relay (lines 817-823).
    ///   • CP-registered + relay-registered    → mirror submit_pairing_proposal
    ///     (control_plane_registry::is_registered:357 + relay_registry::is_registered).
    ///     NOTE: promote_relay does NOT assert is_registered — it asserts heartbeat
    ///     STALENESS (E_RELAY_NOT_STALE:852); a spill APPEND is not a staleness swap, so
    ///     the registered gates come from submit_pairing_proposal, not promote_relay.
    /// Gated this way (CP cap + CP-registration) — NOT permissionless promote_relay: a
    /// relay cannot self-co-opt a peer (§4.4 Byzantine guard). The economic + canary
    /// loops tolerate a zero-proof appended relay (under-covered = skip / not slashable
    /// until it forwards), verified by grep of room_assigned_relays consumers.
    public entry fun authorize_spill_relay(
        net_reg:   &NetworkRegistry,
        manager:   &mut RoomManager,
        cp_reg:    &ControlPlaneRegistry,
        relay_reg: &RelayRegistry,
        cap:       &ControlPlaneCap,
        room_id:   ID,
        spill_relay: ID,
        ctx:       &mut TxContext,
    ) {
        // 1. Reused promote_relay guards (verbatim, room_manager.move:819-825):
        //    paused, room-exists, not-closed.
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        let info = table::borrow(&manager.rooms, room_id);
        assert!(info.status != constants::room_status_closed(), E_ALREADY_CLOSED);

        // 2. CP gate (mirrors submit_pairing_proposal:357, NOT promote_relay): the cap's
        //    cp_id MUST be a registered control plane — a relay cannot unilaterally
        //    co-opt a peer. Fresh code 565 (not E_NOT_FOUND) for a precise abort reason.
        let cp_id = caps::cp_cap_miner_id(cap);
        assert!(control_plane_registry::is_registered(cp_reg, cp_id), E_CP_NOT_REGISTERED);

        // 3. The spill relay must be a registered relay (mirrors submit_pairing_proposal;
        //    promote_relay does NOT do this check). Fresh code 567 — do NOT reuse the F1
        //    STANDBY code 561, a spill relay is a distinct concept.
        assert!(relay_registry::is_registered(relay_reg, spill_relay), E_SPILL_RELAY_NOT_REGISTERED);

        // 4. No-dup: the spill relay must not already be assigned.
        assert!(!vector::contains(&info.assigned_relays, &spill_relay), E_RELAY_ALREADY_ASSIGNED);

        // 5. Mutate: APPEND (push_back) — distinct from promote_relay's slot[0] swap.
        let info_mut = table::borrow_mut(&mut manager.rooms, room_id);
        vector::push_back(&mut info_mut.assigned_relays, spill_relay);
        let relay_count = vector::length(&info_mut.assigned_relays);

        // 6. Emit the additive RelaySpillAuthorized event.
        event::emit(RelaySpillAuthorized {
            room_id,
            spill_relay,
            authorized_by: cp_id,
            relay_count,
            epoch: ctx.epoch(),
        });
    }

    // ══════════════════════════════════════════════════════════
    // INTERNAL HELPERS
    // ══════════════════════════════════════════════════════════

    // ══════════════════════════════════════════════════════════
    // PACKAGE-ONLY MUTATIONS
    // ══════════════════════════════════════════════════════════

    /// Transition room status (Phase 3 uses this for PENDING → READY → ACTIVE).
    public(package) fun set_room_status(
        manager: &mut RoomManager,
        room_id: ID,
        status: u8,
    ) {
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.status = status;
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun active_count(m: &RoomManager): u64 { m.active_count }

    public fun has_room(m: &RoomManager, room_id: ID): bool {
        table::contains(&m.rooms, room_id)
    }

    public fun borrow_room(m: &RoomManager, room_id: ID): &RoomInfo {
        table::borrow(&m.rooms, room_id)
    }

    public fun room_rules(m: &RoomManager): RoomRules { m.room_rules }

    public fun room_creator(r: &RoomInfo): address    { r.creator }
    public fun room_status(r: &RoomInfo): u8          { r.status }
    public fun room_relay_mode(r: &RoomInfo): u8      { r.relay_mode }
    public fun room_created_at(r: &RoomInfo): u64     { r.created_at }
    public fun room_closed_at(r: &RoomInfo): u64      { r.closed_at }
    public fun room_assigned_relays(r: &RoomInfo): vector<ID>       { r.assigned_relays }
    public fun room_assigned_signaling(r: &RoomInfo): Option<ID>    { r.assigned_signaling }
    public fun room_assigned_cp(r: &RoomInfo): Option<ID>          { r.assigned_cp }

    /// Backward-compat accessor: returns first assigned relay as Option<ID>.
    public fun room_assigned_relay(r: &RoomInfo): Option<ID> {
        if (vector::is_empty(&r.assigned_relays)) {
            option::none()
        } else {
            option::some(*vector::borrow(&r.assigned_relays, 0))
        }
    }

    public fun room_proposals_count(m: &RoomManager, room_id: ID): u64 {
        if (table::contains(&m.room_proposals, room_id)) {
            vector::length(table::borrow(&m.room_proposals, room_id))
        } else {
            0
        }
    }

    public fun room_expected_participants(r: &RoomInfo): u64 { r.expected_participants }
    public fun room_assigned_validators(r: &RoomInfo): vector<ID> { r.assigned_validators }
    public fun room_verified_score(r: &RoomInfo): u64 { r.verified_score }
    public fun room_consensus_reached(r: &RoomInfo): bool { r.consensus_reached }
    public fun room_standby_relay(r: &RoomInfo): Option<ID> { r.standby_relay_id }

    /// Returns a vector of (room_id, RoomInfo) for all active (non-closed) rooms.
    /// Used by client devInspect for dashboard batch-fetch.
    /// Cost: O(n) where n = size of active_room_ids. Acceptable for < 200 rooms.
    public fun get_active_rooms(m: &RoomManager): vector<RoomInfo> {
        let ids = vec_set::keys(&m.active_room_ids);
        let mut result = vector::empty<RoomInfo>();
        let mut i = 0;
        let len = ids.length();
        while (i < len) {
            let id = *ids.borrow(i);
            if (table::contains(&m.rooms, id)) {
                result.push_back(*table::borrow(&m.rooms, id));
            };
            i = i + 1;
        };
        result
    }

    /// Returns the set of active room IDs for iteration.
    public fun get_active_room_ids(m: &RoomManager): vector<ID> {
        *vec_set::keys(&m.active_room_ids)
    }

    public fun rules_min_relay(r: &RoomRules): u64     { r.min_relay }
    public fun rules_min_cp(r: &RoomRules): u64        { r.min_cp }
    public fun rules_min_validator(r: &RoomRules): u64 { r.min_validator }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        transfer::share_object(RoomManager {
            id: object::new(ctx),
            rooms: table::new(ctx),
            active_count: 0,
            room_rules: RoomRules {
                min_relay: constants::default_min_relays_per_room(),
                min_cp: constants::default_min_cps_per_room(),
                min_validator: constants::default_min_validators_per_room(),
            },
            room_proposals: table::new(ctx),
            active_room_ids: vec_set::empty(),
        });
    }

    #[test_only]
    /// Add a room with a specific ID and status for testing.
    public fun add_room_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        creator: address,
        status: u8,
        relay_mode: u8,
        expected_participants: u64,
        ctx: &mut TxContext,
    ) {
        let info = RoomInfo {
            creator,
            status,
            relay_mode,
            created_at: ctx.epoch(),
            closed_at: 0,
            assigned_relays: vector::empty(),
            assigned_signaling: option::none(),
            assigned_cp: option::none(),
            expected_participants,
            assigned_validators: vector::empty(),
            verified_score: 0,
            consensus_reached: false,
            standby_relay_id: option::none(),
        };
        table::add(&mut manager.rooms, room_id, info);
        manager.active_count = manager.active_count + 1;
        vec_set::insert(&mut manager.active_room_ids, room_id);
    }

    #[test_only]
    /// Set the assigned CP for a room (for testing CP pool distribution).
    public fun set_assigned_cp_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        cp_id: ID,
    ) {
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.assigned_cp = option::some(cp_id);
    }

    #[test_only]
    /// Set the assigned signaling for a room (for testing signaling pool distribution).
    public fun set_assigned_signaling_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        sig_id: ID,
    ) {
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.assigned_signaling = option::some(sig_id);
    }

    #[test_only]
    /// Set assigned validators for a room (for testing assignment enforcement).
    public fun set_assigned_validators_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        validator_ids: vector<ID>,
    ) {
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.assigned_validators = validator_ids;
    }

    #[test_only]
    /// Set assigned relays for a room (for testing slash distribution).
    public fun set_assigned_relays_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        relay_ids: vector<ID>,
    ) {
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.assigned_relays = relay_ids;
    }

    #[test_only]
    /// Add a pairing proposal directly (bypasses consensus check).
    /// Used to set up dispute-path test scenarios.
    public fun add_proposal_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        cp_id: ID,
        relay_ids: vector<ID>,
        validator_ids: vector<ID>,
        signaling_id: ID,
        submitted_score: u64,
    ) {
        if (!table::contains(&manager.room_proposals, room_id)) {
            table::add(&mut manager.room_proposals, room_id, vector::empty<PairingProposal>());
        };
        let proposal = PairingProposal {
            cp_id,
            relay_ids,
            validator_ids,
            signaling_id,
            submitted_score,
        };
        table::borrow_mut(&mut manager.room_proposals, room_id).push_back(proposal);
    }
}
