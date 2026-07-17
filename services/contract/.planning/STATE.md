---
gsd_state_version: 1.0
milestone: v4.0
milestone_name: "Decentralized Consensus"
status: complete
stopped_at: "v4.0 shipped — Phases 17-18 complete"
last_updated: "2026-03-27"
last_activity: "2026-03-27 - Phase 18 shipped (slashing, validator enforcement, daemon filtering)"
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 2
  completed_plans: 2
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-09)

**Core value:** Users can hold real-time video conferences through decentralized relay nodes where honest operators are economically rewarded and dishonest ones are slashed -- all verifiable on-chain.
**Current focus:** v4.0 complete — all phases shipped

## Current Position

Phase: 18 (Multi-Validator Assignment) -- COMPLETE
Plan: 1/1 (8 tasks)
Status: All tasks complete, 206 Move tests passing, spec coverage 97%
Last activity: 2026-03-27 -- Phase 18 shipped (slashing + validator enforcement)

Progress: [==========] 100% (2/2 v4.0 phases complete)

## Phase 16 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: On-chain security fixes (SEC-001, SEC-002) | SEC-001, SEC-002, SEC-009 | QC Approved (1 fix cycle) |
| T2: Overflow protection in reward calc | SEC-003 | QC Approved (1 fix cycle) |
| T3: Cross-registry cleanup on unregister | P1-7 | QC Approved (1 fix cycle) |
| T4: Fix skill file error codes | DOC/CONSIST-01 | QC Approved |
| T5: Fix broken refs in CLAUDE.md | DOC/DEPLOY-03 | QC Approved |
| T6: Update README error codes | DOC/DEPLOY-01 | QC Approved |
| T7: Create daemons README | DOC/README-01 | QC Approved |
| T8: Create client README | DOC/README-02 | QC Approved |
| T9: WebSocket hardening | SEC-005, SEC-006 | QC Approved |
| T10: Add .env.example files | DOC/DEPLOY-02 | QC Approved |
| T11: QC batch review | Quality gate | APPROVED (1 fix cycle) |

## Phase 16 Files Created/Modified

### New files (8):
- `dvconf-daemons/README.md` — monorepo overview, per-daemon run guide
- `dvconf-client/README.md` — client overview, env vars, architecture
- `dvconf-daemons/apps/cp-daemon/.env.example` — CP daemon env vars
- `dvconf-daemons/apps/validator-daemon/.env.example` — validator daemon env vars
- `dvconf-daemons/apps/signaling/.env.example` — signaling daemon env vars
- `dvconf-daemons/apps/relay/.env.example` — relay daemon env vars
- `docs/architecture/contract-changes/CC-016-unregister-cleanup.md` — CONTRACT CHANGE notice

### Modified files (OnChain — 8):
- `sources/miner/staking.move` — assert locked in destroy() (SEC-001)
- `sources/registry/economic_layer.move` — creator gate on distribute_rewards (SEC-002), overflow-safe formula (SEC-003)
- `sources/miner/registration.move` — unregister() accepts 4 registry params, calls cleanup
- `sources/registry/relay_registry.move` — add remove_if_registered()
- `sources/registry/validator_registry.move` — add remove_if_registered()
- `sources/registry/control_plane_registry.move` — add remove_if_registered()
- `tests/registry/economic_layer_tests.move` — 3 new tests
- `tests/miner/registration_tests.move` — updated unregister calls
- `tests/verification/phase_14_gaps.move` — updated unregister call

### Modified files (OffChain — 2):
- `dvconf-daemons/apps/signaling/src/index.ts` — maxPayload + rate limiting
- `dvconf-daemons/apps/relay/src/signaling.ts` — maxPayload

### Modified files (Docs — 4):
- `docs/skills/ONCHAIN_AGENT_SKILL.md` — fixed error code namespace table
- `CLAUDE.md` — fixed broken phase1-foundation.md path
- `README.md` — added Phase 2+ error codes, updated UC3 unregister example
- `.planning/AGENT_ROUTING.md` — updated error codes and spec path

