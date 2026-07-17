# Phase 16 Plan: Security Hardening & Documentation
Date: 2026-03-16

## Goal
Fix all P0 security vulnerabilities and critical documentation gaps identified by the triple review (Documentation, Architecture, Security) before thesis defense. Include highest-impact P1 items that strengthen the thesis.

## Success Criteria
1. `staking::destroy()` aborts with `E_STAKE_LOCKED` if position is locked (test added)
2. `distribute_rewards()` requires `escrow.creator == ctx.sender()` (test added)
3. Duplicate `create_escrow()` for same room_id is prevented (test added)
4. Error code namespace in `ONCHAIN_AGENT_SKILL.md` matches actual code (510/520/530/540/600/650)
5. All broken references in `CLAUDE.md` are fixed
6. Both `dvconf-daemons` and `dvconf-client` have `README.md` files
7. WebSocket servers enforce `maxPayload` limits
8. All Move tests pass (`sui move test`)
9. QC APPROVED on all changes

## Requirements Covered
- SEC-001: Stake lock defense-in-depth
- SEC-002: Reward distribution access control
- SEC-009: Duplicate escrow prevention
- SEC-003: Overflow protection in reward calculation (P1)
- SEC-005/SEC-006: WebSocket hardening (P1)
- DOC-01 through DOC-08: Documentation fixes (P0)

## Tasks

### Task 1: On-chain security fixes (staking + economic_layer)
- **Agent**: OnChain
- **Files**:
  - `sources/miner/staking.move` — add `assert!(!position.locked, E_STAKE_LOCKED)` in `destroy()`
  - `sources/registry/economic_layer.move` — add `assert!(escrow.creator == ctx.sender(), E_NOT_ROOM_CREATOR)` in `distribute_rewards()`; add duplicate escrow guard in `create_escrow()` (requires tracking room_id → escrow existence)
  - `tests/registry/economic_layer_tests.move` — add 3 tests: locked destroy abort, ungated distribute abort, duplicate escrow abort
- **Requirements**: SEC-001, SEC-002, SEC-009
- **Depends on**: None
- **Description**:
  Three surgical security fixes:

  **SEC-001** (`staking.move:93-96`): `destroy()` destructures `locked: _` discarding the lock flag. Add:
  ```move
  assert!(!position.locked, E_STAKE_LOCKED);
  ```
  before the destructure. This is defense-in-depth — `registration::unregister` already checks, but any future caller would bypass it.

  **SEC-002** (`economic_layer.move:286`): `distribute_rewards()` has no caller check. Anyone can trigger distribution once min proofs are met, creating a timing attack. Add:
  ```move
  assert!(escrow.creator == ctx.sender(), E_NOT_ROOM_CREATOR);
  ```
  at the start of the function.

  **SEC-009**: `create_escrow()` can be called multiple times for the same room, creating orphaned escrow objects. Options: (a) add a `has_escrow` Table in economic_layer, or (b) check room status more strictly. Simplest: accept that multiple escrows per room are possible but only one can distribute (already guarded by `distributed` flag). If PM prefers prevention, add a `Table<ID, bool>` to a new shared config object. **Recommendation**: Document as known limitation — the `distributed` flag already prevents double-distribution, and orphaned escrow funds can be returned to creator. No code change needed unless PM insists.

  Add 3 test cases:
  1. `test_destroy_locked_position_aborts` — lock a position, call destroy, expect abort 201
  2. `test_distribute_rewards_non_creator_aborts` — call distribute_rewards from non-creator, expect abort 651
  3. `test_duplicate_escrow_is_harmless` — create two escrows for same room, verify only one can distribute

### Task 2: Overflow protection in reward calculation
- **Agent**: OnChain
- **Files**:
  - `sources/registry/economic_layer.move` — refactor `total_reward` calculation to use two-step division
  - `tests/registry/economic_layer_tests.move` — add overflow boundary test
- **Requirements**: SEC-003 (P1)
- **Depends on**: Task 1 (same files)
- **Description**:
  Current: `base_rate * median_bytes * quality_multiplier / bp` can overflow u64 if `median_bytes > 1.8 * 10^15`.

  Fix: Split into two divisions to keep intermediates small:
  ```move
  let step1 = base_rate * median_bytes / bp;
  let total_reward = step1 * quality_multiplier / bp;
  ```
  This changes the math slightly (integer division ordering) but keeps values within u64 for any practical session size.

  Add test with large `bytes_transferred` value (10^12) to verify no overflow.

