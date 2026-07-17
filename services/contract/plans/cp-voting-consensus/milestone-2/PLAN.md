# M2: Consensus-First, Verify-on-Dispute — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor room assignment to consensus-first model (happy path = zero on-chain computation), align daemon scoring with on-chain formula, add dispute fallback, and build consensus progress UI.

**Architecture:** CPs compute scores off-chain with deterministic formula + canonical sort, submit `(tuple, submitted_score)` on-chain. Contract groups by score equality — ≥2/3 of votes cast finalizes without scoring. Dispute fallback: room creator triggers on-chain verification after cooldown. Client shows live voting progress via ProposalSubmitted events.

**Tech Stack:** Sui Move (contracts), TypeScript/Vitest (daemon), React/TypeScript/Vitest (client)

**TDD Approach:** Every task starts with a failing test, then minimal implementation to pass it.

---

## File Structure

### On-Chain (dvconf-contracts)
| File | Action | Responsibility |
|------|--------|---------------|
| `sources/core/constants.move` | Modify (lines 88-109) | Add PVR_DISPUTE_COOLDOWN, PVR_CONSENSUS_THRESHOLD_BPS |
| `sources/registry/room_manager.move` | Modify (lines 22-465) | Refactor submit_pairing_proposal, add finalize_room, update structs/events |
| `tests/scoring/pvr_consensus_tests.move` | Create | All M2 Move tests (consensus happy path, dispute, finalize_room guards) |

### Off-Chain (dvconf-daemons/apps/cp-daemon)
| File | Action | Responsibility |
|------|--------|---------------|
| `src/scoring.ts` | Rewrite (lines 1-205) | Match on-chain 6-factor formula exactly |
| `src/event-handler.ts` | Modify (lines 48-54, 211-317) | Use PVR_WEIGHTS, compute submitted_score, pass to TX |
| `src/room-assignment.ts` | Modify (lines 60-108) | Add submitted_score param to submitProposal TX |
| `src/__tests__/scoring.test.ts` | Rewrite (lines 1-129) | Test new 6-factor formula + canonical sort |

### Client (dvconf-client)
| File | Action | Responsibility |
|------|--------|---------------|
| `src/hooks/useChain.ts` | Modify (lines 82-121) | Accept expectedParticipants param |
| `src/pages/HomePage.tsx` | Modify (lines 18-49) | Add participant count input |
| `src/hooks/useRoomConsensus.ts` | Create | Subscribe to ProposalSubmitted events, group by score |
| `src/components/ConsensusProgress.tsx` | Create | Voting progress bars + tooltip + finalize button |
| `src/pages/RoomPage.tsx` | Modify (lines 269-296) | Integrate ConsensusProgress component |
| `src/hooks/dashboard/useActiveRooms.ts` | Modify (lines 23-34) | Add verified_score + consensus_reached to BCS decode |
| `src/components/dashboard/RoomLifecyclePanel.tsx` | Modify (lines 31-86) | Show score + resolution badge |

---

## Task 1: On-Chain — New Constants + Error Codes

**Files:**
- Modify: `sources/core/constants.move:88-192`
- Modify: `sources/registry/room_manager.move:22-33`
- Test: `tests/scoring/pvr_consensus_tests.move` (create)

- [ ] **Step 1: Write failing test — new constants exist**

Create `tests/scoring/pvr_consensus_tests.move`:

```move
#[test_only]
module dvconf::pvr_consensus_tests {
    use dvconf::constants;

    #[test]
    fun test_dispute_cooldown_constant() {
        assert!(constants::pvr_dispute_cooldown() == 2, 0);
    }

    #[test]
    fun test_consensus_threshold_constant() {
        assert!(constants::pvr_consensus_threshold_bps() == 6_667, 0);
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sui move test --filter pvr_consensus_tests`
Expected: FAIL — `pvr_dispute_cooldown` and `pvr_consensus_threshold_bps` not found

- [ ] **Step 3: Add constants and accessors**

In `sources/core/constants.move`, after line 109 (`PVR_PROPOSER_REWARD`), add:

```move
    // ── PVR Consensus ──
    const PVR_DISPUTE_COOLDOWN: u64 = 2;          // epochs before creator can trigger dispute
    const PVR_CONSENSUS_THRESHOLD_BPS: u64 = 6_667; // 2/3 of votes cast
```

After the last PVR accessor (line ~192), add:

```move
    public fun pvr_dispute_cooldown(): u64 { PVR_DISPUTE_COOLDOWN }
    public fun pvr_consensus_threshold_bps(): u64 { PVR_CONSENSUS_THRESHOLD_BPS }
```

- [ ] **Step 4: Add new error codes to room_manager**

In `sources/registry/room_manager.move`, after line 33 (`E_INVALID_BALLOT`), add:

```move
    const E_NOT_ROOM_CREATOR: u64    = 550;
    const E_COOLDOWN_NOT_MET: u64    = 551;
    const E_INSUFFICIENT_PROPOSALS: u64 = 552;
```

- [ ] **Step 5: Run test to verify it passes**

