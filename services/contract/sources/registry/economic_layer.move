/// Economic layer -- manages room escrow deposits, dual-key signed SessionProof
/// submission with on-chain ed25519 verification, median aggregation, work-based
/// reward distribution, and slashing for poor quality.
///
/// This module is a clean top-layer addition: no existing module imports it.
/// Error code namespace: 650-665.
module dvconf::economic_layer {
    use sui::balance::{Self, Balance};
    use sui::coin::{Self, Coin};
    use sui::event;
    use sui::bcs;
    use sui::ed25519;
    use sui::hash;
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::constants;
    use dvconf::staking;
    use sui::sui::SUI;

    // ── Errors (650-665) ──
    const E_PAUSED: u64                  = 650;
    const E_NOT_ROOM_CREATOR: u64        = 651;
    const E_ROOM_NOT_FOUND: u64          = 652;
    const E_ROOM_NOT_PENDING: u64        = 653;
    const E_INVALID_SIGNATURE: u64       = 654;
    const E_SESSION_WALLET_NOT_FOUND: u64 = 655;
    const E_ALREADY_SUBMITTED: u64       = 656;
    const E_ROOM_NOT_CLOSED: u64         = 657;
    const E_INSUFFICIENT_PROOFS: u64     = 658;
    const E_ALREADY_DISTRIBUTED: u64     = 659;
    const E_ZERO_ESCROW: u64             = 660;
    const E_RELAY_NOT_REGISTERED: u64    = 661;
    const E_VALIDATOR_NOT_ASSIGNED: u64  = 662;
    const E_NO_SLASH_PENDING: u64        = 663;
    const E_WRONG_STAKE: u64             = 664;
    // RO-023c (FK-2): aborted only when ZERO assigned relays have sufficient
    // distinct-validator coverage to distribute. A single under-covered relay is
    // SKIPPED (earns 0, folds to pool/creator) — this room-level abort fires only
    // when NO relay qualifies. Next free abort slot was 665 (664 = E_WRONG_STAKE).
    const E_NO_RELAY_COVERAGE: u64       = 665;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    /// Per-validator attestation stored in RoomEscrow.proofs.
    /// Signatures are verified then discarded (verify-then-discard per PM P1-5).
    public struct SessionProof has store, copy, drop {
        validator_id:      ID,
        room_id:           ID,
        relay_miner_id:    ID,
        packets_forwarded: u64,
        bytes_transferred: u64,
        unique_peers:      u64,
        duration_seconds:  u64,
        avg_latency_ms:    u64,
        packet_loss_bps:   u64,   // basis points; 200 = 2% loss
        jitter_ms:         u64,
        submitted_at:      u64,
        // RO-017: chain-derived role label. 0 = primary (assigned_relays[0]),
        // 1 = standby (any other assigned relay). Derived in submit_session_proof
        // from the already-signed relay_miner_id; NOT part of the signed IC-2
        // message (so no abort-654 / no daemon serializeProofBcs lockstep). For
        // viz/grouping convenience only — un-spoofable since the chain derives it.
        relay_role:        u8,
    }

    /// Shared object per room — holds escrowed funds and collected proofs.
    public struct RoomEscrow has key {
        id:          UID,
        room_id:     ID,
        creator:     address,
        escrow:      Balance<SUI>,
        proofs:      vector<SessionProof>,
        distributed: bool,
        // ── Slash tracking (Phase 18) ──
        slash_amount:          u64,
        slash_relay_miner_id:  ID,
        slash_quality:         u64,
        slash_other_relays:    vector<ID>,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct EscrowCreated has copy, drop {
        escrow_id: ID,
        room_id:   ID,
        creator:   address,
        amount:    u64,
    }

    public struct SessionProofSubmitted has copy, drop {
        room_id:           ID,
        validator_id:      ID,
        relay_miner_id:    ID,
        bytes_transferred: u64,
        packet_loss_bps:   u64,
    }

    public struct RewardsDistributed has copy, drop {
        room_id:         ID,
        relay_reward:    u64,   // total relay pool ALLOCATED (pre per-relay split, pre skip/slash folding); NOT the sum of paid relay_rewards; kept for back-compat
        validator_pool:  u64,
        cp_pool:         u64,
        signaling_pool:  u64,
        remainder:       u64,
        // RO-024 (FK-4): additive per-relay breakdown. Parallel vectors — paid
        // relay ids and the exact Coin amount each operator received. Hybrid
        // per-relay amounts differ, so relay_reward/len is NOT a valid fallback.
        // FE viz RO-022 consumes this exact shape. Additive only (W3-F58-safe).
        relay_ids:       vector<ID>,
        relay_rewards:   vector<u64>,
    }

    public struct RelaySlashed has copy, drop {
        room_id:        ID,
        relay_miner_id: ID,
        slash_amount:   u64,
    }

