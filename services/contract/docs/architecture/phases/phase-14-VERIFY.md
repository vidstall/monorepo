PHASE ARCHITECTURE VERIFICATION -- Phase 14: Integration & Hardening
Date: 2026-03-13
ADD reference: docs/architecture/phases/phase-14-ADD.md

---

## BLUEPRINT vs AS-BUILT

### OnChain Modules

**room_manager.move (extension)**
  Boundary:     MATCH -- RoomInfo extended with assigned_relay, assigned_signaling fields; assign_relay_and_signaling() public ControlPlaneCap-gated; get_room_assignment() public; RoomAssigned event added; add_room_for_testing updated.
  Dependencies: MATCH -- depends on network_registry (pause check), caps (ControlPlaneCap), std::option. No extra dependencies.
  Visibility:   MATCH -- assign_relay_and_signaling = public (ControlPlaneCap-gated); get_room_assignment = public; field accessors = public.
  Verdict:      **CONFORMS**

**signaling_registry.move (extension)**
  Boundary:     MATCH -- remove_if_registered() added as package-only helper; silently removes entry if exists; emits SignalingUnregistered event.
  Dependencies: MATCH -- uses existing table, vec_set imports.
  Visibility:   MATCH -- remove_if_registered = public(package).
  Verdict:      **CONFORMS**

**registration.move (modification)**
  Boundary:     MATCH -- unregister() now accepts &mut SignalingRegistry as second parameter; calls signaling_registry::remove_if_registered for cross-registry cleanup (TD-P11-04).
  Dependencies: MATCH -- added signaling_registry import.
  Visibility:   MATCH -- unregister = public (unchanged visibility, added param).
  Verdict:      **CONFORMS**

**room_manager_tests.move**
  Boundary:     MATCH -- 4 assignment tests added: happy path + accessor verification, nonexistent room aborts 502, closed room aborts 503, unassigned returns none.
  Verdict:      **CONFORMS**

**registration_tests.move**
  Boundary:     MATCH -- unregister tests updated to use setup_phase2() and pass SignalingRegistry parameter. Tests using only register/top_up/update still use setup().
  Verdict:      **CONFORMS** (follows IMP-5 selective migration approach)

**economic_layer_tests.move**
  Boundary:     MATCH -- Added test_create_escrow_room_not_found_aborts (TD-P13-02: E_ROOM_NOT_FOUND 652), test_create_escrow_when_paused_aborts (TD-P13-03: E_PAUSED 650), test_submit_proof_when_paused_aborts (TD-P13-03), test_distribute_rewards_when_paused_aborts (TD-P13-03).
  Verdict:      **CONFORMS**

### OffChain Modules

**metrics-server.ts (relay)**
  Boundary:     MATCH -- HTTP server using Node.js built-in http module; GET /metrics/:roomId returns IC-5 shape; GET /metrics returns global health. Port 4001 default, METRICS_PORT configurable.
  Dependencies: MATCH -- depends on metrics.ts (MetricsTracker), Node.js http module.
  Visibility:   MATCH -- startMetricsServer exported.
  Verdict:      **CONFORMS**

**metrics.ts (relay)**
  Boundary:     MATCH -- getRoomMetrics() aggregates per-room data; getGlobalMetrics() provides health. uniquePeersPerRoom tracked via Set<string>. IC-5 response shapes defined (RoomMetricsResponse, GlobalMetricsResponse).
  Dependencies: MATCH -- no external dependencies.
  Verdict:      **CONFORMS**

**probe.ts (validator)**
  Boundary:     MATCH -- STUN probing via dgram (RFC 5389 Binding Request), relay metrics fetch via http GET. All numeric results use bigint (basis-point invariant maintained).
  Dependencies: MATCH -- Node.js dgram/http/crypto, @dvconf/shared for logger.
  Verdict:      **CONFORMS**

**room-assignment.ts (cp-daemon)**
  Boundary:     MATCH -- pickSignalingNode selects lowest-load candidate. assignRoom builds PTB calling room_manager::assign_relay_and_signaling with correct argument order per IC-1. Uses executeWithRetry.
  Dependencies: MATCH -- @mysten/sui, @dvconf/shared.
  IC-1 Check:   MATCH -- PTB arguments: networkRegistryId, roomManagerId, cpCapId, roomId (pure.address), relayMinerId (pure.address), signalingMinerId (pure.address). Matches on-chain signature.
  Verdict:      **CONFORMS**

