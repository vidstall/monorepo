---
phase: 3
slug: off-chain-daemons
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest 4.0.x |
| **Config file** | `vitest.config.ts` at monorepo root (Wave 0) |
| **Quick run command** | `pnpm test` |
| **Full suite command** | `pnpm -r test` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pnpm --filter <affected-package> test`
- **After every plan wave:** Run `pnpm -r test`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | DAEMON-11 | unit (type check) | `pnpm --filter @dvconf/shared test` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | DAEMON-12 | unit (mock client) | `pnpm --filter @dvconf/shared test -- chain` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | DAEMON-07 | unit | `pnpm --filter @dvconf/shared test -- retry` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | DAEMON-01 | unit | `pnpm --filter @dvconf/signaling test` | ❌ W0 | ⬜ pending |
| 03-01-05 | 01 | 1 | DAEMON-02 | unit (import check) | `pnpm --filter @dvconf/signaling test` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | DAEMON-03 | unit (mock client) | `pnpm --filter @dvconf/cp-daemon test` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | DAEMON-04 | unit | `pnpm --filter @dvconf/cp-daemon test -- scoring` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | DAEMON-05 | unit | `pnpm --filter @dvconf/cp-daemon test -- scoring` | ❌ W0 | ⬜ pending |
| 03-02-04 | 02 | 2 | DAEMON-06 | unit (mock TX) | `pnpm --filter @dvconf/cp-daemon test -- heartbeat` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | DAEMON-08 | unit (mock TX) | `pnpm --filter @dvconf/validator-daemon test` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 2 | DAEMON-09 | unit | `pnpm --filter @dvconf/validator-daemon test -- measurements` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 2 | DAEMON-10 | unit | `pnpm --filter @dvconf/validator-daemon test -- session-proof` | ❌ W0 | ⬜ pending |
| SMOKE | -- | 3 | ALL | integration | `pnpm test:integration` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `dvconf-daemons/` repo — entire monorepo needs to be created
- [ ] `pnpm-workspace.yaml` — workspace configuration
- [ ] `vitest.config.ts` — root vitest configuration
- [ ] `tsconfig.base.json` — shared TypeScript configuration
- [ ] All `package.json` files for workspace packages
- [ ] All test stub files (unit tests for each daemon + shared package)
- [ ] Integration test infrastructure (local Sui network start/stop helpers)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Daemon connects to live testnet | DAEMON-12 | Requires funded wallet + testnet | Start daemon with `.env.testnet`, verify heartbeat TX on explorer |
| WebSocket signaling with real browser | DAEMON-01 | Requires browser client | Open two browser tabs, verify ICE exchange via signaling |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
