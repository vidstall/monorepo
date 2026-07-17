# Phase 9 Plan: P2P WebRTC Sessions
Date: 2026-03-10

## Goal
Multiple peers can join a room and see/hear each other through P2P WebRTC connections via the signaling server.

## Success Criteria
1. User is prompted for camera/mic permissions with clear error messages when denied or unavailable
2. Two or more peers in the same room can see and hear each other in a tiled video layout
3. Leaving a room stops all local media tracks and closes all peer connections with no resource leaks
4. Real-time connection stats (RTT, packet loss, jitter) are visible during an active session

## Requirements Covered
RTC-01, RTC-02, RTC-03, RTC-04, RTC-05, RTC-06

## Tasks

### Task 1: Upgrade useWebRTC for multi-peer streams
- **Agent**: FE
- **Files**: `src/hooks/useWebRTC.ts` (modify)
- **Requirements**: RTC-03, RTC-05
- **Depends on**: None
- **Description**:
  Replace single `remoteStream` state with `remoteStreams: Map<string, MediaStream>` to support multiple simultaneous peer connections.

  Changes:
  - Replace `useState<MediaStream | null>(null)` for remoteStream → `useState<Map<string, MediaStream>>(new Map())`
  - `createPC`: instead of `setRemoteStream(remote)`, update the map: `setRemoteStreams(prev => new Map(prev).set(targetPeerId, remote))`
  - `ontrack` handler: update the map entry for the specific peer, not overwrite global
  - `cleanupPeer`: remove the peerId entry from remoteStreams map
  - `cleanup`: clear the entire map, stop local tracks
  - Expose `peerConnections` ref (read-only) for stats hook to access RTCPeerConnections
  - Return shape: `{ localStream, remoteStreams, mediaError, clearMediaError, startLocalStream, createOffer, handleOffer, handleAnswer, handleIceCandidate, cleanup, cleanupPeer, peerConnectionsRef }`

### Task 2: Tiled VideoGrid + MediaControls
- **Agent**: FE
- **Files**: `src/components/VideoGrid.tsx` (rewrite), `src/components/MediaControls.tsx` (new)
- **Requirements**: RTC-01, RTC-04
- **Depends on**: Task 1
- **Description**:
  Rewrite VideoGrid to render N-peer tiled layout and create a MediaControls bar.

  **VideoGrid changes:**
  - Props: `{ localStream: MediaStream | null, remoteStreams: Map<string, MediaStream>, mediaError: string | null }`
  - Render local video + one video tile per remote peer from the Map
  - CSS grid: `grid-template-columns: repeat(auto-fit, minmax(280px, 1fr))` — auto-sizes for 1-6 peers
  - Each tile: `<video>` element with `srcObject` bound via useEffect/useRef (one ref per peer — use callback refs or a sub-component)
  - Local tile labeled "You (muted)", remote tiles labeled "Peer 1", "Peer 2", etc.
  - Show `mediaError` as a prominent message when camera/mic is denied (RTC-01)
  - Extract a `<VideoTile>` sub-component that manages its own video ref

  **MediaControls (new component):**
  - Props: `{ localStream: MediaStream | null, onLeave: () => void }`
  - Mute/unmute button: toggles `localStream.getAudioTracks()[0].enabled`
  - Camera on/off button: toggles `localStream.getVideoTracks()[0].enabled`
  - Leave button: calls `onLeave` callback
  - Visual state: buttons show current muted/camera-off state

### Task 3: RoomPage session orchestration
- **Agent**: FE
- **Files**: `src/pages/RoomPage.tsx` (modify)
- **Requirements**: RTC-01, RTC-02, RTC-03, RTC-04, RTC-05
- **Depends on**: Task 1, Task 2
- **Description**:
  Wire useWebRTC + useSignaling + useRoomStatus together in RoomPage to create the full session lifecycle.

  **Session lifecycle:**
  1. On mount: call `startLocalStream()` to request camera/mic (RTC-01)
  2. If stream obtained: call `signaling.connect()` then `signaling.joinRoom(roomId)`
  3. On `peer-joined`: call `createOffer(localStream, peerId, sendOffer, sendIceCandidate)` (RTC-02)
  4. On `offer` received: call `handleOffer(sdp, fromPeerId, localStream, sendAnswer, sendIceCandidate)`
  5. On `answer` received: call `handleAnswer(sdp, fromPeerId)`
  6. On `ice-candidate` received: call `handleIceCandidate(candidate, fromPeerId)`
  7. On `peer-left`: call `cleanupPeer(peerId)` — remove from remoteStreams (RTC-03)
  8. On leave/unmount: call `cleanup()` + `signaling.disconnect()` (RTC-05)

  **RoomPage layout (when session active):**
  - Room info header (existing: roomId, status badge, creator, relay mode)
  - VideoGrid (localStream + remoteStreams map)
  - MediaControls bar (mute, camera, leave)
  - Close Room button (existing, creator-only)

  **State machine:**
  - `idle` → user sees "Join Session" button
  - `connecting` → starting media + signaling
  - `active` → video grid visible, peers connecting
  - `error` → media error message with retry option
  - Leave button returns to `idle` state and cleans up all resources

  **Cleanup on unmount:** useEffect cleanup must call `cleanup()` + `disconnect()` to prevent resource leaks when navigating away.

### Task 4: Connection stats hook + overlay
- **Agent**: FE
- **Files**: `src/hooks/useConnectionStats.ts` (new), `src/components/VideoGrid.tsx` (modify — add stats overlay to tiles)
- **Requirements**: RTC-06
- **Depends on**: Task 3
- **Description**:
  Create a `useConnectionStats` hook that polls RTCPeerConnection stats and display them on video tiles.

  **useConnectionStats hook:**
  - Input: `peerConnectionsRef: React.RefObject<Map<string, RTCPeerConnection>>`
  - Polls `pc.getStats()` every 2 seconds for each active connection
  - Extracts from stats report:
    - RTT: from `candidate-pair` stats → `currentRoundTripTime` (seconds → ms)
    - Packet loss: from `inbound-rtp` stats → `packetsLost / packetsReceived * 100`
    - Jitter: from `inbound-rtp` stats → `jitter` (seconds → ms)
  - Returns: `Map<peerId, { rtt: number, packetLoss: number, jitter: number }>`
  - Cleanup: clear interval on unmount

  **Stats overlay on VideoGrid:**
  - Small semi-transparent overlay on each remote peer tile
  - Shows: `RTT: 12ms | Loss: 0.1% | Jitter: 3ms`
  - Updates every 2 seconds (matches poll interval)
  - Only visible when stats data is available

## Execution Order

```
T1 (useWebRTC multi-peer)
  └──→ T2 (VideoGrid + MediaControls)
         └──→ T3 (RoomPage orchestration)
                └──→ T4 (Connection stats)
```

All tasks are sequential — each builds on the previous. All are FE-only, no parallelization across domains.

## Risks & Open Questions

1. **ICE connectivity in localhost**: P2P over `localhost` with STUN-only should work for demo. Cross-network demos would need TURN — deferred.
2. **Multiple video refs**: React's `useRef` is per-component — VideoGrid needs a sub-component pattern (`<VideoTile>`) so each peer video gets its own ref. Straightforward but must be done correctly.
3. **Callback ref stability**: Signaling callbacks reference useWebRTC functions. Must ensure stable references via `useCallback` deps or `useRef` patterns to avoid stale closures.
4. **Browser autoplay policies**: Some browsers block autoplay of video with audio. Local video is already `muted`; remote videos use `autoPlay playsInline` which should work. If issues arise, add a user gesture prompt.
