# Phase 10: Client Polish - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase adds three polish features to the React client that demonstrate the decentralized architecture in a thesis demo: a system status dashboard with live on-chain node/room counts, the user's DVCONF token balance in the header, and display name resolution for room participants. All work is FE-only — no Move contract or daemon changes. No new on-chain functions are needed; all required read accessors already exist as public functions.

</domain>

<decisions>
## Implementation Decisions

### POLISH-01: System Status Dashboard
- **Location**: Panel/card on the existing HomePage — not a separate route
- **Data sources**: devInspect calls to public accessors on shared objects:
  - `user_registry::total_users(&UserRegistry)` → total registered users
  - `room_manager::active_count(&RoomManager)` → active rooms
  - `relay_registry::active_count(&RelayRegistry)` → active relays
  - `control_plane_registry::active_cp_count(&ControlPlaneRegistry)` → active CPs
  - `validator_registry::active_count(&ValidatorRegistry)` → active validators
  - `miner_store::total_registered(&MinerStore)` → total registered nodes
- **New env vars required**: `VITE_MINER_STORE_ID`, `VITE_RELAY_REGISTRY_ID`, `VITE_CONTROL_PLANE_REGISTRY_ID`, `VITE_VALIDATOR_REGISTRY_ID`
- **Polling interval**: Reuse `CONFIG.ROOM_POLL_INTERVAL` (default 5s) or a separate `VITE_STATS_POLL_INTERVAL`

### POLISH-02: Token Balance in Header
- **Method**: `client.getBalance({ owner, coinType: '${PACKAGE_ID}::token::TOKEN' })`
- **Display**: In the Header component, next to the wallet address
- **Format**: Human-readable with 9 decimals (DVCONF token has 9 decimal places)
- **Polling**: Re-fetch on wallet change + periodic (same interval as dashboard)

### POLISH-03: Participant Display Names
- **Method**: devInspect `user_registry::borrow_profile` per peer address, then decode `display_name`
- **Trigger**: When a new peer joins (new entry in `remoteStreams` Map)
- **Cache**: In-hook state Map<address, string>, only query once per address per session
- **Display**: Show resolved name in VideoGrid tiles (fallback to truncated address if unregistered)

### Claude's Discretion
- Hook naming and internal structure for dashboard stats
- Exact layout/styling of the NetworkStatus panel
- Whether to combine multiple devInspect calls into one for dashboard counts
- Cache invalidation strategy for participant names
- Token balance formatting details (significant digits, etc.)

</decisions>

<specifics>
## Specific Ideas

- Create `useNetworkStats.ts` hook — polls all registry counts via devInspect, returns { users, rooms, relays, cps, validators, totalNodes }
- Create `NetworkStatus.tsx` component — card with labeled counters, used on HomePage
- Create `useTokenBalance.ts` hook — uses `client.getBalance()` with DVCONF coin type
- Modify `Header.tsx` — add token balance display next to wallet address
- Create `useParticipantNames.ts` hook — takes peer addresses array, returns Map<address, displayName>
- Modify `VideoGrid.tsx` — show display name on each video tile
- Update `config.ts` — add new object IDs (MINER_STORE_ID, RELAY_REGISTRY_ID, CONTROL_PLANE_REGISTRY_ID, VALIDATOR_REGISTRY_ID)
- Update `.env.example` — add new env var entries

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `useRegistration.ts` — devInspect + BCS decode pattern (boolean return). Reuse for name lookups.
- `useRoomStatus.ts` — devInspect + BCS decode pattern for structured data. Reuse for count accessors.
- `useNetworkPause.ts` — `getObject` polling pattern with useEffect + interval. Reuse for balance polling.
- `config.ts` — `requireEnv()` helper for adding new VITE_ vars.
- `useChain.ts` — `useSuiClient()` pattern for SDK access.

### Established Patterns
- devInspect via `client.devInspectTransactionBlock()` for reading on-chain state (Phase 8 pattern)
- BCS decode from `returnValues[0][0]` — bytes to typed values
- `useEffect` with `cancelled` flag for async cleanup
- `as any` cast for Transaction type (pre-existing dapp-kit mismatch)
- Inline styles (no CSS framework used)

### Integration Points
- `HomePage.tsx` — will embed NetworkStatus panel
- `Header.tsx` — will show token balance
- `VideoGrid.tsx` / `RoomPage.tsx` — will show participant names
- `useWebRTC.ts` — exposes `remoteStreams: Map<string, MediaStream>` where keys are peer IDs (wallet addresses from signaling)
- `.env.example` — needs new object IDs documented

</code_context>

<deferred>
## Deferred Ideas

- **Node operator details page** (click a count to see registered nodes) — out of scope for thesis demo, v3.0
- **Token transfer/send UI** — out of scope, document in README
- **User profile editing** — `update_profile` exists on-chain but no UI needed for demo

</deferred>

<revision_log>
## Revision Log

- **2026-03-10 (initial):** Context gathered via /dvconf:discuss-phase

</revision_log>
