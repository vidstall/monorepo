DESIGN PROPOSAL -- FE: Escrow Creation, Assignment-Based Session Flow, and Relay Failover
Author: FE Agent
Phase: 14
Date: 2026-03-12

---

## Scope

This proposal covers two Phase 14 tasks:
- **Task 7**: Client escrow creation + signaling-first session flow (`useEscrow`, `useRoomAssignment`, RoomPage flow changes)
- **Task 8**: Client relay failover with auto-reconnect (exponential backoff in `useRelay`, reconnecting UI state)

---

## Module 1: useEscrow Hook

PURPOSE:
  Executes the `economic_layer::create_escrow` on-chain transaction, allowing the room
  creator to deposit DVCONF tokens as escrow for a room session.

OWNS:
  - `escrowLoading: boolean` -- TX in flight
  - `escrowError: string | null` -- last error from TX
  - `escrowId: string | null` -- object ID of the created RoomEscrow (extracted from EscrowCreated event)

PUBLIC API:
  ```typescript
  interface UseEscrowReturn {
    createEscrow: (roomId: string, amount: bigint) => Promise<CreateEscrowResult>;
    escrowLoading: boolean;
    escrowError: string | null;
    escrowId: string | null;
  }

  interface CreateEscrowResult {
    escrowId: string | null;
    error: string | null;
  }

  function useEscrow(): UseEscrowReturn;
  ```

DEPENDS ON:
  - `@mysten/dapp-kit` -- `useSignAndExecuteTransaction`, `useSuiClient`
  - `config.ts` -- `CONFIG.PACKAGE_ID`, `CONFIG.NETWORK_REGISTRY_ID`, `CONFIG.ROOM_MANAGER_ID`
  - `utils/txErrors.ts` -- `humanizeChainError()`
  - On-chain: `economic_layer::create_escrow(net_reg, room_mgr, room_id, payment, ctx)`

IMPLEMENTATION NOTES:
  - The `amount` parameter is a `bigint` representing DVCONF token units.
  - The hook splits a Coin from the user's wallet balance using `tx.splitCoins(tx.gas, [amount])`.
    However, since DVCONF is a custom token (not SUI), the hook must first find an owned
    `Coin<TOKEN>` object in the user's wallet. Use `client.getCoins({ owner, coinType })` to
    discover the user's DVCONF token coins, then `tx.splitCoins()` on the found coin object.
  - The `escrowId` is extracted from the `EscrowCreated` event emitted by the on-chain function.
    The event has field `escrow_id` which is the shared object ID of the new `RoomEscrow`.
  - Error code 650 (E_PAUSED) should be humanized as "Network is paused".
  - Error code 651 (E_NOT_ROOM_CREATOR) should be humanized as "Only the room creator can deposit escrow".
  - Error code 653 (E_ROOM_NOT_PENDING) should be humanized as "Room must be in PENDING status to create escrow".
  - Error code 660 (E_ZERO_ESCROW) should be humanized as "Escrow amount must be greater than zero".

FILE: `dvconf-client/src/hooks/useEscrow.ts` (new file)

---

## Module 2: useRoomAssignment Hook

PURPOSE:
  Reads the CP-assigned relay and signaling node IDs from on-chain `RoomManager`,
  then resolves those IDs to endpoint URLs by querying `RelayRegistry` and `SignalingRegistry`.
  Polls until assignment is available or a timeout is reached.

OWNS:
  - `relayUrl: string | null` -- resolved relay WebSocket endpoint
  - `signalingUrl: string | null` -- resolved signaling WebSocket endpoint
  - `relayId: string | null` -- on-chain relay node ID
  - `signalingId: string | null` -- on-chain signaling node ID
  - `isAssigned: boolean` -- true when both relay and signaling are assigned
  - `isLoading: boolean` -- polling in progress
  - `isTimedOut: boolean` -- assignment polling exceeded timeout
  - `error: string | null`

PUBLIC API:
  ```typescript
  interface RoomAssignment {
    relayUrl: string | null;
    signalingUrl: string | null;
    relayId: string | null;
    signalingId: string | null;
    isAssigned: boolean;
    isLoading: boolean;
    isTimedOut: boolean;
    error: string | null;
    refetch: () => void;
  }

  function useRoomAssignment(roomId: string | undefined, enabled: boolean): RoomAssignment;
  ```