    /// RO-024 (FK-4): emitted by `pay_slash` when a slashed relay's stake is
    /// redistributed. Parallel vectors — the sibling relays that received the
    /// relay-share of the slash and the exact Coin amount each got. `creator_amount`
    /// is the remaining share (poor-quality penalty + rounding dust) sent to the
    /// room creator. Additive, NEW (the pay_slash path emitted nothing before).
    /// FE viz RO-022 consumes this exact shape.
    public struct RelaySlashRedistributed has copy, drop {
        room_id:         ID,
        slashed:         ID,
        beneficiaries:   vector<ID>,
        amounts:         vector<u64>,
        creator_amount:  u64,
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Create an escrow deposit for a room. Only the room creator can call this,
    /// and the room must be in PENDING status.
    public fun create_escrow(
        net_reg:  &NetworkRegistry,
        room_mgr: &RoomManager,
        room_id:  ID,
        payment:  Coin<SUI>,
        ctx:      &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(room_manager::has_room(room_mgr, room_id), E_ROOM_NOT_FOUND);

        let room_info = room_manager::borrow_room(room_mgr, room_id);
        assert!(room_manager::room_creator(room_info) == ctx.sender(), E_NOT_ROOM_CREATOR);
        assert!(
            room_manager::room_status(room_info) == constants::room_status_pending(),
            E_ROOM_NOT_PENDING,
        );

        // SEC-009: Duplicate escrow prevention is handled by the `distributed` flag
        // in RoomEscrow. Even if multiple escrows are created for the same room,
        // each escrow can only be distributed once (E_ALREADY_DISTRIBUTED = 659).
        let coin_value = coin::value(&payment);
        assert!(coin_value > 0, E_ZERO_ESCROW);

        let escrow_obj = RoomEscrow {
            id: object::new(ctx),
            room_id,
            creator: ctx.sender(),
            escrow: coin::into_balance(payment),
            proofs: vector::empty(),
            distributed: false,
            slash_amount: 0,
            slash_relay_miner_id: object::id_from_address(@0x0),
            slash_quality: 0,
            slash_other_relays: vector::empty(),
        };

        // IMP-1: include escrow_id in event so OffChain daemon can discover it (IC-3)
        event::emit(EscrowCreated {
            escrow_id: object::id(&escrow_obj),
            room_id,
            creator: ctx.sender(),
            amount: coin_value,
        });

        transfer::share_object(escrow_obj);
    }

    /// Submit a dual-key signed session proof attesting to relay quality.
    ///
    /// The validator daemon signs the BCS-serialized measurement fields with both
    /// the public wallet (A) and session wallet (B) keys. This function verifies
    /// both signatures on-chain, then stores the proof without signature data.
    ///
    /// IC-2: BCS Message Byte Layout Contract -- field order:
    ///   room_id, relay_miner_id, packets_forwarded, bytes_transferred,
    ///   unique_peers, duration_seconds, avg_latency_ms, packet_loss_bps, jitter_ms
    public fun submit_session_proof(
        net_reg:           &NetworkRegistry,
        escrow:            &mut RoomEscrow,
        room_mgr:          &RoomManager,
        validator_reg:     &mut ValidatorRegistry,
        relay_reg:         &mut RelayRegistry,
        room_id:           ID,
        relay_miner_id:    ID,
        packets_forwarded: u64,
        bytes_transferred: u64,
        unique_peers:      u64,
        duration_seconds:  u64,
        avg_latency_ms:    u64,
        packet_loss_bps:   u64,
        jitter_ms:         u64,
        pubkey_public:     vector<u8>,
        pubkey_session:    vector<u8>,
        sig_public:        vector<u8>,
        sig_session:       vector<u8>,
        ctx:               &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        // Verify escrow matches the claimed room
        assert!(escrow.room_id == room_id, E_ROOM_NOT_FOUND);

        // Verify relay is registered
        assert!(relay_registry::is_registered(relay_reg, relay_miner_id), E_RELAY_NOT_REGISTERED);

        // Look up which validator owns the sender's session wallet
        let sender = ctx.sender();
        assert!(
            validator_registry::has_session_wallet(validator_reg, sender),
            E_SESSION_WALLET_NOT_FOUND,
        );
        let validator_miner_id = validator_registry::lookup_session_wallet(validator_reg, sender);

        // Verify validator is assigned to this room (Phase 18)
        let room_info = room_manager::borrow_room(room_mgr, escrow.room_id);
        let assigned = room_manager::room_assigned_validators(room_info);
        let mut found = false;
        let mut vi = 0;
        while (vi < vector::length(&assigned)) {
            if (*vector::borrow(&assigned, vi) == validator_miner_id) {
                found = true;
                break
            };
            vi = vi + 1;
        };
        assert!(found, E_VALIDATOR_NOT_ASSIGNED);

        // RO-023a: compound dedup key (validator_id, relay_miner_id). One validator
        // may attest BOTH assigned relays (one proof each), but a 2nd submit for the
        // SAME (validator, relay) pair still aborts. A duplicate is only when BOTH
        // the validator AND the relay match an existing proof.
        let num_proofs = escrow.proofs.length();
        let mut i = 0;
        while (i < num_proofs) {
            let is_dup = escrow.proofs[i].validator_id == validator_miner_id
                && escrow.proofs[i].relay_miner_id == relay_miner_id;
            assert!(!is_dup, E_ALREADY_SUBMITTED);
            i = i + 1;
        };

        // ── IC-2: BCS Message Byte Layout Contract ──
        // Exact field order must match off-chain serialization.
        let mut msg = vector::empty<u8>();
        vector::append(&mut msg, bcs::to_bytes(&room_id));
        vector::append(&mut msg, bcs::to_bytes(&relay_miner_id));
        vector::append(&mut msg, bcs::to_bytes(&packets_forwarded));
        vector::append(&mut msg, bcs::to_bytes(&bytes_transferred));
        vector::append(&mut msg, bcs::to_bytes(&unique_peers));
        vector::append(&mut msg, bcs::to_bytes(&duration_seconds));
        vector::append(&mut msg, bcs::to_bytes(&avg_latency_ms));
        vector::append(&mut msg, bcs::to_bytes(&packet_loss_bps));
        vector::append(&mut msg, bcs::to_bytes(&jitter_ms));

        // ── IC-4: Dual-Key Public Key Passing Contract ──
        // Verify pubkey-to-address binding: blake2b256(0x00 || pubkey) = Sui address
        let validator_info = validator_registry::borrow_info(validator_reg, validator_miner_id);
        let expected_operator = validator_registry::info_operator(validator_info);

        // Derive Sui address from public wallet key: blake2b256(0x00 || pubkey)
        let mut pubkey_with_flag_a = vector::empty<u8>();
        pubkey_with_flag_a.push_back(0x00); // Ed25519 scheme flag
        vector::append(&mut pubkey_with_flag_a, pubkey_public);
        let derived_addr_a = sui::address::from_bytes(hash::blake2b256(&pubkey_with_flag_a));
        assert!(derived_addr_a == expected_operator, E_INVALID_SIGNATURE);

        // Derive Sui address from session wallet key: blake2b256(0x00 || pubkey)
        let mut pubkey_with_flag_b = vector::empty<u8>();
        pubkey_with_flag_b.push_back(0x00); // Ed25519 scheme flag
        vector::append(&mut pubkey_with_flag_b, pubkey_session);
        let derived_addr_b = sui::address::from_bytes(hash::blake2b256(&pubkey_with_flag_b));
        assert!(derived_addr_b == sender, E_INVALID_SIGNATURE);

        // Verify ed25519 signatures from both wallets
        assert!(
            ed25519::ed25519_verify(&sig_public, &pubkey_public, &msg),
            E_INVALID_SIGNATURE,
        );
        assert!(
            ed25519::ed25519_verify(&sig_session, &pubkey_session, &msg),
            E_INVALID_SIGNATURE,
        );

        // RO-017: derive the relay role label from the (already-signed) relay_miner_id.
        // 0 = primary (assigned_relays[0]); 1 = standby (any other slot). Chain-derived
        // and NOT part of the signed IC-2 message above (un-spoofable, no abort-654).
        let role_room_info = room_manager::borrow_room(room_mgr, escrow.room_id);
        let assigned_relays = room_manager::room_assigned_relays(role_room_info);
        let relay_role: u8 = if (
            vector::length(&assigned_relays) > 0
                && *vector::borrow(&assigned_relays, 0) == relay_miner_id
        ) { 0 } else { 1 };

        // Store proof (without signatures -- verify-then-discard)
        let proof = SessionProof {
            validator_id: validator_miner_id,
            room_id,
            relay_miner_id,
            packets_forwarded,
            bytes_transferred,
            unique_peers,
            duration_seconds,
            avg_latency_ms,
            packet_loss_bps,
            jitter_ms,
            submitted_at: ctx.epoch(),
            relay_role,
        };
        escrow.proofs.push_back(proof);

        // NOTE: Session wallet is NOT revealed here. In a multi-room scenario,
        // validators reuse the same session wallet across concurrent rooms.
        // Reveal is deferred to a separate call or post-session cleanup.

        // Increment validator session count
        validator_registry::increment_session_count(validator_reg, validator_miner_id);

        // Write RTT to relay registry (validator-probed, never self-reported)
        relay_registry::update_rtt(relay_reg, relay_miner_id, avg_latency_ms);

        event::emit(SessionProofSubmitted {
            room_id,
            validator_id: validator_miner_id,
            relay_miner_id,
            bytes_transferred,
            packet_loss_bps,
        });
    }

