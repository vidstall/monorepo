# Phase 9: P2P WebRTC Sessions - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 9 wires together the existing WebRTC and signaling hooks into a working multi-peer video call experience. The hooks (`useWebRTC`, `useSignaling`) and basic `VideoGrid` component already exist from Phase 7 stabilization — this phase integrates them in `RoomPage`, upgrades the video grid for N-peer tiled layout (up to 6 peers for P2P mesh), adds media controls (mute/camera toggle), and implements WebRTC stats display. **FE-only phase** — no on-chain or daemon changes needed.

NOT in scope: SFU/MCU relay integration (v3.0), screen sharing, chat, 100+ peer support (requires relay nodes), TURN server configuration.

</domain>

<decisions>
## Implementation Decisions

### Hook Strategy
- **Existing hooks**: Modify `useWebRTC` and `useSignaling` in-place — only change what's needed for multi-peer streams and stats
- **No rewrite**: Hooks are already correct for core P2P logic; Phase 9 extends, not replaces

### Video Grid
- **Peer count**: Design for 4-6 peers (realistic P2P mesh limit)
- **Layout**: Responsive CSS grid that auto-sizes tiles based on peer count
- **100-peer scaling**: Deferred to v3.0 SFU/MCU relay phase

### Media Controls
- **Include in Phase 9**: Mute mic and disable camera toggles are in scope
- **Location**: Control bar below/over the video grid in RoomPage

### Stats Display
- **Claude's discretion**: Pick whatever fits the UI best — likely a subtle overlay or expandable badge per peer tile

### Multi-Stream Support
- **Current gap**: `useWebRTC` stores single `remoteStream` but `peerConnections` is a Map — must change to `remoteStreams: Map<string, MediaStream>`
- **VideoGrid upgrade**: Accept array of remote streams, render tiled grid

### Claude's Discretion
- Stats UI placement and format
- CSS grid breakpoints and tile sizing
- Control bar styling
- Error message wording for media permission denials
- Whether to show peer IDs or just "Peer 1", "Peer 2" labels

</decisions>

<specifics>
## Specific Ideas

- `useWebRTC` needs `remoteStreams: Map<peerId, MediaStream>` instead of single `remoteStream`
- RoomPage orchestration: on mount → `startLocalStream()` → `join(roomId)` → on `peer-joined` → `createOffer()` → exchange SDP/ICE
- On `peer-left` → `cleanupPeer(peerId)` → remove from remoteStreams map
- On leave/unmount → `cleanup()` (stops all tracks, closes all PCs) + signaling disconnect
- Stats via `RTCPeerConnection.getStats()` — poll every 1-2 seconds for active connections
- Extract `candidatePairStats` for RTT, `inboundRtpStats` for packet loss and jitter
- VideoGrid: CSS grid with `grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))`
- Media controls: `localStream.getAudioTracks()[0].enabled = false` for mute, same for video

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/hooks/useWebRTC.ts` — P2P logic: createOffer, handleOffer, handleAnswer, handleIceCandidate, ICE candidate queue, cleanup
- `src/hooks/useSignaling.ts` — WebSocket join/offer/answer/ICE send, peer-joined/left callbacks
- `src/components/VideoGrid.tsx` — 2-video layout (will be upgraded to N-peer)
- `src/pages/RoomPage.tsx` — room view with status polling, placeholder at line ~149
- `src/config.ts` — `SIGNALING_URL` already configured (ws://localhost:8080)

### Established Patterns
- Hooks return state + functions (e.g., `useWebRTC` returns `{ localStream, remoteStream, startLocalStream, ... }`)
- Error states as `string | null` with user-facing messages
- `useRef` for mutable WebSocket/PeerConnection refs (no re-render on ref change)
- Room status polling via `useRoomStatus` (5s interval, devInspect + BCS)
- Constants in `src/constants.ts` (ROOM_STATUS, RELAY_MODE enums)

### Integration Points
- RoomPage line ~149: replace `<div>Video session — coming in Phase 9</div>` with VideoGrid + controls
- Signaling server protocol: join, offer, answer, ice-candidate, leave, welcome, peer-joined, peer-left
- Signaling server assigns `peerId` via `welcome` message — client receives before any room operations
- `useRoomStatus` provides `status`, `creator`, `relayMode` — Phase 9 uses `status` to gate session start
- Room must be ACTIVE (status=2) or at least READY (status=1) before starting WebRTC session

### Signaling Server Protocol (from dvconf-daemons)
Client → Server:
- `{ type: 'join', roomId }` — join room
- `{ type: 'offer', sdp, targetPeerId }` — send SDP offer
- `{ type: 'answer', sdp, targetPeerId }` — send SDP answer
- `{ type: 'ice-candidate', candidate, targetPeerId }` — send ICE candidate
- `{ type: 'leave' }` — leave room

Server → Client:
- `{ type: 'welcome', peerId }` — assigned peer ID
- `{ type: 'peer-joined', peerId, roomId }` — new peer notification
- `{ type: 'peer-left', peerId, roomId }` — peer left notification
- `{ type: 'offer', sdp, fromPeerId }` — forwarded offer
- `{ type: 'answer', sdp, fromPeerId }` — forwarded answer
- `{ type: 'ice-candidate', candidate, fromPeerId }` — forwarded ICE

</code_context>

<deferred>
## Deferred Ideas

- **100+ peer support**: Requires SFU/MCU relay nodes — deferred to v3.0
- **TURN server fallback**: Only STUN configured (Google); TURN needed for symmetric NAT — deferred (localhost demos work without)
- **Screen sharing**: Out of scope per REQUIREMENTS.md
- **Peer display names**: Resolving wallet address → UserRegistry display name deferred to Phase 10 (POLISH-03)
- **Adaptive SFU/MCU view**: `relayMode` from chain is read but not used — deferred to v3.0 relay phase

</deferred>

<revision_log>
## Revision Log

- **2026-03-10 (initial):** Context gathered via /dvconf:discuss-phase

</revision_log>
