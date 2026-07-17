# Phase 14: Integration & Hardening - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

## Phase Boundary

Phase 14 wires together all v3.0 components into a working end-to-end session lifecycle: client creates room + deposits escrow, CP daemon assigns relay + signaling nodes, client discovers assignments from chain and connects through the signaling node to the assigned relay, validators probe the relay with real network measurements, submit dual-key signed SessionProofs, and a daemon triggers reward distribution after room closure. Additionally, this phase adds auto-reconnect with retry for relay failover, fixes all outstanding tech debt items targeted at Phase 14, and includes a simple load testing script for concurrent sessions.

**In scope:** All 7 integration gaps + 3 tech debt items + load test script
**Out of scope:** Full CP multi-node voting/consensus (single CP assigns for thesis), ZK validator identity, CDN/recording

## Implementation Decisions

### CP-Driven Assignment
- CP daemon detects `RoomCreated` event, scores relays + signaling nodes by region/load/reputation, writes assignment on-chain
- New on-chain function needed: `room_manager::assign_relay_and_signaling(room_id, relay_miner_id, signaling_miner_id)` (package-gated, called via CP daemon TX)
- Room struct gets `assigned_relay: Option<ID>` and `assigned_signaling: Option<ID>` fields
- Client reads assignment from chain via devInspect, then connects to assigned nodes
- Single CP makes the assignment (no multi-CP voting for thesis)

### Signaling Node Role in Session
- Signaling node acts as session coordinator: client connects to signaling first, signaling tells client which relay to connect to
- Signaling node may proxy the initial mediasoup handshake (join + RTP capabilities) or simply return the relay endpoint URL
- Decision: **Discovery only** — signaling node returns the assigned relay endpoint. Client connects to relay directly for mediasoup signaling. This keeps the relay daemon's WebSocket signaling protocol unchanged.

### Real Validator Measurements
- Validator daemon sends STUN binding requests through the relay to measure actual RTT
- For packet loss: validator sends N UDP probe packets, counts responses
- For jitter: compute inter-packet arrival variance from probe responses
- For bytes_transferred: query relay daemon's metrics endpoint (HTTP GET /metrics) for room-level bytes forwarded
- Probe interval: every 60s (existing measurement loop)
- Relay daemon needs a `/metrics` HTTP endpoint exposing per-room bytes/peers stats

### Reward Distribution Trigger
- Validator daemon detects room closure (EventPoller on `RoomClosed` events from room_manager)
- After room closes, validator waits for all proofs to land (polls escrow proof count), then calls `economic_layer::distribute_rewards`
- Alternative: CP daemon triggers distribution (already watches room events). Decision: **Validator daemon triggers** since it already has the escrow mapping.

### Relay Failover
- Client detects relay WebSocket disconnect in useRelay hook
- Auto-reconnect: 3 retries with exponential backoff (1s, 2s, 4s)
- On retry, re-discover relay from chain (assignment may have changed if CP reassigned)
- After 3 failures, show error state with manual "Reconnect" button
- During reconnect, local media tracks are preserved (not stopped)

### unique_peers Fix
- Relay daemon tracks unique peer IDs per room in its room state
- Expose via `/metrics` endpoint or WebSocket query
- Validator daemon reads this when building SessionProof

### Signaling Discovery in RoomPage
- RoomPage uses `useSignalingDiscovery()` to find the assigned signaling node
- Signaling node returns the assigned relay endpoint for the room
- Then client connects to relay via `useRelay()`
- This wires signaling into the actual session flow

### Tech Debt Closure
- **TD-P11-04**: Add cross-registry cleanup — when a miner unregisters via `registration::unregister()`, also remove from SignalingRegistry if present
- **TD-P13-02**: Add test for `E_ROOM_NOT_FOUND` (652) in `create_escrow`
- **TD-P13-03**: Add test for `E_PAUSED` (650) on economic layer entry functions

### Load Testing
- Node.js script in `dvconf-daemons/scripts/load-test.ts`
- Spawns N simulated clients (3-5) that connect to relay via mediasoup-client
- Each client produces a fake audio/video track
- Script validates: all clients connect, media flows, proofs are submitted, rewards distributed
- Reports: connection time, session duration, bytes forwarded per client