DEPENDS ON:
  - `@mysten/dapp-kit` -- `useSuiClient`
  - `@mysten/sui/transactions` -- `Transaction`
  - `@mysten/sui/bcs` -- BCS decoding
  - `config.ts` -- `CONFIG.PACKAGE_ID`, `CONFIG.ROOM_MANAGER_ID`, `CONFIG.RELAY_REGISTRY_ID`,
    `CONFIG.SIGNALING_REGISTRY_ID`, `CONFIG.ROOM_POLL_INTERVAL`
  - On-chain: `room_manager::get_room_assignment(manager, room_id) -> (Option<ID>, Option<ID>)`
    (Task 1 adds this function)

IMPLEMENTATION NOTES:
  - `enabled` parameter gates polling -- set to `false` until escrow is deposited.
  - Step 1: devInspect `room_manager::get_room_assignment(manager, room_id)`.
    BCS decode the return as `(Option<ID>, Option<ID>)` -- `(assigned_relay, assigned_signaling)`.
  - Step 2: If both are `some`, resolve relay ID to endpoint URL via devInspect on
    `relay_registry` and signaling ID via devInspect on `signaling_registry`.
    Use the existing BCS layouts from `useRelayDiscovery` and `useSignalingDiscovery`.
  - Polls at `CONFIG.ROOM_POLL_INTERVAL` (5s) until `isAssigned` becomes true.
  - Timeout: after `ASSIGNMENT_TIMEOUT` (default 120s / 120_000ms), sets `isTimedOut = true`
    and stops polling. The timeout constant should be added to `config.ts` as
    `ASSIGNMENT_TIMEOUT` (from env var `VITE_ASSIGNMENT_TIMEOUT`, default 120000).
  - The `refetch` function allows manual retry after timeout.

FILE: `dvconf-client/src/hooks/useRoomAssignment.ts` (new file)

---

## Module 3: RoomPage Flow Changes

PURPOSE:
  Restructure RoomPage to follow the new session lifecycle:
  Room created -> Escrow deposited -> Waiting for CP assignment -> Assignment received -> Join Session -> Active

OWNS:
  - `roomPhase` local state: `'status' | 'escrow' | 'waiting-assignment' | 'ready' | 'session'`
    (UI-only concern for step progression, not chain state)

PUBLIC API:
  No new exports. RoomPage is a page component (default export).

DEPENDS ON:
  - `useRoomStatus` -- existing hook, reads room status/creator/relayMode
  - `useEscrow` -- new (Module 1), deposits escrow
  - `useRoomAssignment` -- new (Module 2), reads CP assignment
  - `useRelay` -- existing hook, connects to relay (now using assignment URL instead of discovery URL)
  - `useChain` -- existing hook, closeRoom
  - `useNetworkPause` -- existing hook

FLOW CHANGES:
  1. Remove `useRelayDiscovery()` import from RoomPage. The relay URL now comes from
     `useRoomAssignment` (CP-assigned), not from client-side discovery scoring.
  2. Add `useEscrow()` for escrow deposit step.
  3. Add `useRoomAssignment(roomId, escrowDeposited)` -- enabled after escrow is deposited.
  4. Pass `assignment.relayUrl` to `useRelay()` instead of `relayDiscovery.url`.
  5. The "Join Session" button is only shown after assignment is received (`isAssigned === true`).
  6. Room creator sees the escrow step; non-creators skip straight to waiting for assignment
     (assuming the creator has already deposited escrow -- they poll for assignment directly).

