---
status: complete
phase: 01-foundation-validation
source: [01-01-SUMMARY.md, 01-02-SUMMARY.md]
started: 2026-03-04T20:00:00Z
updated: 2026-03-04T20:15:00Z
---

## Dependency Tree
<!-- If a parent test fails, all children are auto-skipped -->
<!--
T1 (Move tests pass)
├── T2 (Error codes correct)
├── T3 (Cap visibility correct)
├── T4 (Paused-flag enforcement)
├── T5 (Basis-point invariants)
├── T6 (Stake lock enforcement)
└── T7 (Package on testnet)
    ├── T8 (NetworkRegistry on testnet)
    ├── T9 (MinerStore on testnet)
    └── T10 (.env.testnet complete)
-->

## Current Test

[testing complete]

## Tests

### 1. All 34 Move tests pass
expected: Run `sui move test --silence-warnings`. Output: "Total tests: 34; passed: 34; failed: 0"
depends_on: none
result: pass

### 2. Error codes match namespace table
expected: Verify error constants in source match docs/phase1/README.md: network_registry 100-102, staking 200-202, miner_store 300, registration 400-404
depends_on: 1
result: pass

### 3. Cap constructors are public(package)
expected: In caps.move, new_cp_cap and new_miner_cap use `public(package)`. In staking.move, lock/unlock use `public(package)`. No cap can be minted externally.
depends_on: 1
result: pass

### 4. Paused-flag enforcement on state-mutating entries
expected: registration::register() and registration::top_up_stake() both check `!is_paused(registry)` and abort 403 if paused.
depends_on: 1
result: pass

### 5. Basis-point invariants (weights/ratios sum to 10,000)
expected: Scoring weights sum == 10,000. Reward ratios sum == 10,000. Thresholds are descending. No floating-point math anywhere.
depends_on: 1
result: pass

### 6. Stake lock enforcement
expected: unregister() aborts 401 (E_STAKE_LOCKED) if locked, aborts 402 (E_NOT_OWNER) if not owner. Both paths tested.
depends_on: 1
result: pass

### 7. Package published on testnet
expected: Package visible on Suiscan — shows 8 modules (caps, constants, cp_queries, miner_store, network_registry, registration, staking, token)
depends_on: 1
result: pass

### 8. NetworkRegistry shared object on testnet
expected: Object exists on Suiscan, type is ::network_registry::NetworkRegistry, ownership is Shared.
depends_on: 7
result: pass

### 9. MinerStore shared object on testnet
expected: Object exists on Suiscan, type is ::miner_store::MinerStore, ownership is Shared.
depends_on: 7
result: pass

### 10. .env.testnet contains all object IDs
expected: File contains PACKAGE_ID, NETWORK_REGISTRY_ID, MINER_STORE_ID, TREASURY_CAP_ID, ADMIN_CAP_ID, UPGRADE_CAP_ID — all starting with 0x.
depends_on: 7
result: pass

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0

## Gaps

[none]
