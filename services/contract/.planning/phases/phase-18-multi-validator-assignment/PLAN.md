# Phase 18 Plan: Multi-Validator Room Assignment
Date: 2026-03-17

## Goal
Control Plane assigns multiple validators to each room via their session wallets. Multiple validators independently submit SessionProofs, enabling the existing median aggregation and accuracy scoring to function as designed in the PRD.

## Success Criteria
1. RoomInfo tracks assigned validators (`assigned_validators: vector<ID>`)
2. CP assigns N validators to a room as part of the voting/finalization flow
3. Validator daemon detects its room assignment and joins the session
4. Multiple validators submit independent SessionProofs for the same room
5. `distribute_rewards()` correctly applies median aggregation and accuracy scoring across multiple proofs
6. E2E test: 2+ validators → median bytes + quality → proportional rewards + RTT writeback
7. All existing Move tests still pass + new multi-validator tests added

## Requirements Covered
- PRD §8 Step 4: Validator secret assignment (session wallet on-chain)
- PRD §9.3: Multiple validators → median metrics → outlier detection
- PRD §11: Validator accuracy scoring + reward
- ECON-01, ECON-02 (re-satisfy with multi-validator E2E proof)

## Tasks

### Task 1: On-chain — Add validator assignment to room lifecycle
- **Agent**: OnChain
- **Files**: `sources/registry/room_manager.move`
- **Requirements**: PRD §8.4
- **Depends on**: Phase 17 Task 1
- **Description**:
  Extend RoomInfo and RoomManager:
  - Add `assigned_validators: vector<ID>` to `RoomInfo` struct
  - New package function `assign_validators_to_room(manager, room_id, validator_ids)`:
    - Called during vote finalization (Phase 17) or directly by CP
    - Stores validator miner_ids in room's assigned_validators
    - Emits `ValidatorsAssigned { room_id, validator_ids }` event
  - Add accessor `room_assigned_validators(r: &RoomInfo): vector<ID>`
  - Initialize `assigned_validators: vector::empty()` in `create_room()` and `add_room_for_testing()`

### Task 2: On-chain — CP assigns validators during vote finalization
- **Agent**: OnChain
- **Files**: `sources/registry/room_manager.move`, `sources/registry/validator_registry.move`
- **Requirements**: PRD §8.4, §9.3
- **Depends on**: Task 1, Phase 17 Task 1
- **Description**:
  Wire validator assignment into the CP voting flow:
  - Extend `submit_relay_vote()` to also accept `validator_ids: vector<ID>`
  - On consensus finalization, call `assign_validators_to_room()` with the winning vote's validators
  - Each CP independently picks validators (same scoring approach — available, active, different from relay operator)
  - CP also calls `validator_registry::assign_validator_session()` for each validator assigned to the room
  - Add validator assignment to `RelayVote` struct: `validator_ids: vector<ID>`

### Task 3: On-chain — Multi-validator tests
- **Agent**: OnChain
- **Files**: `tests/registry/room_manager_tests.move`, `tests/registry/economic_layer_tests.move`
- **Requirements**: ECON-01, ECON-02 (coverage)
- **Depends on**: Task 1, Task 2
- **Description**:
  Add tests proving multi-validator flow works E2E on-chain:
  - `test_assign_validators_to_room` — validators stored in RoomInfo
  - `test_vote_with_validators_finalizes` — consensus stores validators
  - `test_distribute_rewards_two_validators` — 2 proofs, median computed, accuracy scored, both get paid
  - `test_distribute_rewards_three_validators_outlier` — 3 proofs, one outlier gets low accuracy score
  - `test_rtt_writeback_from_multiple_proofs` — each proof writes RTT, last one wins (acceptable for thesis)

### Task 4: OffChain — CP daemon assigns validators during voting
- **Agent**: OffChain
- **Files**: `dvconf-daemons/apps/cp-daemon/src/event-handler.ts`, `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts`
- **Requirements**: PRD §8.4
- **Depends on**: Task 2, Phase 17 Task 3
- **Description**:
  Update CP daemon to pick validators when submitting relay votes:
  - Add validator selection logic: pick N validators from active set (N = `min_validator` from room rules, default 2)
  - Exclude relay operator from validator candidates
  - Include `validator_ids` in the vote TX
  - Add `ValidatorsAssigned` to shared event types

### Task 5: OffChain — Validator daemon watches for room assignment
- **Agent**: OffChain
- **Files**: `dvconf-daemons/apps/validator-daemon/src/index.ts`
- **Requirements**: PRD §8.4, §9.3
- **Depends on**: Task 1
- **Description**:
  Update validator daemon to detect when it's assigned to a room:
  - Subscribe to `ValidatorsAssigned` events
  - Check if own miner_id is in the assigned list
  - If assigned: start measurement cycle for that room
  - This replaces the current approach where validator watches for *any* active room
  - Multiple validator daemon instances can run independently (each checks its own ID)

## Execution Order
- Task 1 (OnChain) first — extends the data model
- Task 2 (OnChain) after Task 1 — wires into voting
- Task 3 (OnChain) + Task 4 (OffChain) + Task 5 (OffChain) in parallel after Task 2

## Risks & Open Questions
- **Validator privacy**: In the current model, `ValidatorsAssigned` event reveals validator IDs publicly. For thesis scope this is acceptable — the PRD mentions encrypted on-chain storage as ideal, ZK proofs as future work. The dual-key pattern still hides identity *during* the session (session wallet used, not public wallet).
- **RTT writeback with multiple validators**: Each `submit_session_proof()` overwrites the relay's RTT. With multiple validators, the last submission wins. A weighted average would be better but is not critical for thesis. Document as known limitation.
- **Validator count vs room size**: Using `min_validator` from room rules (default 2). Works for thesis demo. Production would scale with room importance.
