---
phase: 01
slug: foundation-validation
status: draft
nyquist_compliant: false
wave_0_complete: true
created: 2026-03-04
---

# Phase 01 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Sui Move Test (built into `sui move test`) |
| **Config file** | `Move.toml` |
| **Quick run command** | `sui move test --silence-warnings` |
| **Full suite command** | `sui move test --silence-warnings` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `sui move test --silence-warnings`
- **After every plan wave:** Run `sui move test --silence-warnings`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | FOUND-01 | smoke | `sui move test --filter token` | N/A (init) | ⬜ pending |
| 01-01-02 | 01 | 1 | FOUND-02 | unit | `sui move test --filter network_registry_tests` | ✅ | ⬜ pending |
| 01-01-03 | 01 | 1 | FOUND-03 | unit | `sui move test --filter network_registry_tests` | ✅ | ⬜ pending |
| 01-01-04 | 01 | 1 | FOUND-04 | unit | `sui move test --filter registration_tests` | ✅ | ⬜ pending |
| 01-01-05 | 01 | 1 | FOUND-05 | unit | `sui move test --filter registration_tests` | ✅ | ⬜ pending |
| 01-01-06 | 01 | 1 | FOUND-06 | unit | `sui move test --filter registration_tests` | ✅ | ⬜ pending |
| 01-01-07 | 01 | 1 | FOUND-07 | manual | QC review of visibility modifiers | N/A | ⬜ pending |
| 01-01-08 | 01 | 1 | FOUND-08 | unit | `sui move test --filter registration_tests` | ✅ | ⬜ pending |
| 01-01-09 | 01 | 1 | FOUND-09 | manual | QC review of package-private access | N/A | ⬜ pending |
| 01-01-10 | 01 | 1 | FOUND-10 | unit | `sui move test --filter cp_queries_tests` | ✅ | ⬜ pending |
| 01-01-11 | 01 | 1 | FOUND-11 | manual | QC cross-reference error codes | N/A | ⬜ pending |
| 01-01-12 | 01 | 1 | FOUND-12 | unit | `sui move test --silence-warnings` | ✅ | ⬜ pending |
| 01-02-01 | 02 | 2 | FOUND-01..12 | deploy | `sui client publish --gas-budget 100000000 --json` | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. All 34 tests already exist and pass. No new test files needed for this validation-only phase.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cap constructors are `public(package)` | FOUND-07 | Visibility is a compile-time property, not testable at runtime | Grep all `fun new(` in sources/access/caps.move — confirm `public(package)` |
| MinerStore uses package-private access | FOUND-09 | Access control is structural, not behavioral | Verify `validator_set()` is `public(package)` in miner_store.move |
| Error codes match namespace table | FOUND-11 | Requires cross-referencing docs vs code constants | Compare error constants in each module against docs/phase1/README.md |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
