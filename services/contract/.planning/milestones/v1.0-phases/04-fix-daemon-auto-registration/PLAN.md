# Phase 4 Plan: Fix Daemon Auto-Registration
Date: 2026-03-07

## Goal
All daemon auto-registration TX calls use correct argument types and order, restoring CP and Validator registration E2E flows

## Success Criteria
1. CP daemon `register_cp` TX passes correct argument types: `[networkRegistryId, cpRegistryId, controlPlaneCapId, stakePositionId]`
2. Validator daemon `registration::register` TX has no extra MinerRole argument
3. Validator daemon `register_validator` TX passes `[networkRegistryId, validatorRegistryId, minerCapId, stakePositionId]`
4. CP Node Registration E2E flow completes without TX errors
5. Validator Node Registration E2E flow completes without TX errors

## Requirements Covered
Gap closure — no new REQ-IDs. Fixes 3 integration gaps + 3 broken E2E flows from v1.0-MILESTONE-AUDIT.md.

## Tasks

### Task 1: Fix CP daemon `registration::register` TX argument types
- **Agent**: OffChain
- **Files**: `../dvconf-daemons/apps/cp-daemon/src/auto-register.ts`
- **Requirements**: Success Criteria 4 (partial)
- **Depends on**: None
- **Description**: Fix two type mismatches in the CP daemon's Step 1 (`registration::register`) call:
  1. **Arg 7 `region`**: Change `tx.pure.u8(0)` → `tx.pure.vector('u8', [...Buffer.from('local')])` (or similar byte-string encoding). Move expects `vector<u8>`, not `u8`.
  2. **Arg 10 `cpu_cores`**: Change `tx.pure.u8(1)` → `tx.pure.u64(1)`. Move expects `u64`, not `u8`.

### Task 2: Fix CP daemon `register_cp` TX argument order and object IDs
- **Agent**: OffChain
- **Files**: `../dvconf-daemons/apps/cp-daemon/src/auto-register.ts`
- **Requirements**: Success Criteria 1, 4
- **Depends on**: Task 1
- **Description**: Fix Step 2 (`control_plane_registry::register_cp`) call. The Move signature is `(net_reg, registry, cap, stake)`. Current daemon passes:
  - arg2 = `config.minerStoreId` (wrong — should be the `ControlPlaneCap` created in Step 1)
  - arg3 = `minerCapId` (wrong — should be the `StakePosition` created in Step 1)

  Fix:
  1. After Step 1 TX execution, extract **both** created objects from effects: `ControlPlaneCap` and `StakePosition`. Use object type filtering (`objectType` field in `createdObjects`) rather than fragile index-based extraction (`createdObjects[0]`).
  2. Pass Step 2 args as: `[networkRegistryId, cpRegistryId, controlPlaneCapId, stakePositionId]`.

### Task 3: Fix Validator daemon `registration::register` TX — remove extra MinerRole arg
- **Agent**: OffChain
- **Files**: `../dvconf-daemons/apps/validator-daemon/src/auto-register.ts`
- **Requirements**: Success Criteria 2, 5 (partial)
- **Depends on**: None
- **Description**: Remove the extra `tx.pure.u8(MinerRole.Validator)` argument at position 3. The Move function `registration::register` does NOT accept a role parameter — role is determined on-chain by `staking::determine_role()`. Removing this arg fixes the cascade of shifted arguments (14 → 13 args). Also fix `tx.pure.string(...)` usages to `tx.pure.vector('u8', ...)` for `ip`, `stun_url`, `turn_url`, `region` fields, and fix `port` from `tx.pure.u64(0)` to `tx.pure.u16(port)`.

### Task 4: Fix Validator daemon `register_validator` TX argument order and completeness
- **Agent**: OffChain
- **Files**: `../dvconf-daemons/apps/validator-daemon/src/auto-register.ts`
- **Requirements**: Success Criteria 3, 5
- **Depends on**: Task 3
- **Description**: Fix Step 2 (`validator_registry::register_validator`) call. The Move signature is `(net_reg, registry, cap, stake)` — 4 args. Current daemon passes only 3 args with wrong objects:
  1. Add missing `config.networkRegistryId` as arg 0
  2. Fix arg 1 from `config.minerStoreId` to `config.validatorRegistryId`
  3. Keep `minerCapId` as arg 2 (MinerCap — correct type)
  4. Add missing `stakePositionId` as arg 3 — extract from Step 1 effects using type-based filtering (same pattern as Task 2)

### Task 5: Update auto-registration tests
- **Agent**: OffChain
- **Files**: `../dvconf-daemons/apps/cp-daemon/src/__tests__/auto-register.test.ts`, `../dvconf-daemons/apps/validator-daemon/src/__tests__/auto-register.test.ts`
- **Requirements**: Success Criteria 4, 5
- **Depends on**: Tasks 1–4
- **Description**: Update existing tests (or add new ones) to verify:
  1. CP Step 1 TX uses correct types for `region` (vector\<u8\>) and `cpu_cores` (u64)
  2. CP Step 2 TX passes `[networkRegistryId, cpRegistryId, controlPlaneCapId, stakePositionId]` in correct order
  3. Validator Step 1 TX has exactly 13 args (no MinerRole), correct types
  4. Validator Step 2 TX passes `[networkRegistryId, validatorRegistryId, minerCapId, stakePositionId]` — 4 args
  5. Object extraction from TX effects uses type-based filtering, not index-based

## Execution Order

```
Task 1 (CP register types) ──→ Task 2 (CP register_cp args) ──┐
                                                                ├──→ Task 5 (tests)
Task 3 (Validator register args) ──→ Task 4 (Validator register_validator args) ──┘
```

- Tasks 1 and 3 are **independent** — can run in parallel (different daemon packages)
- Task 2 depends on Task 1 (same file, sequential logic)
- Task 4 depends on Task 3 (same file, sequential logic)
- Task 5 depends on all prior tasks

## Risks & Open Questions

1. **Object type strings**: The exact `objectType` strings returned in TX effects need to match what we filter on (e.g., `0x<pkg>::registration::StakePosition`). The package ID varies by network — extraction should use suffix matching (e.g., `endsWith('::ControlPlaneCap')`) rather than full type strings.
2. **TX effects structure**: The `@mysten/sui` SDK's `SuiTransactionBlockResponse` structure for `effects.created` may have changed since the daemons were written. Verify the correct field paths for object type extraction.
3. **Config keys**: `controlPlaneCapId` and `stakePositionId` should NOT be in config — they are created dynamically in Step 1 and used in Step 2 within the same registration flow.
