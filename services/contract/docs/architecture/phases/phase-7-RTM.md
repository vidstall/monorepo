# Requirements Traceability Matrix — Phase 7: Client Stabilization
Date: 2026-03-09

## Requirements Coverage

| REQ-ID | Requirement | Source File | Verification Evidence | Verified? |
|--------|-------------|-------------|----------------------|-----------|
| FIX-01 | localStreamRef uses `useRef` instead of plain object literal | `App.tsx:16` | `const localStreamRef = useRef<MediaStream \| null>(null);` — React `useRef` hook used, not a plain `{ current: null }` object. Ref is read in callbacks at lines 27, 31 and written at line 57. | YES (CODE REVIEW) |
| FIX-02 | WebSocket join waits for `open` event instead of `setTimeout` | `hooks/useSignaling.ts:26-73` | `connect()` returns a `Promise<void>` that resolves inside `ws.onopen` (line 33-35) and rejects on `ws.onerror` (line 38-39). In `App.tsx:58-64`, `await connect()` completes before `joinRoom(roomId)` is called at line 64. No `setTimeout` anywhere in the codebase. | YES (CODE REVIEW) |
| FIX-03 | `createRoom` throws on missing `RoomCreated` event instead of falling back to digest | `hooks/useChain.ts:52-58` | After extracting `roomId` from events, if `!roomId` the code executes `throw new Error('Room created on-chain but RoomCreated event was not returned...')` (line 57). No digest fallback exists. In `App.tsx:47-48`, the caught null triggers a visible error message via `setRoomError()`. | YES (CODE REVIEW) |
| FIX-04 | Multiple `RTCPeerConnection`s tracked in a `Map` keyed by `peerId` (not single `pcRef`) | `hooks/useWebRTC.ts:6` | `const peerConnections = useRef<Map<string, RTCPeerConnection>>(new Map());` — Map keyed by peerId. `createPC` sets entries at line 41 (`peerConnections.current.set(targetPeerId, pc)`). `cleanupPeer` (lines 112-122) closes and removes individual peers. `cleanup` (lines 124-131) iterates and closes all. No single `pcRef` found in codebase. | YES (CODE REVIEW) |
| FIX-05 | Camera/mic errors caught and displayed to user | `hooks/useWebRTC.ts:14-33`, `App.tsx:93-98` | `startLocalStream` wraps `getUserMedia` in try/catch, classifies `NotAllowedError`, `NotFoundError`, `NotReadableError`, and generic errors into human-readable `mediaError` state (lines 20-29). `App.tsx:93-98` renders a red error banner with the message and a Retry button. Connection errors also handled in `App.tsx:86-91`. | YES (CODE REVIEW) |
| FIX-06 | Object IDs read from `VITE_` environment variables, not hardcoded | `config.ts:12-27` | `requireEnv()` helper reads `import.meta.env[name]` and throws if missing (lines 12-18). All IDs (`PACKAGE_ID`, `NETWORK_REGISTRY_ID`, `USER_REGISTRY_ID`, `ROOM_MANAGER_ID`, `SIGNALING_URL`, `SUI_NETWORK`) populated via `requireEnv('VITE_*')` calls. `.env.example` documents all variables. Grep for hardcoded `0x` hex strings in `src/` returned zero matches. | YES (CODE REVIEW) |

## Success Criteria Coverage

| # | Criterion | Code Evidence | Verified? |
|---|-----------|---------------|-----------|
| 1 | Local video stream persists across re-renders without going stale (useRef, not plain object) | `App.tsx:16` uses `useRef<MediaStream \| null>(null)`. The ref identity is stable across renders. Callbacks read `localStreamRef.current` (lines 27, 31) which always points to the latest stream set at line 57. | YES (CODE REVIEW) |
| 2 | WebSocket join message is never sent before the connection is open | `useSignaling.connect()` returns a Promise resolved only inside `ws.onopen` (line 33-35). `App.tsx:59` awaits this promise before calling `joinRoom()` at line 64. The `send()` helper (line 20-23) also guards with `readyState === WebSocket.OPEN`. Double protection. | YES (CODE REVIEW) |
| 3 | Room creation fails visibly when RoomCreated event is missing (no silent digest fallback) | `useChain.ts:56-58` throws an explicit error when `!roomId`. This propagates to the catch block which returns `null`. `App.tsx:48` checks for `!id` and sets `roomError` state, which `RoomControls.tsx:38-42` renders as a red banner. No digest fallback exists anywhere. | YES (CODE REVIEW) |
| 4 | Two peers can connect and disconnect without orphaned RTCPeerConnections leaking | `useWebRTC.ts:6` uses `Map<string, RTCPeerConnection>`. `cleanupPeer()` (lines 112-122) closes the specific peer's connection, deletes it from the map, and clears pending candidates. `App.tsx:36` wires `onPeerLeft` to `cleanupPeer(peerId)`. Full `cleanup()` (lines 124-131) closes all connections and clears the map. | YES (CODE REVIEW) |
| 5 | All on-chain object IDs are read from VITE_ environment variables, not hardcoded in source | `config.ts` uses `requireEnv()` for all six configuration values. `useChain.ts` references `CONFIG.PACKAGE_ID`, `CONFIG.NETWORK_REGISTRY_ID`, `CONFIG.USER_REGISTRY_ID`, `CONFIG.ROOM_MANAGER_ID`. `useSignaling.ts` references `CONFIG.SIGNALING_URL`. Grep for hardcoded `0x` hex patterns in `src/` returned zero matches. | YES (CODE REVIEW) |

## Gap Analysis

No gaps found. All 6 requirements (FIX-01 through FIX-06) are fully implemented with corresponding code evidence. All 5 success criteria are satisfied.

## Regression Check

| Check | Result |
|-------|--------|
| Hardcoded `0x` hex object IDs in `src/` | **CLEAN** — zero matches |
| Plain object refs (`{ current: ... }`) instead of `useRef` | **CLEAN** — zero matches |
| `setTimeout`-based WebSocket waits | **CLEAN** — zero matches in entire `src/` |
| Digest fallbacks in `createRoom` | **CLEAN** — no reference to "digest" anywhere in `src/` |
| Single `pcRef` instead of `Map` | **CLEAN** — no `pcRef` found; `peerConnections` is a `Map<string, RTCPeerConnection>` |

No regressions detected.

## Test Execution Report

Phase 7 has no automated test infrastructure (by design — PLAN.md notes "no test infrastructure, manual testing via DEMO-GUIDE.md").
TypeScript compilation: Pre-existing @mysten/sui version mismatch (dapp-kit@0.14 wants sui@1.24, monorepo has sui@1.45) causes 2 type errors in useChain.ts. NOT from Phase 7 changes — documented in STATE.md.

Verification method for all items: **CODE REVIEW** (static analysis of source files).

## Summary

| Metric | Value |
|--------|-------|
| Total requirements | 6 |
| Covered | 6/6 |
| Gaps | 0 |
| Coverage | **100%** |
| Success criteria verified | 5/5 |
| Regression issues found | 0 |
