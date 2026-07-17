# DVConf — Task Tracker
> Last updated: 2026-03-03 · Phase: 1 (Post-Review Redesign Sprint — QC Fixes Applied)

---

## 🔴 Blocked

| ID | Task | Owner | Blocks |
|---|---|---|---|
| T-21 | Cap re-issuance mechanism for role upgrades — when a miner tops-up stake from RELAY→CP, the old MinerCap remains in their wallet but a ControlPlaneCap was never issued; no on-chain flow exists to swap caps | OnChain | Phase 2 session flow; Phase 3 validator/relay assignment cannot rely on cap validity if stale caps exist |

**Resolution path:** Deferred to Phase 2. PM must open a Requirements Discussion before Phase 2 `room_manager.move` work begins. Options to evaluate: (A) burn-and-reissue via new `exchange_cap` entry point, (B) caps carry role at issue time only and are re-verified against MinerStore at use-time, (C) role upgrade always destroys old cap atomically.

---

## 🟡 In Progress

*(none)*

---

## 🟢 Pending

| ID | Task | Owner | Priority |
|---|---|---|---|
| T-40 | Update `docs/phase1/flows.md` — UC1 flow (add duplicate-guard step), UC4 flow (add turn_credential_hash param), UC6 flow (add update_reward_ratios) | PM / OnChain | P1 |
| T-41 | Update `CLAUDE.md` Build Phase Tracker — mark all Phase 1 tasks ✅ Done after QC APPROVED | PM | P1 |
| T-42 | Deploy Phase 1 contracts to Sui testnet; record package ID, NetworkRegistry ID, MinerStore ID, TreasuryCap ID in `.env` | Both devs | P1 |
| T-43 | Resolve Q3 (cap re-issuance) and write Requirements Discussion before Phase 2 `room_manager.move` work begins | PM | P1 |

---

## ✅ Done

| ID | Task | Completed | Notes |
|---|---|---|---|
| T-01 | `constants.move` — initial implementation (all numeric parameters, basis-point constants, role codes) | 2026-02-28 | All parameters defined; DEFAULT_MIN_RELAYS_PER_ROOM was 1 (updated to 2 in T-16) |
| T-02 | `token.move` — DVCONF fungible coin with OTW pattern, mint/burn, TreasuryCap | 2026-02-28 | OTW pattern correct; `init_for_testing` present |
| T-03 | `network_registry.move` — singleton governance config, AdminCap, ScoringWeights, RewardRatios, RoleThresholds | 2026-02-28 | Missing `update_reward_ratios` (remediated in T-15); E_INVALID_RATIO absent (added in T-15) |
| T-04 | `caps.move` — ControlPlaneCap and MinerCap with `public(package)` constructors | 2026-02-28 | Cap constructors correctly package-private; no error codes needed |
| T-05 | `miner_store.move` — MinerStore shared object, MinerProfile, Endpoint, NodeStrength | 2026-02-28 | Missing existence checks on mutation paths (T-13, T-14); Endpoint missing turn_credential_hash (T-17); validator_set public visibility (T-18) |
| T-06 | `staking.move` — StakePosition, create/destroy/lock/unlock/slash, role determination | 2026-02-28 | slash() had no balance guard (T-11); StakePosition had store (T-19) |
| T-07 | `registration.move` — register/unregister/top_up/update_* entry points | 2026-02-28 | Missing duplicate-registration guard (T-12); update_endpoint missing credential hash param (T-20) |
| T-08 | `cp_queries.move` — CP-gated scoring queries | 2026-02-28 | No issues found in QC review |
| T-09 | `tests/helpers.move` — shared setup(), mint_to(), do_register() | 2026-02-28 | Updated in T-31–T-37 sprint; added default_bandwidth_mbps / default_max_concurrent accessors |
| T-10 | Initial test suite — registration_tests, network_registry_tests, cp_queries_tests | 2026-02-28 | UC1-UC6 happy paths covered; failure paths added in T-31–T-37 |
| T-11 | `staking.move` — add `balance::value` guard before `balance::split` in `slash()` | 2026-03-03 | Fixed; E_INSUFFICIENT_STAKE (200) now guards slash |
| T-12 | `registration.move` — add `E_ALREADY_REGISTERED = 404`; duplicate-registration guard | 2026-03-03 | Fixed; assert !has_profile before table::add |
| T-13 | `miner_store.move` — add existence check to `borrow_profile_mut()` | 2026-03-03 | Fixed; aborts E_NOT_REGISTERED (300) |
| T-14 | `miner_store.move` — add existence check to `change_role()` | 2026-03-03 | Fixed; aborts E_NOT_REGISTERED (300) |
| T-15 | `network_registry.move` — add `E_INVALID_RATIO = 102`; add `update_reward_ratios()` | 2026-03-03 | Fixed; sum == 10_000 invariant enforced |
| T-16 | `constants.move` — update `DEFAULT_MIN_RELAYS_PER_ROOM` from 1 to 2 | 2026-03-03 | Fixed; PM decision Option B |
| T-17 | `miner_store.move` — add `turn_credential_hash` to Endpoint; add accessors | 2026-03-03 | Fixed; endpoint_turn_credential_hash() accessor added |
| T-18 | `miner_store.move` — change `validator_set()` to `public(package)` | 2026-03-03 | Fixed; external callers must go through cp_queries |
| T-19 | `staking.move` — remove `has store` ability from `StakePosition` | 2026-03-03 | Fixed; transfer_to() helper added for intra-package transfer |
| T-20 | `registration.move` — add `turn_credential_hash` param to `register()` and `update_endpoint()` | 2026-03-03 | Fixed (QC C1 catch: update_endpoint was hard-coding b"") |
| T-22 | PM Phase 1 Architecture Review — QC initial review pass | 2026-03-03 | Four P0 BLOCK items found (BLOCK-1 through BLOCK-4); five P1 items; four open questions surfaced |
| T-23 | PM design decisions recorded in REDESIGN_PLAN.md | 2026-03-03 | All five decisions recorded; Q1 and Q2 resolved, Q3 deferred (T-21), Q4 resolved |
| T-31 | Add `test_slash_over_balance_fails` — expected_failure abort_code=200 | 2026-03-03 | PASS |
| T-32 | Add `test_double_register_fails` — expected_failure abort_code=404 | 2026-03-03 | PASS |
| T-33 | Add `test_top_up_non_owner_fails` — expected_failure abort_code=402 | 2026-03-03 | PASS |
| T-34 | Add `test_update_endpoint_non_owner_fails` — expected_failure abort_code=402 | 2026-03-03 | PASS |
| T-35 | Add `test_governance_update_reward_ratios` — happy path | 2026-03-03 | PASS |
| T-36 | Add `test_governance_invalid_reward_ratios` — expected_failure abort_code=102 | 2026-03-03 | PASS |
| T-37 | Add `test_governance_invalid_thresholds_relay_below_validator` — expected_failure abort_code=101 | 2026-03-03 | PASS |
| T-38 | QC re-review of all changed files | 2026-03-03 | NEEDS REVISION → C1 (update_endpoint credential hash) and C2 (namespace table) found and fixed; all N-items resolved; re-run → 34/34 PASS |
| T-39 | Update `docs/phase1/README.md` — error namespace (add 102, 404, staking 201/202 note) | 2026-03-03 | Done; namespace table now complete |
