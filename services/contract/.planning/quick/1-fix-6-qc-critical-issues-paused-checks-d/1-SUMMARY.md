---
phase: quick-fix-qc-critical
plan: 01
subsystem: registry-layer
tags: [bugfix, security, paused-guard, error-codes, identity-hiding]
key-files:
  modified:
    - sources/registry/user_registry.move
    - sources/registry/relay_registry.move
    - sources/registry/validator_registry.move
    - sources/registry/room_manager.move
    - tests/registry/user_registry_tests.move
    - tests/registry/relay_registry_tests.move
    - tests/registry/room_manager_tests.move
decisions:
  - "E_NOT_FOUND (502) is the correct error for missing room existence checks, E_ALREADY_CLOSED (503) reserved for status-based checks"
  - "has_session_wallet changed to public(package) to prevent external identity probing"
metrics:
  tasks: 2
  tests-before: 77
  tests-after: 79
  completed: 2026-03-05
---

# Quick Fix 1: Fix 6 QC-Critical Issues Summary

Fixed 6 QC-critical issues across 4 Phase 2 registry modules: paused guards on mutating functions, dead code removal, validator identity leak prevention, and error code semantics.

## Task Summary

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Fix sources | `38fe7a6` | C1-C6 applied to 4 source files |
| 2 | Update tests | `3849809` | 3 test files updated, 2 new paused-guard tests added |

## Fixes Applied

| ID | Module | Issue | Fix |
|----|--------|-------|-----|
| C1 | user_registry | `update_profile` missing paused guard | Added `net_reg: &NetworkRegistry` param + `is_paused` assert |
| C2 | relay_registry | `update_mode` missing paused guard | Added `net_reg: &NetworkRegistry` param + `is_paused` assert |
| C3 | relay_registry | Dead `let mode = staking::role(stake)` line | Removed dead assignment and stale comment |
| C4 | validator_registry | `SessionWalletAssigned` leaks `miner_id`, `has_session_wallet` publicly accessible | Removed `miner_id` from event struct+emit, changed visibility to `public(package)` |
| C5 | room_manager | `close_room` existence check uses wrong error code (503) | Changed to `E_NOT_FOUND` (502) |
| C6 | room_manager | `set_room_status` existence check uses wrong error code (503) | Changed to `E_NOT_FOUND` (502) |

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- `sui move test --silence-warnings`: 79 tests, 0 failures
- All 6 spot-checks passed (grep verification)

## Self-Check: PASSED

- [x] `sources/registry/user_registry.move` - FOUND
- [x] `sources/registry/relay_registry.move` - FOUND
- [x] `sources/registry/validator_registry.move` - FOUND
- [x] `sources/registry/room_manager.move` - FOUND
- [x] Commit `38fe7a6` - FOUND
- [x] Commit `3849809` - FOUND