**event-handler.ts (cp-daemon)**
  Boundary:     MATCH -- Handles RelayRegistered, RelayLoadUpdated, RelayRTTUpdated, SignalingRegistered, SignalingLoadUpdated, RoomCreated. On RoomCreated: scores relays, picks signaling, submits assignRoom TX.
  Dependencies: MATCH -- imports scoring.ts, room-assignment.ts.
  Verdict:      **CONFORMS**

**index.ts (cp-daemon)**
  Boundary:     MATCH -- Polls relay_registry, control_plane_registry, room_manager, signaling_registry events. Creates event handler with TX context for room assignment.
  Verdict:      **CONFORMS**

**reward-trigger.ts (validator)**
  Boundary:     MATCH -- triggerDistribution builds PTB with all 6 shared object arguments in correct order per IC-3: net_reg, escrow, room_mgr, relay_reg, validator_reg, relay_stake. waitForProofs polls escrow object for proof_count.
  Dependencies: MATCH -- @mysten/sui, @dvconf/shared.
  Verdict:      **CONFORMS** (fixed 2026-03-13)

**index.ts (validator)**
  Boundary:     MATCH -- Room lifecycle management via activeRooms map; RoomCreated adds to measurement set; RoomClosed triggers handleRoomClosed with proof waiting and reward distribution. EscrowCreated events tracked via escrowMap. collectMeasurements remains synchronous (see DEV-2).
  Dependencies: MATCH -- imports probe.ts, reward-trigger.ts.
  Verdict:      **CONFORMS** (with DEV-2 justified deviation on IC-8)

**shared/types/events.ts**
  Boundary:     MATCH -- RoomAssigned interface added with room_id, relay_id, signaling_id. Matches on-chain event struct exactly. All Phase 14 event types present.
  Verdict:      **CONFORMS**

**shared/types/chain.ts**
  Boundary:     MATCH -- signalingRegistryId added to NetworkConfig. economicLayerModuleName exported.
  Verdict:      **CONFORMS**

**shared/types/constants.ts**
  Boundary:     MATCH -- All error code namespaces present including roomManager (500-506), signalingRegistry (600-604), economicLayer (650-661). MIN_PROOFS_FOR_DISTRIBUTION exported.
  Verdict:      **CONFORMS**

**load-test.ts**
  Boundary:     MATCH -- createRoom PTB passes all 4 arguments in correct order: networkRegistryId, roomManagerId, userRegistryId, relay_mode. createEscrow, waitForAssignment, closeRoom, simulateClient, waitForRewards all correctly structured.
  Verdict:      **CONFORMS** (fixed 2026-03-13)

### FE Modules

**useEscrow.ts**
  Boundary:     MATCH -- Fetches DVCONF coins (Coin<TOKEN>), merges + splits payment amount, calls economic_layer::create_escrow. Error humanization via txErrors. IC-7 contract followed.
  Dependencies: MATCH -- @mysten/dapp-kit, config.ts, txErrors.ts.
  Verdict:      **CONFORMS**

**useRoomAssignment.ts**
  Boundary:     MATCH -- devInspect get_room_assignment, BCS decodes returnValues[0] and returnValues[1] separately as Option<ID> (per IMP-7). Resolves relay/signaling IDs to endpoint URLs via borrow_info devInspect. Polls every 3s, stops on resolution.
  Dependencies: MATCH -- @mysten/dapp-kit, @mysten/sui/bcs, config.ts.
  IC-2 Check:   MATCH -- devInspect call, BCS decode of Option<ID> per IC-2 spec.
  Verdict:      **CONFORMS**

**useRelay.ts (modification)**
  Boundary:     MATCH -- Added 'reconnecting' session state. Exponential backoff: 1s, 2s, 4s (3 retries). Local media preserved during reconnect. Manual reconnect button exposed. relayUrlRef synced with prop for reassignment awareness.
  Dependencies: MATCH -- mediasoup-client.
  Verdict:      **CONFORMS**

**RoomPage.tsx (modification)**
  Boundary:     MATCH -- Three-step flow: (1) Deposit Escrow, (2) Wait for assignment, (3) Join Session. Uses useEscrow + useRoomAssignment. Reconnecting UI with spinner and attempt count. Error state with manual Reconnect button. Assignment info shown. Auto-leave on room close.
  Dependencies: MATCH -- useRelay, useEscrow, useRoomAssignment.
  Verdict:      **CONFORMS**

