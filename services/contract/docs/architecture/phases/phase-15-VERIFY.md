# PHASE ARCHITECTURE VERIFICATION -- Phase 15: Economic Flow Fix

Date: 2026-03-13
Reviewer: Architect Agent
ADD reference: N/A (gap closure phase -- no ADD)

---

## SCOPE

Phase 15 is a gap closure phase fixing three integration bugs (BUG-INT-001, BUG-INT-002, BUG-INT-004) discovered during end-to-end testing. No new modules are introduced; only existing off-chain daemon code is corrected and extended.

**Files reviewed:**
- `dvconf-daemons/apps/validator-daemon/src/reward-trigger.ts`
- `dvconf-daemons/apps/validator-daemon/src/index.ts`
- `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts`
- `dvconf-daemons/apps/validator-daemon/src/__tests__/reward-trigger.test.ts`

---

## ARCHITECTURE QUALITY REVIEW (No-ADD Checklist)

### 1. Naming Consistency

| Item | Assessment |
|------|------------|
| `lookupRelayStakeId` function name | GOOD -- follows existing `lookup*` / `ensure*` naming pattern in daemon codebase |
| `relayMinerId` parameter name | GOOD -- matches on-chain `relay_id` field semantics; "MinerId" suffix is consistent with `ValidatorConfig.relayMinerId` |
| `ActiveRoom.relayMinerId` field | GOOD -- mirrors `relayMinerId` used throughout index.ts |
| `ActiveRoom.relayStakeId` field | GOOD -- matches the `relayStakeId` parameter in `triggerDistribution()` |
| `RoomAssigned` event interface | GOOD -- fields `room_id`, `relay_id`, `signaling_id` exactly match on-chain Move struct `RoomAssigned { room_id: ID, relay_id: ID, signaling_id: ID }` |

**Verdict: PASS** -- No naming inconsistencies found.

### 2. Dependency Direction

```
index.ts (orchestrator)
  -> reward-trigger.ts (domain logic: proof polling, distribution TX, stake lookup)
  -> session-proof.ts (proof construction)
  -> auto-register.ts (registration)
  -> @dvconf/shared (types, utilities, constants)
```

Dependencies flow correctly: `index.ts` (higher-level orchestrator) imports from `reward-trigger.ts` (lower-level domain module). `reward-trigger.ts` depends only on `@dvconf/shared` and Sui SDK -- no upward or circular dependencies.

The new `lookupRelayStakeId` export from `reward-trigger.ts` is consumed only in `index.ts`. This keeps the dependency direction clean.

**Verdict: PASS** -- No dependency inversions.

### 3. Error Handling

| Location | Pattern | Assessment |
|----------|---------|------------|
| `lookupRelayStakeId` | try/catch wrapping entire function, returns `undefined` on failure | GOOD -- graceful degradation, logged at `warn` level |
| `lookupRelayStakeId` devInspect null check | Checks `result.results?.[1]?.returnValues?.[0]` before accessing | GOOD -- defensive against malformed devInspect responses |
| RoomAssigned handler | try/catch around `lookupRelayStakeId` call | GOOD -- prevents a failed lookup from crashing the event poller |
| `handleRoomClosed` missing `relayStakeId` | Falls back to `process.env['RELAY_STAKE_ID']` | GOOD -- graceful fallback for demo scenarios |
| `waitForProofs` getObject failure | Caught per-poll, logged as warn, continues polling | GOOD -- transient RPC errors don't abort the wait |

**Verdict: PASS** -- Error handling is thorough and consistent with existing daemon patterns.

### 4. API Surface

- `lookupRelayStakeId` is correctly exported as `export async function` -- it is consumed by `index.ts` and needs to be importable.
- No unnecessary exports were added. `handleRoomClosed`, `runMeasurementCycle`, and `measureRoom` remain module-private.
- `ActiveRoom` interface is exported from `index.ts` -- appropriate since it's part of the `DaemonState` public interface used in tests.

