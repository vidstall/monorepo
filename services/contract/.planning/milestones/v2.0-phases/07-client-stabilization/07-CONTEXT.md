# Phase 7 Context: Client Stabilization

**Phase Goal:** Existing client code works correctly as a 2-peer P2P demo without silent failures
**Requirements:** FIX-01, FIX-02, FIX-03, FIX-04, FIX-05, FIX-06
**Created:** 2026-03-09

## Prior Decisions (from STATE.md / PROJECT.md)

- P2P WebRTC via signaling server (no mediasoup — deferred to v3.0)
- No Zustand/Redux — React Query for chain state, refs for WebRTC state
- Bug fixes first (FIX-*) before any feature work
- react-router-dom v6 for URL routing (Phase 8+, not this phase)

## Decisions

### 1. Error Display Style

**Decision:** Inline banners, not toasts or modals.

- Red banner appears above the relevant section (above room controls for room errors, above video area for camera errors)
- Banners stay until the user takes another action (e.g., clicks Create Room again) — no manual dismiss, no auto-timeout
- Camera/mic errors include a **Retry** button to re-request permissions
- Room creation errors show the error message only — user retries via the normal Create Room button
- No external toast library needed — plain CSS + React state

### 2. Environment Variable Configuration

**Decision:** VITE_ env vars with mode-based .env files.

- **Naming:** `VITE_PACKAGE_ID`, `VITE_NETWORK_REGISTRY_ID`, `VITE_USER_REGISTRY_ID`, `VITE_ROOM_MANAGER_ID`, `VITE_SIGNALING_URL`, `VITE_SUI_NETWORK`
- **Location:** `.env` files live in `apps/client/` (not monorepo root) — Vite reads from app root
- **Mode files:** `.env.local` for localnet, `.env.testnet` for testnet. Run `vite --mode testnet` to switch.
- **Validation:** `config.ts` validates all required vars at import time — app won't start if any VITE_ var is missing. Error message names the missing variable.
- **Template:** Ship `.env.example` in `apps/client/` with all var names and placeholder comments

### 3. Peer Disconnect Feedback

**Decision:** Remove video immediately, no transition.

- When `peer-left` signal arrives, remove the peer's video tile instantly
- No "peer left" overlay or message — keep it simple for a bug-fix phase
- Phase 9 will build richer peer lifecycle UX

### 4. Video Grid Scope

**Decision:** Keep 1-local + 1-remote for Phase 7.

- FIX-04 changes connection tracking from single `pcRef` to `Map<peerId, RTCPeerConnection>` — this is the data model fix
- VideoGrid still renders only the first remote stream — multi-peer tiled layout is Phase 9 (RTC-04)
- This keeps Phase 7 scope tight: fix the bugs, don't add features

## Code Context

**Files to modify:**
| File | Bug | Change |
|------|-----|--------|
| `apps/client/src/App.tsx` | FIX-01 | Change `localStreamRef` from plain object to `useRef` |
| `apps/client/src/hooks/useSignaling.ts` | FIX-02 | Wait for WebSocket `open` event before sending `join` |
| `apps/client/src/hooks/useChain.ts` | FIX-03 | Throw error when RoomCreated event missing (remove digest fallback) |
| `apps/client/src/hooks/useWebRTC.ts` | FIX-04 | Replace single `pcRef` with `Map<string, RTCPeerConnection>` |
| `apps/client/src/App.tsx` | FIX-05 | Wrap `getUserMedia` in try/catch, display inline banner with retry |
| `apps/client/src/config.ts` | FIX-06 | Read from `import.meta.env.VITE_*`, validate at import |

**New files:**
| File | Purpose |
|------|---------|
| `apps/client/.env.example` | Template with all VITE_ var names |
| `apps/client/.env.local` | Localnet object IDs (gitignored) |
| `apps/client/.env.testnet` | Testnet object IDs (gitignored) |

**Existing patterns to preserve:**
- `@mysten/dapp-kit` for wallet — don't change wallet integration
- `useSignedAndExecuteTransaction` for chain TXs
- WebSocket message protocol: `{ type, roomId, peerId, sdp, candidate, targetPeerId }`
- STUN server: `stun:stun.l.google.com:19302`

## Deferred Ideas

None captured during discussion.

## Next Steps

→ `/dvconf:plan-phase 7` to create the task breakdown

---
*Context created: 2026-03-09*