ROOMPAGE STATE MACHINE:
  ```
  [Loading]
      |
      v
  [Room Status Loaded]
      |
      +-- Room is CLOSED --> [Closed View]
      |
      +-- Room is PENDING, user is creator --> [Escrow Step]
      |       |
      |       v (escrow TX success)
      |   [Waiting for Assignment]
      |       |
      |       +-- timeout --> [Assignment Timeout - show retry]
      |       |
      |       v (isAssigned = true)
      |   [Ready to Join]
      |       |
      |       v (user clicks "Join Session")
      |   [Connecting]
      |       |
      |       +-- error --> [Error - show retry]
      |       |
      |       v
      |   [Active Session]
      |       |
      |       +-- relay disconnect --> [Reconnecting] (Task 8)
      |       |       |
      |       |       +-- retry success --> [Active Session]
      |       |       +-- max retries --> [Error - show manual reconnect]
      |       |
      |       +-- room closed on-chain --> [Closed View]
      |       |
      |       v (user clicks "Leave")
      |   [Idle]
      |
      +-- Room is PENDING, user is NOT creator --> [Waiting for Assignment]
      |       (same sub-flow as above)
      |
      +-- Room is READY (already assigned) --> [Ready to Join]
              (same sub-flow as above)
  ```

UI SECTIONS (in render order):
  1. **Room header** -- room ID, status badge, creator address, relay mode (unchanged)
  2. **Escrow step** (new) -- shown when room is PENDING and user is creator:
     - Amount input field (bigint, labeled "DVCONF tokens")
     - "Deposit Escrow" button with loading/error/success states
     - On success, auto-advance to waiting-assignment phase
  3. **Waiting for assignment** (new) -- shown after escrow or for non-creators:
     - Spinner with "Waiting for relay assignment..." text
     - Poll counter: "Checking... (Xs elapsed)"
     - On timeout: "No assignment received. The Control Plane may not be running." + "Retry" button
  4. **Assignment info** (new, optional) -- shown when assignment is received:
     - Relay node ID (truncated) and signaling node ID (truncated)
     - Shown as small info text, not prominent
  5. **Join Session button** -- only shown when `isAssigned === true` and sessionState is idle
  6. **Session view** -- VideoGrid + MediaControls (unchanged)
  7. **Reconnecting overlay** (new, Task 8) -- see Module 4

FILE: `dvconf-client/src/pages/RoomPage.tsx` (edit existing)

---

## Module 4: useRelay Reconnect Logic (Task 8)

PURPOSE:
  Add automatic reconnect with exponential backoff to the relay WebSocket connection.
  When the relay disconnects during an active session, attempt to reconnect transparently
  while preserving local media tracks.

OWNS:
  - `reconnectAttempt: number` -- current retry count (0 when connected)
  - Extended `sessionState` with new value: `'reconnecting'`

PUBLIC API:
  ```typescript
  // Extended sessionState type
  type SessionState = 'idle' | 'connecting' | 'active' | 'reconnecting' | 'error';

  // UseRelayReturn remains the same shape, but sessionState now includes 'reconnecting'
  // and a new field is added:
  interface UseRelayReturn {
    localStream: MediaStream | null;
    remoteStreams: Map<string, MediaStream>;
    mode: number;
    mediaError: string | null;
    clearMediaError: () => void;
    sessionState: SessionState;
    reconnectAttempt: number;  // NEW: 0 when connected, 1-3 during retries
    startSession: () => Promise<void>;
    cleanup: () => void;
  }
  ```

DEPENDS ON:
  - `useRoomAssignment` (indirectly, via the `relayUrl` parameter) -- on reconnect,
    the caller should re-read assignment from chain (relay may have been reassigned)
  - mediasoup-client `Device`, `Transport`

IMPLEMENTATION NOTES:
  - Add an `onclose` handler to the `RelaySocket.connect()` method that triggers reconnect
    when `sessionState === 'active'` (not during intentional cleanup).
  - Use a `reconnectingRef` boolean to distinguish intentional close (cleanup) from unexpected
    disconnect.
  - Exponential backoff schedule: 1000ms, 2000ms, 4000ms (3 retries max).
  - On each reconnect attempt:
    1. Set `sessionState` to `'reconnecting'`, increment `reconnectAttempt`.
    2. Wait the backoff delay.
    3. Create a new `RelaySocket`, connect to `relayUrl` (which may have been updated
       by `useRoomAssignment` re-reading chain state).
    4. Re-join room, re-load device (router capabilities may differ), re-create transports.
    5. Re-produce all local tracks (preserved in `localStreamRef`).
    6. Re-consume existing remote producers (relay sends `newProducer` notifications on rejoin).
    7. On success: set `sessionState` back to `'active'`, reset `reconnectAttempt` to 0.
  - After 3 failed attempts:
    1. Set `sessionState` to `'error'`.
    2. Set `mediaError` to `'Connection lost. Please try reconnecting manually.'`
    3. Do NOT stop local media tracks (user can click manual "Reconnect" which calls `startSession`).
  - The `cleanup()` function sets `reconnectingRef.current = true` before closing the socket,
    so the `onclose` handler knows not to trigger auto-reconnect.