### Claude's Discretion
- STUN probe implementation details (packet format, timeout thresholds)
- Relay `/metrics` endpoint format (JSON response schema)
- Exact CP scoring formula for relay+signaling assignment
- Load test script structure and assertion details
- Error code namespace for any new on-chain errors (if needed)

## Specific Ideas

- Room struct extension: `assigned_relay: Option<ID>`, `assigned_signaling: Option<ID>` + accessor functions
- CP daemon: new `assignRoom()` function that queries RelayRegistry + SignalingRegistry, scores, calls `room_manager::assign_relay_and_signaling` PTB
- Relay daemon: add Express HTTP server on separate port (e.g., 4001) with `GET /metrics/:roomId` returning `{ bytesForwarded, uniquePeers, packetsLost, duration }`
- Validator daemon: replace `collectMeasurements()` random values with STUN probe + relay metrics fetch
- Validator daemon: add `RoomClosed` event poller, call `distribute_rewards` after sufficient proofs
- Client RoomPage: add `create_escrow` TX after room creation (or integrate into room creation flow)
- Client RoomPage: read `assigned_relay` + `assigned_signaling` from chain, connect through signaling
- Client useRelay: add reconnect logic with exponential backoff and re-discovery

## Existing Code Insights

### Reusable Assets
- `control_plane_registry.move` — `assign_to_room()` already exists for CP assignment tracking
- `relay_registry::get_active_relays()` — returns scored relay list for CP scoring
- `signaling_registry::get_active_nodes()` — returns scored signaling list
- `useSignalingDiscovery.ts` — already works, just needs to be wired into RoomPage
- `useRelayDiscovery.ts` — scoring logic reusable for CP daemon
- `cp-daemon/` — EventPoller + scoring logic already implemented
- `relay/metrics.ts` — MetricsTracker already tracks bytesForwarded per room
- `validator-daemon/session-proof.ts` — BCS serialization + dual-key signing complete

### Established Patterns
- Registry modules: `public(package)` for internal mutations, entry functions for external
- Daemon auto-register: two-step (miner registration then registry registration)
- Heartbeat: 30s interval, combined PTB with load update
- Client discovery: devInspect + BCS decode + scoring + fallback
- Error codes in 10-code namespaces

### Integration Points
- `room_manager.move` — needs relay/signaling assignment fields + accessor
- `control_plane_registry.move` — already has `assign_to_room()`, may need relay assignment variant
- `economic_layer.move` — `distribute_rewards` needs to be callable by validator daemon
- `relay/index.ts` — needs HTTP metrics endpoint
- `relay/signaling.ts` — needs unique peer tracking exposure
- `validator-daemon/measurements.ts` — replace simulation with real probes
- `validator-daemon/index.ts` — add RoomClosed event handler + distribute_rewards TX
- `cp-daemon/index.ts` — add relay+signaling assignment logic on RoomCreated
- `client/src/pages/RoomPage.tsx` — add escrow creation + signaling-first flow
- `client/src/hooks/useRelay.ts` — add reconnect with backoff

## Deferred Ideas

- Multi-CP voting/consensus on relay assignment — thesis uses single CP assignment
- ZK proof for validator identity — post-thesis extension
- CDN integration for MCU output distribution — post-thesis
- Hybrid SFU+MCU mode per room — resolved NO, one mode per room
- Governance mechanism for BASE_RATE — fixed constant for thesis
- Cross-registry cleanup for relay/validator/CP on unregister — only signaling cleanup in scope (TD-P11-04)

## Revision Log

- **2026-03-12 (initial):** Context gathered via /dvconf:discuss-phase 14
  - Scope: all 7 integration gaps + 3 tech debt items + load test
  - CP-driven relay+signaling assignment (single CP, no voting)
  - Real validator probing via STUN + relay metrics endpoint
  - Signaling as discovery coordinator (not mediasoup proxy)
  - Auto-reconnect with 3 retries + exponential backoff
  - Validator daemon triggers reward distribution on room close
