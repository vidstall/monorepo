---
phase: 03-off-chain-daemons
plan: 01
subsystem: off-chain-daemons
tags: [typescript, pnpm, monorepo, websocket, sui-sdk, vitest, pino, ws]

# Dependency graph
requires:
  - phase: 02-registry-layer
    provides: "Move event structs and registry contracts that daemons consume"
provides:
  - "@dvconf/shared package with Move event types, TX retry wrapper, EventPoller, keypair loader, SuiClient factory, pino logger"
  - "@dvconf/signaling WebSocket server with room-based ICE/SDP routing"
  - "pnpm monorepo skeleton at dvconf-daemons/ for all daemon packages"
affects: [03-02-PLAN, 03-03-PLAN, cp-daemon, validator-daemon]

# Tech tracking
tech-stack:
  added: ["@mysten/sui ^1.0.0", "ws ^8", "pino ^9", "vitest ^3", "tsx ^4", "tsup ^8", "dotenv ^16"]
  patterns: ["executeWithRetry exponential backoff (1s/2x/30s/5)", "EventPoller cursor-based queryEvents polling", "room-based WebSocket routing", "pnpm workspace with packages/ and apps/"]

key-files:
  created:
    - "dvconf-daemons/packages/shared/src/chain/tx.ts"
    - "dvconf-daemons/packages/shared/src/chain/events.ts"
    - "dvconf-daemons/packages/shared/src/types/events.ts"
    - "dvconf-daemons/packages/shared/src/types/constants.ts"
    - "dvconf-daemons/apps/signaling/src/rooms.ts"
    - "dvconf-daemons/apps/signaling/src/index.ts"
  modified: []

key-decisions:
  - "Used SuiClient (not SuiGrpcClient) for stability -- abstracted behind factory for future migration"
  - "queryEvents polling with cursor persistence (not deprecated subscribeEvent)"
  - "Signaling uses @dvconf/shared ONLY for logger -- zero chain imports (DAEMON-02)"
  - "Separate git repo for dvconf-daemons (sibling of dvconf-contracts)"

patterns-established:
  - "executeWithRetry: all chain writes go through shared TX wrapper with backoff"
  - "EventPoller: all event consumption uses cursor-based polling with file persistence"
  - "createLogger(service): all daemons use pino structured logging"
  - "Room-based WebSocket routing with peer notifications"

requirements-completed: [DAEMON-01, DAEMON-02, DAEMON-07, DAEMON-11, DAEMON-12]

# Metrics
duration: 15min
completed: 2026-03-05
---

# Phase 3 Plan 1: Monorepo + Shared + Signaling Summary

**pnpm monorepo with @dvconf/shared chain helpers (TX retry, EventPoller, 17 Move event types) and @dvconf/signaling WebSocket server for ICE/SDP exchange**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-05T12:19:00Z
- **Completed:** 2026-03-05T12:31:00Z
- **Tasks:** 2
- **Files created:** 25

## Accomplishments
- pnpm monorepo at `dvconf-daemons/` with ESM-only TypeScript strict mode throughout
- @dvconf/shared exports 17 Move event type interfaces, TX wrapper with exponential backoff (1s/2x/30s/5 retries), EventPoller with cursor-based queryEvents pagination, keypair loader, SuiClient factory, pino logger
- @dvconf/signaling: stateless WebSocket server with room-based ICE/SDP routing, peer notifications, graceful shutdown -- zero chain dependency (DAEMON-02 verified by test)
- 41 tests passing (31 shared + 10 signaling)

## Task Commits

Each task was committed atomically in the `dvconf-daemons` repository:

1. **Task 1: Create monorepo skeleton + @dvconf/shared package** - `1df543c` (feat)
2. **Task 2: Build signaling WebSocket server with room-based routing** - `163a99e` (feat)

## Files Created

**Root config:**
- `dvconf-daemons/package.json` - Root monorepo config with scripts
- `dvconf-daemons/pnpm-workspace.yaml` - Workspace definition (packages/*, apps/*)
- `dvconf-daemons/tsconfig.base.json` - Shared TypeScript strict config
- `dvconf-daemons/vitest.config.ts` - Test framework config
- `dvconf-daemons/.env.example` - Environment variable template
- `dvconf-daemons/.gitignore` - Ignore patterns

**@dvconf/shared package:**
- `packages/shared/src/types/events.ts` - 17 Move event interfaces (MinerRegistered, CPHeartbeat, RoomCreated, etc.)
- `packages/shared/src/types/chain.ts` - SuiObjectRef, NetworkConfig, TxResult types
- `packages/shared/src/types/constants.ts` - RelayMode, MinerRole enums, ErrorCodes namespaces
- `packages/shared/src/chain/client.ts` - SuiClient factory with network config loader
- `packages/shared/src/chain/tx.ts` - executeWithRetry with exponential backoff
- `packages/shared/src/chain/events.ts` - EventPoller class with cursor persistence
- `packages/shared/src/chain/keypair.ts` - Keypair loader and session wallet generator
- `packages/shared/src/logger.ts` - Pino logger factory (pretty in dev, JSON in prod)
- `packages/shared/src/index.ts` - Barrel export
- `packages/shared/src/__tests__/tx.test.ts` - 4 tests for TX retry
- `packages/shared/src/__tests__/events.test.ts` - 4 tests for EventPoller
- `packages/shared/src/__tests__/types.test.ts` - 23 tests for type compilation

**@dvconf/signaling app:**
- `apps/signaling/src/rooms.ts` - RoomManager class with join/leave/broadcast
- `apps/signaling/src/index.ts` - WebSocket signaling server (ICE/SDP/offer/answer)
- `apps/signaling/src/__tests__/rooms.test.ts` - 7 unit tests for RoomManager
- `apps/signaling/src/__tests__/signaling.test.ts` - 3 integration tests + DAEMON-02 compliance check

## Decisions Made
- Used `SuiClient` from `@mysten/sui/client` (not `SuiGrpcClient`) for stability; factory abstraction allows one-line migration later
- queryEvents polling with cursor persistence to file (not deprecated subscribeEvent WebSocket)
- Signaling imports @dvconf/shared ONLY for logger -- verified by test that source files contain zero `@mysten/sui` imports
- Separate git repo for dvconf-daemons as sibling directory (not subdirectory of dvconf-contracts)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- @dvconf/shared package ready for CP daemon (03-02) and Validator daemon (03-03) to consume
- TX wrapper, EventPoller, and Move event types are the foundation for all chain-interacting daemons
- Signaling server is complete and independent -- no further work needed for it

## Self-Check: PASSED

- All 5 key source files verified on disk
- Commit 1df543c verified in dvconf-daemons git log
- Commit 163a99e verified in dvconf-daemons git log
- 03-01-SUMMARY.md verified on disk
- 41 tests confirmed passing (31 shared + 10 signaling)

---
*Phase: 03-off-chain-daemons*
*Completed: 2026-03-05*
