/// Canary forwarding-audit slashing — REQ-CFA-006 / INV-C / D-CFA-8,9.
///
/// A relay that forwards a CANARY frame whose ciphertext DIVERGES from what the
/// covering validators locally recomputed (or DROPS it) is slashed on-chain. A
/// covering cell of >= 2 DISTINCT validators each ATTEST the SAME divergence by
/// signing a FROZEN 145-byte canonical proof message with their Wallet-B SESSION
/// keypair ONLY. This module verifies each session signature, resolves each
/// attestation to a DISTINCT `validator_miner_id` (so a Wallet-A↔Wallet-B link
/// never appears on-chain — INV-C), enforces the >= 2-distinct quorum, checks the
/// relay is assigned to the room, asserts a real divergence, then slashes the
/// relay's bond.
///
/// This is a clean top-layer ADDITION: no existing module imports it.
/// Error code namespace: 680-689.
///
/// ── PER-ATTESTATION RESOLUTION (CRITICAL — differs from submit_session_proof) ──
/// economic_layer::submit_session_proof resolves its SINGLE attester via ctx.sender().
/// Here there are >= 2 attesters but ONE tx sender, so each attestation's validator is
/// resolved from ITS OWN session pubkey:
///   addr_i    = sui::address::from_bytes(blake2b256(0x00 || pubkey_session_i))
///   miner_id_i = validator_registry::lookup_session_wallet(validator_reg, addr_i)
/// Distinct miner_ids are deduped via a VecSet<ID>; a single validator rotating
/// Wallet-B twice yields 2 distinct pubkeys but ONE miner_id => size 1 => ABORT. The
/// daemon cannot enforce this distinctness (it never sees Wallet-A); only this
/// package-gated chain path can.
///
/// ── FROZEN 145-BYTE CANONICAL MESSAGE (byte-mirror of proof.ts canonicalProofMessage) ──
///   off0   room_id          BCS<ID>  = raw 32 bytes
///   off32  relay_miner_id   BCS<ID>  = raw 32 bytes
///   off64  canary_id        BCS<u64> = 8-byte little-endian
///   off72  frame_seq        BCS<u64> = 8-byte little-endian
///   off80  expected_hash    RAW 32 bytes (NOT bcs::to_bytes — a vector<u8> bcs adds a
///                           ULEB length prefix that would break the mirror)
///   off112 observed_present 1-byte tag: 0x01 present / 0x00 MISSING (drop)
///   off113 observed_hash    RAW 32 bytes (all-zero when drop)
///   total                   145
module dvconf::canary_audit {
    use sui::event;
    use sui::bcs;
    use sui::ed25519;
    use sui::hash;
    use sui::coin;
    use sui::vec_set::{Self, VecSet};
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::staking::{Self, StakePosition};

    // ── Errors (680-689) ──
    /// Network is paused (SoT paused-flag invariant).
    const E_PAUSED: u64                          = 680;
    /// attestations payload is malformed (pubkey/sig vectors length mismatch, or empty).
    const E_MALFORMED_ATTESTATIONS: u64          = 681;
    /// A session pubkey resolved to no registered validator (no session-wallet binding).
    const E_SESSION_WALLET_NOT_FOUND: u64        = 682;
    /// An attestation signature failed ed25519 verification over the canonical message.
    const E_INVALID_SIGNATURE: u64               = 683;
    /// Fewer than MIN_DISTINCT_ATTESTERS (2) DISTINCT validator_miner_ids (INV-C quorum).
    const E_INSUFFICIENT_DISTINCT_ATTESTERS: u64 = 684;
    /// The culprit relay is not assigned to the audited room.
    const E_RELAY_NOT_ASSIGNED: u64              = 685;
    /// No actual divergence (expected == observed AND observed present).
    const E_NO_DIVERGENCE: u64                   = 686;
    /// The provided bond StakePosition is not the relay's (miner_id mismatch).
    const E_WRONG_STAKE: u64                     = 687;
    /// An expected/observed hash is not exactly 32 bytes (canonical-message shape).
    const E_BAD_HASH_LEN: u64                    = 688;

    /// Minimum distinct validator_miner_ids required to slash (RO-023c / DESIGN §4.1).
    /// Equals constants::MIN_PROOFS_FOR_DISTRIBUTION (2) but the canary quorum is its
    /// own knob, so it is named locally.
    const MIN_DISTINCT_ATTESTERS: u64 = 2;

    /// Byte length of the FROZEN canonical proof message (must match proof.ts).
    const CANARY_PROOF_MSG_LEN: u64 = 145;

    /// The fraction of the relay bond slashed per proven divergence, in basis points.
    /// D-CFA-9: a single divergence is a hard fault; the slash is a fixed share of the
    /// bond. 1000 bps = 10% (conservative; full economic tuning deferred — see fidelity).
    const SLASH_BPS: u64 = 1000;
    const BASIS_POINTS: u64 = 10_000;