## Phase 15 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: Fix waitForProofs proofs vector read | ECON-01, ECON-02 | QC Approved |
| T2: Populate relayStakeId from RoomAssigned events | ECON-01, ECON-02 | QC Approved |
| T3: Fix tx.pure.id() for Move ID params | ECON-01 (transitive) | QC Approved |
| T4: Add reward-trigger tests (5 tests) | ECON-01, ECON-02 (coverage) | QC Approved |

## Phase 15 Files Created/Modified

### New files (1):
- `dvconf-daemons/apps/validator-daemon/src/__tests__/reward-trigger.test.ts` — 5 tests for waitForProofs + lookupRelayStakeId

### Modified files (OffChain — 3):
- `dvconf-daemons/apps/validator-daemon/src/reward-trigger.ts` — fixed proofs vector read (BUG-INT-002), added lookupRelayStakeId export (BUG-INT-001)
- `dvconf-daemons/apps/validator-daemon/src/index.ts` — RoomAssigned event handler, relayMinerId field on ActiveRoom
- `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts` — tx.pure.id() for Move ID params (BUG-INT-004)

## Phase 13 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: Add economic constants to constants.move | ECON-01 (partial) | QC Approved |
| T2: Create economic_layer.move module | ECON-01, ECON-02, ECON-03 | QC Approved (1 fix cycle) |
| T3: Write economic_layer tests (19 tests) | ECON-01, ECON-02, ECON-03 (coverage) | QC Approved (1 fix cycle) |
| T4: Update shared types for economic layer | ECON-03 (partial) | QC Approved |
| T5: Upgrade validator daemon proof submission | ECON-03 | QC Approved |
| T6: Add signaling node economic tracking | ECON-01 (partial) | QC Approved |

## Phase 13 Files Created/Modified

### New files (2):
- `sources/registry/economic_layer.move` — RoomEscrow, SessionProof, create_escrow, submit_session_proof, distribute_rewards
- `tests/registry/economic_layer_tests.move` — 19 test cases

### Modified files (OnChain — 5):
- `sources/core/constants.move` — 10 economic constants + accessors
- `sources/registry/validator_registry.move` — lookup_session_wallet + test helper
- `sources/registry/room_manager.move` — add_room_for_testing test helper
- `sources/registry/relay_registry.move` — add_relay_for_testing test helper
- `sources/miner/staking.move` — create_for_testing/destroy_for_testing test helpers
- `tests/helpers.move` — setup_phase3()

### Modified files (OffChain — 5):
- `dvconf-daemons/packages/shared/src/types/constants.ts` — error codes 650-661, economic constants
- `dvconf-daemons/packages/shared/src/types/events.ts` — 4 economic event interfaces
- `dvconf-daemons/packages/shared/src/types/chain.ts` — economicLayerModuleName
- `dvconf-daemons/apps/validator-daemon/src/session-proof.ts` — BCS serialization + PTB submission
- `dvconf-daemons/apps/validator-daemon/src/index.ts` — escrow discovery + proof wiring
- `dvconf-daemons/apps/signaling/src/rooms.ts` — sessionsRouted counter
- `dvconf-daemons/apps/signaling/src/index.ts` — reward eligibility logging

## Phase 12 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: Add get_active_relays() to RelayRegistry | RELAY-04 (partial) | QC Approved |
| T2: Update shared types for relay daemon | RELAY-05 (partial) | QC Approved (1 fix cycle) |
| T3: Create relay daemon with mediasoup | RELAY-05 | QC Approved |
| T4: Client relay discovery hook | RELAY-04 | QC Approved |
| T5: Replace P2P WebRTC with mediasoup-client | RELAY-01, RELAY-02, RELAY-03 | QC Approved (1 fix cycle) |
| T6: Update relay heartbeat | RELAY-05 (partial) | QC Approved (no changes needed) |