### Task 3: Cross-registry cleanup on unregister
- **Agent**: OnChain
- **Files**:
  - `sources/miner/registration.move` — add relay_registry, validator_registry, control_plane_registry cleanup calls
  - `sources/registry/relay_registry.move` — add `remove_if_registered()` (similar to signaling_registry)
  - `sources/registry/validator_registry.move` — add `remove_if_registered()`
  - `sources/registry/control_plane_registry.move` — add `remove_if_registered()`
  - `tests/miner/registration_tests.move` — add test for unregister with relay/validator/CP entries
- **Requirements**: SEC-020 / P1-7
- **Depends on**: Task 1 (overlapping module area)
- **Description**:
  Currently `registration::unregister()` only cleans up SignalingRegistry (TD-P11-04 fix). Relay, validator, and CP registry entries become stale ghost entries after unregister. Add `remove_if_registered()` to each registry module (pattern: check `has_info()`, if true remove entry). Call all 4 cleanup functions in `unregister()`.

  Note: This adds coupling to `registration.move` — it will import all 4 registry modules. Acceptable for thesis scope. Production would use event-driven cleanup.

  **Signature change**: `unregister()` gains 3 new parameters:
  ```move
  public fun unregister(
      store: &mut MinerStore,
      signaling_reg: &mut SignalingRegistry,
      relay_reg: &mut RelayRegistry,         // NEW
      validator_reg: &mut ValidatorRegistry,  // NEW
      cp_reg: &mut ControlPlaneRegistry,      // NEW
      position: StakePosition,
      ctx: &mut TxContext
  )
  ```
  This is a **breaking change** — all daemon callers of `unregister()` must update their PTBs. File a CONTRACT CHANGE notice.

### Task 4: Fix error code namespace in ONCHAIN_AGENT_SKILL.md
- **Agent**: PM
- **Files**:
  - `docs/skills/ONCHAIN_AGENT_SKILL.md` — update error code table
- **Requirements**: DOC/CONSIST-01 (P0)
- **Depends on**: None
- **Description**:
  The skill file has wrong error codes:
  ```
  WRONG:  CP=550, Relay=600, Validator=650, User=700
  ACTUAL: CP=510, Relay=520, Validator=530, User=540, Signaling=600, Economic=650
  ```
  Also add the missing `signaling_registry` (600-604) and `economic_layer` (650-661) rows. Update the "reserved" range to start at 700.

### Task 5: Fix broken references in CLAUDE.md
- **Agent**: PM
- **Files**:
  - `CLAUDE.md` — fix `local-dev.md` reference, verify `phase1-foundation.md` path
- **Requirements**: DOC/DEPLOY-03 (P0)
- **Depends on**: None
- **Description**:
  CLAUDE.md references `local-dev.md` which doesn't exist. Either:
  - Create a minimal `local-dev.md` with local network setup commands, OR
  - Remove the reference and inline the key commands in CLAUDE.md

  Also verify `docs/phase1-foundation.md` path is correct.

### Task 6: Update contracts README error codes
- **Agent**: PM
- **Files**:
  - `README.md` — add Phase 2+ error codes (500-661)
- **Requirements**: DOC/DEPLOY-01 (P0)
- **Depends on**: None
- **Description**:
  The contracts README only shows Phase 1 error codes. Add all Phase 2+ namespaces:
  - room_manager: 500-506
  - control_plane_registry: 510-515
  - relay_registry: 520-525
  - validator_registry: 530-535
  - user_registry: 540-542
  - signaling_registry: 600-604
  - economic_layer: 650-661

### Task 7: Create dvconf-daemons README
- **Agent**: OffChain
- **Files**:
  - `C:\Thesis\dvconf\dvconf-daemons\README.md` — create
- **Requirements**: DOC/README-01 (P0)
- **Depends on**: None
- **Description**:
  Create a README covering:
  - Project overview (4 daemon apps in pnpm monorepo)
  - Repo structure (apps/cp-daemon, apps/validator-daemon, apps/signaling, apps/relay + packages/shared)
  - Prerequisites (Node.js, pnpm, Sui CLI)
  - Install & build (`pnpm install`, `pnpm build`)
  - How to run each daemon (env vars needed, startup command)
  - Architecture overview (event-driven, chain-aware, auto-registration)
  - Link back to dvconf-contracts for on-chain context

### Task 8: Create dvconf-client README
- **Agent**: FE
- **Files**:
  - `C:\Thesis\dvconf\dvconf-client\README.md` — create
- **Requirements**: DOC/README-02 (P0)
- **Depends on**: None
- **Description**:
  Create a README covering:
  - Project overview (React + Vite + @mysten/dapp-kit)
  - Prerequisites (Node.js, Sui wallet extension)
  - Install & run (`npm install`, `npm run dev`)
  - Environment variables (VITE_* from .env.example)
  - Key features (wallet connect, room management, mediasoup WebRTC, network dashboard)
  - Architecture overview (hooks pattern, chain polling, mediasoup-client)