---

## DEVIATIONS

### [DEV-1] reward-trigger.ts -- distribute_rewards PTB argument mismatch (FIXED)
  Type: DRIFT -> RESOLVED (2026-03-13)
  Original severity: ERROR
  Description:
    The PTB originally passed 4 arguments in wrong order. Fixed to pass all 6 shared object
    arguments in correct order per IC-3: net_reg, escrow, room_mgr, relay_reg, validator_reg, relay_stake.
  Resolution: OffChain Agent added config.relayRegistryId and config.validatorRegistryId, reordered arguments.

### [DEV-2] collectMeasurements remains synchronous (JUSTIFIED DEVIATION)
  Type: JUSTIFIED DEVIATION
  Description:
    IC-8 in the ADD specified that collectMeasurements would become async with optional params for real probing. The implementation kept collectMeasurements synchronous (simulation only) and instead calls fetchRelayMetrics separately in measureRoom(). This achieves the same functional result (real relay metrics fetched when available, simulation fallback otherwise) with cleaner separation of concerns. The sync simulation path has zero callers that need updating.
  Reason: Better separation of concerns; no functional difference.

### [DEV-3] load-test.ts -- create_room TX missing UserRegistry argument (FIXED)
  Type: DRIFT -> RESOLVED (2026-03-13)
  Original severity: ERROR
  Description:
    The createRoom PTB originally passed only 3 arguments, missing UserRegistry.
    Fixed to include config.userRegistryId as the third argument.
  Resolution: OffChain Agent added tx.object(config.userRegistryId) as third argument.

---

## TECH DEBT VERIFICATION

### TD-P11-04: Signaling cleanup on unregister -- **RESOLVED**
  registration.move now accepts `&mut SignalingRegistry` and calls `signaling_registry::remove_if_registered(signaling_reg, miner_id)` on unregister. Tests updated.

### TD-P13-02: Missing E_ROOM_NOT_FOUND test -- **RESOLVED**
  `test_create_escrow_room_not_found_aborts` added in economic_layer_tests.move. Calls create_escrow with non-existent room ID, expects abort 652.

### TD-P13-03: Missing E_PAUSED tests -- **RESOLVED**
  Three tests added:
  - `test_create_escrow_when_paused_aborts` (abort 650)
  - `test_submit_proof_when_paused_aborts` (abort 650)
  - `test_distribute_rewards_when_paused_aborts` (abort 650)

---

## NEW TECH DEBT INTRODUCED

_None. Both findings (TD-P14-01, TD-P14-02) were fixed during the verification cycle._

### Previously found and resolved within this phase:

- [TD-P14-01] reward-trigger.ts distribute_rewards PTB argument mismatch -- RESOLVED 2026-03-13
- [TD-P14-02] load-test.ts create_room TX missing UserRegistry -- RESOLVED 2026-03-13

---

## ARCHITECTURE HEALTH TREND

  Phase 13:   8/10
  Phase 14:   8/10 (after fixes)
  Direction:  STABLE

  Coupling:    8/10  -- clean module boundaries maintained
  Cohesion:    9/10  -- each module has single responsibility
  Testability: 9/10  -- good test coverage, tech debt tests added
  Consistency: 8/10  -- naming conventions consistent; all IC contracts now match

---

## CROSS-PHASE INTEGRATION

  Phase 13 -> Phase 14: Clean (after fixes)
  Issues: None remaining. DEV-1 and DEV-3 resolved.

---

## OPEN BUG REVIEW

  BUG-OFF-001 (Reversal Protocol not followed on Task 4 shared type changes): OPEN -- process violation from Phase 13, does not block Phase 14 code correctness.
  BUG-ON-*: No bugs.
  BUG-FE-*: No bugs.

---

## VERIFICATION VERDICT: **CONFORMS**

All 22 reviewed files conform to the approved ADD.

Two critical integration mismatches (DEV-1, DEV-3) were found during initial review and
fixed by the OffChain Agent on 2026-03-13. Re-verification confirmed both fixes are correct.

One justified deviation (DEV-2: collectMeasurements kept synchronous) accepted -- achieves
same functional result with cleaner separation of concerns.

Three tech debt items (TD-P11-04, TD-P13-02, TD-P13-03) confirmed resolved.
No new tech debt remains from this phase.
