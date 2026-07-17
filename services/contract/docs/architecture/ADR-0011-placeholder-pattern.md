---
name: ADR-0011-placeholder-pattern
description: Convention for L1 placeholder stubs across Move + TypeScript when a downstream feature needs a deferred-impl interface lock ahead of real implementation.
metadata:
  type: adr
  area: meta
  status: ACCEPTED
  adr-number: "0011"
  shipped-date: 2026-05-25
  parent: 20-decisions
  related-feature: F62
  related-roadmap: plans/room-admission-control/milestone-1/ROADMAP.md
  cross-ref:
    - ADR-0010  # F62 room-admission-control (consumer of this convention)
  tags:
    - "#adr"
    - "#harness"
    - "#testing"
---

# ADR-0011 — L1 Placeholder Pattern Convention

## Status

**ACCEPTED** — codified S43 (Strict 3-layer harness design) in `plans/room-admission-control/milestone-1/DESIGN.md`. Documented S53 alongside Phase 1.1 ship (`cp_quorum_sig.move`).

## Context

The "Strict 3-layer harness" execution strategy (DESIGN.md § Implementation Strategy, locked S43) calls for:

- **L1 — Placeholder pattern** — REQs that are not yet implemented are checked-in as skeletal tests that abort or skip with a sentinel marker, so the gap is visible to humans + automated audit scripts.
- **L2 — Contract test** — interface lock at Stage 1 ship gate; signature changes blocked by pre-merge hook.
- **L3 — Cross-lane regression** — pre-merge any lane runs other lane's tests + Phase 1 tests.

This ADR documents L1 only.

The motivation is **Hybrid parallelism**: Stage 1 ships shared primitives, Stage 2/3 lanes fan out in parallel. Lanes need to reference deferred REQs (e.g. F62 admission Stage 2 tests reference an F47 cooldown event that lands later) without breaking the build. Placeholders mark "intentional gap, not forgotten" — and `scripts/audit-placeholders.ps1` at the SHIP gate (Phase 5.2) enforces count = 0 before declaring milestone-done.

## Decision

Adopt two language-specific placeholder forms with a shared sentinel value.

### Move — `#[expected_failure(abort_code = 999)]`

```move
#[test]
#[expected_failure(abort_code = 999, location = dvconf::placeholder)]
public fun test_REQ_ADM_007_cache_invalidate_on_revoke() {
    // TODO REQ-ADM-007 — implemented in Phase 3.3 cap-token-cache module
    abort 999
}
```

- The `abort 999` body satisfies the compiler.
- `abort_code = 999` is the reserved sentinel for "not_implemented" — no production module may use 999 for any other purpose.
- `location = dvconf::placeholder` is optional but recommended to silence the "passes for an abort from any module" linter warning (W10007).
- Comments must reference the REQ-ID and the future phase that will implement it.

### TypeScript / Vitest — `it.todo` or `it.skip`

```ts
it.todo('REQ-RV-005 — should enforce 14-day cooldown (Phase 3 lane B)');

it.skip('REQ-ADM-013 — should keep old token valid during 60s grace window', () => {
  // TODO Phase 3.4
});
```

- `it.todo` is preferred when no test body exists yet.
- `it.skip` is preferred when a test body exists but is intentionally disabled (e.g. waiting on a sibling lane's mock).
- Reason string must reference the REQ-ID and the future phase.

### When to use

| Situation | Use placeholder? |
|---|---|
| Sibling lane test needs a stable reference to a future event/struct | YES |
| ADR-locked interface needs a frozen snapshot test before downstream consumers exist | YES |
| Function exists in spec, will land in a clearly-named later phase of the same ROADMAP | YES |
| Test exists but flakes intermittently | NO — diagnose root cause (per `superpowers:systematic-debugging`) |
| Real implementation gap that the team forgot about | NO — use a proper backlog ticket + Bug log |
| Performance or stress test that needs a measurement environment | NO — use `it.skip` with a measurement-driven gate, not the placeholder sentinel |

### Migration when impl lands

1. Replace the `#[expected_failure(abort_code = 999)]` annotation with the appropriate real expected-failure (or remove it entirely if the test is now happy-path).
2. Replace `abort 999` body with real test code.
3. Convert `it.todo` to `it()` with a real test body.
4. Re-run the audit script (`scripts/audit-placeholders.ps1`) to verify count decreases.
5. Reference the REQ-ID in the commit message.

### Zero-placeholder ship gate

At Phase 5.2 SHIP gate of each milestone (`/quangflow:4-verify`):

```powershell
scripts/audit-placeholders.ps1 --strict
# Counts:
#   Move    abort 999            = 0
#   Vitest  it.todo / it.skip    = 0
# Exits non-zero if any > 0.
```

The audit script is owned by QC Agent (per DESIGN.md § Open implementation questions, line 470) — file the assignment in REVIEW.md when Phase 5.2 lands.

## Consequences

### Positive

- Lanes can fan out in parallel without "TypeScript can't compile this import" or "Move can't resolve this symbol" hard-failures.
- Audit script gives objective SHIP-gate signal — no human handwave about "I think we got them all".
- REQ-ID coverage matrix (RTM in CERTIFICATION.md) trivially maps each placeholder to a real owner phase.

### Negative

- Cosmetic linter noise on `#[expected_failure(abort_code = 999)]` without `location = …` (Sui linter W10007 "passes for an abort from any module"). Mitigated by always adding `location = dvconf::placeholder` or accepting the warning until a future-phase impl lands.
- Risk that a developer commits an `abort 999` and forgets to migrate it when the impl lands. Mitigated by the SHIP-gate audit.

### Risks

- If multiple milestones overlap in time, the sentinel `999` is shared across all of them. A future ADR may need to introduce milestone-scoped sentinels (e.g. `999`, `998`, `997`) if cross-milestone placeholder leakage becomes a problem. Out of scope for this ADR.

## Alternatives considered

### A — Use `#[test_only]` empty function with `// TODO` comment

Rejected: no machine-readable marker. Audit script would need to grep for `// TODO` which is noisy + non-deterministic.

### B — Per-feature sentinel constants

Rejected: scope creep. `abort 999` is universally understood as "not_implemented" placeholder; no need for per-feature codes.

### C — Skip the placeholder layer entirely (only L2 + L3)

Rejected: removes the visible "intentional gap" signal. Lanes that need to reference a future symbol would have to either inline-mock it (silent regression risk) or block on the other lane (defeats Hybrid parallelism).

## References

- `plans/room-admission-control/milestone-1/DESIGN.md` § Implementation Strategy — Strict 3-layer harness locked S43
- `plans/room-admission-control/milestone-1/ROADMAP.md` § Execution Strategy
- `dvconf-contracts/sources/security/cp_quorum_sig.move` — first module to formally cite this ADR (Phase 1.1 S53)
- ADR-0010 — F62 capability-token admission control (consumer of cp_quorum_sig primitive)
