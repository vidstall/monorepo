# Phase 15 Plan: Economic Flow Fix
Date: 2026-03-13

## Goal
Fix 3 integration bugs that prevent reward distribution from triggering at runtime, completing the E2E session lifecycle.

## Success Criteria
1. Validator daemon populates relayStakeId from on-chain relay assignment (not env var only)
2. waitForProofs correctly reads proof count from RoomEscrow's proofs vector length
3. CP daemon uses tx.pure.id() for Move ID parameters in assign_relay_and_signaling PTB
4. Full E2E flow completes: create room → deposit escrow → assign → session → submit proof → distribute rewards

## Requirements Covered
- ECON-01 (re-satisfy): Reward distribution based on SessionProofs
- ECON-02 (re-satisfy): Slashing for misbehavior returns Coin to economic layer

## Gap Closure
Closes BUG-INT-001, BUG-INT-002, BUG-INT-004 from v3.0 audit.

## Tasks

### Task 1: Fix waitForProofs to read proofs vector length (BUG-INT-002)
- **Agent**: OffChain
- **Files**: `dvconf-daemons/apps/validator-daemon/src/reward-trigger.ts`
- **Requirements**: ECON-01, ECON-02
- **Depends on**: None
- **Description**:
  `waitForProofs` reads `fields['proof_count']` from the RoomEscrow Sui object, but RoomEscrow has no `proof_count` stored field — it has `proofs: vector<SessionProof>`. The proof readiness check always returns 0.

  Fix: Read `fields['proofs']` which is a vector. The Sui JSON representation of a Move vector is an array. Read the array's `.length` to get the proof count.

  Before:
  ```ts
  const proofCount = Number(fields['proof_count'] ?? 0);
  ```

  After:
  ```ts
  const proofs = fields['proofs'] as unknown[];
  const proofCount = Array.isArray(proofs) ? proofs.length : 0;
  ```

  Update JSDoc comment on `waitForProofs` to reflect it reads the proofs vector length, not a proof_count field.

### Task 2: Populate relayStakeId from on-chain relay assignment (BUG-INT-001)
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/validator-daemon/src/index.ts` (event handler + stake lookup)
  - `dvconf-daemons/apps/validator-daemon/src/reward-trigger.ts` (new `lookupRelayStakeId` export)
- **Requirements**: ECON-01, ECON-02
- **Depends on**: None
- **Description**:
  `ActiveRoom.relayStakeId` is never populated. The only fallback is `RELAY_STAKE_ID` env var (single-relay, demo-only). Without it, `handleRoomClosed` silently skips reward distribution.

  Fix in two parts:

  **A) Listen for RoomAssigned events in the room_manager poller.**
  The existing `roomPoller` already subscribes to `room_manager` events and handles `RoomCreated` and `RoomClosed`. Add a handler for `RoomAssigned`:
  - Extract `relay_id` (miner_id) from the event
  - Store `relay_id` in `ActiveRoom` (add `relayMinerId?: string` field)
  - Look up the relay operator's StakePosition object ID

  **B) Add `lookupRelayStakeId()` function in reward-trigger.ts.**
  Given a relay miner_id:
  1. Use `devInspectTransactionBlock` to call `relay_registry::borrow_info(registry, miner_id)` and extract the operator address from the BCS result
  2. Use `client.getOwnedObjects({ owner: operatorAddress, filter: { StructType: '<packageId>::staking::StakePosition' } })` to find the relay's StakePosition object ID
  3. Return the object ID (or undefined if not found)

  When the RoomAssigned event handler gets the StakePosition ID, store it in `activeRooms.get(roomId).relayStakeId`.

  The `RELAY_STAKE_ID` env var remains as a fallback for single-relay demo setups.

### Task 3: Fix CP daemon ID type in assign_relay_and_signaling PTB (BUG-INT-004)
- **Agent**: OffChain
- **Files**: `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts`
- **Requirements**: ECON-01 (transitive — correct assignment is prerequisite for distribution)
- **Depends on**: None
- **Description**:
  `assignRoom()` uses `tx.pure.address()` for Move `ID` parameters (`roomId`, `relayMinerId`, `signalingMinerId`). While BCS-compatible at wire level (both 32 bytes), this violates the type contract and may fail depending on SDK version validation.

  Fix: Replace `tx.pure.address(roomId)` with `tx.pure.id(roomId)` for all three ID parameters.

  Before:
  ```ts
  tx.pure.address(roomId),
  tx.pure.address(relayMinerId),
  tx.pure.address(signalingMinerId),
  ```

  After:
  ```ts
  tx.pure.id(roomId),
  tx.pure.id(relayMinerId),
  tx.pure.id(signalingMinerId),
  ```

### Task 4: Update validator daemon tests for fixed reward flow
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/validator-daemon/src/__tests__/reward-trigger.test.ts` (new or updated)
- **Requirements**: ECON-01, ECON-02 (coverage)
- **Depends on**: Task 1, Task 2
- **Description**:
  Update or create tests for the fixed reward trigger:

  1. **waitForProofs test**: Mock `client.getObject` returning a RoomEscrow with `proofs: [{...}, {...}]` array, assert `waitForProofs` returns true when proofs.length >= minProofs
  2. **waitForProofs empty test**: Mock `proofs: []`, assert returns false (timeout)
  3. **lookupRelayStakeId test**: Mock `devInspectTransactionBlock` and `getOwnedObjects`, verify it returns the correct StakePosition ID

## Execution Order

```
Task 1 (waitForProofs fix)     ─┐
Task 2 (relayStakeId populate) ─┤── parallel (different functions, no shared files)
Task 3 (tx.pure.id fix)        ─┘
         │
         ▼
Task 4 (tests) ── sequential (depends on T1 + T2)
```

Tasks 1, 2, and 3 can run in parallel — they modify different files in different daemons. Task 4 depends on Tasks 1 and 2 being complete.

## Risks & Open Questions

1. **StakePosition ownership**: `distribute_rewards` takes `relay_stake: &mut StakePosition` which is an owned object (owned by relay operator). The validator daemon cannot include another wallet's owned object in its PTB. In the thesis demo setup, this works when:
   - The relay and validator share an operator wallet, OR
   - The relay operator calls distribution themselves
   - **Mitigation**: Document this limitation. The Phase 15 fix ensures the validator *discovers* the correct StakePosition ID. If ownership blocks the TX at runtime, a follow-up change could make StakePosition shared or remove it from the distribution signature (the relay_miner_id is already in the proofs and can verify via relay_registry).

2. **BCS decode for devInspect**: The `lookupRelayStakeId` function needs to decode relay_registry::borrow_info BCS output. The operator address is the first field of RelayNodeInfo. This follows the same devInspect pattern used throughout the project (Phase 8, Phase 10, Phase 11).

3. **tx.pure.id() availability**: Available in @mysten/sui SDK v1.x (project uses 1.45.2). If not available, fallback is `tx.pure(bcs.id().serialize(value))`.
