# Phase 14 Plan: Integration & Hardening
Date: 2026-03-12

## Goal
End-to-end flow works: client discovers signaling node, connects to relay, validators measure quality, rewards are distributed

## Success Criteria
1. Full session lifecycle works: discover signaling -> connect relay -> measure quality -> submit proof -> distribute reward
2. Misbehaving nodes are slashed and returned Coin is accessible
3. Load testing validates concurrent sessions

## Requirements Covered
- SIG-01..06 (integration testing of signaling flow)
- RELAY-01..06 (integration testing of relay flow)
- ECON-01..03 (integration testing of economic flow)
- TD-P11-04, TD-P13-02, TD-P13-03 (tech debt closure)

## Tasks

### Task 1: Extend RoomManager with relay/signaling assignment
- **Agent**: OnChain
- **Files**:
  - `sources/registry/room_manager.move` — add `assigned_relay: Option<ID>`, `assigned_signaling: Option<ID>` to RoomInfo; add `assign_relay_and_signaling()` package-gated function + accessor; add `RoomAssigned` event
  - `tests/registry/room_manager_tests.move` — add assignment tests
  - `tests/helpers.move` — update `add_room_for_testing` if struct changes
- **Requirements**: RELAY-04 (integration), SIG-03 (integration)
- **Depends on**: None
- **Description**: Extend RoomInfo struct with `assigned_relay: Option<ID>` and `assigned_signaling: Option<ID>`. Add `public(package) fun assign_relay_and_signaling(manager, room_id, relay_id, signaling_id)` that sets both fields and emits `RoomAssigned { room_id, relay_id, signaling_id }`. Room must be in PENDING status. Add read accessors `room_assigned_relay()` and `room_assigned_signaling()`. Add a `public fun get_room_assignment(manager, room_id): (Option<ID>, Option<ID>)` for devInspect queries. Update `add_room_for_testing` to include the new fields (defaulting to `option::none()`). Write 3-4 tests: assign succeeds, assign to non-existent room fails, assign to closed room fails, accessor returns correct values.

### Task 2: Close tech debt (OnChain)
- **Agent**: OnChain
- **Files**:
  - `sources/miner/registration.move` — add signaling registry cleanup call on unregister (TD-P11-04)
  - `sources/registry/signaling_registry.move` — add `public(package) fun remove_if_registered()` helper
  - `tests/registry/economic_layer_tests.move` — add test for E_ROOM_NOT_FOUND (TD-P13-02) and E_PAUSED (TD-P13-03)
- **Requirements**: Tech debt (TD-P11-04, TD-P13-02, TD-P13-03)
- **Depends on**: None
- **Description**: TD-P11-04: Add `public(package) fun remove_if_registered(registry, miner_id)` to signaling_registry.move that silently removes an entry if it exists. Call this from `registration::unregister()` passing the SignalingRegistry. This requires unregister to accept `&mut SignalingRegistry` as an additional parameter — check if this breaks existing callers and update accordingly. TD-P13-02: Add test that calls `create_escrow` with a non-existent room_id and expects abort 652. TD-P13-03: Add test that pauses the network, then calls `create_escrow` / `submit_session_proof` / `distribute_rewards` and expects abort 650.

### Task 3: Relay daemon metrics HTTP endpoint
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/relay/src/metrics-server.ts` — new file: Express/http server on port 4001
  - `dvconf-daemons/apps/relay/src/metrics.ts` — add `getRoomMetrics(roomId)` and `getRoomUniquePeers(roomId)` methods
  - `dvconf-daemons/apps/relay/src/signaling.ts` — track unique peer IDs per room in room state
  - `dvconf-daemons/apps/relay/src/index.ts` — start metrics server
  - `dvconf-daemons/apps/relay/package.json` — add express dependency (if not present)
- **Requirements**: ECON-01 (partial — metrics for proof), RELAY-06 (partial — bytes tracking)
- **Depends on**: None
- **Description**: Add an HTTP metrics endpoint to the relay daemon. Create `metrics-server.ts` with a simple http server (use Node.js built-in `http` module, no Express needed) on `METRICS_PORT` (default 4001). Expose `GET /metrics/:roomId` returning JSON: `{ bytesForwarded: string, uniquePeers: number, packetsLost: number, jitter: number, duration: number, activePeers: number }`. Add `getRoomMetrics(roomId)` to MetricsTracker that aggregates all peer entries for a room. Track unique peer IDs in the signaling server's room state — when a peer joins, add to a `Set<string>` per room; expose via MetricsTracker. Also expose `GET /metrics` (no roomId) returning global stats for health checks.

### Task 4: Real validator measurements via STUN probing
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/validator-daemon/src/measurements.ts` — replace simulation with real probing
  - `dvconf-daemons/apps/validator-daemon/src/probe.ts` — new file: STUN/UDP probe implementation
  - `dvconf-daemons/apps/validator-daemon/package.json` — add stun dependency if needed
