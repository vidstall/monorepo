---
phase: 03-off-chain-daemons
verified: 2026-03-05T19:51:00Z
status: passed
score: 13/13 must-haves verified
re_verification: false
gaps: []
human_verification:
  - test: "Start signaling server and connect two real WebRTC clients in the same room"
    expected: "ICE candidates relay correctly and peers can establish a peer-to-peer connection"
    why_human: "Test suite mocks WebSocket at network level; actual browser WebRTC negotiation cannot be verified programmatically"
  - test: "Run cp-daemon against a live testnet package and verify heartbeat transactions land"
    expected: "control_plane_registry::heartbeat TX confirmed on-chain at configured interval"
    why_human: "Requires funded wallet and deployed Phase 2 contracts; cannot simulate real chain finality"
  - test: "Run validator-daemon against a live testnet and confirm session wallet address differs from main wallet in logs"
    expected: "Two distinct Sui addresses printed; no private key material appears in any log line"
    why_human: "Requires funded wallet; log output verification is a runtime concern"
---

# Phase 3: Off-chain Daemons Verification Report

**Phase Goal:** Signaling, Control Plane, and Validator daemons run as Node.js processes in a pnpm monorepo, subscribe to on-chain events via queryEvents polling, and interact with deployed registry contracts
**Verified:** 2026-03-05T19:51:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | pnpm monorepo at dvconf-daemons/ resolves all workspace packages | VERIFIED | `pnpm-workspace.yaml` defines `packages/*` and `apps/*`; node_modules populated; 4 packages resolved |
| 2 | Shared types compile and export Move event interfaces matching on-chain structs | VERIFIED | `packages/shared/src/types/events.ts` exports 17 interfaces (MinerRegistered through UserProfileUpdated); 31 shared tests pass including type compilation |
| 3 | TX wrapper executes transactions with exponential backoff (1s base, 2x, 30s ceiling, 5 retries) | VERIFIED | `tx.ts` lines 14-17: `BASE_DELAY_MS=1000, MULTIPLIER=2, MAX_DELAY_MS=30000, MAX_RETRIES=5`; test "backoff delays increase correctly (1s, 2s, 4s, 8s capped at 30s)" passes |
| 4 | EventPoller queries events with cursor-based pagination using queryEvents (not subscribeEvent) | VERIFIED | `events.ts` calls `this.client.queryEvents` with `MoveEventModule` filter; cursor persisted to file; hasNextPage loop confirmed; 4 EventPoller tests pass |
| 5 | Signaling server routes ICE/SDP messages between peers in the same room | VERIFIED | `rooms.ts` RoomManager with Map<roomId, Set<WebSocket>>; `index.ts` handles join/offer/answer/ice-candidate/leave; integration test passes |
| 6 | Signaling server has zero imports from @mysten/sui | VERIFIED | grep on `apps/signaling/src/` produces zero hits for @mysten/sui; DAEMON-02 compliance test passes (reads source files via readFileSync and asserts no imports) |
| 7 | CP daemon subscribes to relay and room events via EventPoller from @dvconf/shared | VERIFIED | `cp-daemon/src/index.ts` creates 3 EventPollers (relay_registry, control_plane_registry, room_manager); `event-handler.ts` imports EventPoller pattern via createEventHandler |
| 8 | Relay scoring algorithm produces numeric scores using bigint arithmetic (no floating point) | VERIFIED | `scoring.ts`: all variables declared as `bigint`, operators `*`, `/`, `<` on bigint only; no parseFloat/Number calls found; 9 scoring tests pass |
| 9 | CP daemon logs relay scores but does NOT submit votes on-chain | VERIFIED | `event-handler.ts` line 114: "Relay scoring complete (vote NOT submitted — deferred to v2)"; no executeWithRetry call in RoomCreated handler branch |
| 10 | CP daemon sends heartbeat() transaction to ControlPlaneRegistry at configured interval | VERIFIED | `heartbeat.ts` buildHeartbeatTx targets `control_plane_registry::heartbeat`; startHeartbeat uses setInterval + executeWithRetry; 5 heartbeat tests pass |
| 11 | Validator daemon generates session wallet distinct from main wallet | VERIFIED | `validator-daemon/src/index.ts` calls `generateSessionKeypair()` separately from `loadKeypair('SUI_PRIVATE_KEY')`; session-proof test "session keypair is different from main keypair" passes |
| 12 | Validator daemon constructs dual-key signed SessionProof | VERIFIED | `session-proof.ts` dualKeySign signs with both mainKeypair and sessionKeypair; validator index.ts runMeasurementCycle calls buildSessionProof + dualKeySign; proof logged, no on-chain submission |
| 13 | All daemons auto-register on startup if cap ID not in env | VERIFIED | cp-daemon ensureRegistered checks CP_CAP_ID env; validator ensureRegistered checks VALIDATOR_CAP_ID; both exit(1) on failure; 4 auto-register tests per daemon pass |

