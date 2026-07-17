# SHIP gate — multi-cp-quorum Leg 8 (parametric M-of-N on-chain tests)

- **Date:** 2026-06-22
- **Leg:** Leg 8 (TAIL) — parametric M-of-N tests (M=1..5 × N=3..10) vs the byte-frozen `cp_quorum_sig::verify_quorum`
- **Commit under gate:** dvconf-contracts `main` `f42ebe3`
- **Verdict:** **GATE_PASS** — 0 blockers, 0 overclaims
- **Closer:** single independent adversarial reviewer (read-only), right-sized for a test-only tail leg (0 production change / Move byte-frozen). Lane milestone gates (Phase 1, Leg 7) used a multi-auditor workflow; Leg 8 is an additive characterization tail, so one independent teeth/honesty audit is proportionate.

## Scope built

Pure additive `tests/security/cp_quorum_sig_parametric_tests.move` (11 `#[test]`) sweeping the M-of-N parameter matrix against the SHIPPED, byte-frozen on-chain quorum predicate. **0 production change** — `sources/security/cp_quorum_sig.move` byte-identical (INV held). Closes ADR-0020's Leg 8 deferral (defer-condition "after live carrier stable" — met by the Leg 7 loopback ship).

Cells (M, N, k→expected): P-01 (1,3): 1→T,0→F,3→T · P-02 (2,3): 2→T,1→F,3→T · P-03 (3,5): 3→T,2→F,5→T · P-04 (4,7): 4→T,3→F,7→T · P-05 (5,10): 5→T,4→F,10→T · P-06 (5,5 M==N): 5→T,4→F · P-07 (1,10): 1→T,0→F,10→T · P-08 (3,3 M==N): 3→T,2→F · P-09 (4,4 M==N): 4→T,3→F · P-10 (floor 3,5 N<M): 3→F · P-11 (2,10): 2→T,1→F,10→T.

Method (mirrors QSIG-01): one RFC 8032 §7.1 valid (pubkey, sig) pair over the empty message, reused under N distinct *registered* operator addresses — faithful because `verify_quorum` counts a quorum by distinct signer-address (F-01 dedup) and runs `ed25519::ed25519_verify` per signer.

## Evidence

- Full Move suite non-regression: **377/377** (366 baseline + 11 new), 0 failures — `.evidence/tdd/REQ-ADM-008-leg8-parametric-green.log`.
- Run-state note: `sui move test` in this machine state requires a **reachable** active client env (the committed `[environments] local = "8f16e176"` localnet is gone — pre-existing infra; the 377/377 run used active env `testnet`, which lets sui resolve automated-address-management without a localnet). Repo manifests (`Move.toml`/`Move.lock`) and the client config were restored to as-found after the run — the commit touches ONLY the test file + evidence log.

## Independent audit findings (read-only, adversarial)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Byte-frozen invariant | PASS | `git diff f42ebe3~1 f42ebe3 -- sources/` empty; only test file + evidence log changed |
| 2 | Tests have teeth (not vacuous) | PASS | helper asserts `ok == expected` (parametric:127); below-threshold & floor cells assert false via `n < required` (cp_quorum_sig.move:153) |
| 3 | RFC-vector reuse legitimate (no ed25519 bypass) | PASS | per-signer `ed25519_verify` (cp_quorum_sig.move:180) + addr-keyed dedup (:169); QSIG-03 proves tampered sig → false |
| 4 | Matrix framing honest | PASS | header enumerates the 11 cells; "M=1..5, N=3..10" worded as a representative sweep, not exhaustive (N∈{6,8,9} unexercised — stated) |
| 5 | `update_threshold` semantics for floor cell | PASS | asserts only `new>=1` (:208) → M=5 with N=3 registered valid; floor yields false (3<5) |

**Overclaims:** none. **Blockers:** none.

## Carried (partials, on record)

- **Coverage is a representative sweep** (N∈{6,8,9} not exercised) — stated honestly in the artifact header; not a defect.
- **Audit methodology partial:** the reviewer could not re-execute `sui move test` live (the active-env publish-resolution quirk above); verdict rests on the committed timestamped green log + static teeth analysis tracing each cell's expectation to a specific branch in the frozen impl. No failing or vacuous test found.

## Lane status after Leg 8

multi-cp-quorum: Phase 1 hermetic (Legs 0-6) + Leg 7 LIVE loopback carrier + **Leg 8 parametric tests** all SHIPPED. **Only remaining tail:** live multi-host topology (OQ-7) — DEFERRED on the W5 connection-arch operator port-8092 sign-off (same sign-off as canary M4b-live; not code-buildable without ops input).
