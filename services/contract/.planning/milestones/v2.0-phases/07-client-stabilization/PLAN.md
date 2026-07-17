# Phase 7 Plan: Client Stabilization

Date: 2026-03-09

## Goal

Existing client code works correctly as a 2-peer P2P demo without silent failures.

## Success Criteria

1. Local video stream persists across re-renders without going stale (useRef, not plain object)
2. WebSocket join message is never sent before the connection is open
3. Room creation fails visibly when RoomCreated event is missing (no silent digest fallback)
4. Two peers can connect and disconnect without orphaned RTCPeerConnections leaking
5. All on-chain object IDs are read from VITE_ environment variables, not hardcoded in source

## Requirements Covered

FIX-01, FIX-02, FIX-03, FIX-04, FIX-05, FIX-06

## Tasks

### Task 1: Environment variable config and validation (FIX-06)

- **Agent**: FE
- **Files**:
  - Modify: `apps/client/src/config.ts`
  - Create: `apps/client/.env.example`
  - Create: `apps/client/.env.local` (gitignored)
  - Create: `apps/client/.env.testnet` (gitignored)
- **Requirements**: FIX-06
- **Depends on**: None
- **Description**:
  Replace hardcoded object IDs in `config.ts` with `import.meta.env.VITE_*` reads. Add startup validation that throws a clear error naming any missing variable. Variables: `VITE_PACKAGE_ID`, `VITE_NETWORK_REGISTRY_ID`, `VITE_USER_REGISTRY_ID`, `VITE_ROOM_MANAGER_ID`, `VITE_SIGNALING_URL`, `VITE_SUI_NETWORK`. Create `.env.example` with all var names and comments. Create `.env.local` with current localnet IDs (from existing config.ts). Create `.env.testnet` with testnet IDs (from `.env.testnet` in dvconf-contracts). Add `.env.local` and `.env.testnet` to `.gitignore` (or the monorepo root gitignore).

### Task 2: Fix localStreamRef and add camera/mic error handling (FIX-01, FIX-05)

- **Agent**: FE
- **Files**:
  - Modify: `apps/client/src/App.tsx`
  - Modify: `apps/client/src/hooks/useWebRTC.ts`
- **Requirements**: FIX-01, FIX-05
- **Depends on**: None
- **Description**:
  **FIX-01**: In `App.tsx` line 14, change `const localStreamRef = { current: null as MediaStream | null }` to `const localStreamRef = useRef<MediaStream | null>(null)`. Add `useRef` to the import.

  **FIX-05**: In `useWebRTC.ts`, wrap `navigator.mediaDevices.getUserMedia()` in try/catch. On failure, return `null` and expose an error state (`mediaError: string | null`) from the hook. Error messages: `'Camera/microphone permission denied'` for NotAllowedError, `'No camera or microphone found'` for NotFoundError, `'Camera is already in use'` for NotReadableError, generic `'Could not access camera/microphone'` for other errors. Also expose a `clearMediaError()` function.

  In `App.tsx`, display an inline red banner above the VideoGrid when `mediaError` is set, with a "Retry" button that calls `startLocalStream()` again and clears the error. Banner clears when user retries (clear-on-next-action pattern from CONTEXT.md).

### Task 3: Fix WebSocket join timing (FIX-02)

- **Agent**: FE
- **Files**:
  - Modify: `apps/client/src/hooks/useSignaling.ts`
  - Modify: `apps/client/src/App.tsx`
- **Requirements**: FIX-02
- **Depends on**: None
- **Description**:
  Current bug: `App.tsx` line 47 uses `setTimeout(() => joinRoom(roomId), 500)` to wait for WebSocket open. Fix by making `connect()` return a Promise that resolves when the WebSocket `open` event fires. Then in `App.tsx`, `await connect()` before calling `joinRoom()`. Remove the setTimeout.

  In `useSignaling.ts`: change `connect()` to return `Promise<void>`. Store a resolve callback in a ref. In `ws.onopen`, call the stored resolve and set connected state. If the WebSocket errors before opening, reject the promise.

### Task 4: Fix createRoom error handling (FIX-03)

- **Agent**: FE
- **Files**:
  - Modify: `apps/client/src/hooks/useChain.ts`
  - Modify: `apps/client/src/components/RoomControls.tsx`