## Phase 11 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: Add signaling role constant and threshold | SIG-01 (partial) | QC Approved |
| T2: Create SignalingRegistry module | SIG-01, SIG-02 | QC Approved |
| T3: Write SignalingRegistry tests (18 tests) | SIG-01, SIG-02 (coverage) | QC Approved |
| T4: Fix relay_registry ownership bugs | BUG-RR-01, BUG-RR-02 | QC Approved |
| T5: Update shared constants (OffChain) | SIG-01 (type sync) | QC Approved |
| T6: Upgrade signaling daemon to chain-aware | SIG-01, SIG-02 | QC Approved (1 fix cycle) |
| T7: Client signaling discovery hook | SIG-03, SIG-04 | QC Approved |

## Phase 11 Files Created/Modified

### New files (5):
- `sources/registry/signaling_registry.move` — SignalingRegistry module (register, heartbeat, load, discovery)
- `tests/registry/signaling_registry_tests.move` — 18 test cases
- `dvconf-daemons/apps/signaling/src/auto-register.ts` — two-step chain registration
- `dvconf-daemons/apps/signaling/src/heartbeat.ts` — combined heartbeat+load PTB (30s)
- `dvconf-client/src/hooks/useSignalingDiscovery.ts` — devInspect discovery + region/load scoring

### Modified files (10):
- `sources/core/network_registry.move` — RoleThresholds 4th field (signaling_threshold)
- `sources/miner/staking.move` — signaling tier in determine_role/minimum_for_role
- `sources/miner/miner_store.move` — signaling_miners VecSet + role_signaling() accessor
- `tests/core/network_registry_tests.move` — updated threshold tests with 4th param
- `tests/registry/relay_registry_tests.move` — 2 new ownership violation tests
- `tests/helpers.move` — signaling setup helpers
- `dvconf-daemons/packages/shared/src/types/constants.ts` — MinerRole.Signaling, error codes 600-604
- `dvconf-daemons/packages/shared/src/types/events.ts` — 4 signaling event types
- `dvconf-daemons/packages/shared/src/types/chain.ts` — signalingRegistryId in NetworkConfig
- `dvconf-daemons/apps/signaling/src/index.ts` — chain bootstrap startup

## Phase 10 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: Config + env vars for new shared objects | supports POLISH-01, POLISH-02 | QC Approved |
| T2: Network status dashboard (useNetworkStats + NetworkStatus) | POLISH-01 | QC Approved |
| T3: Token balance in header (useTokenBalance + Header update) | POLISH-02 | QC Approved |
| T4: Participant display names (useParticipantNames + VideoGrid) | POLISH-03 | QC Approved |

## Phase 10 Files Created/Modified

### New files (4):
- `src/hooks/useNetworkStats.ts` — devInspect batched registry counts (6 moveCall in 1 TX)
- `src/hooks/useTokenBalance.ts` — getBalance for DVCONF token, 9-decimal formatting
- `src/hooks/useParticipantNames.ts` — devInspect borrow_profile + BCS UserProfile decode
- `src/components/NetworkStatus.tsx` — stat card grid (users, rooms, relays, CPs, validators, total)

### Modified files (5):
- `src/config.ts` — added MINER_STORE_ID, RELAY_REGISTRY_ID, CONTROL_PLANE_REGISTRY_ID, VALIDATOR_REGISTRY_ID
- `.env.example` — added 4 new VITE_ entries
- `src/components/Header.tsx` — added DVCONF token balance display
- `src/components/VideoGrid.tsx` — added peerNames prop for display name labels
- `src/pages/HomePage.tsx` — embedded NetworkStatus panel
- `src/pages/RoomPage.tsx` — wired useParticipantNames hook, passes peerNames to VideoGrid

