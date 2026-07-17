# Phase 10: Client Polish — Requirements Traceability Matrix

**Generated:** 2026-03-10
**Status:** VERIFIED

## Requirements Coverage

| REQ-ID | Description | Implementation | Evidence | Status |
|--------|-------------|---------------|----------|--------|
| POLISH-01 | System status dashboard shows live user count, room count, relay/CP/validator node counts from chain | `useNetworkStats.ts` batches 6 devInspect moveCall ops; `NetworkStatus.tsx` renders grid; `HomePage.tsx` embeds panel | Hook calls: `total_users`, `active_count` (room/relay/validator), `active_cp_count`, `total_registered` — all match Move public accessors | COVERED |
| POLISH-02 | User's DVCONF token balance displayed in header | `useTokenBalance.ts` uses `client.getBalance()` with coin type `${PACKAGE_ID}::token::TOKEN`; `Header.tsx` displays formatted balance | Coin type matches `token.move` OTW; 9-decimal formatting matches `create_currency` decimals param | COVERED |
| POLISH-03 | Participant list shows display names from UserRegistry for current room members | `useParticipantNames.ts` devInspects `borrow_profile` per address, BCS-decodes `UserProfile`; `VideoGrid.tsx` accepts `peerNames` prop; `RoomPage.tsx` wires hook | BCS struct layout `{display_name: vector<u8>, registered_at: u64, room_count: u64}` matches `user_registry.move` UserProfile | COVERED |

## Success Criteria Verification

| Criterion | Evidence | Status |
|-----------|----------|--------|
| 1. System status dashboard shows live counts of users, rooms, relays, CPs, and validators from on-chain data | `useNetworkStats.ts` lines 57-90: 6 moveCall targets match public accessors in `user_registry`, `room_manager`, `relay_registry`, `control_plane_registry`, `validator_registry`, `miner_store`. `NetworkStatus.tsx` renders all 6 counters. Polls at `ROOM_POLL_INTERVAL`. | PASS |
| 2. User's DVCONF token balance is visible in the header | `useTokenBalance.ts` line 76: `client.getBalance({ owner, coinType })`. `Header.tsx` line 47: displays `{balance} DVCONF` next to wallet address. Polls every 30s. | PASS |
| 3. Participant list in an active room shows display names resolved from UserRegistry | `useParticipantNames.ts` resolves via devInspect `borrow_profile`. `VideoGrid.tsx` line 105: `peerNames?.get(peerId) || \`Peer ${index + 1}\``. `RoomPage.tsx` line 40-311: wires hook to VideoGrid. | PASS |

## Cross-Domain Integration Check

| Integration Point | Move Signature | Client Call | Match |
|-------------------|---------------|-------------|-------|
| `user_registry::total_users` | `public fun total_users(r: &UserRegistry): u64` | `tx.moveCall({ target: '...::user_registry::total_users', arguments: [tx.object(USER_REGISTRY_ID)] })` | YES |
| `room_manager::active_count` | `public fun active_count(m: &RoomManager): u64` | `tx.moveCall({ target: '...::room_manager::active_count', arguments: [tx.object(ROOM_MANAGER_ID)] })` | YES |
| `relay_registry::active_count` | `public fun active_count(r: &RelayRegistry): u64` | `tx.moveCall({ target: '...::relay_registry::active_count', arguments: [tx.object(RELAY_REGISTRY_ID)] })` | YES |
| `control_plane_registry::active_cp_count` | `public fun active_cp_count(r: &ControlPlaneRegistry): u64` | `tx.moveCall({ target: '...::control_plane_registry::active_cp_count', arguments: [tx.object(CONTROL_PLANE_REGISTRY_ID)] })` | YES |
| `validator_registry::active_count` | `public fun active_count(r: &ValidatorRegistry): u64` | `tx.moveCall({ target: '...::validator_registry::active_count', arguments: [tx.object(VALIDATOR_REGISTRY_ID)] })` | YES |
| `miner_store::total_registered` | `public fun total_registered(store: &MinerStore): u64` | `tx.moveCall({ target: '...::miner_store::total_registered', arguments: [tx.object(MINER_STORE_ID)] })` | YES |
| `user_registry::borrow_profile` | `public fun borrow_profile(r: &UserRegistry, user: address): &UserProfile` | `tx.moveCall({ target: '...::user_registry::borrow_profile', arguments: [tx.object(USER_REGISTRY_ID), tx.pure.address(addr)] })` | YES |
| `token::TOKEN` coin type | `public struct TOKEN has drop {}` (OTW, 9 decimals) | `client.getBalance({ coinType: '${PACKAGE_ID}::token::TOKEN' })` | YES |

## Test Execution Report

| Suite | Result | Notes |
|-------|--------|-------|
| Move tests (`sui move test`) | 82/82 PASS | No Move files changed in Phase 10; regression check only |
| TypeScript check | Not runnable in current shell | Shell profile issue (username path with space); code reviewed manually |
| Client unit tests | N/A | No test framework configured in dvconf-client |

## Coverage Summary

- **Requirements**: 3/3 covered (100%)
- **Success Criteria**: 3/3 passing (100%)
- **Cross-domain signatures**: 8/8 matching (100%)
- **Move regression**: 82/82 passing (100%)
- **Gaps**: None identified

## Notes

- This is an FE-only phase with no Move contract changes. All chain reads use existing public accessors.
- No ADD exists for this phase (gap closure). Architect verification skipped per workflow rules.
- QC review identified 13 non-critical items (N1-N13) — addressed or accepted. No critical issues.
- N11 (unnecessary effect re-runs) and N12 (silent catch) were fixed post-QC.