    // ══════════════════════════════════════════════════════════
    // EVENT
    // ══════════════════════════════════════════════════════════

    /// Emitted when a relay is slashed for a proven canary forwarding divergence.
    /// Carries the distinct attesting validator_miner_ids (NO session pubkeys / NO
    /// Wallet-A material — INV-C). `observed_present=false` => the relay DROPPED the frame.
    public struct CanaryDivergenceSlashed has copy, drop {
        room_id:          ID,
        relay_miner_id:   ID,
        canary_id:        u64,
        frame_seq:        u64,
        slash_amount:     u64,
        attester_count:   u64,
        attester_ids:     vector<ID>,
        observed_present: bool,
    }

    // ══════════════════════════════════════════════════════════
    // CANONICAL MESSAGE BUILDER (byte-mirror of proof.ts::canonicalProofMessage)
    // ══════════════════════════════════════════════════════════

    /// Rebuild the FROZEN 145-byte canonical proof message. See the module header for
    /// the exact field order / encodings. CRITICAL: room_id/relay_miner_id (ID, fixed 32)
    /// and canary_id/frame_seq (u64) go through bcs::to_bytes; the 32-byte hash vectors
    /// are RAW-appended (NO bcs — a vector<u8> bcs adds a ULEB length prefix); the presence
    /// tag is a single pushed byte. On a drop (observed_present=false) the observed-hash
    /// region is an all-zero 32-byte block.
    fun build_canonical_message(
        room_id:          ID,
        relay_miner_id:   ID,
        canary_id:        u64,
        frame_seq:        u64,
        expected_hash:    vector<u8>,
        observed_hash:    vector<u8>,
        observed_present: bool,
    ): vector<u8> {
        assert!(vector::length(&expected_hash) == 32, E_BAD_HASH_LEN);

        let mut msg = vector::empty<u8>();
        vector::append(&mut msg, bcs::to_bytes(&room_id));        // off0  32
        vector::append(&mut msg, bcs::to_bytes(&relay_miner_id)); // off32 32
        vector::append(&mut msg, bcs::to_bytes(&canary_id));      // off64 8 LE
        vector::append(&mut msg, bcs::to_bytes(&frame_seq));      // off72 8 LE
        vector::append(&mut msg, expected_hash);                  // off80 RAW 32
        if (observed_present) {
            msg.push_back(1u8);                                   // off112 presence
            assert!(vector::length(&observed_hash) == 32, E_BAD_HASH_LEN);
            vector::append(&mut msg, observed_hash);              // off113 RAW 32
        } else {
            msg.push_back(0u8);                                   // off112 presence (drop)
            let mut zeros = vector::empty<u8>();
            let mut z = 0;
            while (z < 32) { zeros.push_back(0u8); z = z + 1; };
            vector::append(&mut msg, zeros);                      // off113 all-zero 32
        };

        assert!(vector::length(&msg) == CANARY_PROOF_MSG_LEN, E_BAD_HASH_LEN);
        msg
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY — slash for a proven canary forwarding divergence
    // ══════════════════════════════════════════════════════════

    /// Slash `relay_bond` for a canary forwarding divergence attested by >= 2 DISTINCT
    /// validators (Wallet-B session signatures ONLY). The `pubkeys`/`sigs` vectors are
    /// positionally paired (attestation i = pubkeys[i] over the canonical message, sigs[i]).
    ///
    /// Order of checks (the divergence assertion fires BEFORE signature verification so a
    /// no-divergence call aborts E_NO_DIVERGENCE regardless of the supplied sigs):
    ///   1. !is_paused                                       (SoT paused-flag)
    ///   2. relay_bond.miner_id == relay_miner_id            (right bond)
    ///   3. relay_miner_id ∈ room.assigned_relays            (R_k assigned)
    ///   4. real divergence (drop, OR present-and-different)
    ///   5. payload shape (pubkeys.len == sigs.len, > 0)
    ///   6. per-attestation: ed25519_verify + resolve miner_id + VecSet dedup
    ///   7. distinct count >= 2
    ///   8. slash + emit
    public fun slash_for_canary_divergence(
        net_reg:          &NetworkRegistry,
        validator_reg:    &ValidatorRegistry,
        room_mgr:         &RoomManager,
        relay_bond:       &mut StakePosition,
        room_id:          ID,
        relay_miner_id:   ID,
        canary_id:        u64,
        frame_seq:        u64,
        expected_hash:    vector<u8>,
        observed_hash:    vector<u8>,
        observed_present: bool,
        pubkeys:          vector<vector<u8>>,
        sigs:             vector<vector<u8>>,
        ctx:              &mut TxContext,
    ) {
        // 1. SoT paused-flag invariant — checked on this state-mutating entry.
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        // 2. The provided bond must belong to the accused relay.
        assert!(staking::miner_id(relay_bond) == relay_miner_id, E_WRONG_STAKE);

        // 3. R_k must be assigned to the audited room.
        let room_info = room_manager::borrow_room(room_mgr, room_id);
        let assigned = room_manager::room_assigned_relays(room_info);
        assert!(vector::contains(&assigned, &relay_miner_id), E_RELAY_NOT_ASSIGNED);

        // 4. There must be a REAL divergence: either the relay dropped the frame
        //    (observed_present == false) or it forwarded a DIFFERENT ciphertext.
        let diverged = !observed_present || (expected_hash != observed_hash);
        assert!(diverged, E_NO_DIVERGENCE);

        // 5. Payload shape.
        let n = vector::length(&pubkeys);
        assert!(n > 0 && vector::length(&sigs) == n, E_MALFORMED_ATTESTATIONS);

        // Rebuild the FROZEN canonical message ONCE (every attester signed the SAME bytes).
        let msg = build_canonical_message(
            room_id, relay_miner_id, canary_id, frame_seq,
            expected_hash, observed_hash, observed_present,
        );

        // 6. Per-attestation verify + resolve + dedup (CRITICAL #1 — INV-C). Kept INLINE:
        //    the >=2-Wallet-B verifier is not extractable (IC-4 derive-then-verify loop).
        let mut distinct: VecSet<ID> = vec_set::empty();
        let mut i = 0;
        while (i < n) {
            let pk = vector::borrow(&pubkeys, i);
            let sig = vector::borrow(&sigs, i);

            // ed25519 over the canonical message (raw session sig — matches proof.ts).
            assert!(ed25519::ed25519_verify(sig, pk, &msg), E_INVALID_SIGNATURE);

            // Resolve THIS attestation's validator from its OWN session pubkey:
            // addr = blake2b256(0x00 || pubkey); miner_id = lookup_session_wallet(addr).
            let mut flagged = vector::empty<u8>();
            flagged.push_back(0x00); // Ed25519 scheme flag
            vector::append(&mut flagged, *pk);
            let addr = sui::address::from_bytes(hash::blake2b256(&flagged));

            assert!(
                validator_registry::has_session_wallet(validator_reg, addr),
                E_SESSION_WALLET_NOT_FOUND,
            );
            let miner_id = validator_registry::lookup_session_wallet(validator_reg, addr);

            // Dedup: a validator rotating Wallet-B twice -> same miner_id -> not added twice.
            if (!vec_set::contains(&distinct, &miner_id)) {
                vec_set::insert(&mut distinct, miner_id);
            };
            i = i + 1;
        };

        // 7. INV-C distinctness quorum: >= 2 DISTINCT validator_miner_ids.
        let attester_count = vec_set::size(&distinct);
        assert!(attester_count >= MIN_DISTINCT_ATTESTERS, E_INSUFFICIENT_DISTINCT_ATTESTERS);

        // 8. Slash a fixed share of the bond. D-CFA-8: the bond is the relay's shared
        //    StakePosition; we deduct SLASH_BPS of the CURRENT bond value. Redistribution
        //    fidelity (the economic_layer::pay_slash quality-weighted split among other
        //    relays) is intentionally MINIMAL here — the slashed Coin is sent to the room
        //    creator (the slash sink), keeping the shared-bond path hermetic. Full
        //    redistribution is the W-E9 owned-stake lane's job; see designChoices.
        let bond_value = staking::amount(relay_bond);
        let slash_amount = bond_value * SLASH_BPS / BASIS_POINTS;
        let slashed: coin::Coin<sui::sui::SUI> = staking::slash(relay_bond, slash_amount, ctx);

        let room_creator = room_manager::room_creator(room_info);
        transfer::public_transfer(slashed, room_creator);

        event::emit(CanaryDivergenceSlashed {
            room_id,
            relay_miner_id,
            canary_id,
            frame_seq,
            slash_amount,
            attester_count,
            attester_ids: vec_set::into_keys(distinct),
            observed_present,
        });
    }

    // ══════════════════════════════════════════════════════════
    // TEST-ONLY — expose the canonical-message builder for the golden-vector byte-mirror
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun build_canonical_message_for_testing(
        room_id:          ID,
        relay_miner_id:   ID,
        canary_id:        u64,
        frame_seq:        u64,
        expected_hash:    vector<u8>,
        observed_hash:    vector<u8>,
        observed_present: bool,
    ): vector<u8> {
        build_canonical_message(
            room_id, relay_miner_id, canary_id, frame_seq,
            expected_hash, observed_hash, observed_present,
        )
    }
}
