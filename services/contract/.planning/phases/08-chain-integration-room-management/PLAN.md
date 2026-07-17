# Phase 8 Plan: Chain Integration & Room Management
Date: 2026-03-09

## Goal
Users can connect wallet, register on-chain, create rooms, and monitor room status through the full Pending/Ready/Active/Closed lifecycle

## Success Criteria
1. User can connect and disconnect Sui wallet from any page
2. Unregistered user is prompted to register and can submit display name as on-chain TX
3. User can create a room and see it transition through Pending/Ready/Active/Closed states via chain polling
4. Room URL (/rooms/:id) can be shared and opened by another user to join the same room
5. All write operations are blocked with a visible message when NetworkRegistry is paused

## Requirements Covered
CLIENT-01, CLIENT-02, CLIENT-03, CLIENT-04, ROOM-01, ROOM-02, ROOM-03, ROOM-04, ROOM-05

## Tasks

### Task 1: Add react-router-dom and app routing shell
- **Agent**: FE
- **Files**:
  - `dvconf-client/package.json` (add react-router-dom dependency)
  - `dvconf-client/src/main.tsx` (wrap App in BrowserRouter)
  - `dvconf-client/src/App.tsx` (replace single-page layout with Routes: `/` home, `/rooms/:roomId` room page)
  - `dvconf-client/src/pages/HomePage.tsx` (new — lobby with create/join room)
  - `dvconf-client/src/pages/RoomPage.tsx` (new — room view, reads roomId from URL params)
- **Requirements**: ROOM-03
- **Depends on**: None
- **Description**: Install react-router-dom v6. Restructure App.tsx into a router with two routes: `/` (lobby/home) and `/rooms/:roomId` (room page). This enables shareable room URLs. The HomePage renders wallet connect, registration, room creation, and a join-by-ID input. The RoomPage reads `roomId` from `useParams()` and renders the video session (wired up in later tasks). Both pages share a persistent header with wallet connect.

### Task 2: Wallet connect header + registration gate
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/components/Header.tsx` (new — persistent header with ConnectButton + disconnect)
  - `dvconf-client/src/hooks/useRegistration.ts` (new — checks UserRegistry on wallet connect, exposes `isRegistered`, `register()`, loading/error states)
  - `dvconf-client/src/components/RegistrationPrompt.tsx` (new — modal/inline prompt for unregistered users)
  - `dvconf-client/src/App.tsx` (add Header, wrap routes with registration context)
  - `dvconf-client/src/components/WalletConnect.tsx` (remove — replaced by Header)
- **Requirements**: CLIENT-01, CLIENT-02, CLIENT-03, CLIENT-04
- **Depends on**: Task 1
- **Description**: Create a persistent Header component with dapp-kit ConnectButton (handles connect/disconnect on any page — CLIENT-01). Create `useRegistration` hook that uses `useSuiClientQuery` to read the UserRegistry object and check if the connected wallet address is in the users table. If not registered, show RegistrationPrompt with display name input and submit as on-chain TX (CLIENT-02, CLIENT-03). All TX operations (register, create room, close room) must show loading spinners, success feedback, and error banners with retry (CLIENT-04). The `useChain` hook's `registerUser` already handles the TX — `useRegistration` wraps it with the on-load check.

### Task 3: Room creation with event extraction
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useChain.ts` (refactor: add `closeRoom()`, improve error handling for CLIENT-04)
  - `dvconf-client/src/pages/HomePage.tsx` (add create room button, navigate to `/rooms/:roomId` on success)
- **Requirements**: ROOM-01, ROOM-04, CLIENT-04
- **Depends on**: Task 2
- **Description**: The existing `createRoom` in `useChain.ts` already extracts `room_id` from the `RoomCreated` event and throws on missing event (FIX-03). Extend `useChain` with `closeRoom(roomId)` that calls `room_manager::close_room` on-chain. On HomePage, after successful room creation, `navigate('/rooms/' + roomId)` to enter the room. All TX calls must surface loading/success/error states (CLIENT-04) — wrap with a generic `executeTx` helper that manages state transitions.

### Task 4: Room status polling hook
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useRoomStatus.ts` (new — polls RoomManager for room status at configurable interval)
  - `dvconf-client/src/pages/RoomPage.tsx` (display room status badge: Pending/Ready/Active/Closed)
- **Requirements**: ROOM-02
- **Depends on**: Task 1
- **Description**: Create `useRoomStatus(roomId)` hook that uses `useSuiClientQuery` with `refetchInterval` (default 5s, configurable via config) to read `RoomManager.rooms[roomId]` from chain. Returns `{ status: 'pending'|'ready'|'active'|'closed', creator, relayMode, loading, error }`. The hook reads the RoomManager shared object via `getDynamicFieldObject` or `getObject` with content parsing. RoomPage displays a status badge that updates in real-time as the room transitions through its lifecycle. Map on-chain status codes (0=Pending, 1=Ready, 2=Active, 3=Closed) to display labels.

### Task 5: Network pause guard
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useNetworkPause.ts` (new — reads NetworkRegistry.paused field)
  - `dvconf-client/src/components/PauseBanner.tsx` (new — warning banner when paused)
  - `dvconf-client/src/App.tsx` (add PauseBanner, pass paused state to disable write buttons)
  - `dvconf-client/src/hooks/useChain.ts` (guard all write operations with pause check)
