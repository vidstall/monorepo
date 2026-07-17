# Phase 11 Plan: Signaling Node Registry
Date: 2026-03-11

## Goal
Signaling nodes register on-chain with stake, send heartbeats, and clients discover them from the registry instead of hardcoded URLs.

## Success Criteria
1. Signaling node registers on-chain with stake via new SignalingRegistry module
2. Registered signaling node sends periodic heartbeats to maintain active status
3. Client discovers available signaling nodes from on-chain registry (no hardcoded URL)
4. Client selects signaling node using region/load scoring

> **Note:** Success criteria 5 (rewards) and 6 (slashing) are deferred to Phase 13 per 11-CONTEXT.md.

## Requirements Covered
- **SIG-01**: Signaling node registers on-chain with stake (new SignalingRegistry module)
- **SIG-02**: Signaling node sends periodic heartbeat to maintain active status
- **SIG-03**: Client discovers available signaling nodes from on-chain registry (no hardcoded URL)
- **SIG-04**: Client selects signaling node by region/load scoring
- **BUG-RR-01**: relay_registry `update_load()` missing operator ownership check (found in code review)
- **BUG-RR-02**: relay_registry `update_mode()` missing operator ownership check (found in code review)

## Tasks

### Task 1: Add signaling role constant and threshold
- **Agent**: OnChain
- **Files**:
  - `sources/core/constants.move` — add `ROLE_SIGNALING = 4`, `DEFAULT_SIGNALING_THRESHOLD = 250_000_000`
  - `sources/core/network_registry.move` — add `signaling_threshold` to `RoleThresholds`, update `update_role_thresholds()` to accept 4th param, update `init()` and `init_for_testing()`
  - `sources/miner/staking.move` — add signaling tier to `determine_role()` and `minimum_for_role()`
  - `sources/miner/miner_store.move` — add `role_signaling()` accessor if needed
- **Requirements**: SIG-01 (partial — role system support)
- **Depends on**: None
- **Description**: Extend the role system to support signaling nodes. The new tier sits between User (0) and Validator (0.5 DVCONF) at 0.25 DVCONF. Role determination in `staking::determine_role()` must check signaling threshold BEFORE the existing user fallback. The `RoleThresholds` struct gets a 4th field `signaling_threshold`. `update_role_thresholds()` must enforce `cp >= relay >= validator >= signaling`. Registration already issues a `MinerCap` for non-CP roles, so signaling nodes will receive a `MinerCap` with `role = 4` automatically.

### Task 2: Create SignalingRegistry module
- **Agent**: OnChain
- **Files**:
  - `sources/registry/signaling_registry.move` — NEW file
- **Requirements**: SIG-01, SIG-02
- **Depends on**: Task 1
- **Description**: Create `signaling_registry.move` mirroring `control_plane_registry.move` pattern. Struct: `SignalingNodeInfo { operator, miner_id, stake_amount, last_heartbeat, is_active, endpoint_url: vector<u8>, region: vector<u8>, load: u64, registered_at }`. Error codes 600-609. Functions:
  - `create(&AdminCap, ctx)` — AdminCap-gated constructor (shared object)
  - `register_signaling(&NetworkRegistry, &mut SignalingRegistry, &MinerCap, &StakePosition, endpoint_url, region, ctx)` — pause check, role check (`ROLE_SIGNALING`), duplicate check, emits `SignalingRegistered`
  - `heartbeat(&NetworkRegistry, &mut SignalingRegistry, &MinerCap, ctx)` — pause check, updates `last_heartbeat`, emits `SignalingHeartbeat`
  - `update_load(&NetworkRegistry, &mut SignalingRegistry, &MinerCap, new_load, ctx)` — pause check, ownership check via MinerCap, emits `SignalingLoadUpdated`
  - `unregister_signaling(&mut SignalingRegistry, &MinerCap, ctx)` — removes from table, emits `SignalingUnregistered`
  - Read accessors: `active_signaling_count()`, `is_registered()`, `borrow_info()`, field accessors
  - `init_for_testing(ctx)` for tests
  - Events: `SignalingRegistered`, `SignalingHeartbeat`, `SignalingLoadUpdated`, `SignalingUnregistered`