    /// Distribute rewards from the escrow after a room session ends.
    ///
    /// Computes median metrics, quality multiplier, and distributes funds
    /// using scarcity-based dynamic splits (SCAR-02). The static 70/15/15
    /// ratio from NetworkRegistry is replaced by `compute_scarcity_ratios()`
    /// which reads live node counts from all four registries.
    ///
    /// CP pool routes to the assigned CP operator (via room_assigned_cp).
    /// Signaling pool routes to the assigned signaling operator.
    /// If no CP/signaling is assigned, their pools go to the creator as remainder.
    ///
    /// Callable by anyone (crank pattern) -- funds always go to the rightful
    /// recipients (relay operator, validators, CP, signaling, room creator).
    ///
    /// NOTE on overflow: base_rate * median_bytes * quality_multiplier can overflow
    /// u64 for very large sessions. For thesis scope, values are bounded by practical
    /// session sizes (< 10GB). (PM P1-6 overflow boundary)
    public fun distribute_rewards(
        net_reg:        &NetworkRegistry,
        escrow:         &mut RoomEscrow,
        room_mgr:       &RoomManager,
        relay_reg:      &mut RelayRegistry,
        validator_reg:  &mut ValidatorRegistry,
        cp_reg:         &ControlPlaneRegistry,
        signaling_reg:  &SignalingRegistry,
        ctx:            &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        // Verify room is closed
        let room_id = escrow.room_id;
        assert!(room_manager::has_room(room_mgr, room_id), E_ROOM_NOT_FOUND);
        let room_info = room_manager::borrow_room(room_mgr, room_id);
        assert!(
            room_manager::room_status(room_info) == constants::room_status_closed(),
            E_ROOM_NOT_CLOSED,
        );

        // Verify sufficient proofs and not already distributed
        let num_proofs = escrow.proofs.length();
        assert!(num_proofs >= constants::min_proofs_for_distribution(), E_INSUFFICIENT_PROOFS);
        assert!(!escrow.distributed, E_ALREADY_DISTRIBUTED);

        // ── RO-023b: per-relay partition ──
        // Group proofs by their assigned relay. Each relay gets its OWN median
        // (bytes + loss) and OWN quality multiplier; the room-wide blended median
        // of M1 is gone. All proof reads happen HERE (immutable borrow) BEFORE any
        // mutable escrow.escrow balance split (borrow-checker order, ROADMAP 1.3).
        let assigned_relays = room_manager::room_assigned_relays(room_info);
        let num_relays = vector::length(&assigned_relays);

        let base_rate = network_registry::base_rate_per_mb(net_reg);
        let bp = constants::basis_points();

        // Read assigned CP and signaling from room
        let assigned_cp_opt = room_manager::room_assigned_cp(room_info);
        let assigned_sig_opt = room_manager::room_assigned_signaling(room_info);

        // Per-relay aggregates, parallel-indexed by `assigned_relays`.
        let mut relay_quality      = vector::empty<u64>(); // per-relay quality multiplier
        let mut relay_median_bytes = vector::empty<u64>(); // per-relay median bytes
        let mut relay_covered      = vector::empty<bool>(); // RO-023c: >=N distinct validators
        let mut relay_live         = vector::empty<bool>(); // RO-016: liveness gate (standby)
        let mut total_gross: u64   = 0;

        // RO-023c: a relay needs >= min_proofs DISTINCT validator_ids attesting it
        // to qualify for distribution (OQ-M2-6 — one validator covering both relays
        // does NOT alone satisfy either). This is independence, not raw proof count.
        let min_distinct = constants::min_proofs_for_distribution();

        let mut ri = 0;
        while (ri < num_relays) {
            let rid = *vector::borrow(&assigned_relays, ri);

            // Filter proofs attesting THIS relay + tally DISTINCT validators.
            let mut r_bytes    = vector::empty<u64>();
            let mut r_loss     = vector::empty<u64>();
            let mut r_duration = vector::empty<u64>(); // RO-016 liveness byte
            let mut r_validators = vector::empty<ID>(); // distinct validator set
            let mut r_role: u8 = 0;          // RO-017 role of this relay's proofs
            let mut r_role_seen = false;
            let mut pi = 0;
            while (pi < num_proofs) {
                if (escrow.proofs[pi].relay_miner_id == rid) {
                    r_bytes.push_back(escrow.proofs[pi].bytes_transferred);
                    r_loss.push_back(escrow.proofs[pi].packet_loss_bps);
                    r_duration.push_back(escrow.proofs[pi].duration_seconds);
                    if (!r_role_seen) { r_role = escrow.proofs[pi].relay_role; r_role_seen = true; };
                    let vid = escrow.proofs[pi].validator_id;
                    if (!vector::contains(&r_validators, &vid)) {
                        r_validators.push_back(vid);
                    };
                };
                pi = pi + 1;
            };

            let r_distinct = vector::length(&r_validators);
            let r_covered  = r_distinct >= min_distinct;

            let r_median_bytes = compute_median(&r_bytes);
            let r_median_loss  = compute_median(&r_loss);
            // Quality only meaningful for a covered relay; an under-covered relay
            // is SKIPPED (earns 0, folds to pool/creator) and is NEVER slashed —
            // a coverage gap is not a quality failure (FK-2).
            let r_quality = if (r_covered) {
                compute_quality_multiplier(r_median_loss)
            } else { 0 };

            // RO-016 LIVENESS GATE (FROZEN contract for RO-020 / Phase 2.3):
            //   primary (relay_role==0): always live (it actively forwards media).
            //   standby (relay_role==1): live IFF its per-relay median
            //     `duration_seconds > 0` — the probe-answered liveness byte.
            // duration_seconds is in the signed IC-2 message (un-spoofable,
            // validator-attested) and survives bytes_transferred≈0 for a warm-idle
            // standby. A covered+healthy-but-unanswered standby earns 0 (folds back)
            // and is NOT slashed — a liveness miss is not a quality failure. Closes
            // the DA C4 standby-grinding attack.
            let r_live = if (r_role == 1) {
                compute_median(&r_duration) > 0
            } else { true };

            // Only a covered + live relay contributes gross to the pot sizing.
            // An under-covered relay or a non-live standby must NOT inflate the
            // reward pool (else the not-live standby's notional share would leak
            // into actual_total and over-pay the remainder/creator unevenly).
            let r_gross = if (r_covered && r_live) {
                let r_step1 = base_rate * r_quality / bp; // SEC-003 reorder
                r_step1 * r_median_bytes
            } else { 0 };

            relay_quality.push_back(r_quality);
            relay_median_bytes.push_back(r_median_bytes);
            relay_covered.push_back(r_covered);
            relay_live.push_back(r_live);
            total_gross = total_gross + r_gross;

            ri = ri + 1;
        };

        // RO-023c (FK-2): whole-room abort ONLY when NO relay has sufficient
        // distinct-validator coverage. A single under-covered relay is skipped,
        // not fatal — distribution proceeds for the covered relay(s).
        let mut any_covered = false;
        let mut ci = 0;
        while (ci < num_relays) {
            if (*vector::borrow(&relay_covered, ci)) { any_covered = true; break };
            ci = ci + 1;
        };
        assert!(any_covered, E_NO_RELAY_COVERAGE);

        // ── Pool sizing (escrow-bounded) + scarcity split ──
        let escrow_value = balance::value(&escrow.escrow);
        let actual_total = if (total_gross > escrow_value) { escrow_value } else { total_gross };

        // SCAR-02: Dynamic scarcity-based splits
        let relay_count = relay_registry::active_count(relay_reg);
        let validator_count = validator_registry::active_count(validator_reg);
        let cp_count = control_plane_registry::active_cp_count(cp_reg);
        let sig_count = signaling_registry::active_signaling_count(signaling_reg);

        let (relay_ratio, validator_ratio, cp_ratio, sig_ratio) =
            compute_scarcity_ratios(relay_count, validator_count, cp_count, sig_count);

        let relay_pool     = actual_total * relay_ratio / bp;
        let validator_pool = actual_total * validator_ratio / bp;
        let cp_pool        = actual_total * cp_ratio / bp;
        let signaling_pool = actual_total * sig_ratio / bp;

        // ── Per-relay relay-pool distribution + slash trigger (RO-016/RO-018) ──
        // Equal split of the relay pool across QUALIFYING relays (covered AND
        // per-relay quality > 0 AND live). A COVERED relay with quality 0 is
        // slashed (RO-018, 1.6); an UNDER-COVERED relay or a covered-healthy-but-
        // NOT-LIVE standby (RO-016 gate) is skipped (no pay/no slash) and its
        // share folds to the qualifying relays / remainder. RO-024 (1.7) records
        // the per-relay paid amounts in parallel vectors.
        let mut qualifying = 0;
        let mut qi = 0;
        while (qi < num_relays) {
            if (*vector::borrow(&relay_covered, qi)
                && *vector::borrow(&relay_quality, qi) > 0
                && *vector::borrow(&relay_live, qi)) {
                qualifying = qualifying + 1;
            };
            qi = qi + 1;
        };
        let per_relay_share = if (qualifying > 0) { relay_pool / qualifying } else { 0 };

        // RO-024 (1.7): per-relay event breakdown vectors.
        let mut paid_relay_ids     = vector::empty<ID>();
        let mut paid_relay_rewards = vector::empty<u64>();

        let mut di = 0;
        while (di < num_relays) {
            let rid = *vector::borrow(&assigned_relays, di);
            let r_quality = *vector::borrow(&relay_quality, di);
            let r_covered = *vector::borrow(&relay_covered, di);
            let r_live    = *vector::borrow(&relay_live, di);

            if (!r_covered) {
                // ── Skip branch (RO-023c FK-2): under-covered relay earns 0 and
                // is NOT slashed (a coverage gap is not a quality failure). ──
            } else if (r_quality == 0) {
                // ── Slash branch (RO-018): COVERED-but-failing relay. ──
                if (relay_registry::is_registered(relay_reg, rid)) {
                    relay_registry::set_reputation(relay_reg, rid, 0);

                    let relay_info = relay_registry::borrow_info(relay_reg, rid);
                    let relay_stake_amount = relay_registry::info_stake_amount(relay_info);
                    let slash_amount = relay_stake_amount * constants::slash_percentage_bps() / bp;

                    // Other assigned relays (excluding this slashed one) receive the
                    // relay-share of the slash in pay_slash (payout isolation reused).
                    let mut other_relays = vector::empty<ID>();
                    let mut orr = 0;
                    while (orr < num_relays) {
                        let oid = *vector::borrow(&assigned_relays, orr);
                        if (oid != rid) { other_relays.push_back(oid); };
                        orr = orr + 1;
                    };

                    escrow.slash_amount = slash_amount;
                    escrow.slash_relay_miner_id = rid;
                    escrow.slash_quality = r_quality;
                    escrow.slash_other_relays = other_relays;

                    event::emit(RelaySlashed {
                        room_id,
                        relay_miner_id: rid,
                        slash_amount,
                    });
                };
            } else if (!r_live) {
                // ── RO-016 liveness gate: a covered, healthy STANDBY that did NOT
                // answer the probe (median duration_seconds == 0) earns 0 and folds
                // back. Reputation still set to its (good) quality — it was healthy,
                // just not live this round; no slash (DA C4 standby-grinding closed). ──
                relay_registry::set_reputation(relay_reg, rid, r_quality);
            } else {
                // ── Pay branch: qualifying relay (covered, quality>0, live) earns
                // its equal per-relay share. ──
                relay_registry::set_reputation(relay_reg, rid, r_quality);
                if (per_relay_share > 0 && relay_registry::is_registered(relay_reg, rid)) {
                    let relay_info = relay_registry::borrow_info(relay_reg, rid);
                    let relay_operator = relay_registry::info_operator(relay_info);
                    let relay_coin = coin::from_balance(
                        balance::split(&mut escrow.escrow, per_relay_share), ctx,
                    );
                    transfer::public_transfer(relay_coin, relay_operator);
                    paid_relay_ids.push_back(rid);
                    paid_relay_rewards.push_back(per_relay_share);
                };
            };

            di = di + 1;
        };

        // ── Validator shares (FK-3: each validator scores vs the median of the
        // relay it attested, NOT a room-wide median). ──
        if (validator_pool > 0 && num_proofs > 0) {
            let mut accuracy_scores = vector::empty<u64>();
            let mut total_accuracy: u64 = 0;
            let mut j = 0;
            while (j < num_proofs) {
                // Find this proof's relay index → its per-relay median bytes.
                let p_rid = escrow.proofs[j].relay_miner_id;
                let mut rel_median = 0;
                let mut mi = 0;
                while (mi < num_relays) {
                    if (*vector::borrow(&assigned_relays, mi) == p_rid) {
                        rel_median = *vector::borrow(&relay_median_bytes, mi);
                        break
                    };
                    mi = mi + 1;
                };
                let score = compute_accuracy_score(
                    escrow.proofs[j].bytes_transferred, rel_median,
                );
                accuracy_scores.push_back(score);
                total_accuracy = total_accuracy + score;
                j = j + 1;
            };

            let mut k = 0;
            while (k < num_proofs) {
                let proof = &escrow.proofs[k];
                let validator_info = validator_registry::borrow_info(
                    validator_reg, proof.validator_id,
                );
                let operator = validator_registry::info_operator(validator_info);

                let share = if (total_accuracy > 0) {
                    validator_pool * accuracy_scores[k] / total_accuracy
                } else {
                    validator_pool / num_proofs
                };

                if (share > 0) {
                    let v_coin = coin::from_balance(
                        balance::split(&mut escrow.escrow, share), ctx,
                    );
                    transfer::public_transfer(v_coin, operator);
                };

                validator_registry::set_reputation(
                    validator_reg, proof.validator_id, accuracy_scores[k],
                );

                k = k + 1;
            };
        };

        // Route CP pool to assigned CP operator
        if (cp_pool > 0 && option::is_some(&assigned_cp_opt)) {
            let cp_miner_id = *option::borrow(&assigned_cp_opt);
            let cp_info = control_plane_registry::borrow_info(cp_reg, cp_miner_id);
            let cp_operator = control_plane_registry::info_operator(cp_info);
            let cp_coin = coin::from_balance(
                balance::split(&mut escrow.escrow, cp_pool), ctx,
            );
            transfer::public_transfer(cp_coin, cp_operator);
        };

        // Route signaling pool to assigned signaling operator
        if (signaling_pool > 0 && option::is_some(&assigned_sig_opt)) {
            let sig_miner_id = *option::borrow(&assigned_sig_opt);
            let sig_info = signaling_registry::borrow_info(signaling_reg, sig_miner_id);
            let sig_operator = signaling_registry::info_operator(sig_info);
            let sig_coin = coin::from_balance(
                balance::split(&mut escrow.escrow, signaling_pool), ctx,
            );
            transfer::public_transfer(sig_coin, sig_operator);
        };

        // Remainder (unrouted pools + slashed-relay shares + dust) to creator.
        let remaining = balance::value(&escrow.escrow);
        if (remaining > 0) {
            let remainder_coin = coin::from_balance(
                balance::split(&mut escrow.escrow, remaining), ctx,
            );
            transfer::public_transfer(remainder_coin, escrow.creator);
        };

        escrow.distributed = true;

        // RO-024 (1.7): additive per-relay breakdown vectors on RewardsDistributed.
        event::emit(RewardsDistributed {
            room_id,
            relay_reward: relay_pool,
            validator_pool,
            cp_pool,
            signaling_pool,
            remainder: remaining,
            relay_ids: paid_relay_ids,
            relay_rewards: paid_relay_rewards,
        });
    }