- **Requirements**: ECON-03 (real measurement data for proofs)
- **Depends on**: Task 3 (relay metrics endpoint must exist)
- **Description**: Replace simulated measurements with real probing. Create `probe.ts` with two measurement strategies: (1) **STUN probing** — send STUN Binding Request to relay's public endpoint, measure RTT from request to response; send N probes (10), compute avg latency and jitter (inter-arrival variance). (2) **Relay metrics fetch** — HTTP GET to relay's metrics endpoint (Task 3) for `bytesForwarded`, `uniquePeers`, `packetsLost`. For packet loss: send N UDP probe packets to relay, count STUN responses received, compute loss in basis points. Update `collectMeasurements()` to call real probes with fallback to simulation if relay is unreachable (log warning). The relay endpoint URL should be read from `RELAY_ENDPOINT_URL` env var (same host, metrics port). Keep `MeasurementResult` interface unchanged.

### Task 5: CP daemon relay+signaling assignment
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/cp-daemon/src/room-assignment.ts` — new file: scoring + assignment logic
  - `dvconf-daemons/apps/cp-daemon/src/index.ts` — wire room assignment into RoomCreated event handler
  - `dvconf-daemons/packages/shared/src/types/events.ts` — add RoomAssigned event type
  - `dvconf-daemons/packages/shared/src/types/chain.ts` — add roomManagerModuleName if missing
- **Requirements**: SIG-03 (CP assigns signaling), RELAY-04 (CP assigns relay)
- **Depends on**: Task 1 (on-chain assignment function must exist)
- **Description**: Create `room-assignment.ts` with: (1) `scoreRelays(client, config)` — devInspect `relay_registry::get_active_relays()`, score by `w1*reputation + w2*(1/rtt) + w3*(1/load) + w4*stake + w5*region_match` using weights from NetworkRegistry. (2) `scoreSignalingNodes(client, config)` — devInspect `signaling_registry::get_active_nodes()`, score by `region_match + 1/(load+1)`. (3) `assignRoom(client, signer, config, roomId, relayMode)` — calls score functions, picks top relay (matching `relayMode`) and top signaling node, submits `room_manager::assign_relay_and_signaling` PTB. In `index.ts`, add a `RoomCreated` event handler: when detected, call `assignRoom()`. Log the assignment. Add `RoomAssigned` to shared event types.

### Task 6: Validator daemon room lifecycle + reward distribution
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/validator-daemon/src/reward-trigger.ts` — new file: room closure detection + distribute_rewards TX
  - `dvconf-daemons/apps/validator-daemon/src/index.ts` — add RoomClosed event poller, wire reward trigger, fix unique_peers from relay metrics, dynamic room discovery