### Task 3: Write SignalingRegistry tests
- **Agent**: OnChain
- **Files**:
  - `tests/registry/signaling_registry_tests.move` — NEW file
  - `tests/helpers.move` — add `setup_phase3()` or extend `setup_phase2()` to create SignalingRegistry
- **Requirements**: SIG-01, SIG-02 (test coverage)
- **Depends on**: Task 2
- **Description**: Write tests following `control_plane_registry_tests.move` pattern:
  1. `test_register_signaling` — happy path registration
  2. `test_register_signaling_wrong_role` — abort 600 if not signaling role
  3. `test_register_signaling_duplicate` — abort 601
  4. `test_heartbeat` — updates last_heartbeat
  5. `test_heartbeat_not_registered` — abort 602
  6. `test_update_load` — updates load value
  7. `test_update_load_wrong_cap` — abort if cap doesn't match
  8. `test_unregister_signaling` — happy path
  9. `test_register_when_paused` — abort 603
  10. `test_signaling_role_determination` — stake 0.25 DVCONF gets ROLE_SIGNALING

### Task 4: Fix relay_registry ownership bugs
- **Agent**: OnChain
- **Files**:
  - `sources/registry/relay_registry.move` — add ownership checks to `update_load()` and `update_mode()`
  - `tests/registry/relay_registry_tests.move` — add tests for ownership violations
- **Requirements**: BUG-RR-01, BUG-RR-02
- **Depends on**: None (independent of Tasks 1-3)
- **Description**: Both `update_load()` and `update_mode()` accept a `&MinerCap` but don't verify `ctx.sender()` matches the registered operator. Fix: after the existing `E_NOT_REGISTERED` check, borrow the `RelayNodeInfo` and assert `info.operator == ctx.sender()` with error `E_NOT_OPERATOR (524)`. Add test cases: `test_update_load_wrong_operator` and `test_update_mode_wrong_operator` that register as one address and try to update as another — expect abort 524.

### Task 5: Update shared constants (off-chain)
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/packages/shared/src/types/constants.ts` — add `Signaling: 4` to `MinerRole`, add signaling error codes 600-609
  - `dvconf-daemons/packages/shared/src/types/events.ts` — add `SignalingRegistered`, `SignalingHeartbeat`, `SignalingLoadUpdated`, `SignalingUnregistered` event types
  - `dvconf-daemons/packages/shared/src/types/chain.ts` — add `signalingRegistryId` to `NetworkConfig` type (if not already)
- **Requirements**: SIG-01 (off-chain type sync)
- **Depends on**: Task 2 (needs final event/error code design)
- **Description**: Keep `@dvconf/shared` types in sync with the new on-chain module. Add signaling role, error code namespace, and event type definitions so the signaling daemon and client can use them.

### Task 6: Upgrade signaling daemon to chain-aware
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/signaling/src/auto-register.ts` — NEW file (follow cp-daemon pattern)
  - `dvconf-daemons/apps/signaling/src/heartbeat.ts` — NEW file (follow cp-daemon pattern)
  - `dvconf-daemons/apps/signaling/src/index.ts` — add chain startup (auto-register, heartbeat loop, load reporting)
  - `dvconf-daemons/apps/signaling/package.json` — add `@mysten/sui` dependency
- **Requirements**: SIG-01, SIG-02
- **Depends on**: Task 5
- **Description**: Upgrade the signaling daemon from stateless WebSocket server to chain-aware node:
  - `auto-register.ts`: Two-step registration (1) register as miner with 0.25 DVCONF stake, (2) register in SignalingRegistry with endpoint URL and region. Follow cp-daemon's `ensureRegistered()` pattern exactly. Check `MINER_CAP_ID` env var to skip if already registered.
  - `heartbeat.ts`: 30s interval loop calling `signaling_registry::heartbeat()` TX + `signaling_registry::update_load()` TX with current connection count from `roomManager.getStats().connections`.
  - `index.ts`: On startup, call `ensureRegistered()`, then start WebSocket server, then start heartbeat loop. On shutdown, clean up heartbeat interval.
  - New env vars: `SIGNALING_REGISTRY_ID`, `ENDPOINT_URL`, `REGION`, `MINER_CAP_ID` (optional)

