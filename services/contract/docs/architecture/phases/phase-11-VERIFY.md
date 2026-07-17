# PHASE ARCHITECTURE VERIFICATION -- Phase 11: Signaling Node Registry

Date: 2026-03-12
ADD reference: docs/architecture/phases/phase-11-ADD.md
Reviewer: Architect Agent

---

## BLUEPRINT vs AS-BUILT

### signaling_registry.move (OnChain, NEW)

  Boundary:     MATCH -- Module tracks registered signaling nodes, heartbeats, load, and provides vector-returning accessor for client discovery.
  Dependencies: MATCH -- Imports constants, network_registry (AdminCap, is_paused), caps (MinerCap), staking (StakePosition). All as specified.
  Visibility:   MATCH -- All entry functions are `public`; constructor gated by AdminCap.
  Verdict:      **CONFORMS**

  Function signature verification against ADD COMPLETE FUNCTION SIGNATURES:
  - `create(_: &AdminCap, ctx: &mut TxContext)` -- MATCH
  - `register_signaling(net_reg, registry, cap, stake, endpoint_url, region, ctx)` -- MATCH
  - `heartbeat(net_reg, registry, cap, ctx)` -- MATCH
  - `update_load(net_reg, registry, cap, new_load, ctx)` -- MATCH
  - `unregister_signaling(registry, cap, ctx)` -- MATCH
  - `active_signaling_count(r)` -- MATCH
  - `is_registered(r, miner_id)` -- MATCH
  - `borrow_info(r, miner_id)` -- MATCH
  - `get_active_nodes(registry)` -- MATCH (IMP-1 implemented)
  - All 9 `info_*` field accessors -- MATCH
  - `init_for_testing(ctx)` -- MATCH

  Struct fields (SignalingNodeInfo): operator, miner_id, stake_amount, last_heartbeat, is_active, endpoint_url, region, load, registered_at -- MATCH (order and types correct)

  Error codes: E_NOT_SIGNALING=600, E_ALREADY_REGISTERED=601, E_NOT_REGISTERED=602, E_PAUSED=603, E_NOT_OPERATOR=604 -- MATCH

  Events: SignalingRegistered, SignalingHeartbeat, SignalingLoadUpdated, SignalingUnregistered -- MATCH (field names and types correct per IC-4)

### constants.move (OnChain, MODIFIED)

  Boundary:     MATCH -- ROLE_SIGNALING = 4 added, DEFAULT_SIGNALING_THRESHOLD = 250_000_000 added.
  Dependencies: MATCH -- No dependencies (leaf module).
  Visibility:   MATCH -- Public accessors `role_signaling()` and `default_signaling_threshold()` present.
  Verdict:      **CONFORMS**

### network_registry.move (OnChain, MODIFIED)

  Boundary:     MATCH -- RoleThresholds struct has `signaling_threshold: u64` as 4th field.
  Dependencies: MATCH -- Depends on constants only.
  Visibility:   MATCH -- `signaling_threshold(t)` accessor present. `update_role_thresholds` accepts 4 params (cp, relay, validator, signaling) with ordering constraint `validator >= signaling`.
  Verdict:      **CONFORMS**

### staking.move (OnChain, MODIFIED)

  Boundary:     MATCH -- `determine_role()` includes signaling tier: `stake >= signaling_threshold -> role_signaling()`, placed between validator and user tiers. `minimum_for_role()` handles signaling case.
  Dependencies: MATCH -- Depends on network_registry (thresholds), miner_store (role constants).
  Visibility:   MATCH -- Public functions unchanged.
  Verdict:      **CONFORMS**

### miner_store.move (OnChain, MODIFIED)

  Boundary:     MATCH -- `signaling_miners: VecSet<ID>` field added to MinerStore (IMP-2). `role_signaling()` accessor present. `signaling_count()` accessor present. `add_to_role_set` and `remove_from_role_set` handle signaling role.
  Dependencies: MATCH -- Depends on constants.
  Visibility:   MATCH -- `signaling_count()` is public, `role_signaling()` is public.
  Verdict:      **CONFORMS**

### auto-register.ts (OffChain, NEW)

  Boundary:     MATCH -- Two-step registration: (1) register miner, (2) register in SignalingRegistry. Exports `ensureRegistered()`.
  Dependencies: MATCH -- Uses @dvconf/shared (NetworkConfig, executeWithRetry, extractCreatedObjectByType, Logger), @mysten/sui.
  Verdict:      **CONFORMS**

  IC-1 verification:
  - `register_signaling` moveCall arguments match ADD exactly: networkRegistryId, signalingRegistryId, minerCapId, stakePositionId, endpoint_url (vector<u8>), region (vector<u8>). -- MATCH
  - MINER_CAP_ID skip logic with devInspect verification (ADD Q3 resolution) -- MATCH
  - Hardcoded stake 250_000_000n (ADD Q4 resolution) -- MATCH

