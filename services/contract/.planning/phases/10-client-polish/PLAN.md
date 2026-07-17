# Phase 10 Plan: Client Polish
Date: 2026-03-10

## Goal
The client surfaces network health and identity information that demonstrates the decentralized architecture in a thesis demo.

## Success Criteria
1. System status dashboard shows live counts of users, rooms, relays, CPs, and validators from on-chain data
2. User's DVCONF token balance is visible in the header
3. Participant list in an active room shows display names resolved from UserRegistry

## Requirements Covered
POLISH-01, POLISH-02, POLISH-03

## Tasks

### Task 1: Config + env vars for new shared objects
- **Agent**: FE
- **Files**:
  - Modify `src/config.ts` — add MINER_STORE_ID, RELAY_REGISTRY_ID, CONTROL_PLANE_REGISTRY_ID, VALIDATOR_REGISTRY_ID
  - Modify `.env.example` — add new VITE_ entries
- **Requirements**: (supports POLISH-01, POLISH-02)
- **Depends on**: None
- **Description**: Add the four new shared object IDs to the AppConfig interface and requireEnv calls. Update `.env.example` with placeholder entries. These IDs are needed by the dashboard stats hook and token balance hook.

### Task 2: Network status dashboard (useNetworkStats + NetworkStatus component)
- **Agent**: FE
- **Files**:
  - Create `src/hooks/useNetworkStats.ts` — polls registry counts via devInspect
  - Create `src/components/NetworkStatus.tsx` — card displaying labeled counters
  - Modify `src/pages/HomePage.tsx` — embed NetworkStatus below the lobby controls
- **Requirements**: POLISH-01
- **Depends on**: Task 1
- **Description**: Create a `useNetworkStats` hook that uses devInspect to call public read accessors on each shared object:
  - `user_registry::total_users(&UserRegistry)` → u64
  - `room_manager::active_count(&RoomManager)` → u64
  - `relay_registry::active_count(&RelayRegistry)` → u64
  - `control_plane_registry::active_cp_count(&ControlPlaneRegistry)` → u64
  - `validator_registry::active_count(&ValidatorRegistry)` → u64
  - `miner_store::total_registered(&MinerStore)` → u64

  Each call returns a BCS-encoded u64 (8 bytes, little-endian). Poll on a configurable interval (reuse ROOM_POLL_INTERVAL). The `NetworkStatus` component renders a grid of labeled stat cards. Embed it on HomePage below the join room section.

### Task 3: Token balance in header (useTokenBalance + Header update)
- **Agent**: FE
- **Files**:
  - Create `src/hooks/useTokenBalance.ts` — queries DVCONF token balance
  - Modify `src/components/Header.tsx` — display balance next to wallet address
- **Requirements**: POLISH-02
- **Depends on**: Task 1
- **Description**: Create a `useTokenBalance` hook that calls `client.getBalance({ owner: address, coinType: '${PACKAGE_ID}::token::TOKEN' })`. The DVCONF token has 9 decimal places. Format the balance as human-readable (e.g., "1,234.56 DVCONF" or "0 DVCONF" if none). Re-fetch when wallet address changes and on a polling interval. Update `Header.tsx` to show the balance between the truncated address and the ConnectButton.

### Task 4: Participant display names (useParticipantNames + VideoGrid update)
- **Agent**: FE
- **Files**:
  - Create `src/hooks/useParticipantNames.ts` — resolves peer addresses to display names
  - Modify `src/components/VideoGrid.tsx` — show display name on video tiles
- **Requirements**: POLISH-03
- **Depends on**: None (independent of Tasks 1-3)
- **Description**: Create a `useParticipantNames` hook that takes an array of peer addresses (from `remoteStreams` keys) and returns `Map<string, string>` (address → display name). For each address not yet cached, devInspect `user_registry::borrow_profile` and decode the `display_name` field (BCS vector<u8>). Cache results in state — only query once per address per session. Fallback to truncated address (`0x1234...abcd`) if unregistered or query fails. Update `VideoGrid` to accept an optional `peerNames` prop and use it in the VideoTile label instead of `Peer ${index + 1}`. The RoomPage passes names from the hook to VideoGrid.

## Execution Order

```
Task 1 (config)
  ├── Task 2 (dashboard) — depends on Task 1
  └── Task 3 (token balance) — depends on Task 1
Task 4 (participant names) — independent, can run in parallel with Tasks 1-3
```

Tasks 2 and 3 can run in parallel after Task 1 completes.
Task 4 has no dependency on the new config vars (uses existing USER_REGISTRY_ID).

## Risks & Open Questions

- **BCS decoding u64**: devInspect returns raw bytes. u64 is 8 bytes little-endian. The existing codebase decodes booleans (1 byte) and has BCS decode for room status. u64 decode is straightforward: `new DataView(bytes.buffer).getBigUint64(0, true)`.
- **borrow_profile returns a reference**: devInspect handles references transparently — the return value is serialized as if it were owned. The `display_name` field is `vector<u8>` which BCS-encodes as length-prefixed bytes. Need to decode ULEB128 length + raw bytes.
- **Token balance when no coins exist**: `getBalance` returns `{ totalBalance: '0' }` when the user has no DVCONF coins — no error handling needed, just show "0 DVCONF".
- **New env vars on localnet**: After local deploy, users must run the Phase 2 registry `create()` calls and capture the object IDs. The DEMO-GUIDE.md already documents this flow.
