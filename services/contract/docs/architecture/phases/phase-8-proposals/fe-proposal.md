DESIGN PROPOSAL — FE: Chain Integration & Room Management
Author: FE Agent
Phase: 8
Date: 2026-03-09

PURPOSE:
  Connect the React client to on-chain state so users can register, create/close rooms,
  monitor room lifecycle status, and respect network pause — all driven by Sui chain reads.

OWNS:
  - Client-side routing (`/`, `/rooms/:roomId`)
  - Registration check and prompt UI (reads UserRegistry.users Table)
  - Room creation flow with event extraction and navigation
  - Room status polling (reads RoomManager.rooms Table)
  - Network pause guard (reads NetworkRegistry.paused)
  - Close room TX (creator-only)
  - All loading / success / error UI state for chain operations

STRUCTS / TYPES:

```typescript
// ── Room status constants (mirror constants.move) ──────────────

export const ROOM_STATUS = {
  PENDING: 0,
  READY:   1,
  ACTIVE:  2,
  CLOSED:  3,
} as const;

export type RoomStatusCode = typeof ROOM_STATUS[keyof typeof ROOM_STATUS];

export const ROOM_STATUS_LABELS: Record<RoomStatusCode, string> = {
  [ROOM_STATUS.PENDING]: 'Pending',
  [ROOM_STATUS.READY]:   'Ready',
  [ROOM_STATUS.ACTIVE]:  'Active',
  [ROOM_STATUS.CLOSED]:  'Closed',
};

// ── Relay mode constants (mirror constants.move) ───────────────

export const RELAY_MODE = {
  SFU: 0,
  MCU: 1,
} as const;

export type RelayModeCode = typeof RELAY_MODE[keyof typeof RELAY_MODE];

// ── On-chain object shapes (parsed from Sui getObject / getDynamicFieldObject) ──

/** Mirrors dvconf::room_manager::RoomInfo */
export interface RoomInfoOnChain {
  creator:    string;   // address
  status:     number;   // u8 — use RoomStatusCode
  relay_mode: number;   // u8 — use RelayModeCode
  created_at: string;   // u64 as string (epoch)
  closed_at:  string;   // u64 as string (0 if not closed)
}

/** Mirrors dvconf::user_registry::UserProfile */
export interface UserProfileOnChain {
  display_name:  number[];  // vector<u8> — UTF-8 bytes
  registered_at: string;    // u64 as string (epoch)
  room_count:    string;    // u64 as string
}

// ── Hook return types ──────────────────────────────────────────

export interface UseRegistrationReturn {
  isRegistered: boolean;
  isChecking:   boolean;
  checkError:   Error | null;
  register:     (displayName: string) => Promise<boolean>;
  isRegistering: boolean;
  registerError: Error | null;
}

export interface UseRoomStatusReturn {
  status:     RoomStatusCode | null;
  statusLabel: string | null;
  creator:    string | null;
  relayMode:  RelayModeCode | null;
  isLoading:  boolean;
  error:      Error | null;
  refetch:    () => void;
}

export interface UseNetworkPauseReturn {
  isPaused:  boolean;
  isLoading: boolean;
  error:     Error | null;
}

export interface TxState {
  loading: boolean;
  error:   string | null;
  success: boolean;
}
```

PUBLIC API:

```typescript
// ── Hooks ──────────────────────────────────────────────────────

// src/hooks/useRegistration.ts
export function useRegistration(): UseRegistrationReturn;

// src/hooks/useRoomStatus.ts
export function useRoomStatus(roomId: string | undefined): UseRoomStatusReturn;

// src/hooks/useNetworkPause.ts
export function useNetworkPause(): UseNetworkPauseReturn;

// src/hooks/useChain.ts (extended)
export function useChain(): {
  registerUser: (displayName: string) => Promise<boolean>;
  createRoom:   (relayMode?: RelayModeCode) => Promise<string | null>;
  closeRoom:    (roomId: string) => Promise<boolean>;
  loading:      boolean;
};

// ── Pages ──────────────────────────────────────────────────────

// src/pages/HomePage.tsx
export default function HomePage(): JSX.Element;

// src/pages/RoomPage.tsx
export default function RoomPage(): JSX.Element;

// ── Components ─────────────────────────────────────────────────

// src/components/Header.tsx
export function Header(): JSX.Element;

// src/components/RegistrationPrompt.tsx
export function RegistrationPrompt(props: {
  onRegister: (name: string) => Promise<boolean>;
  isRegistering: boolean;
  error: string | null;
}): JSX.Element;

// src/components/PauseBanner.tsx
export function PauseBanner(): JSX.Element;

// src/components/RoomStatusBadge.tsx
export function RoomStatusBadge(props: {
  status: RoomStatusCode;
}): JSX.Element;
```