**Verdict: PASS** -- API surface is minimal and justified.

### 5. Cross-Module Integration

**BUG-INT-001 fix (relay StakePosition discovery):**
- `lookupRelayStakeId` calls `relay_registry::borrow_info` then `relay_registry::info_operator` via devInspect. Verified these functions exist on-chain in `relay_registry.move` with matching signatures: `borrow_info(r: &RelayRegistry, miner_id: ID): &RelayNodeInfo` and `info_operator(i: &RelayNodeInfo): address`.
- The two-step devInspect pattern (borrow_info -> info_operator) correctly chains move call results -- `info` result from first call is passed as argument to second call.
- `getOwnedObjects` filter uses `${config.packageId}::staking::StakePosition` -- matches the on-chain type.

**BUG-INT-002 fix (proofs read):**
- `waitForProofs` reads `fields['proofs']` from the escrow MoveObject. The on-chain `RoomEscrow` struct has a `proofs: vector<SessionProof>` field. Field access pattern is correct.

**BUG-INT-004 fix (tx.pure.id):**
- `room-assignment.ts` uses `tx.pure.id(roomId)`, `tx.pure.id(relayMinerId)`, `tx.pure.id(signalingMinerId)` for the three `ID` parameters. On-chain `assign_relay_and_signaling` expects `room_id: ID, relay_id: ID, signaling_id: ID`. The `tx.pure.id()` encoding is the correct Sui SDK method for passing Move `ID` values as pure arguments.
- This is consistent with the same pattern used in `session-proof.ts` (line 254-255) and `reward-trigger.ts` (line 174).

**distribute_rewards PTB argument order:**
- `triggerDistribution` passes 6 arguments: `networkRegistryId`, `escrowId`, `roomManagerId`, `relayRegistryId`, `validatorRegistryId`, `relayStakeId`.
- On-chain signature: `net_reg: &NetworkRegistry, escrow: &mut RoomEscrow, room_mgr: &RoomManager, relay_reg: &mut RelayRegistry, validator_reg: &mut ValidatorRegistry, relay_stake: &mut StakePosition, ctx: &mut TxContext`.
- Order matches exactly (ctx is auto-appended by Sui runtime). This was the TD-P14-01 fix from Phase 14, now confirmed correct.

**Verdict: PASS** -- All cross-module integration points are correct.

### 6. Tech Debt Review

**Dimension scan of changed files:**

| Dimension | Finding |
|-----------|---------|
| Coupling | LOW -- `lookupRelayStakeId` depends only on SuiClient and NetworkConfig; no internal imports |
| Cohesion | GOOD -- `reward-trigger.ts` handles all reward-related concerns (proofs, distribution, stake lookup) |
| Code duplication | MINOR -- `escrowMap` and `activeRooms` both store `escrowId` for the same room. `escrowMap` is a legacy Map<roomId, escrowId> while `activeRooms` now also carries `escrowId`. See TD-P15-01 below. |
| Hardcoded values | `PROOF_POLL_INTERVAL_MS = 5_000` and timeout `60_000` in `handleRoomClosed` -- acceptable for thesis demo |
| Stale code | `escrowMap` is now partially redundant with `activeRooms[roomId].escrowId` but still used in `handleRoomClosed` and `measureRoom`. Not stale yet but signals future consolidation. |
| Test coverage | 5 new tests covering `waitForProofs` (3 cases) and `lookupRelayStakeId` (2 cases). Good coverage of happy path and edge cases. Missing: no test for `triggerDistribution` itself, but that is a thin wrapper around `executeWithRetry` which is tested in shared. |

**New tech debt identified:**