RECONNECT FLOW:
  ```
  [Active Session]
      |
      v (WebSocket onclose fires unexpectedly)
  [Reconnecting] (attempt=1, delay=1s)
      |
      +-- success --> [Active Session] (attempt=0)
      |
      +-- failure --> [Reconnecting] (attempt=2, delay=2s)
          |
          +-- success --> [Active Session] (attempt=0)
          |
          +-- failure --> [Reconnecting] (attempt=3, delay=4s)
              |
              +-- success --> [Active Session] (attempt=0)
              |
              +-- failure --> [Error] "Connection lost" + manual "Reconnect" button
  ```

UI IN ROOMPAGE (reconnecting state):
  - When `sessionState === 'reconnecting'`:
    - Keep the VideoGrid visible (local stream still active, remote streams frozen)
    - Overlay a semi-transparent banner: "Reconnecting... (attempt N of 3)"
    - Spinner in the banner
  - When `sessionState === 'error'` after reconnect failure:
    - Show VideoGrid with local stream (camera still on)
    - Error message: "Connection to relay lost."
    - "Reconnect" button (calls `startSession()` which does a full reconnect)
    - "Leave" button (calls `cleanup()`)

FILE: `dvconf-client/src/hooks/useRelay.ts` (edit existing)
FILE: `dvconf-client/src/pages/RoomPage.tsx` (edit existing -- add reconnecting UI)

---

## Module 5: Config Additions

PURPOSE:
  Add new configuration entries for Phase 14 features.

OWNS:
  - `ASSIGNMENT_TIMEOUT` config value
  - `ESCROW_SUGGESTED_AMOUNT` config value

PUBLIC API:
  ```typescript
  // Added to AppConfig interface:
  ASSIGNMENT_TIMEOUT: number;       // ms before assignment polling gives up (default 120000)
  ESCROW_SUGGESTED_AMOUNT: string;  // suggested escrow in token units (default '1000000')
  ```

DEPENDS ON:
  - Vite env vars: `VITE_ASSIGNMENT_TIMEOUT`, `VITE_ESCROW_SUGGESTED_AMOUNT`

FILE: `dvconf-client/src/config.ts` (edit existing)

---

## Module 6: Error Humanization Updates

PURPOSE:
  Add human-readable messages for economic_layer error codes.

PUBLIC API:
  No new exports. Updates the internal error mapping.

DEPENDS ON:
  - `utils/txErrors.ts` (existing file)

ERROR CODES TO ADD:
  - 650: "Network is paused. Please try again later."
  - 651: "Only the room creator can deposit escrow."
  - 652: "Room not found."
  - 653: "Room must be in PENDING status to create escrow."
  - 654: "Invalid session proof signature."
  - 660: "Escrow amount must be greater than zero."

FILE: `dvconf-client/src/utils/txErrors.ts` (edit existing)

---

## OPEN QUESTIONS -- Resolutions

### Q1: Should escrow amount be fixed (from constants) or user-specified via input?

**Resolution: User-specified with a suggested default.**

Rationale: The on-chain `create_escrow` accepts any `Coin<TOKEN>` with a non-zero value
(`assert!(coin_value > 0, E_ZERO_ESCROW)`). There is no fixed escrow constant on-chain.
The UI should show an input field pre-filled with `CONFIG.ESCROW_SUGGESTED_AMOUNT` (default
1,000,000 token units). The user can adjust the amount. This gives flexibility for different
room sizes and durations while providing a sensible default for the thesis demo.

### Q2: Should the client show the assigned relay/signaling node info in the UI?

**Resolution: Yes, as secondary info -- truncated IDs shown in small text.**

Rationale: For a thesis demo, showing the assigned node IDs confirms the CP assignment
worked correctly. It aids debugging and demonstrates the decentralized assignment flow.
The info should be de-emphasized (small gray text below the "Ready to Join" state) so it
does not clutter the main UX. Full addresses are never shown -- only first 8 + last 4 chars
(e.g., `0x1234abcd...ef01`).