### Task 7: Client signaling discovery hook
- **Agent**: FE
- **Files**:
  - `dvconf-client/src/hooks/useSignalingDiscovery.ts` — NEW file
  - `dvconf-client/src/config.ts` — add `SIGNALING_REGISTRY_ID` from `VITE_SIGNALING_REGISTRY_ID`
  - `dvconf-client/src/hooks/useSignaling.ts` — replace hardcoded `CONFIG.SIGNALING_URL` with dynamic discovery result
  - `dvconf-client/.env.example` — add `VITE_SIGNALING_REGISTRY_ID`
- **Requirements**: SIG-03, SIG-04
- **Depends on**: Task 2 (needs on-chain module deployed to query)
- **Description**: Create `useSignalingDiscovery` hook:
  - Query `SignalingRegistry` via devInspect to get active signaling nodes (endpoint_url, region, load)
  - Score nodes: `score = region_match_bonus + (1 / (load + 1))` — simple client-side scoring
  - Return `{ url: string, isFromChain: boolean }` — highest-scoring node's endpoint_url
  - Fallback: if no nodes registered or query fails, use `CONFIG.SIGNALING_URL` (from `VITE_SIGNALING_URL` env var), set `isFromChain: false`
  - Update `useSignaling.ts` to accept URL parameter instead of reading `CONFIG.SIGNALING_URL` directly
  - Follow `useNetworkStats.ts` pattern for devInspect calls

## Execution Order

```
Phase 1 (parallel):
  Task 1: Add signaling role (OnChain)  ─┐
  Task 4: Fix relay_registry bugs (OnChain) ─ independent, can run in parallel
                                            │
Phase 2 (sequential, after Task 1):        │
  Task 2: Create SignalingRegistry module  ←┘
                                            │
Phase 3 (sequential, after Task 2):        │
  Task 3: Write SignalingRegistry tests    ←┘
                                            │
Phase 4 (sequential, after Task 2):        │
  Task 5: Update shared constants (OffChain) ←┘
                                            │
Phase 5 (parallel, after Task 5):          │
  Task 6: Upgrade signaling daemon (OffChain) ←┘
  Task 7: Client signaling discovery (FE)  ←── depends on Task 2 only
```

**Summary:**
- Tasks 1 + 4 run in parallel (both OnChain but different files)
- Task 2 depends on Task 1
- Tasks 3, 5, 7 depend on Task 2
- Task 6 depends on Task 5
- Tasks 6 + 7 can run in parallel (different repos)

## Risks & Open Questions

1. **RoleThresholds struct change is breaking**: Adding `signaling_threshold` to `RoleThresholds` changes the struct layout. Since this is a package upgrade (not re-publish), existing data must be migrated. **Mitigation**: Since Phase 2 registries use `create(&AdminCap)` post-upgrade, the `init()` only runs at first publish. For upgrades, the `RoleThresholds` change requires a migration function or re-initialization of the `NetworkRegistry`. This needs careful handling — may need a governance TX to set the new threshold.

2. **Signaling daemon discovery on localnet**: devInspect queries in the client need the SignalingRegistry shared object to exist. During local dev, the deploy script (`run-local.ps1`) must be updated to call `signaling_registry::create()` and export the new object ID.

3. **MinerCap reuse**: Signaling nodes reuse `MinerCap` (not a new cap type). The `registration::register()` function issues `MinerCap` for all non-CP roles. Role=4 (Signaling) gets a `MinerCap` with role=4. This works because `signaling_registry::register_signaling()` checks `miner_cap_role(cap) == role_signaling()`. No changes needed to `caps.move`.

4. **No unregister from SignalingRegistry in registration::unregister()**: When a signaling miner calls `registration::unregister()`, it removes the miner profile from `MinerStore` but does NOT remove the SignalingRegistry entry. This is the same pattern as `control_plane_registry` — the registry entry becomes stale but the heartbeat timeout handles liveness. Acceptable for Phase 11.