Run: `sui move test --filter pvr_consensus_tests`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add sources/core/constants.move sources/registry/room_manager.move tests/scoring/pvr_consensus_tests.move
git commit -m "feat(m2): add PVR consensus constants + finalize_room error codes"
```

---

## Task 2: On-Chain — Update Structs and Events

**Files:**
- Modify: `sources/registry/room_manager.move:39-122`
- Test: `tests/scoring/pvr_consensus_tests.move`

- [ ] **Step 1: Write failing test — RoomInfo has new fields**

Add to `pvr_consensus_tests.move`:

```move
    use dvconf::room_manager::{Self, RoomManager};
    use sui::test_scenario as ts;
    use dvconf::test_helpers;
    use dvconf::constants;

    const ADMIN: address = @0xAD;

    #[test]
    fun test_room_info_has_consensus_fields() {
        let mut scenario = test_helpers::setup_phase2();

        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            // Add a room and verify the new fields default correctly
            room_manager::add_room_for_testing(
                &mut manager, test_helpers::id_from_addr(@0xR1), @0xE1,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                6, ctx,
            );

            let room = room_manager::borrow_room(&manager, test_helpers::id_from_addr(@0xR1));
            assert!(room_manager::room_verified_score(room) == 0, 0);
            assert!(room_manager::room_consensus_reached(room) == false, 1);

            ts::return_shared(manager);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sui move test --filter test_room_info_has_consensus_fields`
Expected: FAIL — `room_verified_score` and `room_consensus_reached` not found

- [ ] **Step 3: Update RoomInfo struct**

In `sources/registry/room_manager.move`, replace the `RoomInfo` struct (lines 39-50):

```move
    public struct RoomInfo has store, copy, drop {
        creator:                address,
        status:                 u8,
        relay_mode:             u8,
        created_at:             u64,
        closed_at:              u64,
        assigned_relays:        vector<ID>,
        assigned_signaling:     Option<ID>,
        assigned_cp:            Option<ID>,
        expected_participants:  u64,
        assigned_validators:    vector<ID>,
        verified_score:         u64,        // NEW: winning score after finalization
        consensus_reached:      bool,       // NEW: true = happy path, false = dispute
    }
```

- [ ] **Step 4: Update PairingProposal struct**

Replace the `PairingProposal` struct (lines 58-64):

```move
    public struct PairingProposal has store, copy, drop {
        cp_id:           ID,
        relay_ids:       vector<ID>,
        validator_ids:   vector<ID>,
        signaling_id:    ID,
        submitted_score: u64,     // CP-computed score (consensus key)
    }
```

- [ ] **Step 5: Update RoomAssigned event**

Replace the `RoomAssigned` struct (lines 97-102):

```move
    public struct RoomAssigned has copy, drop {
        room_id:           ID,
        relay_ids:         vector<ID>,
        signaling_id:      ID,
        relay_mode:        u8,
        verified_score:    u64,
        consensus_reached: bool,
        winning_cp:        ID,
    }
```

- [ ] **Step 6: Add accessor functions for new fields**

Add near the existing room accessors (after `room_assigned_validators`):

```move
    public fun room_verified_score(r: &RoomInfo): u64 { r.verified_score }
    public fun room_consensus_reached(r: &RoomInfo): bool { r.consensus_reached }
```

- [ ] **Step 7: Fix all compilation errors**

Update every place that constructs `RoomInfo` to include the new fields (`verified_score: 0, consensus_reached: false`). This includes:
- `create_room()` function
- `add_room_for_testing()` function

Update every place that constructs `RoomAssigned` event to include new fields. This includes:
- The finalization block in `submit_pairing_proposal()`
- The `assign_relay_and_signaling()` fallback

Update every place that constructs `PairingProposal` — rename `verified_score` to `submitted_score`.

Update `useActiveRooms.ts` BCS struct (lines 23-34) — add `verified_score` and `consensus_reached` fields. (Done in Task 7.)

- [ ] **Step 8: Run test to verify it passes**

Run: `sui move test --filter test_room_info_has_consensus_fields`
Expected: PASS

- [ ] **Step 9: Run ALL tests to check for regressions**

Run: `sui move test`
Expected: All 172+ tests pass (some may need signature updates due to struct changes)

- [ ] **Step 10: Commit**

```bash
git add sources/registry/room_manager.move tests/scoring/pvr_consensus_tests.move
git commit -m "feat(m2): update RoomInfo, PairingProposal, RoomAssigned with consensus fields"
```

---

## Task 3: On-Chain — Refactor submit_pairing_proposal to Consensus-First

**Files:**
- Modify: `sources/registry/room_manager.move:250-465`
- Test: `tests/scoring/pvr_consensus_tests.move`

This is the core change. The function now:
1. Accepts `submitted_score` from the CP
2. Stores proposal without computing score on-chain
3. Groups by `submitted_score` equality
4. Finalizes if any group ≥ 2/3 of votes cast

- [ ] **Step 1: Write failing test — happy path consensus finalization**

Add to `pvr_consensus_tests.move`:

```move
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::caps::{Self, ControlPlaneCap};

    // Test addresses
    const CP1_OP: address = @0xC1;
    const CP2_OP: address = @0xC2;
    const CP3_OP: address = @0xC3;
    const CP1_ID: address = @0xA1;
    const CP2_ID: address = @0xA2;
    const CP3_ID: address = @0xA3;
    const RELAY1: address = @0xB1;
    const RELAY2: address = @0xB2;
    const VAL1: address   = @0xD1;
    const VAL2: address   = @0xD2;
    const SIG1: address   = @0xF1;
    const ROOM1: address  = @0xE1;

    fun setup_consensus(): ts::Scenario {
        let mut scenario = test_helpers::setup_phase2();

        // Register relays
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, test_helpers::id_from_addr(RELAY1), @0xB1, ctx);
            relay_registry::add_relay_for_testing(&mut relay_reg, test_helpers::id_from_addr(RELAY2), @0xB2, ctx);
            ts::return_shared(relay_reg);
        };

        // Register validators
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            validator_registry::add_validator_for_testing(&mut val_reg, test_helpers::id_from_addr(VAL1), @0xD1, 100_000_000, ctx);
            validator_registry::add_validator_for_testing(&mut val_reg, test_helpers::id_from_addr(VAL2), @0xD2, 100_000_000, ctx);
            ts::return_shared(val_reg);
        };

        // Register signaling
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            signaling_registry::add_signaling_for_testing(&mut sig_reg, test_helpers::id_from_addr(SIG1), @0xF1, ctx);
            ts::return_shared(sig_reg);
        };

        // Register 3 CPs
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, test_helpers::id_from_addr(CP1_ID), CP1_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, test_helpers::id_from_addr(CP2_ID), CP2_OP, 500_000_000, ctx);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, test_helpers::id_from_addr(CP3_ID), CP3_OP, 500_000_000, ctx);
            ts::return_shared(cp_reg);
        };

        // Create CP caps
        ts::next_tx(&mut scenario, CP1_OP);
        {
            let cap = caps::new_cp_cap(test_helpers::id_from_addr(CP1_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP1_OP);
        };
        ts::next_tx(&mut scenario, CP2_OP);
        {
            let cap = caps::new_cp_cap(test_helpers::id_from_addr(CP2_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP2_OP);
        };
        ts::next_tx(&mut scenario, CP3_OP);
        {
            let cap = caps::new_cp_cap(test_helpers::id_from_addr(CP3_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP3_OP);
        };

        // Add PENDING room (creator = ADMIN)
        ts::next_tx(&mut scenario, ADMIN);
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            room_manager::add_room_for_testing(
                &mut manager, test_helpers::id_from_addr(ROOM1), ADMIN,
                constants::room_status_pending(), constants::relay_mode_sfu(),
                6, ctx,
            );
            ts::return_shared(manager);
        };

        scenario
    }

    // Helper: submit proposal with submitted_score
    fun do_submit_consensus(
        scenario: &mut ts::Scenario,
        cp_addr: address,
        relay_ids: vector<ID>,
        validator_ids: vector<ID>,
        signaling_id: ID,
        room_id: ID,
        submitted_score: u64,
    ) {
        ts::next_tx(scenario, cp_addr);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut manager = ts::take_shared<RoomManager>(scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(scenario);

            room_manager::submit_pairing_proposal(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                &cap, room_id,
                relay_ids, validator_ids, signaling_id,
                submitted_score,
                ts::ctx(scenario),
            );

            ts::return_to_sender(scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };
    }

    #[test]
    fun test_consensus_happy_path_3_of_3_agree() {
        let mut scenario = setup_consensus();
        let room_id = test_helpers::id_from_addr(ROOM1);
        let relays = vector[test_helpers::id_from_addr(RELAY1), test_helpers::id_from_addr(RELAY2)];
        let vals = vector[test_helpers::id_from_addr(VAL1), test_helpers::id_from_addr(VAL2)];
        let sig = test_helpers::id_from_addr(SIG1);

        // CP1 submits score 8500
        do_submit_consensus(&mut scenario, CP1_OP, relays, vals, sig, room_id, 8500);

        // CP2 submits same score 8500 — should trigger consensus (2/3 = 66.7%)
        do_submit_consensus(&mut scenario, CP2_OP, relays, vals, sig, room_id, 8500);

        // Verify room is now READY
        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let room = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(room) == constants::room_status_ready(), 0);
            assert!(room_manager::room_verified_score(room) == 8500, 1);
            assert!(room_manager::room_consensus_reached(room) == true, 2);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sui move test --filter test_consensus_happy_path_3_of_3_agree`
Expected: FAIL — `submit_pairing_proposal` doesn't accept `submitted_score` param yet

- [ ] **Step 3: Refactor submit_pairing_proposal**

Rewrite the function in `sources/registry/room_manager.move` (replace lines 250-465). The new implementation:

```move
    /// Submit a pairing proposal with CP-computed score.
    /// Consensus-first: if >= 2/3 of votes match this score, finalize immediately.
    /// No on-chain scoring in the happy path.
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
        // 1. Guards
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
        let room_info = table::borrow(&manager.rooms, room_id);
        assert!(room_info.status == constants::room_status_pending(), E_NOT_PENDING);

        let cp_id = caps::cp_miner_id(cap);
        assert!(control_plane_registry::is_registered(cp_reg, cp_id), E_PAUSED);

        // 2. Duplicate check
        if (table::contains(&manager.room_proposals, room_id)) {
            let proposals = table::borrow(&manager.room_proposals, room_id);
            let mut i = 0;
            let len = vector::length(proposals);
            while (i < len) {
                assert!(vector::borrow(proposals, i).cp_id != cp_id, E_DUPLICATE_VOTE);
                i = i + 1;
            };
        };

        // 3. Ballot size validation
        let expected = room_info.expected_participants;
        let min_relays = manager.rules.min_relay;
        let min_validators = pairing_score::required_validators(expected);
        assert!(vector::length(&relay_ids) >= min_relays, E_INVALID_BALLOT);
        assert!(vector::length(&validator_ids) >= min_validators, E_INVALID_BALLOT);

        // 4. Liveness check — all proposed nodes must have active heartbeat
        let current_epoch = tx_context::epoch(ctx);
        let stale_threshold = constants::pvr_heartbeat_stale();

        let mut r = 0;
        while (r < vector::length(&relay_ids)) {
            let rid = *vector::borrow(&relay_ids, r);
            let info = relay_registry::borrow_info(relay_reg, rid);
            assert!(current_epoch - relay_registry::info_last_heartbeat(info) < stale_threshold, 700);
            r = r + 1;
        };

        let mut v = 0;
        while (v < vector::length(&validator_ids)) {
            let vid = *vector::borrow(&validator_ids, v);
            let info = validator_registry::borrow_info(validator_reg, vid);
            assert!(current_epoch - validator_registry::info_last_heartbeat(info) < stale_threshold, 700);
            v = v + 1;
        };

        let sig_info = signaling_registry::borrow_info(signaling_reg, signaling_id);
        assert!(current_epoch - signaling_registry::info_last_heartbeat(sig_info) < stale_threshold, 700);

        // 5. Store proposal
        let proposal = PairingProposal {
            cp_id,
            relay_ids,
            validator_ids,
            signaling_id,
            submitted_score,
        };

        if (!table::contains(&manager.room_proposals, room_id)) {
            table::add(&mut manager.room_proposals, room_id, vector::empty());
        };
        let proposals = table::borrow_mut(&mut manager.room_proposals, room_id);
        vector::push_back(proposals, proposal);

        // 6. Emit ProposalSubmitted
        event::emit(ProposalSubmitted {
            room_id,
            cp_id,
            verified_score: submitted_score,
            relay_count: vector::length(&relay_ids),
            validator_count: vector::length(&validator_ids),
        });

        // 7. Check consensus: group by submitted_score
        let all_proposals = table::borrow(&manager.room_proposals, room_id);
        let total_votes = vector::length(all_proposals);
        let threshold_bps = constants::pvr_consensus_threshold_bps();

        // Count votes for the just-submitted score
        let mut matching_votes: u64 = 0;
        let mut best_idx: u64 = 0;
        let mut first_match_found = false;
        let mut k: u64 = 0;
        while (k < total_votes) {
            let p = vector::borrow(all_proposals, k);
            if (p.submitted_score == submitted_score) {
                matching_votes = matching_votes + 1;
                if (!first_match_found) {
                    best_idx = k;
                    first_match_found = true;
                };
            };
            k = k + 1;
        };

        // 8. Check if consensus reached
        let participation_bps = matching_votes * constants::basis_points() / total_votes;
        if (participation_bps < threshold_bps) {
            return
        };

        // 9. Finalize: consensus reached!
        let winner = *vector::borrow(all_proposals, best_idx);

        let room_info = table::borrow_mut(&mut manager.rooms, room_id);
        room_info.assigned_relays = winner.relay_ids;
        room_info.assigned_validators = winner.validator_ids;
        room_info.assigned_signaling = option::some(winner.signaling_id);
        room_info.assigned_cp = option::some(winner.cp_id);
        room_info.status = constants::room_status_ready();
        room_info.verified_score = submitted_score;
        room_info.consensus_reached = true;

        // Increment winner reputation (first submitter of this score)
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
        });

        event::emit(ProposerRewarded {
            room_id,
            cp_id: winner.cp_id,
            reward: constants::pvr_proposer_reward(),
        });
    }