### Q3: How does the client handle the case where CP never assigns (timeout)?

**Resolution: 120-second polling timeout with manual retry.**

Rationale: The client polls `get_room_assignment` every 5 seconds (same as room status poll
interval). After 120 seconds (24 polls) with no assignment, the UI shows:
- Message: "No relay assignment received. The Control Plane daemon may not be running."
- "Retry" button that resets the timeout and resumes polling for another 120 seconds.
- The room remains in PENDING status on-chain; no destructive action is taken.

This balances user experience (not waiting forever) with the reality that in a local dev
environment, the CP daemon might not be running. The timeout is configurable via
`VITE_ASSIGNMENT_TIMEOUT` env var.

---

## Cross-Module Dependencies

```
useRoomStatus (existing)
    |
    v reads room status
RoomPage
    |-- uses --> useEscrow (new) -- TX --> economic_layer::create_escrow
    |-- uses --> useRoomAssignment (new) -- devInspect --> room_manager::get_room_assignment
    |                                      devInspect --> relay_registry (resolve URL)
    |                                      devInspect --> signaling_registry (resolve URL)
    |-- uses --> useRelay (modified) <-- relayUrl from useRoomAssignment
    |-- uses --> useChain (existing) -- closeRoom
    |-- uses --> useNetworkPause (existing)
```

---

## Integration Contracts

### IC-FE-1: useRoomAssignment depends on Task 1 (on-chain `get_room_assignment`)
  - FE calls: `room_manager::get_room_assignment(manager: &RoomManager, room_id: ID)`
  - Expected return: `(Option<ID>, Option<ID>)` -- `(assigned_relay, assigned_signaling)`
  - BCS decode: `bcs.struct('RoomAssignmentResult', { relay: bcs.option(bcs.Address), signaling: bcs.option(bcs.Address) })`
    (exact BCS layout depends on how Move serializes the tuple return)

### IC-FE-2: useEscrow depends on economic_layer::create_escrow (existing)
  - FE calls: `economic_layer::create_escrow(net_reg, room_mgr, room_id, payment, ctx)`
  - Payment: `Coin<TOKEN>` split from user's wallet
  - Event: `EscrowCreated { escrow_id, room_id, creator, amount }`

### IC-FE-3: useRelay receives relayUrl from useRoomAssignment (internal FE contract)
  - `useRelay(relayUrl, roomId, peerId)` -- `relayUrl` is now the CP-assigned URL,
    not the discovery-scored URL from `useRelayDiscovery`.
  - The `relayUrl` parameter type (`string`) is unchanged.

---

## Files Changed Summary

| File | Action | Module |
|------|--------|--------|
| `src/hooks/useEscrow.ts` | NEW | Module 1 |
| `src/hooks/useRoomAssignment.ts` | NEW | Module 2 |
| `src/pages/RoomPage.tsx` | EDIT | Module 3, Module 4 (UI) |
| `src/hooks/useRelay.ts` | EDIT | Module 4 |
| `src/config.ts` | EDIT | Module 5 |
| `src/utils/txErrors.ts` | EDIT | Module 6 |

---

## Risks

1. **BCS decoding of `(Option<ID>, Option<ID>)` tuple return**: Move functions returning
   tuples serialize each return value as a separate BCS-encoded byte array in `returnValues`.
   The hook must decode `returnValues[0]` as `Option<ID>` and `returnValues[1]` as `Option<ID>`
   separately, not as a single struct. This matches the existing pattern in `useRoomStatus`
   which decodes `returnValues[0]` as a single struct.

2. **DVCONF token coin discovery**: The user needs owned `Coin<TOKEN>` objects to deposit escrow.
   For the thesis demo, test accounts must have DVCONF tokens minted. The hook should show a
   clear error if no DVCONF coins are found: "You need DVCONF tokens to deposit escrow."

3. **Race condition on relay URL update during reconnect**: If the relay is reassigned on-chain
   while the client is reconnecting, the `relayUrl` prop to `useRelay` will update on the next
   render. The reconnect logic should use a ref to always read the latest `relayUrl` value,
   not the stale closure value.
