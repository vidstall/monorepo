# Phase 6 RTM: Daemon Tech Debt Cleanup

Date: 2026-03-07
Verification Agent: Requirements Traceability Matrix

## Requirements Traceability Matrix

Phase 6 has no REQ-IDs (gap closure / tech debt). Verification is against 4 success criteria from ROADMAP.md.

| SC | Description | Evidence (file:line) | Test | Status |
|----|-------------|---------------------|------|--------|
| SC-1 | CP daemon scoring weights match on-chain constants (rtt=2500, stake=1500) | `dvconf-daemons/apps/cp-daemon/src/event-handler.ts:20-26` — `rtt: 2_500n, stake: 1_500n` matches `dvconf-contracts/sources/core/constants.move:29-31` — `DEFAULT_W_RTT = 2_500, DEFAULT_W_STAKE = 1_500` | No direct assertion test comparing daemon weights to on-chain values. Weights are imported by `event-handler.test.ts` but values are not explicitly asserted. Scoring tests use `EQUAL_WEIGHTS` (all 2000n), not `DEFAULT_WEIGHTS`. | PASS (code correct, test GAP noted) |
| SC-2 | `.env.example` key names match what daemons actually read (`CP_KEYPAIR`, `SUI_PRIVATE_KEY`) | `.env.example:18` — `CP_KEYPAIR=suiprivkey...`; `.env.example:21` — `SUI_PRIVATE_KEY=suiprivkey...`; `cp-daemon/src/index.ts:26` — `loadKeypair('CP_KEYPAIR')`; `validator-daemon/src/index.ts:76` — `loadKeypair('SUI_PRIVATE_KEY')` | No test asserting env key names match. Verified by code inspection: key names in `.env.example` match `loadKeypair()` arguments exactly. | PASS (code correct, no test needed — config file) |
| SC-3 | TX effects parsing uses robust object extraction (not fragile `createdObjects[0]?.reference?.objectId`) | `packages/shared/src/chain/tx.ts:84-102` — `extractCreatedObjectByType()` matches by type suffix; `cp-daemon/src/auto-register.ts:74-75` — uses `extractCreatedObjectByType(minerResult, '::caps::ControlPlaneCap')` and `'::staking::StakePosition'`; `validator-daemon/src/auto-register.ts:102-103` — uses `extractCreatedObjectByType(minerResult, '::caps::MinerCap')` and `'::staking::StakePosition'` | `cp-daemon/__tests__/auto-register.test.ts:192-249` — tests missing ControlPlaneCap and missing StakePosition extraction failures; `validator-daemon/__tests__/auto-register.test.ts:204-258` — tests missing MinerCap and missing StakePosition extraction failures. Both test suites use mock effects with `objectType` fields to exercise the type-suffix matching path. | PASS |
| SC-4 | Hardcoded `roomId: 'pending-room'` replaced with configurable or deferred placeholder | `validator-daemon/src/index.ts:174` — `process.env['ROOM_ID'] ?? 'unassigned'`; `.env.example:31` — `ROOM_ID=` with comment "populated by room assignment in v2; default: 'unassigned'" | `validator-daemon/__tests__/index.test.ts:163-177` — `'uses ROOM_ID from env when set'` verifies env value `'test-room-42'` is passed to `buildSessionProof`; `index.test.ts:179-191` — `'defaults roomId to "unassigned" when ROOM_ID env is not set'` verifies fallback default | PASS |

## Test Execution Report

```
VITEST:
  Test Files:  13 passed (13)
  Tests:       103 passed (103)
  Duration:    1.87s

  Breakdown by package:
    apps/signaling:          2 files, 10 tests - PASS
    apps/cp-daemon:          4 files, 31 tests - PASS
    apps/validator-daemon:   4 files, 31 tests - PASS
    packages/shared:         3 files, 31 tests - PASS

OVERALL: ALL PASS
```

## Gap Analysis

### [GAP-001] SC-1: No test asserts DEFAULT_WEIGHTS values match on-chain constants
- **Type**: MISSING TEST — the `DEFAULT_WEIGHTS` object in `event-handler.ts` has the correct values (`rtt: 2_500n, stake: 1_500n`) but no test explicitly asserts these values match `constants.move`
- **Risk**: LOW — values are hardcoded constants that change rarely; any drift would require manual inspection. The code itself is correct.
- **Recommendation**: Add a unit test in `event-handler.test.ts` that asserts `DEFAULT_WEIGHTS.rtt === 2_500n` and `DEFAULT_WEIGHTS.stake === 1_500n` to prevent regression.

### [GAP-002] SC-3: No direct unit test for `extractCreatedObjectByType` in shared package
- **Type**: WEAK COVERAGE — the helper function in `packages/shared/src/chain/tx.ts:84-102` is only tested indirectly via CP and validator auto-register test suites. The shared `tx.test.ts` only tests `executeWithRetry`.
- **Risk**: LOW — the helper is simple (type suffix matching) and is exercised by 4+ tests across two daemon test suites including failure cases. But a direct unit test would cover edge cases like: empty created array, missing `objectType` field, missing `reference` field, non-string `objectId`.
- **Recommendation**: Add a dedicated `describe('extractCreatedObjectByType')` block in `packages/shared/src/__tests__/tx.test.ts` testing happy path, no match, null reference, and missing objectType edge cases.

## Cross-Domain Validation

No new Integration Contracts were changed in Phase 6. All changes are internal to daemon code (scoring weights, env config, TX parsing, room ID config). Cross-domain signature validation is not required for this phase.

## Verdict

**All 4 success criteria are satisfied.** The code changes are correct and match the specified requirements. Two minor test coverage gaps exist (GAP-001, GAP-002) but both are LOW risk — the underlying code is correct and functionally tested through adjacent test paths. Phase 6 is **VERIFIED** pending gap closure at the team's discretion.