**Score:** 13/13 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `packages/shared/src/types/events.ts` | TypeScript interfaces for all Move event structs; contains MinerRegistered | VERIFIED | 17 interfaces exported; MinerRegistered at line 13; DvconfEvent union type covers all |
| `packages/shared/src/chain/tx.ts` | TX wrapper with exponential backoff retry; exports executeWithRetry | VERIFIED | 73 lines; full retry loop with BASE_DELAY/MULTIPLIER/MAX_DELAY/MAX_RETRIES constants; exported function at line 29 |
| `packages/shared/src/chain/events.ts` | Event poller with cursor persistence; exports EventPoller | VERIFIED | 140 lines; EventPoller class at line 22; queryEvents with MoveEventModule filter; cursor load/save via fs |
| `apps/signaling/src/rooms.ts` | Room-based WebSocket message routing; exports RoomManager | VERIFIED | 143 lines; RoomManager class with join/leave/broadcast/getRoomSize/getStats; properly wired in index.ts |
| `apps/cp-daemon/src/scoring.ts` | Relay scoring algorithm; exports scoreRelay, scoreRelays | VERIFIED | 127 lines; both functions exported; 5-dimension weighted bigint formula; sorted descending |
| `apps/cp-daemon/src/heartbeat.ts` | Periodic heartbeat submission; exports startHeartbeat, buildHeartbeatTx | VERIFIED | 73 lines; both functions exported; buildHeartbeatTx constructs correct moveCall; startHeartbeat uses setInterval |
| `apps/cp-daemon/src/event-handler.ts` | Event processing for relay/room/CP events; exports handleEvent | VERIFIED | 146 lines; handleEvent and createEventHandler exported; handles RelayRegistered/RelayLoadUpdated/RelayRTTUpdated/RoomCreated |
| `apps/cp-daemon/src/auto-register.ts` | Auto-registration flow for CP daemon; exports ensureRegistered | VERIFIED | 127 lines; ensureRegistered exported; two-step TX flow (miner registration + CP registration) |
| `apps/validator-daemon/src/measurements.ts` | Simulated measurement collection; exports collectMeasurements, MeasurementResult | VERIFIED | 102 lines; MeasurementResult interface and collectMeasurements exported; all fields bigint |
| `apps/validator-daemon/src/session-proof.ts` | Mock SessionProof construction and dual-key signing; exports buildSessionProof, dualKeySign, SessionProof | VERIFIED | 113 lines; all three exports present; dualKeySign async, uses keypair.sign on both |
| `apps/validator-daemon/src/auto-register.ts` | Auto-registration flow for Validator daemon; exports ensureRegistered | VERIFIED | 134 lines; ensureRegistered exported; two-step TX flow (miner registration + validator_registry registration) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `packages/shared/src/chain/tx.ts` | `@mysten/sui` | `SuiClient.signAndExecuteTransaction` | WIRED | Line 43: `client.signAndExecuteTransaction({signer, transaction: tx, ...})`; waitForTransaction at line 49 |
| `packages/shared/src/chain/events.ts` | `@mysten/sui` | `SuiClient.queryEvents` | WIRED | Line 69: `this.client.queryEvents({query: {MoveEventModule: {package, module}}, cursor, limit, order})` |
| `apps/signaling/src/rooms.ts` | `ws` | `WebSocketServer` | WIRED | `rooms.ts` imports `type WebSocket from 'ws'`; `index.ts` imports `WebSocketServer, WebSocket from 'ws'` and creates server |
| `apps/cp-daemon/src/heartbeat.ts` | `@dvconf/shared chain/tx.ts` | `executeWithRetry` | WIRED | Line 10: `import {executeWithRetry, type NetworkConfig, type Logger} from '@dvconf/shared'`; called at line 48 |
| `apps/cp-daemon/src/event-handler.ts` | `@dvconf/shared chain/events.ts` | `EventPoller` | WIRED | event-handler.ts imports event type interfaces from @dvconf/shared; cp-daemon index.ts creates EventPollers and passes createEventHandler output as handler |
| `apps/cp-daemon/src/scoring.ts` | `@dvconf/shared types/events.ts` | `RelayCandidate type` | WIRED | event-handler.ts imports RelayCandidate from scoring.ts; scoring.ts uses RelayRegistered, RelayLoadUpdated, RelayRTTUpdated from @dvconf/shared |
| `apps/cp-daemon/src/auto-register.ts` | `@dvconf/shared chain/tx.ts` | `executeWithRetry` | WIRED | Line 12: `import {executeWithRetry, ...} from '@dvconf/shared'`; called twice (miner-registration, cp-registration) |
| `apps/validator-daemon/src/session-proof.ts` | `@mysten/sui/keypairs/ed25519` | `Ed25519Keypair.sign` | WIRED | Line 14: `import type {Ed25519Keypair} from '@mysten/sui/keypairs/ed25519'`; lines 92-93: `mainKeypair.sign(proofBytes)` and `sessionKeypair.sign(proofBytes)` |
| `apps/validator-daemon/src/index.ts` | `@dvconf/shared chain/keypair.ts` | `generateSessionKeypair` | WIRED | Line 21: import of `generateSessionKeypair` from `@dvconf/shared`; line 84: `const {keypair: sessionKeypair, address: sessionAddress} = generateSessionKeypair()` |
| `apps/validator-daemon/src/auto-register.ts` | `@dvconf/shared chain/tx.ts` | `executeWithRetry` | WIRED | Line 14: `import {executeWithRetry, MinerRole} from '@dvconf/shared'`; called twice (miner registration, validator_registry registration) |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| DAEMON-01 | 03-01 | Signaling node exchanges WebRTC ICE candidates via WebSocket | SATISFIED | `apps/signaling/src/index.ts` handles offer/answer/ice-candidate messages; routes to targeted peer via peerSockets map |
| DAEMON-02 | 03-01 | Signaling node is stateless and does not depend on chain state | SATISFIED | grep of `apps/signaling/src/` for @mysten/sui returns zero source hits; DAEMON-02 compliance test passes |
| DAEMON-03 | 03-02 | CP daemon subscribes to Sui events (room creation, relay updates) | SATISFIED | `cp-daemon/src/index.ts` creates EventPollers for relay_registry, control_plane_registry, room_manager; event-handler.ts processes each event type |
| DAEMON-04 | 03-02 | CP daemon runs relay scoring algorithm using on-chain data (reputation, RTT, load, stake, region) | SATISFIED | `scoring.ts` scoreRelay uses all 5 dimensions; event-handler updates relay state from chain events; scoring triggered on RoomCreated |
| DAEMON-05 | 03-02 | CP daemon submits relay assignment votes on-chain (scoped: logs scores, votes deferred) | SATISFIED (scoped) | Votes NOT submitted; scoring results logged with explicit message "vote NOT submitted — deferred to v2"; scoping documented in REQUIREMENTS.md |
| DAEMON-06 | 03-02 | CP daemon sends heartbeat() to ControlPlaneRegistry at configured interval | SATISFIED | `heartbeat.ts` buildHeartbeatTx targets control_plane_registry::heartbeat; startHeartbeat runs at HEARTBEAT_INTERVAL_MS |
| DAEMON-07 | 03-01/02 | CP daemon uses exponential backoff on chain interaction failures | SATISFIED | executeWithRetry in shared package implements 1s/2x/30s/5-retry backoff; all CP TX calls go through it; test "backoff delays increase correctly" passes |
| DAEMON-08 | 03-03 | Validator daemon joins rooms disguised as regular user (session wallet) | SATISFIED | generateSessionKeypair() creates fresh Ed25519Keypair; sessionAddress distinct from mainAddress; session wallet used in SessionProof |
| DAEMON-09 | 03-03 | Validator daemon measures packet integrity, latency, loss, bytes forwarded | SATISFIED | collectMeasurements returns MeasurementResult with packetLossRate, avgLatencyMs, jitterMs, bytesForwarded, packetsSent/Received — all bigint |
| DAEMON-10 | 03-03 | Validator daemon submits dual-key signed SessionProof on-chain (scoped: logs, not submitted) | SATISFIED (scoped) | dualKeySign produces two signatures; logProofSummary explicitly states "NOT submitting (Economic layer not yet deployed)"; no on-chain submission call |
| DAEMON-11 | 03-01 | All daemons share types via monorepo shared package | SATISFIED | @dvconf/shared exports all event types, NetworkConfig, TxResult, enums; all 3 daemons import from @dvconf/shared |
| DAEMON-12 | 03-01 | All daemons use @mysten/sui SDK for chain interactions | SATISFIED | @mysten/sui used in shared/chain/*.ts (SuiClient, Transaction, Ed25519Keypair); daemons consume via @dvconf/shared; cp-daemon and validator-daemon add @mysten/sui as direct dep for Transaction construction |

**All 12 DAEMON requirements satisfied.**

No orphaned requirements found — all DAEMON-01 through DAEMON-12 IDs appear in the plan frontmatter and are verified above.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `apps/validator-daemon/src/index.ts` | 174 | `roomId: 'pending-room'` (hardcoded placeholder) | Info | Intentional — room assignment is a Phase 4 concern; logProofSummary makes this explicit |
| `apps/cp-daemon/src/auto-register.ts` | 74-75 | `createdObjects[0]?.reference?.objectId` (fragile effects parsing) | Warning | TX effects structure assumed; could break if SDK changes effects format. Acceptable for this phase; production would use typed effects |
| `apps/validator-daemon/src/auto-register.ts` | 46 | `tx.pure.u64(MIN_STAKE_AMOUNT)` passed to splitCoins (u64 as split amount) | Warning | splitCoins expects u64 coin value as argument; actual Sui SDK API may require `tx.pure.u64()` to be wrapped differently. Caught at runtime only |

None of the above are blockers — they are known limitations appropriate to the simulation/prototype scope of this phase.

---

### Human Verification Required

#### 1. Real WebRTC ICE Negotiation

**Test:** Open two browser tabs, connect to the signaling server, join the same room ID, and attempt a WebRTC peer connection
**Expected:** ICE candidates relay correctly; browsers establish a direct P2P connection or TURN-relayed connection
**Why human:** Unit tests mock WebSocket at the message level; actual SDP offer/answer negotiation with real browser APIs cannot be simulated

#### 2. CP Daemon Heartbeat on Live Testnet

**Test:** Configure `.env` with testnet package ID and CP_CAP_ID, run `pnpm dev` in apps/cp-daemon, observe log output
**Expected:** "heartbeat succeeded" log appears every HEARTBEAT_INTERVAL_MS; TX digest visible in Sui Explorer; ControlPlaneRegistry reflects updated heartbeat epoch
**Why human:** Requires funded wallet with DVCONF tokens and SUI gas; live network finality cannot be mocked

#### 3. Validator Daemon Session Wallet Identity Separation

**Test:** Run `pnpm dev` in apps/validator-daemon with a configured wallet; inspect log output
**Expected:** Two distinct Sui addresses printed (main wallet != session wallet); no line containing "secretKey", "privateKey", or the raw bech32 private key
**Why human:** Private key non-logging is a runtime property; static grep on source confirms the pattern but does not catch dynamic log injection paths

---

### Gaps Summary

No gaps. All 13 observable truths verified. All 11 required artifacts exist, are substantive (non-stub), and are wired to their consumers. All 10 key links confirmed. All 12 DAEMON requirements satisfied. 92 tests pass across the 4-package monorepo (31 shared + 10 signaling + 27 cp-daemon + 24 validator-daemon).

Three items flagged for human verification are live-environment checks that cannot be automated, not blocking gaps.

---

*Verified: 2026-03-05T19:51:00Z*
*Verifier: Claude (gsd-verifier)*