DEPENDS ON:
  - `@mysten/dapp-kit` — wallet connection (ConnectButton, useCurrentAccount, useSuiClientQuery, useSignAndExecuteTransaction)
  - `@mysten/sui` — Transaction builder, SuiClient type utilities
  - `@tanstack/react-query` — query caching and refetch (used internally by dapp-kit)
  - `react-router-dom` v6 — client-side routing
  - On-chain objects (read-only):
    - `NetworkRegistry` (shared object, ID from `CONFIG.NETWORK_REGISTRY_ID`)
    - `UserRegistry` (shared object, ID from `CONFIG.USER_REGISTRY_ID`)
    - `RoomManager` (shared object, ID from `CONFIG.ROOM_MANAGER_ID`)

ERROR CODES:
  Client-side error handling maps to these on-chain abort codes:
  - 500 (E_PAUSED) — "Network is paused. Please try again later."
  - 501 (E_NOT_CREATOR) — "Only the room creator can close this room."
  - 502 (E_NOT_FOUND) — "Room not found."
  - 503 (E_ALREADY_CLOSED) — "Room is already closed."
  - 504 (E_INVALID_MODE) — "Invalid relay mode."
  - 506 (E_USER_NOT_REGISTERED) — "You must register before creating a room."
  - 540 (E_ALREADY_REGISTERED) — treated as success (idempotent register)
  - 542 (E_PAUSED) — "Network is paused."

EVENTS EMITTED:
  N/A — FE does not emit events. It reads:
  - `RoomCreated { room_id, creator, relay_mode }` — extracted from createRoom TX result
  - `RoomClosed { room_id, closed_by, epoch }` — extracted from closeRoom TX result

