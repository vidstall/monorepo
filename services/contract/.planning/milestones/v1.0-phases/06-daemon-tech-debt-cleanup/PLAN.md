# Phase 6 Plan: Daemon Tech Debt Cleanup
Date: 2026-03-07

## Goal
Daemon code quality issues identified in the v1.0 audit are resolved.

## Success Criteria
1. CP daemon scoring weights match on-chain constants (rtt=2500, stake=1500)
2. `.env.example` key names match what daemons actually read (`CP_KEYPAIR`, `SUI_PRIVATE_KEY`)
3. TX effects parsing uses robust object extraction (not fragile `createdObjects[0]?.reference?.objectId`)
4. Hardcoded `roomId: 'pending-room'` replaced with configurable or deferred placeholder

## Requirements Covered
(gap closure — tech debt from v1.0 audit, no REQ-IDs)

## Tasks

### Task 1: Fix scoring weights to match on-chain constants
- **Agent**: OffChain
- **Files**: `apps/cp-daemon/src/event-handler.ts`, `apps/cp-daemon/src/__tests__/event-handler.test.ts`
- **Requirements**: N/A (tech debt)
- **Depends on**: None
- **Description**: Change `DEFAULT_WEIGHTS` in `event-handler.ts:21-26` from `rtt: 3_000n, stake: 1_000n` to `rtt: 2_500n, stake: 1_500n` to match on-chain `constants.move` values (`DEFAULT_W_RTT = 2_500`, `DEFAULT_W_STAKE = 1_500`). Update any tests that assert against the old values.
- **Success criterion**: SC-1

### Task 2: Fix .env.example key names
- **Agent**: OffChain
- **Files**: `.env.example`
- **Requirements**: N/A (tech debt)
- **Depends on**: None
- **Description**: Replace `DAEMON_SECRET_KEY=suiprivkey...` with two keys matching actual daemon usage: `CP_KEYPAIR=suiprivkey...` (used by cp-daemon `loadKeypair('CP_KEYPAIR')`) and `SUI_PRIVATE_KEY=suiprivkey...` (used by validator-daemon `loadKeypair('SUI_PRIVATE_KEY')`). Add a comment explaining which daemon uses which key.
- **Success criterion**: SC-2

### Task 3: Robust TX effects parsing in CP auto-register
- **Agent**: OffChain
- **Files**: `apps/cp-daemon/src/auto-register.ts`, `apps/cp-daemon/src/__tests__/auto-register.test.ts`
- **Requirements**: N/A (tech debt)
- **Depends on**: None
- **Description**: The CP daemon's `auto-register.ts:75-84` uses fragile `(effects as any)?.created` pattern with inline type casting. The validator daemon already has a robust `extractCreatedObjectByType()` helper. Either: (a) move that helper to `@dvconf/shared` and use it in both daemons, or (b) add an equivalent helper to cp-daemon. The helper should match objects by type suffix (e.g. `::caps::ControlPlaneCap`) instead of relying on array index. Update tests if the helper signature changes.
- **Success criterion**: SC-3

### Task 4: Replace hardcoded roomId placeholder
- **Agent**: OffChain
- **Files**: `apps/validator-daemon/src/index.ts`, `apps/validator-daemon/src/__tests__/index.test.ts`
- **Requirements**: N/A (tech debt)
- **Depends on**: None
- **Description**: In `index.ts:174`, `buildSessionProof('pending-room', ...)` uses a hardcoded string. Replace with `process.env['ROOM_ID'] ?? 'unassigned'` and add `ROOM_ID` to `.env.example` with a comment noting it will be populated by room assignment in v2. The `'unassigned'` default makes it clear this is a placeholder, not an actual room. Update tests that assert the old value.
- **Success criterion**: SC-4

## Execution Order

All 4 tasks are independent (different files, no shared dependencies). They CAN run in parallel.

However, Tasks 2 and 4 both touch `.env.example`, so they should run sequentially (Task 2 first, then Task 4 adds `ROOM_ID`).

**Wave 1** (parallel): Task 1, Task 2, Task 3
**Wave 2** (after Task 2): Task 4

## Risks & Open Questions

- **Risk**: Task 3 option (a) — moving helper to `@dvconf/shared` — requires changes in both `packages/shared/` and `apps/validator-daemon/` (to import from shared instead of local). Option (b) is safer (duplicate a small helper locally). Recommend option (a) for DRY but defer to agent judgment based on test impact.
- **No blocking questions** — all changes are straightforward tech debt fixes with clear before/after values.
