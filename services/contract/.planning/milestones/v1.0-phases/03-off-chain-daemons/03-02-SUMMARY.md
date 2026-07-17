---
phase: 03-off-chain-daemons
plan: "02"
subsystem: cp-daemon
tags: [cp-daemon, scoring, heartbeat, event-polling, auto-registration]
dependency_graph:
  requires: ["03-01"]
  provides: ["cp-daemon-scoring", "cp-daemon-heartbeat", "cp-daemon-event-handler", "cp-daemon-auto-register"]
  affects: ["03-03"]
tech_stack:
  added: ["dotenv"]
  patterns: ["vi.hoisted mock pattern", "bigint-only scoring", "setInterval heartbeat", "in-memory relay state map"]
key_files:
  created:
    - dvconf-daemons/apps/cp-daemon/package.json
    - dvconf-daemons/apps/cp-daemon/tsconfig.json
    - dvconf-daemons/apps/cp-daemon/src/scoring.ts
    - dvconf-daemons/apps/cp-daemon/src/event-handler.ts
    - dvconf-daemons/apps/cp-daemon/src/auto-register.ts
    - dvconf-daemons/apps/cp-daemon/src/heartbeat.ts
    - dvconf-daemons/apps/cp-daemon/src/index.ts
    - dvconf-daemons/apps/cp-daemon/src/__tests__/scoring.test.ts
    - dvconf-daemons/apps/cp-daemon/src/__tests__/event-handler.test.ts
    - dvconf-daemons/apps/cp-daemon/src/__tests__/auto-register.test.ts
    - dvconf-daemons/apps/cp-daemon/src/__tests__/heartbeat.test.ts
  modified:
    - dvconf-daemons/pnpm-lock.yaml
decisions:
  - "Bigint-only scoring: all relay scoring math uses bigint (0-10_000 basis points)"
  - "Scores logged not voted: RoomCreated triggers scoring but votes are NOT submitted (Room lifecycle deferred)"
  - "In-memory relay state: event handler maintains Map<string, RelayCandidate> populated from chain events"
  - "vi.hoisted pattern: vitest mock factories use vi.hoisted() to avoid hoisting issues with vi.mock"
metrics:
  duration: "~8min"
  completed: "2026-03-05"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 27
  tests_total_after: 92
---

# Phase 3 Plan 02: Control Plane Daemon Summary

CP daemon with bigint-only relay scoring, event-driven state management, heartbeat liveness via shared TX wrapper, and auto-registration on startup.

## What Was Built

### Task 1: Relay Scoring Algorithm and Event Handler
- **scoring.ts**: `scoreRelay()` and `scoreRelays()` implementing weighted scoring formula with 5 dimensions (reputation, RTT, load, stake, regionMatch). All math is bigint with basis point normalization (0-10_000). RTT and load use inverse scoring (lower = better, capped at ceiling). Region uses exact match bonus.
- **event-handler.ts**: Processes `RelayRegistered`, `RelayLoadUpdated`, `RelayRTTUpdated`, and `RoomCreated` events. Maintains in-memory `Map<string, RelayCandidate>` relay state. On `RoomCreated`, runs scoring against all known relays and logs ranked results. Unknown events are logged at debug level and skipped. `createEventHandler()` factory returns a handler bound to its own state map.
- **18 tests**: 9 scoring tests (equal weights, region boost, RTT ordering, all-zero, bigint types, cap overflow, sorted output) + 9 event-handler tests (relay add/update/RTT, room scoring, unknown events, graceful handling).

### Task 2: Auto-Registration, Heartbeat, and Entry Point
- **auto-register.ts**: `ensureRegistered()` checks `CP_CAP_ID` env var. If set, returns immediately. If not, executes two transactions via `executeWithRetry`: (1) `registration::register` with role=CP, (2) `control_plane_registry::register_cp`. Exits with clear error on failure.
- **heartbeat.ts**: `buildHeartbeatTx()` constructs the moveCall to `control_plane_registry::heartbeat`. `startHeartbeat()` runs it at a configurable interval via `setInterval`, sending the first heartbeat immediately. Returns a stop function.
- **index.ts**: Entry point that loads env, creates SuiClient, loads keypair, runs auto-registration, starts heartbeat loop, creates 3 EventPollers (relay_registry, control_plane_registry, room_manager), and handles graceful shutdown on SIGTERM/SIGINT.
- **9 tests**: 4 auto-register tests (env skip, two-step registration, failure exit, executeWithRetry usage) + 5 heartbeat tests (moveCall target, interval calls, stop clears, shared wrapper delegation, failure handling).

## Verification Results

- `pnpm --filter @dvconf/cp-daemon test`: 4 test files, 27 tests, all passing
- `pnpm -r test`: 92 tests across all packages (shared 31, signaling 10, cp-daemon 27, validator-daemon 24), all passing
- Scoring uses only bigint math (no parseFloat, no Number() on amounts)
- heartbeat.ts and auto-register.ts import executeWithRetry from @dvconf/shared (not reimplemented)
- Auto-registration checks env first, registers if missing, exits on failure

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 8941a30 | feat(03-02): implement relay scoring algorithm and event handler |
| 2 | 552585b | feat(03-02): implement auto-registration, heartbeat, and CP daemon entry point |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added @mysten/sui as direct dependency**
- **Found during:** Task 2 (test execution)
- **Issue:** cp-daemon source files import from `@mysten/sui/transactions` and `@mysten/sui/client` directly, but only had `@dvconf/shared` as dependency. pnpm strict isolation prevented resolving the transitive dependency.
- **Fix:** Added `"@mysten/sui": "^1.0.0"` to cp-daemon's package.json dependencies.
- **Files modified:** apps/cp-daemon/package.json

**2. [Rule 1 - Bug] Fixed vi.mock hoisting issue in tests**
- **Found during:** Task 2 (test execution)
- **Issue:** `const mockExecuteWithRetry = vi.fn()` declared before `vi.mock()` caused "Cannot access before initialization" error because vitest hoists `vi.mock()` calls above variable declarations.
- **Fix:** Used `vi.hoisted()` pattern: `const { mockExecuteWithRetry } = vi.hoisted(() => ({ mockExecuteWithRetry: vi.fn() }))`.
- **Files modified:** auto-register.test.ts, heartbeat.test.ts

**3. [Rule 3 - Blocking] Removed direct @mysten/sui import from heartbeat test**
- **Found during:** Task 2 (test execution)
- **Issue:** Test file imported `Transaction` from `@mysten/sui/transactions` directly but package was not yet a dependency. Changed to dynamic import within the test.
- **Fix:** Used `await import('@mysten/sui/transactions')` inside the test case.
- **Files modified:** heartbeat.test.ts

## Requirements Covered

- DAEMON-03: CP daemon subscribes to relay and room events via EventPoller
- DAEMON-04: Relay scoring algorithm produces numeric scores using on-chain data
- DAEMON-05: CP daemon logs relay scores but does NOT submit votes on-chain (scoped)
- DAEMON-06: CP daemon sends heartbeat() to ControlPlaneRegistry at configured interval
- DAEMON-07: All chain interactions use exponential backoff via shared TX wrapper
- DAEMON-12: Chain helpers use @mysten/sui SDK via shared package

## Self-Check: PASSED

- All 11 source/test files: FOUND
- Commit 8941a30: FOUND (Task 1)
- Commit 552585b: FOUND (Task 2)
- Full test suite: 92 tests passing