OPEN QUESTIONS:
  ⚠️ OQ-1: Table<ID, RoomInfo> dynamic field key type — Sui Move `Table` stores entries
     as dynamic fields with a type-tagged key. For `Table<ID, RoomInfo>`, the dynamic field
     name type is `sui::dynamic_field::Field<ID, RoomInfo>`. The client must use
     `getDynamicFieldObject` with `parentId = RoomManager.rooms.id` (the Table's inner UID)
     and `name: { type: '0x2::object::ID', value: roomId }`. Need to verify that the Table
     UID is accessible from the parent object's content fields, or whether we must use
     `devInspectTransactionBlock` to call `room_manager::borrow_room` instead.

  ⚠️ OQ-2: Table UID extraction — When reading `RoomManager` via `getObject`, the `rooms`
     field in content is serialized as an object ID (the Table's inner UID). We need to
     confirm this ID can be used as `parentId` in `getDynamicFieldObject`. If Sui SDK
     does not expose Table internals, the fallback is `devInspectTransactionBlock` calling
     the read accessor.

  ⚠️ OQ-3: UserRegistry table lookup — Same pattern as OQ-1 but with `Table<address, UserProfile>`.
     The key type would be `{ type: 'address', value: walletAddress }`. If `getDynamicFieldObject`
     does not support `address` as a dynamic field key type, fallback to `devInspectTransactionBlock`
     calling `user_registry::is_registered`.

---

## Detailed Module Design

### 1. Routing Shell (Task 1)

**File: `src/main.tsx`**
Wrap `<App />` in `<BrowserRouter>` from `react-router-dom`.

```typescript
import { BrowserRouter } from 'react-router-dom';

// Inside render:
<BrowserRouter>
  <App />
</BrowserRouter>
```

**File: `src/App.tsx`**
Replace the monolithic layout with a router shell. The `Header` and `PauseBanner` persist across all routes.

```
<App>
  <Header />                          ← persistent, all routes
  <PauseBanner />                     ← persistent, shows when paused
  <RegistrationGate>                  ← blocks routes until registered
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/rooms/:roomId" element={<RoomPage />} />
    </Routes>
  </RegistrationGate>
</App>
```

Component tree and state flow:

```
main.tsx
  <QueryClientProvider>
    <SuiClientProvider>
      <WalletProvider>
        <BrowserRouter>
          <App>
            useNetworkPause()  → isPaused
            useRegistration()  → isRegistered, register()

            <Header>
              <ConnectButton />
              wallet address display
            </Header>

            <PauseBanner isPaused={isPaused} />

            {!isRegistered && account
              ? <RegistrationPrompt onRegister={register} />
              : <Routes>
                  <Route "/" element={<HomePage />}>
                    useChain() → createRoom()
                    "Create Room" button (disabled if paused)
                    "Join Room" input + navigate
                  </Route>
                  <Route "/rooms/:roomId" element={<RoomPage />}>
                    useRoomStatus(roomId) → status, creator
                    useChain() → closeRoom()
                    <RoomStatusBadge />
                    "Close Room" button (creator only, disabled if paused)
                    <VideoGrid /> (placeholder for Phase 9)
                  </Route>
                </Routes>
            }
          </App>
        </BrowserRouter>
      </WalletProvider>
    </SuiClientProvider>
  </QueryClientProvider>
```

### 2. Registration Hook — `useRegistration` (Task 2)

**Purpose**: On wallet connect, check if the address is registered in UserRegistry. Expose `isRegistered` and a `register()` function.

**Strategy — Two Approaches (Primary + Fallback)**:

**Primary approach — `getDynamicFieldObject`**:
```typescript
import { useSuiClient, useCurrentAccount } from '@mysten/dapp-kit';

export function useRegistration(): UseRegistrationReturn {
  const client = useSuiClient();
  const account = useCurrentAccount();

  // Step 1: Read UserRegistry object to get the Table UID for `users`
  // getObject(CONFIG.USER_REGISTRY_ID) → content.fields.users → this is the Table's UID

  // Step 2: Check if address exists as a dynamic field in that Table
  // client.getDynamicFieldObject({
  //   parentId: usersTableUid,
  //   name: { type: 'address', value: account.address },
  // })
  // If the response contains data → registered. If error/null → not registered.

  // Wrap both reads in useSuiClientQuery with appropriate staleTime.
}
```

**Fallback approach — `devInspectTransactionBlock`**:
If `getDynamicFieldObject` does not support `address` as a dynamic field key, use:
```typescript
const tx = new Transaction();
tx.moveCall({
  target: `${CONFIG.PACKAGE_ID}::user_registry::is_registered`,
  arguments: [
    tx.object(CONFIG.USER_REGISTRY_ID),
    tx.pure.address(account.address),
  ],
});
const result = await client.devInspectTransactionBlock({
  transactionBlock: tx,
  sender: account.address,
});
// Parse the boolean return value from result.results[0].returnValues
```

**Registration flow**:
1. Wallet connects → `useRegistration` fires query
2. If not registered → show `RegistrationPrompt` with display name input
3. User submits → call `useChain().registerUser(displayName)`
4. On success (or E_ALREADY_REGISTERED=540) → `isRegistered = true`
5. Invalidate the registration query cache on success

**Important**: The registration check runs on every wallet change (re-queries when `account.address` changes). Uses `useSuiClientQuery` with `enabled: !!account` to prevent queries when no wallet is connected.

### 3. Room Creation + Close Room TX (Task 3)

**Extension to `useChain.ts`**:

```typescript
const closeRoom = useCallback(async (roomId: string): Promise<boolean> => {
  setLoading(true);
  try {
    const tx = new Transaction();
    tx.moveCall({
      target: `${CONFIG.PACKAGE_ID}::room_manager::close_room`,
      arguments: [
        tx.object(CONFIG.NETWORK_REGISTRY_ID),
        tx.object(CONFIG.ROOM_MANAGER_ID),
        tx.pure.id(roomId),          // room_id: ID
      ],
    });
    await signAndExecute({ transaction: tx });
    return true;
  } catch (err) {
    console.error('closeRoom failed:', err);
    return false;
  } finally {
    setLoading(false);
  }
}, [signAndExecute]);
```

**Room creation navigation flow**:
1. User clicks "Create Room" on HomePage
2. `useChain().createRoom()` executes TX, extracts `room_id` from `RoomCreated` event
3. On success → `navigate('/rooms/' + roomId)` (react-router-dom)
4. User lands on RoomPage which starts polling room status

**Error mapping helper** (shared utility):
```typescript
// src/utils/txErrors.ts
export function humanizeChainError(err: unknown): string {
  const msg = String(err);
  if (msg.includes('500')) return 'Network is paused. Please try again later.';
  if (msg.includes('501')) return 'Only the room creator can close this room.';
  if (msg.includes('502')) return 'Room not found.';
  if (msg.includes('503')) return 'Room is already closed.';
  if (msg.includes('504')) return 'Invalid relay mode selected.';
  if (msg.includes('506')) return 'You must register before creating a room.';
  if (msg.includes('User rejected')) return 'Transaction was rejected in your wallet.';
  return 'Transaction failed. Please try again.';
}
```

### 4. Room Status Polling — `useRoomStatus` (Task 4)

**Purpose**: Poll the on-chain `RoomManager.rooms` Table for a specific room's status, updating every 5 seconds.

**Strategy — Two Approaches (Primary + Fallback)**:

**Primary approach — `getDynamicFieldObject`**:
```typescript
export function useRoomStatus(roomId: string | undefined): UseRoomStatusReturn {
  const client = useSuiClient();

  // Step 1: Read RoomManager to get Table UID
  // getObject(CONFIG.ROOM_MANAGER_ID, { showContent: true })
  // → content.fields.rooms  → this is the Table object's ID string

  // Step 2: Read dynamic field for the specific room
  // client.getDynamicFieldObject({
  //   parentId: roomsTableId,
  //   name: { type: `${CONFIG.PACKAGE_ID}::object::ID`, value: roomId },
  //   //  ^^^ The exact type tag for sui::object::ID needs verification.
  //   //  It may be '0x2::object::ID' since it's from the Sui framework.
  // })
  //
  // The response contains the RoomInfo struct fields.

  // Wrap in useSuiClientQuery with refetchInterval: CONFIG_ROOM_POLL_INTERVAL (5000ms)
}
```

**Key detail — Table dynamic field key type for `ID`**:
Sui Move `Table<ID, RoomInfo>` uses `ID` as the key. When stored as a dynamic field, the
name type is `0x2::object::ID`. The `getDynamicFieldObject` call needs:
```typescript
{
  parentId: roomsTableUid,  // The UID inside the Table struct (not the RoomManager ID)
  name: {
    type: '0x2::object::ID',
    value: roomId,
  },
}
```

**Fallback approach — `devInspectTransactionBlock`**:
```typescript
const tx = new Transaction();
tx.moveCall({
  target: `${CONFIG.PACKAGE_ID}::room_manager::borrow_room`,
  arguments: [
    tx.object(CONFIG.ROOM_MANAGER_ID),
    tx.pure.id(roomId),
  ],
});
const result = await client.devInspectTransactionBlock({
  transactionBlock: tx,
  sender: '0x0', // any address works for read-only inspection
});
// Parse RoomInfo fields from result.results[0].returnValues
// BCS decode: creator (address), status (u8), relay_mode (u8),
//             created_at (u64), closed_at (u64)
```

**devInspect is the recommended approach** for Phase 8 because:
1. It avoids the complexity of discovering the Table's inner UID
2. It directly calls the existing read accessor functions
3. It is read-only and gas-free
4. BCS decoding of the return value is straightforward with `@mysten/bcs`

**Status code mapping**:
```typescript
const STATUS_MAP: Record<number, string> = {
  0: 'Pending',
  1: 'Ready',
  2: 'Active',
  3: 'Closed',
};
```

**Polling configuration**: Add to `config.ts`:
```typescript
ROOM_POLL_INTERVAL: Number(import.meta.env.VITE_ROOM_POLL_INTERVAL ?? '5000'),
```

### 5. Network Pause Guard — `useNetworkPause` (Task 5)

**Purpose**: Read the `NetworkRegistry.paused` boolean field. Block all write operations when paused.

**Strategy — `getObject` with content parsing** (simplest approach):
```typescript
export function useNetworkPause(): UseNetworkPauseReturn {
  // NetworkRegistry is a simple shared object (no Table lookup needed).
  // Read it directly via getObject with showContent: true.

  const { data, isLoading, error } = useSuiClientQuery('getObject', {
    id: CONFIG.NETWORK_REGISTRY_ID,
    options: { showContent: true },
  }, {
    refetchInterval: 30_000, // 30s — pause changes are rare
  });

  const isPaused = useMemo(() => {
    if (!data?.data?.content) return false;
    const fields = (data.data.content as { fields: Record<string, unknown> }).fields;
    return fields.paused === true;
  }, [data]);

  return { isPaused, isLoading, error: error ?? null };
}
```

**Why `getObject` works here**: `NetworkRegistry` is a regular shared object with `paused` as a
top-level field. Unlike `Table` entries (which are dynamic fields on a nested UID), `paused`
is directly accessible in `content.fields` after a `getObject` call with `showContent: true`.

**Integration with write operations**:
```typescript
// In useChain.ts — guard pattern:
const { isPaused } = useNetworkPause();

const createRoom = useCallback(async () => {
  if (isPaused) {
    // Return early — the on-chain TX would abort with E_PAUSED anyway,
    // but we prevent the wallet popup entirely for better UX.
    throw new Error('Network is paused');
  }
  // ... existing TX logic
}, [isPaused, signAndExecute]);
```

**PauseBanner component**: Renders a full-width warning bar at the top of the page:
```
[!] Network is paused — all write operations are temporarily disabled.
```
Visible on all pages when `isPaused === true`. All TX-submitting buttons receive `disabled={isPaused}`.

### 6. Room Page Join Flow + Close Room (Task 6)

**RoomPage layout**:
```
/rooms/:roomId
┌─────────────────────────────────────────┐
│ Header (wallet connect)                 │
├─────────────────────────────────────────┤
│ PauseBanner (if paused)                 │
├─────────────────────────────────────────┤
│ Room: 0xabc123...                       │
│ Status: [Ready]  Mode: SFU             │
│ Creator: 0xdef456...                    │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │          Video Grid Area            │ │
│ │     (placeholder for Phase 9)       │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ [Close Room]  ← only if creator         │
│ Signaling: connected / disconnected     │
└─────────────────────────────────────────┘
```

**Close Room button visibility**:
```typescript
const account = useCurrentAccount();
const { creator } = useRoomStatus(roomId);
const isCreator = account?.address === creator;

// Only show Close Room button if current wallet is the room creator
{isCreator && status !== ROOM_STATUS.CLOSED && (
  <button disabled={isPaused || closeTxLoading} onClick={handleClose}>
    {closeTxLoading ? 'Closing...' : 'Close Room'}
  </button>
)}
```

**HomePage join flow**:
```typescript
// Paste-to-join input
const [joinId, setJoinId] = useState('');
const navigate = useNavigate();

<input value={joinId} onChange={e => setJoinId(e.target.value)} placeholder="Paste Room ID" />
<button onClick={() => navigate(`/rooms/${joinId}`)} disabled={!joinId}>Join</button>
```

**Shareable room URLs**: Opening `/rooms/0xabc123...` in any browser loads the RoomPage directly.
The `roomId` is read from `useParams()`. No server-side state needed.

### 7. Version Mismatch Fix (Task 7)

**Current state**: `@mysten/dapp-kit@^0.14.0` requires `@mysten/sui@^1.24.0` as a peer dependency,
but `package.json` has `@mysten/sui@^1.0.0`.

**Fix**: Update both packages to compatible latest versions:
```json
{
  "dependencies": {
    "@mysten/dapp-kit": "^0.14.0",
    "@mysten/sui": "^1.24.0"
  }
}
```

Run `npm install` and verify `tsc --strict` passes. The `@mysten/sui` v1.24+ may have
API changes from v1.0 — verify that `Transaction`, `getFullnodeUrl`, and
`useSignAndExecuteTransaction` still work. If dapp-kit v0.14 has issues, consider upgrading
to the latest dapp-kit that's compatible with the latest sui SDK.

---

## Sui SDK Query Patterns Reference

### Pattern A: Simple Object Read (for NetworkRegistry)
```typescript
// Read a shared object's top-level fields
const { data } = useSuiClientQuery('getObject', {
  id: CONFIG.NETWORK_REGISTRY_ID,
  options: { showContent: true },
});
// Access: data.data.content.fields.paused
```

### Pattern B: Table Entry via getDynamicFieldObject (for RoomManager.rooms, UserRegistry.users)
```typescript
// Step 1: Get the Table's inner UID from the parent object
const parent = await client.getObject({
  id: CONFIG.ROOM_MANAGER_ID,
  options: { showContent: true },
});
const roomsTableId = parent.data.content.fields.rooms; // Table UID string

// Step 2: Read a specific entry
const entry = await client.getDynamicFieldObject({
  parentId: roomsTableId,
  name: {
    type: '0x2::object::ID',
    value: roomId,
  },
});
// Access: entry.data.content.fields.value → RoomInfo fields
```

### Pattern C: devInspectTransactionBlock (fallback for complex reads)
```typescript
// Call a read-only Move function without gas
const tx = new Transaction();
tx.moveCall({
  target: `${PACKAGE_ID}::room_manager::borrow_room`,
  arguments: [tx.object(ROOM_MANAGER_ID), tx.pure.id(roomId)],
});
const result = await client.devInspectTransactionBlock({
  transactionBlock: tx,
  sender: '0x0',
});
// BCS-decode result.results[0].returnValues
```

### Recommended Pattern per Hook

| Hook              | Primary Pattern | Fallback   | Reason                                              |
|-------------------|-----------------|------------|-----------------------------------------------------|
| useNetworkPause   | Pattern A       | —          | `paused` is a top-level field, no Table lookup      |
| useRegistration   | Pattern B       | Pattern C  | Table<address, UserProfile>; address key may not work with getDynamicFieldObject |
| useRoomStatus     | Pattern B       | Pattern C  | Table<ID, RoomInfo>; ID key should work             |

**Implementation note**: Start with Pattern C (devInspect) for both `useRegistration` and
`useRoomStatus` in the initial implementation. Pattern C is guaranteed to work because it
calls the existing Move accessors directly. Optimize to Pattern B in a follow-up if
`getDynamicFieldObject` is verified to work with the respective key types.

---

## Integration Contracts (Phase 9 interfaces)

Phase 9 will wire up WebRTC session join/leave. Phase 8 must expose these interfaces for
Phase 9 to consume without modifying Phase 8 files:

### IC-1: RoomPage provides roomId and status to child components
```typescript
// Phase 9 will render <VideoSession roomId={roomId} /> inside RoomPage
// when status === ROOM_STATUS.ACTIVE
// RoomPage already has roomId from useParams() and status from useRoomStatus()
```

### IC-2: useChain exposes signAndExecute indirectly
Phase 9 may need additional chain operations (e.g., if relay assignment becomes an on-chain
TX). The `useChain` hook's `signAndExecute` is not directly exposed, but new methods can be
added to `useChain` without breaking existing consumers.

### IC-3: useNetworkPause is globally available
Any new component in Phase 9 can call `useNetworkPause()` to check the pause state. No
prop drilling needed — the hook reads directly from SuiClientProvider.

### IC-4: Config object IDs are centralized
All object IDs are in `config.ts`. Phase 9 components that need relay registry IDs or other
object IDs should add new VITE env vars to config.ts following the existing pattern.

### IC-5: VideoGrid remains unchanged
The existing `VideoGrid` component accepts `localStream` and `remoteStream` props. Phase 9
will replace the placeholder in RoomPage with the actual `VideoGrid` wired to
`useWebRTC` + `useSignaling`. The existing hooks (`useWebRTC`, `useSignaling`) are untouched
in Phase 8.

---

## File Inventory

### New Files
| File | Purpose |
|------|---------|
| `src/pages/HomePage.tsx` | Lobby: create room, join-by-paste, registration prompt |
| `src/pages/RoomPage.tsx` | Room view: status badge, close button, video placeholder |
| `src/components/Header.tsx` | Persistent header with ConnectButton |
| `src/components/RegistrationPrompt.tsx` | Display name input + register TX button |
| `src/components/PauseBanner.tsx` | Warning bar when network is paused |
| `src/components/RoomStatusBadge.tsx` | Colored badge showing room status label |
| `src/hooks/useRegistration.ts` | Check UserRegistry + expose register() |
| `src/hooks/useRoomStatus.ts` | Poll RoomManager for room info |
| `src/hooks/useNetworkPause.ts` | Read NetworkRegistry.paused |
| `src/utils/txErrors.ts` | Map on-chain abort codes to user-friendly messages |
| `src/constants.ts` | ROOM_STATUS, RELAY_MODE, status label maps |

### Modified Files
| File | Changes |
|------|---------|
| `src/main.tsx` | Wrap App in `<BrowserRouter>` |
| `src/App.tsx` | Replace monolithic layout with router shell, add Header/PauseBanner/RegistrationGate |
| `src/hooks/useChain.ts` | Add `closeRoom()`, add pause guard, improve error messages |
| `src/config.ts` | Add `ROOM_POLL_INTERVAL` config |
| `package.json` | Add `react-router-dom`, fix `@mysten/sui` version |

### Removed Files
| File | Reason |
|------|--------|
| `src/components/WalletConnect.tsx` | Replaced by `Header.tsx` with ConnectButton |
| `src/components/RoomControls.tsx` | Logic split into `HomePage` and `RoomPage` |

---

## Risks and Alternatives Considered

### Risk 1: Table Dynamic Field Key Type Compatibility
**Risk**: `getDynamicFieldObject` may not accept `address` as a dynamic field name type, or
the Sui SDK may serialize the `ID` type tag differently than expected.
**Mitigation**: Use `devInspectTransactionBlock` (Pattern C) as the primary approach for
Phase 8. This calls the Move read accessors directly and is guaranteed to work. Optimize to
`getDynamicFieldObject` (Pattern B) in a follow-up after manual verification on testnet.
**Severity**: MEDIUM — affects read performance (devInspect is slightly slower than direct
object reads) but is functionally correct.

### Risk 2: @mysten/sui Version Upgrade Breaking Changes
**Risk**: Upgrading from `@mysten/sui@1.0` to `@mysten/sui@1.24+` may introduce breaking
API changes (renamed methods, changed type signatures).
**Mitigation**: Task 7 is independent and runs in Wave 1. If the upgrade causes issues, the
exact compatible version pair can be pinned. The existing `useChain.ts` uses standard APIs
(`Transaction`, `useSignAndExecuteTransaction`) that are stable across minor versions.
**Severity**: LOW — version alignment is routine; dapp-kit documents compatible sui versions.

### Risk 3: Polling Frequency vs RPC Rate Limits
**Risk**: `useRoomStatus` polls every 5 seconds. If many rooms are open simultaneously
(multiple tabs), this could hit Sui RPC rate limits.
**Mitigation**: (1) Use `staleTime` in React Query to deduplicate identical queries.
(2) Only poll when the room page is active (stop polling on navigation away via hook cleanup).
(3) The 5s interval is configurable via `VITE_ROOM_POLL_INTERVAL`.
**Severity**: LOW — single-user thesis demo; rate limits are unlikely to be hit.

### Risk 4: Registration State Stale After Wallet Switch
**Risk**: User switches wallets in dapp-kit. The old registration state may persist briefly.
**Mitigation**: `useRegistration` uses `account.address` as a query key dependency. When the
address changes, React Query automatically invalidates and re-fetches. The registration
prompt re-appears for unregistered wallets.
**Severity**: LOW — standard React Query behavior handles this.

### Alternative Considered: WebSocket-Based Room Status Updates
**Considered**: Instead of polling the chain every 5s, subscribe to room status changes via
the signaling WebSocket (which could relay chain events).
**Rejected**: This would (1) require signaling server changes (out of scope for Phase 8),
(2) introduce a dependency on the signaling server being connected for status updates, and
(3) violate the "chain as source of truth" principle from FE_AGENT_SKILL.md. Polling the
chain directly is simpler and correct.

### Alternative Considered: React Context for Pause State
**Considered**: Create a `PauseContext` provider and consume it via `useContext` instead of
calling `useNetworkPause()` in each component.
**Rejected**: `useNetworkPause()` internally uses `useSuiClientQuery`, which already
deduplicates requests via React Query's cache. Adding a context layer would be redundant
abstraction. Each component calling `useNetworkPause()` gets the same cached data without
extra re-renders. If performance becomes an issue, a context wrapper can be added later
without changing the hook API.
