# Phase 8: Chain Integration & Room Management - Context

**Gathered:** 2026-03-09
**Status:** Ready for planning

## Phase Boundary

Phase 8 adds wallet authentication, on-chain user registration, room creation/closing, room status polling, URL-based room sharing, and paused-network guards to the React client. All chain interactions use dapp-kit hooks — no Move contract changes are needed. "Joining" a room is off-chain only (signaling server WebSocket), since room status transitions are CP-daemon-driven via `public(package)` functions. The @mysten/sui version mismatch is fixed in this phase.

The client now lives in its own repo at `dvconf-client/` (extracted from `dvconf-daemons/apps/client/`). It is a standalone Vite + React project with no monorepo workspace.

NOT in scope: multi-peer video layout (Phase 9), dashboard/stats (Phase 10), any Move contract modifications, any daemon changes.

## Implementation Decisions

### Join Model
- **No on-chain join_room TX**: The Move contracts have no `join_room` entry point. `set_room_status` is `public(package)` only (CP-daemon-driven). Client "joins" by connecting to signaling WS with room_id. Room status is read-only from chain.
- **Room status is informational**: Client polls and displays real chain status. If stuck at Pending (no CPs running in dev), that's accurate. WebRTC join is not gated on room status — user can create + join immediately for P2P demo.

### Routing
- **Minimal routes**: Two routes only — `/` (home: register + create/join) and `/rooms/:id` (room view with video). react-router-dom v6 as previously decided.
- **Shareable room URL**: `/rooms/:id` can be opened by another user to join the same room.

### Chain Queries
- **dapp-kit hooks**: Use `useSuiClientQuery` for `getObject` calls (registration check, room status polling). Integrates with React Query caching and auto-refetch.
- **Registration check (CLIENT-02)**: On app load, query UserRegistry with connected wallet address using `devInspectTransactionBlock` to call `is_registered`. Prompt if not registered.
- **Room status polling (ROOM-02)**: Use `useSuiClientQuery` with `refetchInterval` to poll `RoomManager.borrow_room()` for room status. Display Pending(0)/Ready(1)/Active(2)/Closed(3).

### Paused Network Guard (ROOM-05)
- **Check before each write TX**: Read `NetworkRegistry.is_paused` from chain before every mutating TX (register, createRoom, closeRoom). Always accurate. If paused, show inline error message and block the TX.

### TX Feedback (CLIENT-04)
- **Loading/success/error states**: Every chain TX shows loading spinner, success confirmation, and error message. Follow Phase 7 pattern of inline banners for errors.

### SDK Version Fix
- **Fix @mysten/sui mismatch**: Pin client's `@mysten/sui` to the version dapp-kit@0.14 expects (~1.24). Resolves TS errors in useChain.ts.

### Claude's Discretion
- Component file structure within `apps/client/src/`
- Exact polling interval for room status (suggest 5s default)
- Whether to use `devInspectTransactionBlock` or `getObject` + dynamic field reads for view functions
- Error message wording and styling (follow Phase 7 inline banner pattern)
- React Query key naming conventions

## Specific Ideas

- `useRegistration` hook: checks `is_registered` on wallet connect, exposes `isRegistered`, `register()`, `loading`, `error`
- `useRoomStatus` hook: polls room status by room_id, returns `{status, creator, relayMode, createdAt, closedAt}`
- `usePausedGuard` hook or utility: reads `is_paused` before TX execution, throws/blocks if paused
- Home page (`/`): shows WalletConnect, registration prompt, create room + join room controls
- Room page (`/rooms/:id`): shows room status badge, video grid, leave button
- Room status displayed as colored badge: Pending(yellow), Ready(blue), Active(green), Closed(gray)

### Move Contract Signatures (for TX construction)

```
register_user(net_reg: &NetworkRegistry, registry: &mut UserRegistry, display_name: vector<u8>, ctx)
create_room(net_reg: &NetworkRegistry, manager: &mut RoomManager, user_reg: &mut UserRegistry, relay_mode: u8, ctx)
close_room(net_reg: &NetworkRegistry, manager: &mut RoomManager, room_id: ID, ctx)
```

View functions (via devInspect):
```
is_registered(registry: &UserRegistry, user: address) -> bool
borrow_room(manager: &RoomManager, room_id: ID) -> &RoomInfo
is_paused(net_reg: &NetworkRegistry) -> bool
```

Room status constants: PENDING=0, READY=1, ACTIVE=2, CLOSED=3

## Existing Code Insights

### Reusable Assets
- `useChain.ts`: `registerUser()` and `createRoom()` already work — extend with `closeRoom()` and paused guard
- `useSignaling.ts`: WebSocket connect/join fully functional
- `useWebRTC.ts`: Map-based peer connections ready for multi-peer
- `config.ts`: All VITE_ env vars validated
- `main.tsx`: SuiClientProvider + WalletProvider + QueryClientProvider already wired
- `WalletConnect.tsx`: Basic ConnectButton component exists
- `RoomControls.tsx`: Register + Create + Join UI exists (extend, don't rewrite)

### Established Patterns
- Inline red banners for errors (clear-on-next-action)
- `useCallback` + `useState` for async operations with loading state
- CONFIG object for all object IDs
- `signAndExecute` from dapp-kit for mutating TXs
- `showEvents: true` option for reading events from TX results

### Integration Points
- `useCurrentAccount()` from dapp-kit — wallet address for registration check
- `useSuiClientQuery()` from dapp-kit — chain reads with React Query integration
- `Transaction` from `@mysten/sui/transactions` — TX construction for close_room
- react-router-dom `useParams()` — extract room_id from URL

## Deferred Ideas

- Multi-peer tiled video layout — Phase 9 (RTC-04)
- System status dashboard — Phase 10 (POLISH-01)
- Token balance display — Phase 10 (POLISH-02)
- Participant name resolution — Phase 10 (POLISH-03)
- On-chain join_room tracking — not in v2.0 scope (would require contract changes)

## Revision Log

- **2026-03-09 (initial):** Context gathered via /dvconf:discuss-phase 8