    /// Pay a recorded slash obligation. Called by the relay operator.
    ///
    /// Deducts slash_amount from the relay's StakePosition and distributes
    /// the slashed Coin proportionally based on quality at distribution time:
    ///   - creator_share = slash × (10000 - quality) / 10000
    ///   - relay_share   = slash × quality / 10000  (split equally among other relays)
    ///
    /// If no other relays exist in the room, 100% goes to the creator.
    /// Restores relay reputation to base (10000) after payment.
    public fun pay_slash(
        escrow:      &mut RoomEscrow,
        relay_stake: &mut staking::StakePosition,
        relay_reg:   &mut RelayRegistry,
        ctx:         &mut TxContext,
    ) {
        assert!(escrow.slash_amount > 0, E_NO_SLASH_PENDING);
        assert!(
            staking::miner_id(relay_stake) == escrow.slash_relay_miner_id,
            E_WRONG_STAKE,
        );

        let mut coin = staking::slash(relay_stake, escrow.slash_amount, ctx);
        let total = coin::value(&coin);
        let bp = constants::basis_points();
        let quality = escrow.slash_quality;
        let slashed_id = escrow.slash_relay_miner_id;
        let room_id = escrow.room_id;

        // Proportional split: higher quality -> more to other relays
        let relay_total = total * quality / bp;
        let num_others = vector::length(&escrow.slash_other_relays);

        // RO-024 (1.7): per-beneficiary breakdown for RelaySlashRedistributed.
        let mut beneficiaries = vector::empty<ID>();
        let mut amounts       = vector::empty<u64>();

        // Distribute relay share equally among other assigned relays
        if (relay_total > 0 && num_others > 0) {
            let per_relay = relay_total / num_others;
            let mut i = 0;
            while (i < num_others) {
                let other_id = *vector::borrow(&escrow.slash_other_relays, i);
                let info = relay_registry::borrow_info(relay_reg, other_id);
                let operator = relay_registry::info_operator(info);
                if (per_relay > 0) {
                    let r_coin = coin::split(&mut coin, per_relay, ctx);
                    transfer::public_transfer(r_coin, operator);
                    beneficiaries.push_back(other_id);
                    amounts.push_back(per_relay);
                };
                i = i + 1;
            };
        };

        // Remainder (creator share + rounding dust) to room creator
        let creator_amount = coin::value(&coin);
        if (creator_amount > 0) {
            transfer::public_transfer(coin, escrow.creator);
        } else {
            coin::destroy_zero(coin);
        };

        // RO-024 (1.7): emit the additive slash-redistribution breakdown.
        event::emit(RelaySlashRedistributed {
            room_id,
            slashed: slashed_id,
            beneficiaries,
            amounts,
            creator_amount,
        });

        // Restore base reputation so relay can operate again
        relay_registry::set_reputation(
            relay_reg, escrow.slash_relay_miner_id, bp,
        );

        escrow.slash_amount = 0;
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Compute scarcity-based reward ratios from live node counts (SCAR-02).
    ///
    /// Algorithm: linear inverse ratio — scarcer role types get higher weight.
    /// Each raw weight = total_nodes / max(count_i, 1). Normalize to basis points.
    /// Iterative clamping (SCAR-03): clamp out-of-bounds shares to
    /// [floor, ceiling], redistribute the remaining budget proportionally among
    /// the still-unclamped shares, then RE-CLAMP the recomputed shares and repeat
    /// until stable (<= 4 passes — each pass either clamps at least one more
    /// share or terminates). The exact-sum remainder goes to a share with
    /// ceiling slack, so every returned share lies in [floor, ceiling] and the
    /// four sum to exactly 10_000 (always feasible: 4*floor = 2_000 <= 10_000
    /// <= 4*ceiling = 32_000).
    public(package) fun compute_scarcity_ratios(
        relay_count: u64,
        validator_count: u64,
        cp_count: u64,
        signaling_count: u64,
    ): (u64, u64, u64, u64) {
        let bp = constants::basis_points();
        let total = relay_count + validator_count + cp_count + signaling_count;

        if (total == 0) {
            return (2500, 2500, 2500, 2500)
        };

        // Linear inverse ratio: scarcer type gets higher weight
        let raw_relay = total / if (relay_count > 0) { relay_count } else { 1 };
        let raw_validator = total / if (validator_count > 0) { validator_count } else { 1 };
        let raw_cp = total / if (cp_count > 0) { cp_count } else { 1 };
        let raw_sig = total / if (signaling_count > 0) { signaling_count } else { 1 };
        let raw_total = raw_relay + raw_validator + raw_cp + raw_sig;

        // Normalize to basis points
        let n_relay = raw_relay * bp / raw_total;
        let n_validator = raw_validator * bp / raw_total;
        let n_cp = raw_cp * bp / raw_total;
        let n_sig = raw_sig * bp / raw_total;

        let floor = constants::scarcity_floor_bps();
        let ceiling = constants::scarcity_ceiling_bps();

        // Iterative clamp-and-redistribute (SCAR-03): clamping one share changes
        // the budget available to the others, so a single redistribution pass can
        // itself push a share out of bounds (e.g. counts (2,4,17,27) drove cp to
        // 487 < floor). Re-clamp and redistribute until no unclamped share
        // violates bounds; each pass clamps at least one more share or breaks,
        // so the loop terminates in <= 4 passes.
        let raw = vector[raw_relay, raw_validator, raw_cp, raw_sig];
        let mut value = vector[n_relay, n_validator, n_cp, n_sig];
        let mut is_clamped = vector[false, false, false, false];

        loop {
            let mut newly_clamped = false;
            let mut i = 0;
            while (i < 4) {
                if (!is_clamped[i] && (value[i] < floor || value[i] > ceiling)) {
                    *vector::borrow_mut(&mut value, i) = clamp(value[i], floor, ceiling);
                    *vector::borrow_mut(&mut is_clamped, i) = true;
                    newly_clamped = true;
                };
                i = i + 1;
            };
            if (!newly_clamped) break;

            let mut clamped_budget = 0;
            let mut unclamped_raw = 0;
            let mut j = 0;
            while (j < 4) {
                if (is_clamped[j]) {
                    clamped_budget = clamped_budget + value[j];
                } else {
                    unclamped_raw = unclamped_raw + raw[j];
                };
                j = j + 1;
            };
            if (unclamped_raw == 0) break; // all four clamped — remainder below

            // At most one share can exceed the ceiling (two would need > 16_000
            // of a <= 10_000 budget), so clamped_budget <= 8_000 + 3*500 < bp
            // and this subtraction cannot underflow.
            let remaining_budget = bp - clamped_budget;
            let mut k = 0;
            while (k < 4) {
                if (!is_clamped[k]) {
                    *vector::borrow_mut(&mut value, k) =
                        raw[k] * remaining_budget / unclamped_raw;
                };
                k = k + 1;
            };
        };

        // Exact-sum remainder (integer-division dust, or the 500-bps gap when
        // all four shares clamp at one ceiling + three floors): add it to a
        // share with ceiling slack — preferring an unclamped share — never
        // unconditionally to one fixed role. A share with enough slack always
        // exists: with >= 2 unclamped shares the dust is < 4 bps and at most one
        // share can sit near the ceiling; with all four clamped the gap is
        // exactly 500 bps and every floor-clamped share has 7_500 bps of slack.
        let mut allocated = 0;
        let mut i = 0;
        while (i < 4) {
            allocated = allocated + value[i];
            i = i + 1;
        };
        let deficit = bp - allocated;
        if (deficit > 0) {
            let mut assigned = false;
            let mut pass = 0;
            while (pass < 2 && !assigned) {
                let mut m = 0;
                while (m < 4 && !assigned) {
                    let eligible = if (pass == 0) { !is_clamped[m] } else { true };
                    if (eligible && value[m] + deficit <= ceiling) {
                        *vector::borrow_mut(&mut value, m) = value[m] + deficit;
                        assigned = true;
                    };
                    m = m + 1;
                };
                pass = pass + 1;
            };
        };

        (value[0], value[1], value[2], value[3])
    }

    /// Clamp a value to [min_val, max_val].
    fun clamp(val: u64, min_val: u64, max_val: u64): u64 {
        if (val < min_val) { min_val }
        else if (val > max_val) { max_val }
        else { val }
    }

    /// Compute quality multiplier from median packet loss (basis points).
    /// Returns a basis-point multiplier: 10000 (excellent), 8000 (good),
    /// 5000 (acceptable), or 0 (slash).
    public(package) fun compute_quality_multiplier(median_packet_loss_bps: u64): u64 {
        if (median_packet_loss_bps <= constants::loss_threshold_excellent()) {
            constants::quality_excellent_bps()
        } else if (median_packet_loss_bps <= constants::loss_threshold_good()) {
            constants::quality_good_bps()
        } else if (median_packet_loss_bps <= constants::loss_threshold_acceptable()) {
            constants::quality_acceptable_bps()
        } else {
            constants::quality_slash_bps()
        }
    }

    /// Compute median of a vector of u64 values.
    /// Sorts a copy of the input, then picks the middle element (or average of
    /// two middle elements for even count).
    public(package) fun compute_median(values: &vector<u64>): u64 {
        let len = values.length();
        if (len == 0) return 0;
        if (len == 1) return values[0];

        // Copy and sort (insertion sort -- small vectors expected, 2-5 proofs)
        let mut sorted = *values;
        let mut i = 1;
        while (i < len) {
            let key = sorted[i];
            let mut j = i;
            while (j > 0 && sorted[j - 1] > key) {
                *&mut sorted[j] = sorted[j - 1];
                j = j - 1;
            };
            *&mut sorted[j] = key;
            i = i + 1;
        };

        if (len % 2 == 1) {
            sorted[len / 2]
        } else {
            // Average of two middle elements (integer division)
            (sorted[len / 2 - 1] + sorted[len / 2]) / 2
        }
    }

    /// Compute accuracy score: how close a validator's reported value is to the median.
    /// Returns a basis-point score (10000 = exact match, lower = further from median).
    public(package) fun compute_accuracy_score(validator_value: u64, median: u64): u64 {
        if (median == 0) return constants::basis_points();

        let diff = if (validator_value > median) {
            validator_value - median
        } else {
            median - validator_value
        };

        let deviation_bps = diff * constants::basis_points() / median;

        if (deviation_bps >= constants::basis_points()) {
            0
        } else {
            constants::basis_points() - deviation_bps
        }
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    /// Returns current scarcity-based reward split ratios in basis points.
    /// (relay_bps, validator_bps, cp_bps, signaling_bps) — sums to 10_000.
    /// Used by client devInspect for dashboard display.
    public fun get_scarcity_ratios(
        relay_reg:     &RelayRegistry,
        validator_reg: &ValidatorRegistry,
        cp_reg:        &ControlPlaneRegistry,
        signaling_reg: &SignalingRegistry,
    ): (u64, u64, u64, u64) {
        let relay_count = relay_registry::active_count(relay_reg);
        let validator_count = validator_registry::active_count(validator_reg);
        let cp_count = control_plane_registry::active_cp_count(cp_reg);
        let sig_count = signaling_registry::active_signaling_count(signaling_reg);

        compute_scarcity_ratios(relay_count, validator_count, cp_count, sig_count)
    }

    public fun escrow_room_id(e: &RoomEscrow): ID        { e.room_id }
    public fun escrow_creator(e: &RoomEscrow): address    { e.creator }
    public fun escrow_balance(e: &RoomEscrow): u64        { balance::value(&e.escrow) }
    public fun escrow_proof_count(e: &RoomEscrow): u64    { e.proofs.length() }
    public fun escrow_is_distributed(e: &RoomEscrow): bool { e.distributed }
    public fun escrow_slash_amount(e: &RoomEscrow): u64          { e.slash_amount }
    public fun escrow_slash_quality(e: &RoomEscrow): u64         { e.slash_quality }
    public fun escrow_slash_relay_id(e: &RoomEscrow): ID         { e.slash_relay_miner_id }
    public fun escrow_slash_other_relays(e: &RoomEscrow): vector<ID> { e.slash_other_relays }

    #[test_only]
    /// RO-017: read the chain-derived relay_role of the proof at `idx`
    /// (0 = primary / assigned_relays[0], 1 = standby).
    public fun escrow_proof_relay_role(e: &RoomEscrow, idx: u64): u8 {
        e.proofs[idx].relay_role
    }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    /// Create a RoomEscrow for testing (bypasses create_escrow checks).
    public fun create_escrow_for_testing(
        room_id: ID,
        creator: address,
        payment: Coin<SUI>,
        ctx: &mut TxContext,
    ): RoomEscrow {
        RoomEscrow {
            id: object::new(ctx),
            room_id,
            creator,
            escrow: coin::into_balance(payment),
            proofs: vector::empty(),
            distributed: false,
            slash_amount: 0,
            slash_relay_miner_id: object::id_from_address(@0x0),
            slash_quality: 0,
            slash_other_relays: vector::empty(),
        }
    }

    #[test_only]
    /// Add a proof directly for testing (bypasses signature verification).
    /// `relay_role` (RO-017): 0 = primary, 1 = standby — supplied explicitly here
    /// since the test path bypasses the chain-derivation in submit_session_proof.
    public fun add_proof_for_testing(
        escrow: &mut RoomEscrow,
        validator_id: ID,
        room_id: ID,
        relay_miner_id: ID,
        packets_forwarded: u64,
        bytes_transferred: u64,
        unique_peers: u64,
        duration_seconds: u64,
        avg_latency_ms: u64,
        packet_loss_bps: u64,
        jitter_ms: u64,
        submitted_at: u64,
        relay_role: u8,
    ) {
        let proof = SessionProof {
            validator_id,
            room_id,
            relay_miner_id,
            packets_forwarded,
            bytes_transferred,
            unique_peers,
            duration_seconds,
            avg_latency_ms,
            packet_loss_bps,
            jitter_ms,
            submitted_at,
            relay_role,
        };
        escrow.proofs.push_back(proof);
    }

    #[test_only]
    /// Share a RoomEscrow for testing.
    public fun share_escrow_for_testing(escrow: RoomEscrow) {
        transfer::share_object(escrow);
    }

    #[test_only]
    /// Check if validator is assigned to the escrow's room (for testing).
    /// Aborts with E_VALIDATOR_NOT_ASSIGNED if not.
    public fun check_validator_assigned_for_testing(
        escrow: &RoomEscrow,
        room_mgr: &RoomManager,
        validator_miner_id: ID,
    ) {
        let room_info = room_manager::borrow_room(room_mgr, escrow.room_id);
        let assigned = room_manager::room_assigned_validators(room_info);
        let mut found = false;
        let mut i = 0;
        while (i < vector::length(&assigned)) {
            if (*vector::borrow(&assigned, i) == validator_miner_id) {
                found = true;
                break
            };
            i = i + 1;
        };
        assert!(found, E_VALIDATOR_NOT_ASSIGNED);
    }

    #[test_only]
    /// Set slash fields on an escrow for testing pay_slash.
    public fun set_slash_for_testing(
        escrow: &mut RoomEscrow,
        slash_amount: u64,
        relay_miner_id: ID,
        quality: u64,
        other_relays: vector<ID>,
    ) {
        escrow.slash_amount = slash_amount;
        escrow.slash_relay_miner_id = relay_miner_id;
        escrow.slash_quality = quality;
        escrow.slash_other_relays = other_relays;
    }

    #[test_only]
    /// Destroy a RoomEscrow for testing cleanup.
    public fun destroy_escrow_for_testing(escrow: RoomEscrow) {
        let RoomEscrow {
            id, room_id: _, creator: _, escrow: bal, proofs: _,
            distributed: _, slash_amount: _, slash_relay_miner_id: _,
            slash_quality: _, slash_other_relays: _,
        } = escrow;
        object::delete(id);
        balance::destroy_for_testing(bal);
    }
}
