# Phase 12 Plan: Relay Node Implementation
Date: 2026-03-12

## Goal
Relay nodes forward media streams via mediasoup (SFU or MCU mode) and clients connect through mediasoup-client

## Success Criteria
1. Client connects to SFU relay via mediasoup-client
2. Client connects to MCU relay via mediasoup-client
3. Adaptive session view switches based on relay_mode (communicated via handshake)
4. Join room resolves relay endpoint from RelayRegistry
5. Relay node forwards media streams via mediasoup
6. Relay node earns rewards based on bytes forwarded and quality metrics

**Note:** SC-6 (RELAY-06, rewards) is deferred to Phase 13 (Economic Layer). The relay daemon will track bytes/quality locally but won't submit or distribute rewards.

## Requirements Covered
- **RELAY-01**: Client connects via mediasoup-client to SFU relay node
- **RELAY-02**: Client connects via mediasoup-client to MCU relay node
- **RELAY-03**: Adaptive SFU/MCU session view branched by relay_mode
- **RELAY-04**: Join room resolves relay endpoint from RelayRegistry on chain
- **RELAY-05**: Relay node forwards media streams via mediasoup (SFU or MCU mode)
- **RELAY-06**: _(deferred to Phase 13)_ — relay tracks metrics locally, no reward submission

## Tasks

### Task 1: Add get_active_relays() accessor to RelayRegistry (OnChain)
- **Agent**: OnChain
- **Files**:
  - `sources/registry/relay_registry.move` (modify — add endpoint_url/active_set fields + accessor)
  - `tests/registry/relay_registry_tests.move` (modify — add test for get_active_relays)
- **Requirements**: RELAY-04 (partial — on-chain discovery support)
- **Depends on**: None
- **Description**:
  RelayRegistry currently stores relay nodes in a Table but has no vector-returning accessor for client devInspect discovery. Add:
  1. `endpoint_url: vector<u8>` field to `RelayNodeInfo` (same pattern as SignalingNodeInfo)
  2. An `active_set: VecSet<ID>` to `RelayRegistry` (same pattern as SignalingRegistry) to track active relay IDs
  3. `get_active_relays(registry: &RelayRegistry): vector<RelayNodeInfo>` — iterates active_set, returns info entries (same pattern as `signaling_registry::get_active_nodes`)
  4. Update `register_relay()` to accept `endpoint_url` parameter and insert into active_set
  5. Add test verifying get_active_relays returns registered nodes

### Task 2: Update shared types for relay daemon (OffChain)
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/packages/shared/src/types/events.ts` (modify — add relay daemon events)
  - `dvconf-daemons/packages/shared/src/types/constants.ts` (no change needed — RelayMode already exists)
- **Requirements**: RELAY-05 (partial — type infrastructure)
- **Depends on**: None
- **Description**:
  Add relay-specific event types to `@dvconf/shared` for the relay daemon to use:
  - `RelayRegistered`, `RelayLoadUpdated` event interfaces (matching on-chain events)
  - Any mediasoup-related type exports the relay daemon needs

### Task 3: Create relay daemon with mediasoup (OffChain)
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/relay/package.json` (create)
  - `dvconf-daemons/apps/relay/tsconfig.json` (create)
  - `dvconf-daemons/apps/relay/src/index.ts` (create — main entry, chain bootstrap + mediasoup setup)
  - `dvconf-daemons/apps/relay/src/auto-register.ts` (create — two-step relay registration)
  - `dvconf-daemons/apps/relay/src/heartbeat.ts` (create — heartbeat + load PTB)
  - `dvconf-daemons/apps/relay/src/mediasoup-manager.ts` (create — Worker/Router/Transport lifecycle)
  - `dvconf-daemons/apps/relay/src/signaling.ts` (create — WebSocket server for mediasoup signaling)
  - `dvconf-daemons/apps/relay/src/room-handler.ts` (create — per-room SFU/MCU logic)
  - `dvconf-daemons/apps/relay/src/metrics.ts` (create — bytes forwarded + quality tracking)
  - `dvconf-daemons/apps/relay/.env.example` (create)
- **Requirements**: RELAY-05
- **Depends on**: Task 1 (needs updated register_relay signature with endpoint_url), Task 2
- **Description**:
  Single relay daemon (`apps/relay/`) with `RELAY_MODE` env var (sfu or mcu). Architecture:

  **Startup flow** (same pattern as signaling daemon):
  1. Load env config (RPC_URL, PACKAGE_ID, MINER_CAP_ID, RELAY_MODE, WS_PORT, etc.)
  2. Auto-register: two-step (miner registration → relay_registry::register_relay with endpoint_url)
  3. Start mediasoup Workers (1 per CPU core or configurable)
  4. Start WebSocket signaling server for mediasoup client connections
  5. Start heartbeat loop (30s, combined heartbeat + load update PTB)

  **mediasoup architecture**:
  - Workers created at startup, Routers created per room
  - SFU mode: Producer per participant, Consumer per remote peer in room
  - MCU mode: Pipe producers through AudioLevelObserver or PlainTransport for mixing
  - WebSocket protocol: `createTransport`, `connectTransport`, `produce`, `consume`, `join`, `leave`
  - Transports use enableUdp + enableTcp with preferUdp
  - Codecs: VP8 video, opus audio

  **Heartbeat/load**: reports active room count + total bandwidth as load metric

  **Metrics**: track bytes forwarded per session, quality (packet loss, jitter) locally in memory for Phase 13

