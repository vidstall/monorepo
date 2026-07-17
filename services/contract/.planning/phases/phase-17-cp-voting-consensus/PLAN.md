# Phase 17 Plan: CP Voting Consensus
Date: 2026-03-17

## Goal
Multiple Control Plane nodes independently score relay candidates, submit votes on-chain, and the contract auto-finalizes room assignment when ≥2/3 of active CPs agree on the same relay+signaling choice.

## Success Criteria
1. Each CP node submits an independent relay vote for a room via on-chain TX
2. Contract tallies votes and auto-finalizes when ≥2/3 active CPs agree
3. Disagreement triggers re-evaluation (votes reset for that room)
4. Room transitions PENDING→READY only after consensus is reached
5. CP daemon submits votes instead of direct `assign_relay_and_signaling()` calls
6. All existing Move tests still pass + new voting tests added

## Requirements Covered
- PRD §8 Step 3: CP relay assignment voting + mode selection (≥2/3 consensus)
- PRD §10: Multiple Control Plane Consensus
- Uses existing `DEFAULT_CP_CONSENSUS_THRESHOLD_BPS = 6_667` from constants.move

## Tasks

### Task 1: On-chain — Add CP voting to room_manager
- **Agent**: OnChain
- **Files**: `sources/registry/room_manager.move`, `sources/core/constants.move`
- **Requirements**: PRD §8.3, §10
- **Depends on**: None
- **Description**:
  Add vote tracking to RoomManager:
  - New struct `RelayVote { cp_id: ID, relay_id: ID, signaling_id: ID }`
  - New field on RoomManager: `room_votes: Table<ID, vector<RelayVote>>` (room_id → votes)
  - New entry function `submit_relay_vote(net_reg, manager, cp_reg, cap, room_id, relay_id, signaling_id, ctx)`:
    - Requires ControlPlaneCap, room must be PENDING
    - Checks CP is registered and active
    - Prevents duplicate votes from same CP
    - Stores vote in `room_votes`
    - Calls `check_consensus()` — if ≥ threshold of active CPs voted for same (relay_id, signaling_id), auto-finalize:
      - Set `assigned_relay`, `assigned_signaling`
      - Transition PENDING → READY
      - Emit `RoomAssigned` event
      - Clean up votes for this room
    - If all active CPs voted but no consensus → reset votes, emit `VoteReset` event
  - Keep `assign_relay_and_signaling()` as a package-internal fallback (for testing / single-CP dev mode)
  - Add `VoteSubmitted` and `VoteReset` events
  - Add accessor: `get_room_votes(manager, room_id): vector<RelayVote>`

### Task 2: On-chain — Voting tests
- **Agent**: OnChain
- **Files**: `tests/registry/room_manager_tests.move`
- **Requirements**: PRD §10 (coverage)
- **Depends on**: Task 1
- **Description**:
  Add tests for the voting mechanism:
  - `test_single_cp_vote_with_one_active_finalizes` — 1 active CP, 1 vote = 100% > 66.67% → finalize
  - `test_two_of_three_cps_agree` — 3 active CPs, 2 vote same → 66.67% → finalize
  - `test_two_of_three_cps_disagree` — 3 CPs, all 3 vote differently → no consensus → reset
  - `test_duplicate_vote_aborts` — same CP votes twice → abort
  - `test_vote_on_closed_room_aborts` — vote on CLOSED room → abort
  - `test_vote_on_ready_room_aborts` — vote on already-READY room → abort
  - `test_inactive_cp_cannot_vote` — CP not in active set → abort

### Task 3: OffChain — CP daemon submits votes instead of direct assignment
- **Agent**: OffChain
- **Files**: `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts`, `dvconf-daemons/apps/cp-daemon/src/event-handler.ts`
- **Requirements**: PRD §10
- **Depends on**: Task 1
- **Description**:
  Update CP daemon to use the voting flow:
  - Rename/replace `assignRoom()` → `submitRelayVote()` in `room-assignment.ts`
    - Calls `room_manager::submit_relay_vote` instead of `room_manager::assign_relay_and_signaling`
  - In `event-handler.ts` `EscrowCreated` handler: call `submitRelayVote()` instead of `assignRoom()`
  - Add handling for `VoteReset` event: re-score and re-submit vote
  - Add shared types for new events (`VoteSubmitted`, `VoteReset`, `RoomAssigned` already exists)
  - Update `dvconf-daemons/packages/shared/src/types/events.ts` with new event types

### Task 4: Client — Handle vote-based room readiness
- **Agent**: FE
- **Files**: `dvconf-client/src/hooks/useRoomStatus.ts` (or equivalent polling hook)
- **Requirements**: PRD §8.3 (client-visible)
- **Depends on**: Task 1
- **Description**:
  Minimal client change — the client already polls room status. The `RoomAssigned` event structure is unchanged. Only change needed:
  - If room stays PENDING longer (waiting for votes), add a "Waiting for network consensus..." status message
  - No structural changes — vote finalization emits the same `RoomAssigned` event

## Execution Order
- Task 1 (OnChain) first — defines the interface
- Task 2 (OnChain) + Task 3 (OffChain) in parallel after Task 1
- Task 4 (FE) can run in parallel with Task 2/3

## Risks & Open Questions
- **Single-CP dev mode**: With only 1 active CP, 1 vote = 100% consensus → auto-finalizes. This preserves backward compatibility for local dev.
- **Vote reset loop**: If CPs persistently disagree, votes reset infinitely. Mitigation: after N resets, fall back to highest-voted relay (future improvement, not thesis scope).
- **CP liveness during voting**: A CP that goes offline after partial votes reduces the active count. The threshold is computed against active CPs at finalization time.