### Task 9: WebSocket hardening (maxPayload + rate limiting)
- **Agent**: OffChain
- **Files**:
  - `C:\Thesis\dvconf\dvconf-daemons\apps\signaling\src\index.ts` — add `maxPayload` to WebSocketServer config, add per-IP connection counter
  - `C:\Thesis\dvconf\dvconf-daemons\apps\relay\src\signaling.ts` — add `maxPayload` to WebSocketServer config
- **Requirements**: SEC-005, SEC-006 (P1)
- **Depends on**: None
- **Description**:
  **maxPayload** (1-line each): Add `maxPayload: 64 * 1024` (64KB) to both WebSocketServer constructors. SDP offers are typically ~2KB; 64KB is generous.

  **Rate limiting** (signaling only — most exposed): Add a per-IP connection limit using a `Map<string, number>`. On `connection`, increment; on `close`, decrement. Reject with 429 if IP has > 10 connections. Also add per-connection message rate: track message count per second, close connection if > 100 msg/sec.

  Keep it simple — in-memory maps, no Redis. Reset on server restart.

### Task 10: Add .env.example files for daemon apps
- **Agent**: OffChain
- **Files**:
  - `C:\Thesis\dvconf\dvconf-daemons\apps\cp-daemon\.env.example` — create
  - `C:\Thesis\dvconf\dvconf-daemons\apps\validator-daemon\.env.example` — create
  - `C:\Thesis\dvconf\dvconf-daemons\apps\signaling\.env.example` — create
  - `C:\Thesis\dvconf\dvconf-daemons\apps\relay\.env.example` — create
- **Requirements**: DOC/DEPLOY-02 (P1)
- **Depends on**: None
- **Description**:
  Create `.env.example` for each daemon app listing all required and optional env vars with descriptions. Read each daemon's `index.ts` to find all `process.env` references. Include:
  - `PRIVATE_KEY` — Ed25519 keypair (base64)
  - `SUI_RPC_URL` — Sui RPC endpoint
  - `PACKAGE_ID` — deployed package ID
  - App-specific vars (PORT, REGION, RELAY_MODE, etc.)
  - All shared object IDs (NETWORK_REGISTRY_ID, MINER_STORE_ID, etc.)

### Task 11: QC review of all changes
- **Agent**: QC
- **Files**: All files modified in Tasks 1-10
- **Requirements**: Quality gate
- **Depends on**: Tasks 1-10 (all dev work complete)
- **Description**:
  Batch QC review of all Phase 16 changes. Check:
  - OnChain: error codes match namespace, assert messages correct, tests cover new paths, Change Reversal Protocol applied
  - OffChain: rate limiting logic correct, no security regressions
  - Docs: accuracy of error code tables, README completeness
  - Cross-domain: CONTRACT CHANGE notice filed for `unregister()` signature change

## Execution Order

```
PARALLEL WAVE 1 (no dependencies):
  ├── Task 1: On-chain security fixes (OnChain)
  ├── Task 4: Fix skill file error codes (PM)
  ├── Task 5: Fix CLAUDE.md refs (PM)
  ├── Task 6: Update README error codes (PM)
  ├── Task 7: Create daemons README (OffChain)
  ├── Task 8: Create client README (FE)
  ├── Task 9: WebSocket hardening (OffChain)
  └── Task 10: Add .env.example files (OffChain)

SEQUENTIAL (depends on Task 1):
  Task 2: Overflow protection (OnChain) — after Task 1
  Task 3: Cross-registry cleanup (OnChain) — after Task 1

FINAL:
  Task 11: QC review — after all Tasks 1-10
```

Wave 1 can run 4 agents in parallel:
- **OnChain**: Tasks 1 → 2 → 3 (sequential, same files)
- **PM**: Tasks 4 + 5 + 6 (parallel, different files)
- **OffChain**: Tasks 7 + 9 + 10 (parallel, different files)
- **FE**: Task 8

## Risks & Open Questions

1. **SEC-009 (duplicate escrow)**: PM needs to decide — add prevention or document as known limitation? The `distributed` flag already prevents double-distribution. Recommendation: document only, no code change.

2. **Task 3 (cross-registry cleanup)**: Changes `unregister()` signature — breaking change for all daemon callers. Need CONTRACT CHANGE notice. Daemon PTBs must be updated in the same phase.

3. **Testnet re-deployment**: On-chain fixes (Tasks 1-3) require re-publish to testnet if thesis demo uses live chain. Existing deployed package won't reflect these fixes.

4. **Error code namespace update (Task 4 + Task 6)**: The AGENT_ROUTING.md also has a stale error code table (shows `(reserved future) | 600–1099`). Must be updated alongside the skill file to stay consistent.