### Task 4: Client relay discovery hook (FE)
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useRelayDiscovery.ts` (create)
  - `dvconf-client/src/config.ts` (modify — add RELAY_URL fallback env var)
  - `dvconf-client/.env.example` (modify — add VITE_RELAY_URL)
- **Requirements**: RELAY-04
- **Depends on**: Task 1 (needs get_active_relays accessor on chain)
- **Description**:
  New hook `useRelayDiscovery` — same pattern as `useSignalingDiscovery`:
  1. devInspect call to `relay_registry::get_active_relays(registry)`
  2. BCS-decode `RelayNodeInfo` entries (operator, miner_id, stake_amount, mode, reputation, registered_at, region, endpoint_url)
  3. Score by region match + load (reuse scoring logic from signaling discovery)
  4. Return best relay endpoint URL, mode (SFU/MCU), and all discovered nodes
  5. Fallback to `CONFIG.RELAY_URL` env var if no relays registered
  6. Poll at `CONFIG.DISCOVERY_POLL_INTERVAL` (60s)

### Task 5: Replace P2P WebRTC with mediasoup-client relay connections (FE)
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useRelay.ts` (create — mediasoup-client hook replacing useWebRTC)
  - `dvconf-client/src/hooks/useWebRTC.ts` (delete or deprecate)
  - `dvconf-client/src/pages/RoomPage.tsx` (modify — replace useWebRTC with useRelay, adapt to SFU/MCU views)
  - `dvconf-client/src/components/VideoGrid.tsx` (modify — support both SFU multi-stream and MCU single-stream views)
  - `dvconf-client/package.json` (modify — add mediasoup-client dependency)
- **Requirements**: RELAY-01, RELAY-02, RELAY-03
- **Depends on**: Task 3 (relay daemon must exist to connect to), Task 4 (relay discovery provides endpoint)
- **Description**:
  Fully replace the P2P WebRTC path with mediasoup-client relay connections:

  **useRelay hook**:
  1. Connect to relay WebSocket (URL from useRelayDiscovery)
  2. Load mediasoup Device, get RTP capabilities from relay
  3. Create send Transport (produce local camera/mic)
  4. Create recv Transport (consume remote streams)
  5. SFU mode: one Consumer per remote peer → Map<peerId, MediaStream>
  6. MCU mode: single Consumer for composite stream → one MediaStream
  7. Expose: localStream, remoteStreams (Map for SFU, single for MCU), mode, cleanup
  8. Track media errors same as current useWebRTC

  **RoomPage changes**:
  - Replace `useWebRTC` + `useSignaling` with `useRelay` + `useRelayDiscovery`
  - Remove P2P signaling logic (createOffer/handleOffer/handleAnswer/handleIceCandidate)
  - Keep: useRoomStatus, useChain, useNetworkPause, useConnectionStats, useParticipantNames
  - Session flow: startLocalStream → connect to relay → produce → consume

  **VideoGrid changes**:
  - SFU mode: render one `<video>` per remote stream (existing tiled layout)
  - MCU mode: render single `<video>` for composite stream (full-width)
  - Switch based on `mode` from useRelay

### Task 6: Update relay heartbeat to use RelayRegistry (OffChain)
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/relay/src/heartbeat.ts` (modify if needed after Task 3)
- **Requirements**: RELAY-05 (partial — liveness)
- **Depends on**: Task 1, Task 3
- **Description**:
  Ensure the relay daemon heartbeat sends a combined PTB with:
  1. `relay_registry::update_load(net_reg, registry, cap, load)` — current room count + bandwidth

  Note: RelayRegistry doesn't have a heartbeat function like SignalingRegistry. If the on-chain module needs one, Task 1 should add it. Otherwise, `update_load` serves as the liveness signal. Evaluate during Task 1 whether a dedicated heartbeat function is needed.

## Execution Order

```
Task 1 (OnChain) ──┐
                    ├──► Task 3 (OffChain - relay daemon) ──► Task 6 (OffChain - heartbeat refinement)
Task 2 (OffChain) ─┘                                    │
                                                         │
Task 1 (OnChain) ──► Task 4 (FE - discovery) ────────────┤
                                                         │
                                                         └──► Task 5 (FE - mediasoup-client)
```

**Parallel opportunities:**
- Task 1 (OnChain) || Task 2 (OffChain) — different domains, no shared files
- Task 4 (FE) can start as soon as Task 1 is done
- Task 3 (OffChain) can start as soon as Tasks 1 + 2 are done
- Task 5 (FE) depends on Tasks 3 + 4 (needs relay daemon running + discovery hook)
- Task 6 is a refinement pass after Task 3

**Wave execution:**
1. **Wave 1**: Task 1 (OnChain) + Task 2 (OffChain) — parallel
2. **Wave 2**: Task 3 (OffChain) + Task 4 (FE) — parallel
3. **Wave 3**: Task 5 (FE) + Task 6 (OffChain) — parallel

## Risks & Open Questions

1. **mediasoup native dependency**: mediasoup requires native C++ compilation (node-gyp). The relay daemon needs a build environment with Python + C++ toolchain. This could be a friction point on Windows.

2. **MCU mixing complexity**: True MCU mixing (compositing video into a single output) is non-trivial with mediasoup alone. Options:
   - Use mediasoup's pipe + external ffmpeg/GStreamer for real mixing (complex)
   - Simplified MCU: relay all streams but client only renders one (simulated MCU)
   - Per CONTEXT.md: "For thesis, use mediasoup's built-in pipe or AudioLevelObserver; full GStreamer deferred"

3. **RelayRegistry schema change**: Adding `endpoint_url` and `active_set` to RelayRegistry requires a package upgrade. Existing deployed relay registries will need migration or redeployment.

4. **mediasoup-client bundle size**: mediasoup-client adds ~150KB to client bundle. Acceptable for thesis but worth noting.

5. **RELAY-06 boundary**: Relay daemon tracks bytes/quality locally but Phase 13 owns the reward distribution. Clear handoff needed.