**[TD-P15-01] Dual escrow tracking (escrowMap + activeRooms.escrowId)**
- Severity: LOW
- Dimension: Code duplication / Cohesion
- Location: `validator-daemon/src/index.ts` -- `escrowMap` and `activeRooms`
- Description: `escrowMap: Map<string, string>` duplicates the `escrowId` field now stored in `ActiveRoom`. Both are populated in the EscrowCreated handler. `handleRoomClosed` reads from `escrowMap` while the data is also available in `activeRooms`. This creates a risk of desynchronization if one map is updated but not the other.
- Refactor cost: SMALL (< 1 hour) -- consolidate to use only `activeRooms`, remove `escrowMap`.
- Blocks: nothing (both maps are kept in sync today)
- Recommendation: DEFER to post-thesis cleanup. The duplication is benign in the current codebase.

### 7. Known Limitation Acknowledgment

The `distribute_rewards` Move function takes `relay_stake: &mut StakePosition` as a mutable reference. In a PTB, the validator daemon must supply this object ID. The `lookupRelayStakeId` function discovers the StakePosition via `getOwnedObjects`, meaning the object is owned by the relay operator -- not by the validator calling the TX. This means the PTB will fail at execution time unless the StakePosition is a shared object or the validator has been delegated access.

This is a **known and accepted limitation** documented in the PLAN.md for the thesis demo. The on-chain `StakePosition` would need to be a shared object (or use a different access pattern) for production. This is NOT logged as tech debt because it is an acknowledged design constraint.

---

## MODULES ADDED/CHANGED

- `reward-trigger.ts` -- added `lookupRelayStakeId()` export (BUG-INT-001); fixed `waitForProofs` proof field read (BUG-INT-002)
- `index.ts` -- added `RoomAssigned` event handler with async stake lookup; added `relayMinerId` field to `ActiveRoom` interface
- `room-assignment.ts` -- changed `tx.pure.string()` to `tx.pure.id()` for ID-typed arguments (BUG-INT-004)
- `reward-trigger.test.ts` -- 5 new unit tests for `waitForProofs` and `lookupRelayStakeId`

---

## NEW TECH DEBT INTRODUCED

- [TD-P15-01] Dual escrow tracking (`escrowMap` + `activeRooms.escrowId`) -- LOW severity, SMALL refactor cost, non-blocking

---

## QC BUG LOG CHECK

Checked `.planning/bugs/offchain.md`:
- **BUG-OFF-001** (Reversal Protocol not followed, Phase 13): OPEN but unrelated to Phase 15 changes. Phase 15 changes are all net-new code additions or single-line fixes, not bulk modifications requiring the reversal protocol.

No Phase 15-specific bugs are logged in `.planning/bugs/`.

---

## ARCHITECTURE HEALTH TREND

```
  Phase 14:   8/10
  Phase 15:   8/10
  Direction:  STABLE
```

**Score breakdown:**
- Coupling:     8/10 (clean module boundaries maintained)
- Cohesion:     8/10 (reward-trigger.ts is well-scoped; minor escrowMap duplication)
- Testability:  8/10 (new functions are testable via dependency injection; 5 new tests added)
- Consistency:  9/10 (naming, patterns, and error handling all follow established conventions)

---

## CROSS-PHASE INTEGRATION

- Phase 14 -> Phase 15: CLEAN -- Phase 15 fixes integration bugs found during Phase 14 E2E testing; no structural conflicts.
- Phase 13 -> Phase 15: CLEAN -- `distribute_rewards` argument order matches the Phase 13 on-chain signature exactly.
- Phase 11 -> Phase 15: CLEAN -- `relay_registry::borrow_info` / `info_operator` used in `lookupRelayStakeId` matches the Phase 11-era on-chain API.

---

## VERIFICATION VERDICT: CONFORMS

Phase 15 is a well-scoped gap closure phase. All three bug fixes are architecturally sound:
1. **BUG-INT-001**: Dynamic relay stake discovery via devInspect follows the established read-only inspection pattern.
2. **BUG-INT-002**: Proof field access is now correct against the on-chain escrow schema.
3. **BUG-INT-004**: `tx.pure.id()` encoding matches the Move `ID` parameter types exactly.

No critical findings. One LOW-severity tech debt item (TD-P15-01) logged for future consolidation. All cross-module integration contracts verified correct against on-chain signatures.
