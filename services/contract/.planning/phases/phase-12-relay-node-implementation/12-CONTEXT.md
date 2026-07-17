# Phase 12: Relay Node Implementation - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

## Phase Boundary

Phase 12 covers building the mediasoup relay daemon (single daemon, SFU+MCU mode), replacing the client's P2P WebRTC path with mediasoup-client relay connections, and adding relay endpoint discovery from RelayRegistry. RELAY-06 (rewards based on bytes forwarded) is **deferred to Phase 13** (Economic Layer) since it depends on SessionProof infrastructure. The relay daemon will track bytes/quality metrics locally but won't submit or distribute rewards.

**In scope:** RELAY-01, RELAY-02, RELAY-03, RELAY-04, RELAY-05
**Out of scope:** RELAY-06 (rewards) — deferred to Phase 13

## Implementation Decisions

### Daemon Architecture
- Single relay daemon (`apps/relay/`) with RELAY_MODE env var (sfu or mcu), NOT two separate daemons
- Follows signaling/cp-daemon patterns: auto-register with stake, heartbeat, load reporting
- mediasoup Workers handle ICE/DTLS directly — relay IS the TURN server (no separate coturn)
- Mode set at startup via env var, matches on-chain relay_mode field

### Client Architecture
- **Fully replace P2P** WebRTC path (useWebRTC.ts) with mediasoup-client relay connections
- No P2P fallback — all media goes through relay nodes
- SFU view: one `<video>` per remote peer (mediasoup Consumer per producer)
- MCU view: one composite `<video>` (single Consumer from mixed output)
- Relay tells client its mode during mediasoup signaling handshake (not on-chain query)
- Client adapts renderer based on mode field in handshake response

### Relay Discovery (RELAY-04)
- New hook: `useRelayDiscovery` — query RelayRegistry via devInspect (same pattern as useSignalingDiscovery)
- Join room resolves relay endpoint from RelayRegistry on chain
- Fallback to VITE_RELAY_URL env var if no relays registered

### On-Chain
- RelayRegistry already exists with register, heartbeat, load, mode — minimal changes expected
- May need `get_active_relays()` vector-returning accessor (same pattern as signaling_registry::get_active_nodes)
- Relay auto-register uses existing relay role (ROLE_RELAY = 2, stake 1.5 DVCONF)

### mediasoup Configuration
- rtcMinPort/rtcMaxPort set on Workers
- mediaCodecs declared on Routers (VP8/opus at minimum)
- Workers, Routers, Transports closed on shutdown
- SFU: Router per room, Producer per participant, Consumer per remote peer
- MCU: Router per room with PlainTransport for mixing (or mediasoup pipe)

### Claude's Discretion
- mediasoup codec configurations and Worker count
- Transport options (enableUdp, enableTcp, preferUdp)
- Internal module structure of relay daemon
- Signaling protocol between client and relay (WebSocket message format)
- Test structure and coverage level

## Specific Ideas

- Relay daemon signaling: WebSocket server for mediasoup signaling (create transport, produce, consume)
- Client connects to relay WebSocket, exchanges RTP capabilities, creates send/recv transports
- SFU mode: each client produces to relay, relay creates Consumer for each other client
- MCU mode: relay mixes via AudioLevelObserver or pipe to ffmpeg/GStreamer, sends single composite
- Bytes forwarded tracked per-session in relay daemon memory (for Phase 13 reward claims)
- Heartbeat reports active room count + total bandwidth as load metric

## Existing Code Insights

### Reusable Assets
- `sources/registry/relay_registry.move` — full relay registration + mode tracking
- `dvconf-daemons/apps/signaling/` — chain-aware daemon pattern (auto-register, heartbeat)
- `dvconf-daemons/apps/cp-daemon/` — auto-register two-step pattern
- `dvconf-client/src/hooks/useSignalingDiscovery.ts` — devInspect discovery pattern
- `dvconf-client/src/hooks/useWebRTC.ts` — existing WebRTC logic (will be replaced)
- `@dvconf/shared` — SuiClient, executeWithRetry, MinerRole, error codes

### Established Patterns
- Auto-register: two-step (miner registration then registry registration)
- Heartbeat: 30s interval, combined PTB with load update
- Client discovery: devInspect + BCS decode + scoring + fallback
- Error codes in 10-code namespaces (relay: 520-529, already assigned)

### Integration Points
- `relay_registry.move` — may need get_active_relays() accessor
- `@dvconf/shared/types/constants.ts` — MinerRole.Relay already exists (value 2)
- `@dvconf/shared/types/events.ts` — relay events already defined
- `dvconf-client/src/hooks/useSignaling.ts` — signaling connects to signaling node; relay is separate WebSocket
- `dvconf-client/src/pages/RoomPage.tsx` — replace useWebRTC with useRelay hook

## Deferred Ideas

- **RELAY-06 (rewards):** Relay earns rewards based on bytes forwarded — deferred to Phase 13 (Economic Layer)
- **Relay failover mid-session:** Reconnect flow — deferred to Phase 14 (Integration)
- **MCU GStreamer pipeline:** For thesis, use mediasoup's built-in pipe or AudioLevelObserver; full GStreamer deferred
- **Multi-relay per room:** For thesis, 1 relay per room; redundancy deferred

## Revision Log

- **2026-03-12 (initial):** Context gathered via /dvconf:discuss-phase. RELAY-06 deferred to Phase 13. Single daemon with mode flag. P2P fully replaced. Relay IS TURN. Mode communicated via handshake.