- **Requirements**: ECON-01 (reward distribution), ECON-02 (slashing via distribute_rewards)
- **Depends on**: Task 3 (metrics endpoint for unique_peers), Task 4 (real measurements)
- **Description**: Create `reward-trigger.ts` with: (1) `triggerDistribution(client, signer, config, escrowId, roomId, relayStakeId)` — builds PTB calling `economic_layer::distribute_rewards` with all required shared objects. (2) `waitForProofs(client, escrowId, minProofs, timeoutMs)` — polls escrow object to check proof count, waits until >= minProofs or timeout. In `index.ts`: add a `room_manager` EventPoller for `RoomClosed` events. On room closure, if `escrowMap` has the room, wait for proofs then call `triggerDistribution`. Fix `unique_peers`: before building proof, fetch `GET /metrics/:roomId` from relay to get real `uniquePeers` count (fallback to peer count from measurement if unavailable). For dynamic room discovery: add `RoomCreated` event poller — when a new room is created and has an escrow, the validator should start measuring it. Store active rooms in a `Set<string>` and cycle through them in the measurement loop (not just a single ROOM_ID env var).

### Task 7: Client escrow creation + signaling-first session flow
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useEscrow.ts` — new hook: create_escrow TX
  - `dvconf-client/src/hooks/useRoomAssignment.ts` — new hook: read assigned relay+signaling from chain
  - `dvconf-client/src/pages/RoomPage.tsx` — integrate escrow creation, signaling discovery, assignment-based relay connection
  - `dvconf-client/src/hooks/useSignaling.ts` — update to query signaling node for assigned relay endpoint (or keep direct chain read)
- **Requirements**: ECON-01 (escrow deposit), SIG-03 (signaling in flow), SIG-04 (signaling selection), RELAY-04 (relay from assignment)
- **Depends on**: Task 1 (on-chain assignment), Task 5 (CP assigns so assignment exists when client reads)
- **Description**: Create `useEscrow` hook: calls `economic_layer::create_escrow(net_reg, room_mgr, room_id, payment)` TX. Room creator calls this after room creation — prompt user for escrow amount, execute TX. Create `useRoomAssignment` hook: devInspect `room_manager::get_room_assignment(manager, room_id)` to read `assigned_relay` and `assigned_signaling` IDs. BCS decode the response. Then resolve IDs to endpoints: devInspect relay_registry/signaling_registry to get endpoint URLs for the assigned IDs. Update RoomPage flow: (1) After room creation, show "Deposit Escrow" step. (2) Once escrow deposited, poll for CP assignment (useRoomAssignment). (3) Once assignment available, show "Join Session" button. (4) On join: connect to assigned relay URL (not discovery-scored URL). Remove direct `useRelayDiscovery()` call from RoomPage — replaced by assignment-based relay URL.

### Task 8: Client relay failover with auto-reconnect
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useRelay.ts` — add reconnect logic with exponential backoff
  - `dvconf-client/src/pages/RoomPage.tsx` — add reconnecting UI state