- **Requirements**: FIX-03
- **Depends on**: None
- **Description**:
  Current bug: `useChain.ts` line 56 falls back to `result.digest` when `RoomCreated` event is missing. This silently gives a wrong room ID.

  Fix: Remove the digest fallback. If `roomEvent` is undefined or `roomId` is falsy, throw an `Error('Room created on-chain but RoomCreated event was not returned. Please check the transaction.')`. The existing catch block returns `null` on error — this is fine.

  In `RoomControls.tsx`: accept an optional `roomError: string | null` prop. When set, display a red inline banner above the Create Room button. The banner clears when the user clicks Create Room again (parent clears the error state before calling `onCreateRoom`).

  In `App.tsx`: add `roomError` state. Set it from the `createRoom` catch path. Clear it when user clicks Create Room. Pass it to `RoomControls`.

### Task 5: Fix multi-peer connection tracking (FIX-04)

- **Agent**: FE
- **Files**:
  - Modify: `apps/client/src/hooks/useWebRTC.ts`
  - Modify: `apps/client/src/App.tsx`
- **Requirements**: FIX-04
- **Depends on**: Task 2 (both modify useWebRTC.ts and App.tsx)
- **Description**:
  Current bug: `useWebRTC.ts` uses a single `pcRef` and single `pendingCandidates` ref. When a second peer connects, the first connection is silently overwritten and leaked.

  Fix: Replace `pcRef: useRef<RTCPeerConnection | null>` with `peerConnections: useRef<Map<string, RTCPeerConnection>>` initialized to `new Map()`. Replace `pendingCandidates: useRef<RTCIceCandidateInit[]>` with `pendingCandidates: useRef<Map<string, RTCIceCandidateInit[]>>` (keyed by peerId).

  Update all functions:
  - `createPC(stream, onIceCandidate, targetPeerId)`: store `pc` in `peerConnections.current.set(targetPeerId, pc)` instead of `pcRef.current = pc`
  - `handleAnswer(sdp, fromPeerId)`: look up `peerConnections.current.get(fromPeerId)` instead of `pcRef.current`
  - `handleIceCandidate(candidate, fromPeerId)`: look up by peerId, queue in per-peer pending map
  - `cleanup()`: iterate all connections in the Map, close each, clear the Map
  - Add `cleanupPeer(peerId)`: close and remove a single peer's connection from the Map

  In `App.tsx`:
  - `onAnswer` callback needs to pass `fromPeerId` (currently drops it — see line 31)
  - `onIceCandidate` callback needs to pass `fromPeerId` (currently drops it — see line 32)
  - `onPeerLeft` callback should call `cleanupPeer(peerId)` instead of full `cleanup()`

  **Video grid stays 1+1** per CONTEXT.md decision — `remoteStream` state continues to hold the most recently connected peer's stream. Phase 9 will build the multi-peer tiled layout.

## Execution Order

```
Task 1 (FIX-06: env vars)     ─── independent, can run first or in parallel
Task 2 (FIX-01+05: ref + cam) ─┬─ parallel group (no shared files with T1, T3, T4)
Task 3 (FIX-02: WS timing)    ─┤  (T3 touches App.tsx but different sections than T2)
Task 4 (FIX-03: room error)   ─┘  (T4 touches RoomControls, different from T2/T3)
Task 5 (FIX-04: multi-peer)   ─── AFTER Task 2 (both modify useWebRTC.ts and App.tsx)
```

**Recommended execution**: Tasks 1-4 in parallel (different primary files), then Task 5 sequentially after Task 2 completes.

Note: Tasks 2, 3, and 4 all touch `App.tsx` but in different sections (T2: error banner + useRef import, T3: handleJoin function, T4: roomError state + RoomControls props). If running truly in parallel, the executor should be aware of potential merge conflicts in `App.tsx` and may choose to serialize T2→T3→T4 for safety.

**Safest serial order**: T1 → T2 → T3 → T4 → T5

## Risks & Open Questions

1. **App.tsx contention**: Tasks 2, 3, 4, and 5 all modify App.tsx. Parallel execution risks merge conflicts. Safest to run serially or have one task own all App.tsx changes.
2. **No test infrastructure**: The client has no test setup (no vitest, no testing-library). Phase 7 is bug fixes only — manual testing via the DEMO-GUIDE.md flow. Automated tests are a Phase 9/10 concern.
3. **Vite mode files**: `.env.local` is auto-loaded by Vite in all modes (highest priority). The naming `.env.local` for localnet config may conflict with Vite's built-in `.env.local` behavior. Consider using `.env.development` for localnet instead, or just `.env` (default) + `.env.testnet` (mode override). **Resolution needed before Task 1 execution.**