```

Also update `assign_relay_and_signaling()` fallback to emit the updated `RoomAssigned` event with default values for new fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `sui move test --filter test_consensus_happy_path_3_of_3_agree`
Expected: PASS

- [ ] **Step 5: Write test — no consensus, room stays PENDING**

Add to `pvr_consensus_tests.move`:

```move
    #[test]
    fun test_no_consensus_room_stays_pending() {
        let mut scenario = setup_consensus();
        let room_id = test_helpers::id_from_addr(ROOM1);
        let relays = vector[test_helpers::id_from_addr(RELAY1), test_helpers::id_from_addr(RELAY2)];
        let vals = vector[test_helpers::id_from_addr(VAL1), test_helpers::id_from_addr(VAL2)];
        let sig = test_helpers::id_from_addr(SIG1);

        // All 3 CPs submit different scores — no 2/3 consensus
        do_submit_consensus(&mut scenario, CP1_OP, relays, vals, sig, room_id, 8500);
        do_submit_consensus(&mut scenario, CP2_OP, relays, vals, sig, room_id, 8200);
        do_submit_consensus(&mut scenario, CP3_OP, relays, vals, sig, room_id, 7900);

        // Room should still be PENDING
        ts::next_tx(&mut scenario, ADMIN);
        {
            let manager = ts::take_shared<RoomManager>(&scenario);
            let room = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(room) == constants::room_status_pending(), 0);
            ts::return_shared(manager);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 6: Run test to verify it passes**

Run: `sui move test --filter test_no_consensus_room_stays_pending`
Expected: PASS (room stays PENDING when no group reaches 2/3)

- [ ] **Step 7: Write test — first submitter gets reputation**

Add to `pvr_consensus_tests.move`:

```move
    #[test]
    fun test_consensus_first_submitter_gets_reputation() {
        let mut scenario = setup_consensus();
        let room_id = test_helpers::id_from_addr(ROOM1);
        let relays = vector[test_helpers::id_from_addr(RELAY1), test_helpers::id_from_addr(RELAY2)];
        let vals = vector[test_helpers::id_from_addr(VAL1), test_helpers::id_from_addr(VAL2)];
        let sig = test_helpers::id_from_addr(SIG1);

        // CP1 submits first with score 8500
        do_submit_consensus(&mut scenario, CP1_OP, relays, vals, sig, room_id, 8500);
        // CP2 submits same score — triggers consensus, CP1 should get reputation (first submitter)
        do_submit_consensus(&mut scenario, CP2_OP, relays, vals, sig, room_id, 8500);

        ts::next_tx(&mut scenario, ADMIN);
        {
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let cp1_info = control_plane_registry::borrow_info(&cp_reg, test_helpers::id_from_addr(CP1_ID));
            assert!(control_plane_registry::info_reputation(cp1_info) == 1, 0);

            // CP2 should NOT get reputation (not the first submitter)
            let cp2_info = control_plane_registry::borrow_info(&cp_reg, test_helpers::id_from_addr(CP2_ID));
            assert!(control_plane_registry::info_reputation(cp2_info) == 0, 1);

            ts::return_shared(cp_reg);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 8: Run test and all existing tests**

Run: `sui move test`
Expected: All tests pass (including the 172 existing ones — some may need `submitted_score` parameter added to `do_submit_proposal` in `pvr_integration_tests.move`)

- [ ] **Step 9: Fix pvr_integration_tests.move compatibility**

The existing `do_submit_proposal` in `pvr_integration_tests.move:112-146` doesn't pass `submitted_score`. Update its signature and call sites to pass a dummy score (e.g., `0`). Since those tests tested the old contract-computed path, their behavior changes — update assertions as needed.

- [ ] **Step 10: Commit**

```bash
git add sources/registry/room_manager.move tests/scoring/pvr_consensus_tests.move tests/scoring/pvr_integration_tests.move
git commit -m "feat(m2): consensus-first submit_pairing_proposal — group by score, finalize at 2/3"
```

---

## Task 4: On-Chain — finalize_room Dispute Fallback

**Files:**
- Modify: `sources/registry/room_manager.move`
- Test: `tests/scoring/pvr_consensus_tests.move`

- [ ] **Step 1: Write failing test — creator can finalize after cooldown**

```move
    #[test]
    fun test_finalize_room_dispute_fallback() {
        let mut scenario = setup_consensus();
        let room_id = test_helpers::id_from_addr(ROOM1);
        let relays_a = vector[test_helpers::id_from_addr(RELAY1), test_helpers::id_from_addr(RELAY2)];
        let relays_b = vector[test_helpers::id_from_addr(RELAY2), test_helpers::id_from_addr(RELAY1)];
        let vals = vector[test_helpers::id_from_addr(VAL1), test_helpers::id_from_addr(VAL2)];
        let sig = test_helpers::id_from_addr(SIG1);

        // 3 CPs submit 3 different scores — no consensus
        do_submit_consensus(&mut scenario, CP1_OP, relays_a, vals, sig, room_id, 8500);
        do_submit_consensus(&mut scenario, CP2_OP, relays_b, vals, sig, room_id, 8200);
        do_submit_consensus(&mut scenario, CP3_OP, relays_a, vals, sig, room_id, 7900);

        // Advance 2 epochs for cooldown
        ts::next_epoch(&mut scenario, ADMIN);
        ts::next_epoch(&mut scenario, ADMIN);

        // Room creator (ADMIN) calls finalize_room
        ts::next_tx(&mut scenario, ADMIN);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            room_manager::finalize_room(
                &net_reg, &mut manager, &mut cp_reg,
                &relay_reg, &val_reg, &sig_reg,
                room_id, ts::ctx(&mut scenario),
            );

            // Room should now be READY with dispute resolution
            let room = room_manager::borrow_room(&manager, room_id);
            assert!(room_manager::room_status(room) == constants::room_status_ready(), 0);
            assert!(room_manager::room_consensus_reached(room) == false, 1);
            assert!(room_manager::room_verified_score(room) > 0, 2);

            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sui move test --filter test_finalize_room_dispute_fallback`
Expected: FAIL — `finalize_room` function doesn't exist

- [ ] **Step 3: Implement finalize_room**

Add to `sources/registry/room_manager.move` after `submit_pairing_proposal`:

```move
    /// Dispute fallback: room creator triggers on-chain scoring when no consensus.
    /// Requires: room is PENDING, cooldown elapsed, at least 2 proposals exist.
    /// Contract re-computes verified_score for each unique tuple, picks highest.
    public fun finalize_room(
        net_reg: &NetworkRegistry,
        manager: &mut RoomManager,
        cp_reg: &mut ControlPlaneRegistry,
        relay_reg: &RelayRegistry,
        validator_reg: &ValidatorRegistry,
        signaling_reg: &SignalingRegistry,
        room_id: ID,
        ctx: &TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);

        let room_info = table::borrow(&manager.rooms, room_id);
        assert!(room_info.status == constants::room_status_pending(), E_NOT_PENDING);
        assert!(room_info.creator == tx_context::sender(ctx), E_NOT_ROOM_CREATOR);

        let current_epoch = tx_context::epoch(ctx);
        assert!(current_epoch >= room_info.created_at + constants::pvr_dispute_cooldown(), E_COOLDOWN_NOT_MET);

        assert!(table::contains(&manager.room_proposals, room_id), E_INSUFFICIENT_PROPOSALS);
        let proposals = table::borrow(&manager.room_proposals, room_id);
        assert!(vector::length(proposals) >= 2, E_INSUFFICIENT_PROPOSALS);

        // Compute verified_score for each proposal using on-chain data
        let mut best_idx: u64 = 0;
        let mut best_score: u64 = 0;
        let room_creator_region = b""; // simplified — region matching not critical for dispute

        let mut i: u64 = 0;
        let len = vector::length(proposals);
        while (i < len) {
            let p = vector::borrow(proposals, i);

            // Compute score for each node in this proposal's tuple
            let mut node_scores = vector::empty<u64>();

            // Score relays
            let mut r = 0;
            while (r < vector::length(&p.relay_ids)) {
                let rid = *vector::borrow(&p.relay_ids, r);
                let info = relay_registry::borrow_info(relay_reg, rid);
                let score = pairing_score::compute_node_score(
                    relay_registry::info_rtt(info),
                    relay_registry::info_load(info),
                    relay_registry::info_stake(info),
                    current_epoch - relay_registry::info_last_heartbeat(info),
                    false, // region match simplified
                    constants::pvr_default_history(),
                );
                vector::push_back(&mut node_scores, score);
                r = r + 1;
            };

            // Score validators
            let mut v = 0;
            while (v < vector::length(&p.validator_ids)) {
                let vid = *vector::borrow(&p.validator_ids, v);
                let info = validator_registry::borrow_info(validator_reg, vid);
                let score = pairing_score::compute_node_score(
                    0, // validators don't have RTT in registry
                    0, // validators don't have load
                    validator_registry::info_stake(info),
                    current_epoch - validator_registry::info_last_heartbeat(info),
                    false,
                    constants::pvr_default_history(),
                );
                vector::push_back(&mut node_scores, score);
                v = v + 1;
            };

            // Score signaling
            let sig_info = signaling_registry::borrow_info(signaling_reg, p.signaling_id);
            let sig_score = pairing_score::compute_node_score(
                0,
                signaling_registry::info_load(sig_info),
                signaling_registry::info_stake(sig_info),
                current_epoch - signaling_registry::info_last_heartbeat(sig_info),
                false,
                constants::pvr_default_history(),
            );
            vector::push_back(&mut node_scores, sig_score);

            let pairing = pairing_score::compute_pairing_score(&node_scores);
            if (pairing > best_score) {
                best_score = pairing;
                best_idx = i;
            };

            i = i + 1;
        };

        // Finalize with best-scoring tuple
        let winner = *vector::borrow(proposals, best_idx);

        let room_info = table::borrow_mut(&mut manager.rooms, room_id);
        room_info.assigned_relays = winner.relay_ids;
        room_info.assigned_validators = winner.validator_ids;
        room_info.assigned_signaling = option::some(winner.signaling_id);
        room_info.assigned_cp = option::some(winner.cp_id);
        room_info.status = constants::room_status_ready();
        room_info.verified_score = best_score;
        room_info.consensus_reached = false;

        // No reputation increment for dispute resolution
        table::remove(&mut manager.room_proposals, room_id);

        let room_mode = room_info.relay_mode;
        event::emit(RoomAssigned {
            room_id,
            relay_ids: winner.relay_ids,
            signaling_id: winner.signaling_id,
            relay_mode: room_mode,
            verified_score: best_score,
            consensus_reached: false,
            winning_cp: winner.cp_id,
        });
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sui move test --filter test_finalize_room_dispute_fallback`
Expected: PASS

- [ ] **Step 5: Write guard tests**

Add 3 tests for `finalize_room` error cases:

```move
    #[test]
    #[expected_failure(abort_code = 550)] // E_NOT_ROOM_CREATOR
    fun test_finalize_room_non_creator_fails() {
        // ... setup, submit 2 proposals, advance epochs
        // Call finalize_room from CP1_OP (not ADMIN who is room creator)
        // Should abort with E_NOT_ROOM_CREATOR
    }

    #[test]
    #[expected_failure(abort_code = 551)] // E_COOLDOWN_NOT_MET
    fun test_finalize_room_before_cooldown_fails() {
        // ... setup, submit 2 proposals, DON'T advance epochs
        // Call finalize_room from ADMIN
        // Should abort with E_COOLDOWN_NOT_MET
    }

    #[test]
    #[expected_failure(abort_code = 552)] // E_INSUFFICIENT_PROPOSALS
    fun test_finalize_room_insufficient_proposals_fails() {
        // ... setup, submit only 1 proposal, advance epochs
        // Call finalize_room from ADMIN
        // Should abort with E_INSUFFICIENT_PROPOSALS
    }
```

- [ ] **Step 6: Run all guard tests**

Run: `sui move test --filter finalize_room`
Expected: All 4 finalize_room tests PASS

- [ ] **Step 7: Run ALL tests**

Run: `sui move test`
Expected: All tests pass (172 existing + new consensus tests)

- [ ] **Step 8: Commit**

```bash
git add sources/registry/room_manager.move tests/scoring/pvr_consensus_tests.move
git commit -m "feat(m2): add finalize_room dispute fallback — creator-gated, on-chain scoring"
```

---

## Task 5: Daemon — Rewrite scoring.ts to Match On-Chain Formula

**Files:**
- Rewrite: `dvconf-daemons/apps/cp-daemon/src/scoring.ts`
- Rewrite: `dvconf-daemons/apps/cp-daemon/src/__tests__/scoring.test.ts`

- [ ] **Step 1: Write failing tests — 6-factor formula + canonical sort**

Rewrite `src/__tests__/scoring.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import {
  computeNodeScore,
  computePairingScore,
  canonicalSort,
  PVR_WEIGHTS,
  PVR_MAX_RTT,
  PVR_MAX_LOAD,
  PVR_STAKE_CAP,
  PVR_HEARTBEAT_FRESH,
  PVR_HEARTBEAT_STALE,
  BASIS,
  type NodeCandidate,
} from '../scoring.js';

describe('PVR Scoring — must match pairing_score.move', () => {
  const makeNode = (overrides: Partial<NodeCandidate> = {}): NodeCandidate => ({
    minerId: '0x0001',
    rtt: 100n,
    load: 20n,
    stakeAmount: 2_500_000_000n, // 2.5 SUI
    heartbeatAge: 1n,
    region: 'us-east',
    historyScore: 5_000n,
    ...overrides,
  });

  describe('computeNodeScore', () => {
    it('returns 0-10000 for valid inputs', () => {
      const score = computeNodeScore(makeNode(), 'us-east', PVR_WEIGHTS);
      expect(score).toBeGreaterThanOrEqual(0n);
      expect(score).toBeLessThanOrEqual(BASIS);
    });

    it('perfect node gets max score', () => {
      const perfect = makeNode({
        rtt: 0n,
        load: 0n,
        stakeAmount: PVR_STAKE_CAP,
        heartbeatAge: 0n,
        region: 'us-east',
        historyScore: 10_000n,
      });
      const score = computeNodeScore(perfect, 'us-east', PVR_WEIGHTS);
      expect(score).toBe(BASIS);
    });

    it('worst node gets 0 score', () => {
      const worst = makeNode({
        rtt: PVR_MAX_RTT,
        load: PVR_MAX_LOAD,
        stakeAmount: 0n,
        heartbeatAge: 100n, // dead
        region: 'eu-west',
        historyScore: 0n,
      });
      const score = computeNodeScore(worst, 'us-east', PVR_WEIGHTS);
      expect(score).toBe(0n);
    });

    it('RTT at max gives 0 RTT score', () => {
      const node = makeNode({ rtt: 500n });
      const score = computeNodeScore(node, 'us-east', PVR_WEIGHTS);
      // RTT contributes 0, but other factors still score
      expect(score).toBeLessThan(BASIS);
    });

    it('liveness: fresh < 3 epochs = full score', () => {
      const fresh = makeNode({ heartbeatAge: 2n });
      const stale = makeNode({ heartbeatAge: 5n });
      const scoreFresh = computeNodeScore(fresh, 'us-east', PVR_WEIGHTS);
      const scoreStale = computeNodeScore(stale, 'us-east', PVR_WEIGHTS);
      expect(scoreFresh).toBeGreaterThan(scoreStale);
    });

    it('liveness: >= 7 epochs = zero liveness score', () => {
      const dead = makeNode({ heartbeatAge: 7n });
      const alive = makeNode({ heartbeatAge: 0n });
      const scoreDead = computeNodeScore(dead, 'us-east', PVR_WEIGHTS);
      const scoreAlive = computeNodeScore(alive, 'us-east', PVR_WEIGHTS);
      expect(scoreAlive).toBeGreaterThan(scoreDead);
    });

    it('region match gives bonus', () => {
      const node = makeNode({ region: 'us-east' });
      const match = computeNodeScore(node, 'us-east', PVR_WEIGHTS);
      const noMatch = computeNodeScore(node, 'eu-west', PVR_WEIGHTS);
      expect(match).toBeGreaterThan(noMatch);
    });

    it('weights sum to 10000', () => {
      const sum = PVR_WEIGHTS.rtt + PVR_WEIGHTS.load + PVR_WEIGHTS.stake +
        PVR_WEIGHTS.liveness + PVR_WEIGHTS.region + PVR_WEIGHTS.history;
      expect(sum).toBe(BASIS);
    });
  });

  describe('computePairingScore', () => {
    it('averages node scores correctly', () => {
      expect(computePairingScore([8000n, 6000n])).toBe(7000n);
    });

    it('returns 0 for empty array', () => {
      expect(computePairingScore([])).toBe(0n);
    });

    it('single node returns its own score', () => {
      expect(computePairingScore([8500n])).toBe(8500n);
    });
  });

  describe('canonicalSort', () => {
    it('sorts by score descending', () => {
      const nodes = [
        makeNode({ minerId: '0x01', rtt: 200n }), // lower score
        makeNode({ minerId: '0x02', rtt: 50n }),  // higher score
      ];
      const sorted = canonicalSort(nodes, 'us-east', PVR_WEIGHTS);
      expect(sorted[0].minerId).toBe('0x02');
      expect(sorted[1].minerId).toBe('0x01');
    });

    it('tie-breaks by minerId ascending', () => {
      const nodes = [
        makeNode({ minerId: '0x02' }),
        makeNode({ minerId: '0x01' }),
      ];
      const sorted = canonicalSort(nodes, 'us-east', PVR_WEIGHTS);
      // Same score → lower minerId first
      expect(sorted[0].minerId).toBe('0x01');
      expect(sorted[1].minerId).toBe('0x02');
    });

    it('produces deterministic order', () => {
      const nodes = [
        makeNode({ minerId: '0x03', rtt: 100n }),
        makeNode({ minerId: '0x01', rtt: 50n }),
        makeNode({ minerId: '0x02', rtt: 50n }),
      ];
      const sorted1 = canonicalSort([...nodes], 'us-east', PVR_WEIGHTS);
      const sorted2 = canonicalSort([...nodes].reverse(), 'us-east', PVR_WEIGHTS);
      expect(sorted1.map(n => n.minerId)).toEqual(sorted2.map(n => n.minerId));
    });
  });

  describe('constants match on-chain', () => {
    it('PVR_MAX_RTT = 500', () => expect(PVR_MAX_RTT).toBe(500n));
    it('PVR_MAX_LOAD = 100', () => expect(PVR_MAX_LOAD).toBe(100n));
    it('PVR_STAKE_CAP = 5 SUI', () => expect(PVR_STAKE_CAP).toBe(5_000_000_000n));
    it('PVR_HEARTBEAT_FRESH = 3', () => expect(PVR_HEARTBEAT_FRESH).toBe(3n));
    it('PVR_HEARTBEAT_STALE = 7', () => expect(PVR_HEARTBEAT_STALE).toBe(7n));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:\Thesis\dvconf\dvconf-daemons && pnpm --filter cp-daemon test`
Expected: FAIL — new exports don't exist yet

- [ ] **Step 3: Rewrite scoring.ts**

Replace `dvconf-daemons/apps/cp-daemon/src/scoring.ts` entirely:

```typescript
/**
 * PVR Scoring — deterministic formula matching pairing_score.move exactly.
 *
 * All math in bigint basis points. Consensus depends on all CPs producing
 * identical scores for identical inputs. Any divergence from on-chain
 * formula will cause consensus failures.
 */

// ── Constants — MUST match constants.move ──
export const BASIS = 10_000n;
export const PVR_MAX_RTT = 500n;
export const PVR_MAX_LOAD = 100n;
export const PVR_STAKE_CAP = 5_000_000_000n;
export const PVR_HEARTBEAT_FRESH = 3n;
export const PVR_HEARTBEAT_STALE = 7n;
export const PVR_DEFAULT_HISTORY = 5_000n;

export interface ScoringWeights {
  rtt: bigint;
  load: bigint;
  stake: bigint;
  liveness: bigint;
  region: bigint;
  history: bigint;
}

export const PVR_WEIGHTS: ScoringWeights = {
  rtt:      3_000n,
  load:     2_500n,
  stake:    1_500n,
  liveness: 1_000n,
  region:   1_000n,
  history:  1_000n,
};

export interface NodeCandidate {
  minerId: string;
  rtt: bigint;
  load: bigint;
  stakeAmount: bigint;
  heartbeatAge: bigint;
  region: string;
  historyScore: bigint;
}

/**
 * Compute score for a single node. Must match pairing_score::compute_node_score().
 */
export function computeNodeScore(
  node: NodeCandidate,
  targetRegion: string,
  weights: ScoringWeights,
): bigint {
  // RTT score: lower is better
  const clampedRtt = node.rtt < PVR_MAX_RTT ? node.rtt : PVR_MAX_RTT;
  const rttScore = (PVR_MAX_RTT - clampedRtt) * BASIS / PVR_MAX_RTT;

  // Load score: lower is better
  const clampedLoad = node.load < PVR_MAX_LOAD ? node.load : PVR_MAX_LOAD;
  const loadScore = (PVR_MAX_LOAD - clampedLoad) * BASIS / PVR_MAX_LOAD;

  // Stake score: higher is better, capped
  const clampedStake = node.stakeAmount < PVR_STAKE_CAP ? node.stakeAmount : PVR_STAKE_CAP;
  const stakeScore = clampedStake * BASIS / PVR_STAKE_CAP;

  // Liveness score: based on heartbeat age in epochs
  let livenessScore: bigint;
  if (node.heartbeatAge < PVR_HEARTBEAT_FRESH) {
    livenessScore = BASIS;
  } else if (node.heartbeatAge < PVR_HEARTBEAT_STALE) {
    livenessScore = 5_000n;
  } else {
    livenessScore = 0n;
  }

  // Region score: binary match
  const regionScore = node.region === targetRegion ? BASIS : 0n;

  // Weighted sum divided by basis points
  const weightedSum =
    rttScore * weights.rtt +
    loadScore * weights.load +
    stakeScore * weights.stake +
    livenessScore * weights.liveness +
    regionScore * weights.region +
    node.historyScore * weights.history;

  return weightedSum / BASIS;
}

/**
 * Compute aggregate pairing score = average of all node scores.
 * Must match pairing_score::compute_pairing_score().
 */
export function computePairingScore(nodeScores: bigint[]): bigint {
  if (nodeScores.length === 0) return 0n;
  const total = nodeScores.reduce((sum, s) => sum + s, 0n);
  return total / BigInt(nodeScores.length);
}

/**
 * Canonical sort: score descending, tie-break by minerId ascending.
 * All CPs must produce identical sort order for consensus.
 */
export function canonicalSort(
  nodes: NodeCandidate[],
  targetRegion: string,
  weights: ScoringWeights,
): NodeCandidate[] {
  return [...nodes].sort((a, b) => {
    const scoreA = computeNodeScore(a, targetRegion, weights);
    const scoreB = computeNodeScore(b, targetRegion, weights);
    if (scoreB !== scoreA) {
      return scoreB > scoreA ? 1 : -1;
    }
    // Tie-break: ascending by minerId (lexicographic)
    return a.minerId < b.minerId ? -1 : a.minerId > b.minerId ? 1 : 0;
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Thesis\dvconf\dvconf-daemons && pnpm --filter cp-daemon test`
Expected: PASS for all new scoring tests. Some old tests in `event-handler.test.ts` may fail due to interface changes — fix in Task 6.

- [ ] **Step 5: Commit**

```bash
cd C:\Thesis\dvconf\dvconf-daemons
git add apps/cp-daemon/src/scoring.ts apps/cp-daemon/src/__tests__/scoring.test.ts
git commit -m "feat(m2): rewrite daemon scoring to match on-chain PVR formula exactly"
```

---

## Task 6: Daemon — Update Event Handler + Room Assignment TX

**Files:**
- Modify: `dvconf-daemons/apps/cp-daemon/src/event-handler.ts:48-54, 211-317`
- Modify: `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts:60-108`
- Modify: `dvconf-daemons/apps/cp-daemon/src/__tests__/event-handler.test.ts`

- [ ] **Step 1: Update DEFAULT_WEIGHTS to PVR_WEIGHTS**

In `event-handler.ts`, replace lines 48-54:

```typescript
import { PVR_WEIGHTS, computeNodeScore, computePairingScore, canonicalSort, type NodeCandidate } from './scoring.js';
```

Remove the old `DEFAULT_WEIGHTS` export entirely.

- [ ] **Step 2: Update EscrowCreated handler to use new scoring**

In the EscrowCreated handler (lines 211-317), replace the old `scoreRelays()` / `scoreValidators()` calls with:
1. Build `NodeCandidate[]` from relay/validator/signaling state maps
2. Call `canonicalSort()` for each node type
3. Select top-N from sorted lists
4. Compute `submitted_score` via `computePairingScore()`
5. Pass `submitted_score` to `submitProposal()`

- [ ] **Step 3: Update submitProposal TX to include submitted_score**

In `room-assignment.ts`, update the `submitProposal()` function to accept `submittedScore: bigint` and pass it to the TX:

```typescript
export async function submitProposal(
  client: SuiClient,
  signer: Keypair,
  config: DaemonConfig,
  cpCapId: string,
  roomId: string,
  relayMinerIds: string[],
  validatorMinerIds: string[],
  signalingMinerId: string,
  submittedScore: bigint,  // NEW
  logger: Logger,
): Promise<void> {
  // ... existing retry logic ...
  // Add to TX args:
  // tx.pure.u64(Number(submittedScore))  // 12th argument
}
```

- [ ] **Step 4: Update event-handler tests**

Fix `event-handler.test.ts` to use the new scoring interface. Update mock data to include `heartbeatAge` and `historyScore` fields. Update assertions for the new scoring behavior.

- [ ] **Step 5: Run all daemon tests**

Run: `cd C:\Thesis\dvconf\dvconf-daemons && pnpm --filter cp-daemon test`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd C:\Thesis\dvconf\dvconf-daemons
git add apps/cp-daemon/src/event-handler.ts apps/cp-daemon/src/room-assignment.ts apps/cp-daemon/src/__tests__/event-handler.test.ts
git commit -m "feat(m2): daemon uses PVR scoring + submits submitted_score in proposal TX"
```

---

## Task 7: Client — expectedParticipants Input (PVR-16)

**Files:**
- Modify: `dvconf-client/src/hooks/useChain.ts:82-121`
- Modify: `dvconf-client/src/pages/HomePage.tsx:18-49`

- [ ] **Step 1: Update useChain.ts createRoom to accept parameter**

In `src/hooks/useChain.ts`, change the `createRoom` function (line 83-84) to accept `expectedParticipants`:

```typescript
  const createRoom = useCallback(
    async (expectedParticipants: number = 4): Promise<CreateRoomResult> => {
```

And replace line 95:

```typescript
              tx.pure.u64(expectedParticipants), // from user input
```

- [ ] **Step 2: Update HomePage.tsx to add input**

In `src/pages/HomePage.tsx`, add state and input:

```typescript
  const [expectedParticipants, setExpectedParticipants] = useState(4);

  const handleCreateRoom = async () => {
    const { roomId } = await createRoom(expectedParticipants);
    if (roomId) {
      navigate(`/rooms/${roomId}`);
    }
  };
```

Add number input before the Create Room button:

```tsx
      <div style={{ marginTop: 16 }}>
        <label style={{ fontSize: 14, marginRight: 8 }}>
          Expected participants:
        </label>
        <input
          type="number"
          min={2}
          max={50}
          value={expectedParticipants}
          onChange={(e) => setExpectedParticipants(Math.max(2, Math.min(50, Number(e.target.value))))}
          style={{ width: 60, padding: '6px 8px', fontSize: 14 }}
        />
      </div>
```

- [ ] **Step 3: Verify manually (or write test)**

If test infrastructure exists for hooks: write a test verifying `createRoom(8)` passes `8` to the TX. Otherwise, manual verification: the input should be visible and the value should flow to the TX.

- [ ] **Step 4: Commit**

```bash
cd C:\Thesis\dvconf\dvconf-client
git add src/hooks/useChain.ts src/pages/HomePage.tsx
git commit -m "feat(m2): accept expectedParticipants in create room UI (PVR-16)"
```

---

## Task 8: Client — Consensus Progress UI (PVR-17, PVR-24, PVR-25)

**Files:**
- Create: `dvconf-client/src/hooks/useRoomConsensus.ts`
- Create: `dvconf-client/src/components/ConsensusProgress.tsx`
- Modify: `dvconf-client/src/pages/RoomPage.tsx:269-296`

- [ ] **Step 1: Create useRoomConsensus hook**

Create `src/hooks/useRoomConsensus.ts`:

```typescript
import { useEffect, useState } from 'react';
import { useSuiClient } from '@mysten/dapp-kit';
import { CONFIG } from '../config';

interface ScoreGroup {
  score: number;
  votes: number;
  percentage: number;
}

interface ConsensusState {
  groups: ScoreGroup[];
  totalVotes: number;
  thresholdMet: boolean;
  loading: boolean;
}

/**
 * Subscribe to ProposalSubmitted events for a room, group by score.
 * Shows live voting progress for consensus.
 */
export function useRoomConsensus(roomId: string | null): ConsensusState {
  const client = useSuiClient();
  const [groups, setGroups] = useState<ScoreGroup[]>([]);
  const [totalVotes, setTotalVotes] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!roomId) return;

    const THRESHOLD_BPS = 6_667; // 2/3
    let cancelled = false;

    async function pollProposals() {
      try {
        const events = await client.queryEvents({
          query: {
            MoveEventType: `${CONFIG.PACKAGE_ID}::room_manager::ProposalSubmitted`,
          },
          limit: 50,
        });

        if (cancelled) return;

        // Filter for this room and group by score
        const roomEvents = events.data.filter(
          (e) => (e.parsedJson as any)?.room_id === roomId,
        );

        const scoreMap = new Map<number, number>();
        for (const e of roomEvents) {
          const score = Number((e.parsedJson as any)?.verified_score ?? 0);
          scoreMap.set(score, (scoreMap.get(score) ?? 0) + 1);
        }

        const total = roomEvents.length;
        const grouped: ScoreGroup[] = Array.from(scoreMap.entries())
          .map(([score, votes]) => ({
            score,
            votes,
            percentage: total > 0 ? Math.round((votes / total) * 100) : 0,
          }))
          .sort((a, b) => b.votes - a.votes);

        const met = grouped.some(
          (g) => total > 0 && (g.votes * 10_000) / total >= THRESHOLD_BPS,
        );

        setGroups(grouped);
        setTotalVotes(total);
        setLoading(false);
      } catch {
        if (!cancelled) setLoading(false);
      }
    }

    pollProposals();
    const interval = setInterval(pollProposals, CONFIG.ROOM_POLL_INTERVAL);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [roomId, client]);

  return { groups, totalVotes, thresholdMet: groups.some(g => g.percentage >= 67), loading };
}
```

- [ ] **Step 2: Create ConsensusProgress component**

Create `src/components/ConsensusProgress.tsx`:

```tsx
import { useRoomConsensus } from '../hooks/useRoomConsensus';
import { CONFIG } from '../config';

interface Props {
  roomId: string;
  roomCreator: string;
  currentUser: string | null;
  createdAtEpoch: number;
  currentEpoch: number;
  onFinalize: () => void;
}

export default function ConsensusProgress({
  roomId,
  roomCreator,
  currentUser,
  createdAtEpoch,
  currentEpoch,
  onFinalize,
}: Props) {
  const { groups, totalVotes, loading } = useRoomConsensus(roomId);
  const cooldownEpochs = 2;
  const canFinalize =
    currentUser === roomCreator &&
    currentEpoch >= createdAtEpoch + cooldownEpochs &&
    totalVotes >= 2;

  return (
    <div style={{ marginTop: 12 }}>
      <p style={{ color: '#555', fontSize: 14, marginBottom: 4 }}>
        <strong>Finding the best infrastructure for your room.</strong>
        <br />
        <span style={{ fontSize: 12, color: '#888' }}>
          More votes improve quality — please wait.
        </span>
      </p>

      {loading && <p style={{ fontSize: 13, color: '#888' }}>Loading votes...</p>}

      {!loading && totalVotes === 0 && (
        <p style={{ fontSize: 13, color: '#999' }}>No votes yet — waiting for CP nodes...</p>
      )}

      {!loading && totalVotes > 0 && (
        <div style={{ marginTop: 8 }}>
          <p style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
            Relay assignment consensus ({totalVotes} vote{totalVotes !== 1 ? 's' : ''}):
          </p>
          {groups.map((g) => (
            <div key={g.score} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 12, fontFamily: 'monospace', width: 100 }}>
                Score {g.score.toLocaleString()}
              </span>
              <div style={{ flex: 1, height: 16, background: '#e0e0e0', borderRadius: 8, overflow: 'hidden' }}>
                <div
                  style={{
                    width: `${g.percentage}%`,
                    height: '100%',
                    background: g.percentage >= 67 ? '#4caf50' : '#1976d2',
                    borderRadius: 8,
                    transition: 'width 0.3s ease',
                  }}
                />
              </div>
              <span style={{ fontSize: 12, width: 80, textAlign: 'right' }}>
                {g.votes} ({g.percentage}%)
              </span>
            </div>
          ))}
          <p style={{ fontSize: 11, color: '#888', marginTop: 4 }}>
            Consensus threshold: 67%
          </p>
        </div>
      )}

      {canFinalize && (
        <div style={{ marginTop: 12, padding: 12, background: '#fff3e0', borderRadius: 8 }}>
          <p style={{ fontSize: 13, color: '#e65100', marginBottom: 8 }}>
            No consensus reached. You can finalize now — the contract will verify and pick the best option.
          </p>
          <button
            onClick={onFinalize}
            style={{
              padding: '8px 16px',
              fontSize: 13,
              background: '#ff9800',
              color: 'white',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Finalize Room
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Integrate into RoomPage.tsx**

In `src/pages/RoomPage.tsx`, replace the PENDING waiting section (lines 269-296) with the `ConsensusProgress` component. Import it and add `finalize_room` TX call.

- [ ] **Step 4: Commit**

```bash
cd C:\Thesis\dvconf\dvconf-client
git add src/hooks/useRoomConsensus.ts src/components/ConsensusProgress.tsx src/pages/RoomPage.tsx
git commit -m "feat(m2): consensus progress UI with voting bars + finalize button (PVR-17/24/25)"
```

---

## Task 9: Client — Show Score + Resolution Path (PVR-18, PVR-22)

**Files:**
- Modify: `dvconf-client/src/hooks/dashboard/useActiveRooms.ts:23-34`
- Modify: `dvconf-client/src/components/dashboard/RoomLifecyclePanel.tsx`

- [ ] **Step 1: Update BCS struct to include new fields**

In `useActiveRooms.ts`, update the BCS definition (lines 23-34):

```typescript
const RoomInfoBcs = bcs.struct('RoomInfo', {
  creator: bcs.Address,
  status: bcs.u8(),
  relay_mode: bcs.u8(),
  created_at: bcs.u64(),
  closed_at: bcs.u64(),
  assigned_relays: bcs.vector(bcs.Address),
  assigned_signaling: bcs.option(bcs.Address),
  assigned_cp: bcs.option(bcs.Address),
  expected_participants: bcs.u64(),
  assigned_validators: bcs.vector(bcs.Address),
  verified_score: bcs.u64(),       // NEW
  consensus_reached: bcs.bool(),   // NEW
});
```

Update the `RoomData` interface and mapping to include:

```typescript
export interface RoomData {
  // ... existing fields ...
  verifiedScore: number;
  consensusReached: boolean;
}
```

- [ ] **Step 2: Update RoomLifecyclePanel to show score + badge**

In `RoomLifecyclePanel.tsx`, add to the room detail section:

```tsx
{room.status >= ROOM_STATUS.READY && room.verifiedScore > 0 && (
  <div style={{ marginTop: 4 }}>
    <strong>Score:</strong> {room.verifiedScore.toLocaleString()} / 10,000
    <span
      style={{
        marginLeft: 8,
        padding: '2px 8px',
        borderRadius: 8,
        fontSize: 11,
        fontWeight: 600,
        background: room.consensusReached ? '#c8e6c9' : '#fff3e0',
        color: room.consensusReached ? '#2e7d32' : '#e65100',
      }}
    >
      {room.consensusReached ? 'Consensus reached' : 'Resolved by contract'}
    </span>
  </div>
)}
```

- [ ] **Step 3: Commit**

```bash
cd C:\Thesis\dvconf\dvconf-client
git add src/hooks/dashboard/useActiveRooms.ts src/components/dashboard/RoomLifecyclePanel.tsx
git commit -m "feat(m2): display verified_score + consensus/dispute badge (PVR-18/22)"
```

---

## Task 10: Integration — Full Test Pass + Regression Check

**Files:**
- All modified files across 3 repos

- [ ] **Step 1: Run all Move tests**

Run: `cd C:\Thesis\dvconf\dvconf-contracts && sui move test`
Expected: All tests pass (172 existing + new consensus tests)

- [ ] **Step 2: Run all daemon tests**

Run: `cd C:\Thesis\dvconf\dvconf-daemons && pnpm --filter cp-daemon test`
Expected: All tests pass

- [ ] **Step 3: Run all client tests**

Run: `cd C:\Thesis\dvconf\dvconf-client && pnpm test`
Expected: All tests pass

- [ ] **Step 4: Verify no regressions in existing Move tests**

Run: `sui move test --filter pvr_integration_tests`
Expected: All 8 existing PVR integration tests pass (with updated signatures)

- [ ] **Step 5: Commit final state**

```bash
git add -A
git commit -m "test(m2): all tests pass — consensus-first model complete"
```