- **Requirements**: Integration hardening (success criterion 1 — resilient session)
- **Depends on**: Task 7 (session flow must be wired first)
- **Description**: In `useRelay.ts`, detect relay WebSocket disconnect (`onclose` event on RelaySocket). When disconnect detected during active session: set `sessionState` to `'reconnecting'` (new state). Attempt reconnect with exponential backoff: 1s, 2s, 4s (3 retries). On each retry: re-read room assignment from chain (relay may have been reassigned), attempt new WS connection + rejoin room. Preserve local media tracks during reconnect (don't stop camera/mic). On successful reconnect: re-produce local tracks, re-consume remote producers, set state back to `'active'`. After 3 failures: set `sessionState` to `'error'`, show "Connection lost" with manual "Reconnect" button. In RoomPage, add UI for `reconnecting` state: "Reconnecting..." spinner with attempt count.

### Task 9: Update shared types for integration
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/packages/shared/src/types/constants.ts` — add any new error codes if Task 1/2 introduces them
  - `dvconf-daemons/packages/shared/src/types/events.ts` — add RoomAssigned event interface
  - `dvconf-daemons/packages/shared/src/types/chain.ts` — ensure all module names are present
- **Requirements**: Cross-domain type sync
- **Depends on**: Task 1 (new on-chain types/events defined), Task 2 (new function signatures)
- **Description**: Sync shared TypeScript types with on-chain changes from Tasks 1-2. Add `RoomAssigned` event type matching the Move event struct. If `registration::unregister()` signature changed (new SignalingRegistry param), update any daemon code that calls unregister. Verify all module names in `chain.ts` include `room_manager` for event polling. This is a small sync task — may be absorbed into Tasks 5/6 if trivial, but kept separate for clarity.

### Task 10: Load testing script
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/scripts/load-test.ts` — new file: E2E load test
  - `dvconf-daemons/package.json` — add script entry for load test
- **Requirements**: Success criterion 3 (load testing validates concurrent sessions)
- **Depends on**: Task 3, Task 4, Task 5, Task 6, Task 7 (full E2E flow must work)
- **Description**: Create a Node.js script that validates the full E2E flow with concurrent sessions. The script: (1) Creates a room on-chain via PTB. (2) Deposits escrow via `create_escrow`. (3) Waits for CP assignment (polls chain). (4) Spawns N simulated clients (configurable, default 3) that connect to the assigned relay via mediasoup-client WebSocket protocol. (5) Each client sends a `join` message and creates send/recv transports. (6) Clients produce fake media tracks (use `FakeMediaStreamTrack` or just send the signaling messages without actual media). (7) Runs for a configurable duration (default 30s). (8) Closes room on-chain. (9) Waits for validator proof submission + reward distribution. (10) Reports: connection times, bytes forwarded (from relay metrics), proof count, reward distribution result. Run via `pnpm run load-test` from daemons root. Requires all daemons running locally. Add a `--sessions N` flag to test N concurrent rooms (default 1).

## Execution Order

```
Wave 1 (parallel — no dependencies):
  Task 1: OnChain — room assignment extension
  Task 2: OnChain — tech debt closure
  Task 3: OffChain — relay metrics endpoint

Wave 2 (after Wave 1):
  Task 4: OffChain — real validator measurements (needs Task 3)
  Task 5: OffChain — CP room assignment (needs Task 1)
  Task 9: OffChain — shared types sync (needs Task 1, Task 2)

Wave 3 (after Wave 2):
  Task 6: OffChain — validator room lifecycle + rewards (needs Task 3, Task 4)
  Task 7: FE — client escrow + signaling flow (needs Task 1, Task 5)

Wave 4 (after Wave 3):
  Task 8: FE — relay failover (needs Task 7)

Wave 5 (after all):
  Task 10: OffChain — load testing script (needs everything)
```

**Parallelization notes:**
- Wave 1: Tasks 1+2 are both OnChain but touch different files (room_manager vs registration/signaling_registry/economic_layer_tests) — can run sequentially within OnChain domain, parallel with Task 3 (OffChain).
- Wave 2: Tasks 4 and 5 are both OffChain but touch different daemon apps — can run in parallel.
- Wave 3: Tasks 6 (OffChain) and 7 (FE) are different domains — can run in parallel.

## Risks & Open Questions

1. **registration::unregister() signature change (TD-P11-04)**: Adding `&mut SignalingRegistry` param to `unregister()` is a breaking change. All callers (daemon auto-register flows, tests) must be updated. If too disruptive, alternative: add a separate `cleanup_signaling()` function that's called independently.

2. **STUN probing reliability**: STUN probes to the relay may fail if the relay's mediasoup Workers only accept DTLS/ICE connections (not raw STUN). Fallback: use the relay's metrics HTTP endpoint as primary measurement source, with STUN as supplementary RTT measurement. The relay's public IP should respond to STUN if `enableUdp: true` on mediasoup transports.

3. **Escrow UX flow**: Creating escrow is a separate TX after room creation. Users need DVCONF tokens to deposit. For thesis demo, ensure the test accounts have sufficient token balance. Consider: should escrow amount be fixed (from constants) or user-specified?

4. **CP assignment timing**: Between room creation and CP assignment, there's a window where the room has no relay/signaling. Client must poll and wait for assignment. If no CP daemon is running, the room stays unassigned forever. For thesis demo, ensure CP daemon is always running.

5. **distribute_rewards relay_stake parameter**: The on-chain `distribute_rewards` requires a `&mut StakePosition` object. The validator daemon needs to know the relay's StakePosition object ID. This may require an additional on-chain accessor or the relay must publish its stake ID during registration.