## Phase 9 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: useWebRTC multi-peer streams (Map\<peerId, MediaStream\>) | RTC-03, RTC-05 | QC Approved |
| T2: Tiled VideoGrid + MediaControls | RTC-01, RTC-04 | QC Approved |
| T3: RoomPage session orchestration | RTC-01, RTC-02, RTC-03, RTC-04, RTC-05 | QC Approved |
| T4: Connection stats hook + overlay | RTC-06 | QC Approved |

## Phase 8 Task Status

| Task | Requirements | Status |
|------|-------------|--------|
| T1: Router shell (react-router-dom, BrowserRouter, Routes) | ROOM-03 | Complete |
| T7: Fix @mysten/sui version mismatch (1.0→1.45) | Tech debt | Complete |
| T2: Wallet connect header + registration gate | CLIENT-01, CLIENT-02, CLIENT-03, CLIENT-04 | Complete |
| T4: Room status polling (devInspect + BCS decode) | ROOM-02 | Complete |
| T3: Room creation + closeRoom + humanizeChainError | ROOM-01, ROOM-04, CLIENT-04 | Complete |
| T5: Network pause guard (useNetworkPause + PauseBanner) | ROOM-05 | Complete |
| T6: Room page join flow + close room UI | ROOM-03, ROOM-04, CLIENT-04 | Complete |

## Performance Metrics

**Velocity:**
- Total plans completed: 11 (v1.0) + 4 (v2.0)
- Average duration: ~45 min (v1.0 estimate)

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| v1.0 Phases 1-6 | 11 | ~8h | ~45min |
| v2.0 Phase 7 | 1 (5 tasks) | - | - |
| v2.0 Phase 8 | 1 (7 tasks) | - | - |
| v2.0 Phase 9 | 1 (4 tasks) | - | - |
| v2.0 Phase 10 | 1 (4 tasks) | - | - |

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table for full history.
Recent decisions affecting current work:

- v2.0: P2P WebRTC via signaling server (no mediasoup -- deferred to v3.0)
- v2.0: react-router-dom v6 for URL-based room routing
- v2.0: No Zustand/Redux -- React Query for chain state, refs for WebRTC state
- Phase 8: devInspectTransactionBlock as PRIMARY pattern for reading Table entries (simpler than getDynamicFieldObject)
- Phase 8: humanizeChainError with regex MoveAbort parsing (not string.includes)
- Phase 8: BrowserRouter inside WalletProvider, outside App (ADD IMP-5)
- Phase 8: Registration gate in App.tsx blocks routes until registered
- Phase 8: isPaused disables write buttons but NOT join navigation
- Phase 8: @mysten/sui upgraded to 1.45.2 (resolved version mismatch)
- Phase 10: Dashboard as panel on HomePage (not separate route)
- Phase 10: devInspect batches 6 moveCall ops in single TX for network stats
- Phase 10: Token balance via getBalance (not devInspect), 30s polling
- Phase 10: Participant names cached per session, devInspect per address

### Pending Todos

- @mysten/sui vs dapp-kit Transaction type mismatch requires `as any` casts — cosmetic, no runtime impact
- Confirm devInspect BCS decode works on localnet/testnet (borrow_room returns &RoomInfo reference)
- Token coin type uses PACKAGE_ID which must be the original publisher ID (not upgraded package ID)

### Repo Structure (updated 2026-03-10)

- `dvconf-contracts/` — Sui Move on-chain contracts (git repo)
- `dvconf-daemons/` — Node.js off-chain daemons: signaling, CP, validator (git repo, pnpm monorepo)
- `dvconf-client/` — React client app (git repo, standalone Vite project)

### Blockers/Concerns

- mediasoup relay deferred to v3.0 -- P2P path only for v2.0 demos
- join_room confirmed: NO on-chain TX needed (signaling server only)

## Session Continuity

Last session: 2026-03-10
Stopped at: Phase 10 tasks complete, awaiting verification
Resume file: None