### heartbeat.ts (OffChain, NEW)

  Boundary:     MATCH -- Combined heartbeat + load PTB (IMP-3). Exports `startHeartbeat()`, `buildHeartbeatTx()`, `buildUpdateLoadTx()`.
  Dependencies: MATCH -- Uses @dvconf/shared (NetworkConfig, executeWithRetry, Logger), @mysten/sui, rooms.ts (RoomManager).
  Verdict:      **CONFORMS**

  IC-2 verification:
  - heartbeat moveCall: networkRegistryId, signalingRegistryId, minerCapId -- MATCH
  - update_load moveCall: networkRegistryId, signalingRegistryId, minerCapId, currentLoad (u64) -- MATCH
  - Both calls in same PTB via `buildHeartbeatTx` + `buildUpdateLoadTx` on same Transaction -- MATCH
  - Load source: `roomManager.getStats().connections` (per ADD Q4) -- MATCH

### index.ts (OffChain, MODIFIED)

  Boundary:     MATCH -- Chain bootstrap: loadNetworkConfig, createSuiClient, loadKeypair, then ensureRegistered + createServer + startHeartbeat.
  Dependencies: MATCH -- Uses @dvconf/shared, auto-register.ts, heartbeat.ts, rooms.ts.
  Verdict:      **CONFORMS**

### useSignalingDiscovery.ts (FE, NEW)

  Boundary:     MATCH -- Discovers best signaling node via devInspect `get_active_nodes()`, BCS-decodes SignalingNodeInfo, scores by region/load, falls back to CONFIG.SIGNALING_URL.
  Dependencies: MATCH -- Uses @mysten/dapp-kit (useSuiClient), @mysten/sui (Transaction, bcs), config.ts.
  Verdict:      **CONFORMS**

  IC-3 verification:
  - devInspect call target: `${PACKAGE_ID}::signaling_registry::get_active_nodes` with SignalingRegistryId -- MATCH
  - BCS struct layout matches Move struct field order exactly -- MATCH
  - Fallback to CONFIG.SIGNALING_URL on failure/empty -- MATCH
  - Polling at CONFIG.DISCOVERY_POLL_INTERVAL (default 60s) -- MATCH

### useSignaling.ts (FE, MODIFIED)

  Boundary:     MATCH -- Accepts `signalingUrl: string` param (from discovery). Implements IMP-4: URL locked at connect() time via `lockedUrlRef`.
  Dependencies: MATCH -- React hooks only.
  Verdict:      **CONFORMS**

  IMP-4 verification:
  - `latestUrlRef.current` updated on every render (tracks discovery) -- MATCH
  - `lockedUrlRef.current` set once in `connect()` -- MATCH
  - disconnect clears `lockedUrlRef` -- MATCH
  - Active session never disrupted by URL change -- MATCH

### config.ts (FE, MODIFIED)

  Boundary:     MATCH -- Added SIGNALING_REGISTRY_ID, SIGNALING_URL, CLIENT_REGION, DISCOVERY_POLL_INTERVAL.
  Dependencies: MATCH -- Vite env vars only.
  Verdict:      **CONFORMS**

---

## INTEGRATION CONTRACTS VERIFICATION

### IC-1: OnChain signaling_registry <-> OffChain auto-register.ts
  Status: **CONFORMS**
  - All 6 arguments to `register_signaling` match between Move function signature and TypeScript moveCall.
  - Error codes 600, 601, 603 are the relevant abort codes. TypeScript does not explicitly handle them (uses executeWithRetry generic error handling), which is acceptable.

### IC-2: OnChain signaling_registry <-> OffChain heartbeat.ts
  Status: **CONFORMS**
  - heartbeat: 3 arguments match (networkRegistryId, signalingRegistryId, minerCapId).
  - update_load: 4 arguments match (+ new_load as u64).
  - Combined PTB confirmed: both calls on the same Transaction object.

### IC-3: OnChain signaling_registry <-> FE useSignalingDiscovery.ts
  Status: **CONFORMS**
  - devInspect target and argument match.
  - BCS struct field order matches Move struct field order exactly (operator, miner_id, stake_amount, last_heartbeat, is_active, endpoint_url, region, load, registered_at).
  - Fallback to CONFIG.SIGNALING_URL on error/empty.