- **Requirements**: ROOM-05
- **Depends on**: Task 2
- **Description**: Create `useNetworkPause()` hook that reads the `NetworkRegistry` shared object's `paused` field via `useSuiClientQuery`. When paused is true: (1) show a prominent warning banner at the top of all pages ("Network is paused — write operations are disabled"), (2) disable all TX-submitting buttons (Register, Create Room, Close Room), (3) `useChain` methods return early with an error if paused. The on-chain contracts already enforce paused checks (E_PAUSED errors), but the client should prevent the attempt entirely with a clear UX message.

### Task 6: Room page join flow + close room
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/pages/RoomPage.tsx` (full room page: status display, join button, close button for creator, video grid placeholder)
  - `dvconf-client/src/pages/HomePage.tsx` (add join-by-paste input with navigate)
  - `dvconf-client/src/components/RoomControls.tsx` (refactor or remove — logic moves to pages)
- **Requirements**: ROOM-03, ROOM-04, CLIENT-04
- **Depends on**: Task 3, Task 4, Task 5
- **Description**: Complete the RoomPage: show room status from `useRoomStatus`, a "Close Room" button visible only to the room creator (compare connected wallet to room creator address), and the video grid area (placeholder for Phase 9). On HomePage, add a text input for pasting a room ID and a "Join" button that navigates to `/rooms/:roomId`. The room URL is shareable — opening `/rooms/:roomId` in another browser loads the RoomPage directly. Close Room calls `useChain.closeRoom()` with full loading/error/success states.

### Task 7: Fix @mysten/sui version mismatch
- **Agent**: FE
- **Files**:
  - `dvconf-client/package.json` (align @mysten/sui and @mysten/dapp-kit versions)
- **Requirements**: None (tech debt from Phase 7)
- **Depends on**: None
- **Description**: Resolve the pre-existing version mismatch noted in STATE.md: dapp-kit@0.14 wants sui@1.24 but the project has sui@1.0.0. Update both packages to compatible versions. This is independent of all other tasks and can run in parallel.

## Execution Order

```
Wave 1 (parallel):
  - Task 1: Router shell
  - Task 7: Version mismatch fix

Wave 2 (parallel, after Task 1):
  - Task 2: Wallet + registration
  - Task 4: Room status polling

Wave 3 (after Task 2):
  - Task 3: Room creation + close room TX

Wave 4 (after Task 2):
  - Task 5: Network pause guard

Wave 5 (after Tasks 3, 4, 5):
  - Task 6: Room page join flow + close room UI
```

## Dependency Graph

```
Task 7 ─────────────────────────────────────────┐
                                                 │ (independent)
Task 1 ──┬── Task 2 ──┬── Task 3 ──┐            │
          │            │            │            │
          │            └── Task 5 ──┤            │
          │                         │            │
          └── Task 4 ───────────────┤            │
                                    │            │
                              Task 6 ◄───────────┘
```

## Risks & Open Questions

1. **Dynamic field reading**: Reading `RoomManager.rooms` (a `Table<ID, RoomInfo>`) from the client requires `getDynamicFieldObject` with the correct BCS type tag for the table key. Need to verify the exact Sui SDK API for reading Table entries in the design phase.

2. **UserRegistry lookup**: Checking if an address is registered requires reading `UserRegistry.users` (also a `Table<address, UserProfile>`). Same dynamic field reading concern as above.

3. **NetworkRegistry object ID**: The `NetworkRegistry` object ID is already in config (`VITE_NETWORK_REGISTRY_ID`), so the pause check can read it directly via `getObject`.

4. **Room status codes**: Constants are defined in Move (`ROOM_STATUS_PENDING=0`, etc.) but not exposed as a shared type. The client must hardcode the mapping `{0: 'Pending', 1: 'Ready', 2: 'Active', 3: 'Closed'}`.

5. **No `join_room` on-chain TX**: STATE.md notes "join_room on-chain TX existence needs verification against Move contract." Confirmed: there is NO `join_room` entry function in `room_manager.move`. Joining a room is purely a signaling server operation (WebSocket `join` message) — no on-chain TX needed. The on-chain room tracks creator/status, not participants.