### IC-4: OnChain events <-> OffChain shared types
  Status: **CONFORMS** (verified structurally)
  - Move event structs have correct field names and types.
  - TypeScript shared type interfaces are consumed by the daemon and would be verified at compile time.

### IC-5: Error code alignment
  Status: **CONFORMS**
  - On-chain: E_NOT_SIGNALING=600, E_ALREADY_REGISTERED=601, E_NOT_REGISTERED=602, E_PAUSED=603, E_NOT_OPERATOR=604.
  - All match the ADD specification exactly.

---

## ARCHITECT IMPROVEMENTS VERIFICATION

### IMP-1: get_active_nodes() accessor
  Status: **CONFORMS**
  - Implemented in signaling_registry.move lines 219-232.
  - Iterates VecSet<ID> keys, looks up each in Table, returns vector<SignalingNodeInfo>.
  - O(n) as specified. Used by FE useSignalingDiscovery via devInspect.

### IMP-2: signaling_miners VecSet in MinerStore
  Status: **CONFORMS**
  - Field `signaling_miners: VecSet<ID>` added to MinerStore (line 54).
  - Initialized to empty in `init()` (line 66).
  - `add_to_role_set` and `remove_from_role_set` handle `role_signaling()` (lines 242, 250).
  - `signaling_count()` accessor present (line 224).
  - `role_signaling()` accessor present (line 232).

### IMP-3: Combined heartbeat+load PTB
  Status: **CONFORMS**
  - heartbeat.ts `startHeartbeat()` builds both `buildHeartbeatTx` and `buildUpdateLoadTx` on the same Transaction object (lines 87-89).
  - Single executeWithRetry call wraps both.

### IMP-4: URL locked at connect() time
  Status: **CONFORMS**
  - useSignaling.ts uses `lockedUrlRef` (line 24) set in `connect()` (lines 42-44).
  - `latestUrlRef` tracks discovery updates without disrupting active session.
  - `disconnect()` clears the lock (line 111).

---

## DEVIATIONS

No deviations found. All implementations match the ADD specification.

---

## TECH DEBT ITEMS FROM ADD -- STATUS CHECK

### TD-P11-01: MinerStore struct change requires re-publish
  Status: **STILL VALID** -- `signaling_miners` field added. Re-publish required for localnet/testnet.

### TD-P11-02: RoleThresholds struct change requires re-publish
  Status: **STILL VALID** -- `signaling_threshold` field added. Re-publish required for localnet/testnet.

### TD-P11-03: Hardcoded stake threshold in auto-register.ts
  Status: **STILL VALID** -- `SIGNALING_STAKE = 250_000_000n` hardcoded at line 18. Should query at runtime for production.

### TD-P11-04: No cross-registry cleanup on unregister
  Status: **STILL VALID** -- `registration::unregister()` does not trigger `signaling_registry::unregister_signaling()`. Stale entries rely on heartbeat timeout for liveness detection.

### TD-P11-05: Region strings are free-form, no validation
  Status: **STILL VALID** -- Region is stored as `vector<u8>` with no on-chain validation. Relies on documented canonical list and operator compliance.

---

## NEW TECH DEBT INTRODUCED

None discovered. Implementation is clean and matches the ADD precisely.

---

## ARCHITECTURE HEALTH TREND

  Phase 10: 8/10
  Phase 11: 8/10
  Direction: STABLE

  Coupling:    8/10 -- Clean boundaries; signaling_registry follows established registry pattern
  Cohesion:    9/10 -- Each module has a single clear responsibility
  Testability: 8/10 -- init_for_testing provided; daemon functions are modular and testable
  Consistency: 9/10 -- Naming, error codes, and patterns match existing registries exactly

---

## CROSS-PHASE INTEGRATION

  - Phase 3 (Registration/Staking) -> Phase 11: CLEAN
    - staking.move `determine_role()` and `minimum_for_role()` correctly integrate signaling tier
    - miner_store.move role sets correctly include signaling
    - network_registry.move thresholds correctly include signaling

  - Phase 7 (Relay Registry) -> Phase 11: CLEAN
    - signaling_registry follows the exact same pattern as relay_registry
    - No coupling between the two registries

  - Phase 9 (CP Daemon) -> Phase 11: CLEAN
    - Signaling daemon follows the same auto-register + heartbeat pattern as CP daemon
    - Uses the same @dvconf/shared utilities (executeWithRetry, loadNetworkConfig, etc.)

  Issues: NONE

---

## VERIFICATION VERDICT: **CONFORMS**

All modules match the ADD specification exactly. All integration contracts are correctly implemented. All architect improvements (IMP-1 through IMP-4) are present and functional. No deviations, no drift. The five tech debt items from the ADD remain valid and are tracked in the tech debt registry.
