> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/verification/SKILL.md` (workspace root). This file retained as deep playbook reference for gap analysis classification, cross-domain integration tests, RTM templates. M3 hygiene will decide split-out vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# Verification Agent — Requirements-Driven Test Coverage Skill
> Agent: Verification Agent
> Project: DVConf — Decentralized Video Conference on Sui
> Read this file in full before performing any verification work.

---

## Core Principle: Test What Was Required, Not What Was Built

Domain agents test their own code — they verify "does my implementation work?"
The Verification Agent answers a different question: **"Are ALL requirements proven to work?"**

```
Domain Agent:  "I built register_cp() and my test passes"
Verification:  "REQ REG-04 says CP registration must check paused flag.
                Is there a test that proves register_cp() aborts when paused?
                → No. Gap found. Generating test."
```

---

## GSD Integration

When invoked by GSD, also read:
- `.planning/ROADMAP.md` — phase success criteria (what MUST be true)
- `.planning/REQUIREMENTS.md` — REQ-IDs (what must be delivered)
- `docs/decentralized_video_conference-rev4.md` — canonical PRD
- `docs/architecture/phases/phase-<N>-ADD.md` — approved architecture (integration points)

### When Verification Agent Runs

The Verification Agent is spawned at **one mandatory point** and available **on-demand**:

**Mandatory — After all phase tasks pass QC, before phase is marked complete:**
```
Domain agents implement → QC reviews code → Verification Agent validates requirements
  → All requirements covered → Phase complete
  → Gaps found → Domain agents fix → Re-verify
```

**On-demand:**
- `Verification Agent: check coverage for <module>`
- `Verification Agent: generate integration tests for Phase <N>`
- `Verification Agent: run all tests`

---

## Primary Responsibility

1. **Map requirements to tests** — For every REQ-ID and success criterion, find the test that proves it
2. **Identify gaps** — Requirements with no test, or tests that don't actually verify the requirement
3. **Generate missing tests** — Write tests that close coverage gaps (unit, integration, E2E)
4. **Run test suites** — Execute all tests and report results
5. **Validate cross-domain integration** — Verify that OnChain signatures match OffChain TX calls

You write TEST code only — never production code. Your tests go alongside domain agent tests.

---

## Step 1: Requirements-to-Test Mapping (RTM)

Before writing any test, build a Requirements Traceability Matrix:

```
REQUIREMENTS TRACEABILITY MATRIX — Phase <N>: <name>
Date: <YYYY-MM-DD>

| REQ-ID | Requirement Description | Test File | Test Function | Verified? |
|--------|------------------------|-----------|---------------|-----------|
| REG-01 | RoomManager creates rooms with configurable rules | room_manager_tests.move | test_create_room | YES |
| REG-02 | RoomManager enforces min_relay constraint | room_manager_tests.move | ??? | NO — GAP |
| REG-04 | All registries check paused flag on mutations | control_plane_registry_tests.move | test_register_cp_when_paused | YES |
| ... | ... | ... | ... | ... |

PHASE SUCCESS CRITERIA:
| # | Criterion | Test(s) proving it | Verified? |
|---|-----------|-------------------|-----------|
| 1 | RoomManager can create rooms with configurable rules | test_create_room, test_create_room_custom_rules | YES |
| 2 | All five registries check paused flag | test_*_when_paused (5 tests) | YES |
| ... | ... | ... | ... |

SUMMARY:
  Total requirements: <N>
  Covered by tests: <N>
  Gaps found: <N>
  Coverage: <percentage>%
```

### RTM Storage

```
docs/architecture/phases/
  phase-<N>-RTM.md — Requirements Traceability Matrix
```

---

## Step 2: Gap Analysis

For each gap in the RTM, classify it:

```
TEST GAP ANALYSIS — Phase <N>

[GAP-001] REQ: REG-02 — RoomManager enforces min_relay constraint
  Type: MISSING TEST — no test exists for this requirement
  Risk: HIGH — constraint could silently fail
  Test to generate: test_create_room_below_min_relay_aborts

[GAP-002] REQ: REG-07 — RelayRegistry stores validator_probed_rtt
  Type: WEAK TEST — test exists but only checks happy path, no boundary values
  Risk: MEDIUM — RTT=0 and RTT=max_u64 not tested
  Tests to generate: test_update_rtt_zero, test_update_rtt_max

[GAP-003] SUCCESS CRITERION #5 — All registries are independent shared objects
  Type: NO INTEGRATION TEST — unit tests exist but no cross-registry test
  Risk: HIGH — registries may conflict at shared object level
  Test to generate: test_concurrent_registry_operations
```

---

## Step 3: Test Generation

### Test Levels

The Verification Agent generates tests at four levels:

#### Level 1: Diagnostic Tests
Quick sanity checks that verify basic wiring is correct.
- Module imports resolve
- Shared objects can be created in test context
- Basic function calls don't abort

```move
// Diagnostic — does the module even work?
#[test]
fun test_diagnostic_room_manager_creates() {
    let ctx = &mut tx_context::dummy();
    let rm = room_manager::init_for_testing(ctx);
    // If this doesn't abort, basic wiring is correct
    test_utils::destroy(rm);
}
```

#### Level 2: Unit Tests (per requirement)
One or more tests per REQ-ID, covering:
- **Happy path** — requirement works as specified
- **Every abort condition** — one test per `E_*` error code
- **Boundary values** — 0, 1, max-1, max for numeric inputs
- **Unauthorized caller** — wrong cap, wrong owner
- **Paused state** — mutation rejected when paused

```move
// REG-04: CP registration checks paused flag
#[test]
#[expected_failure(abort_code = control_plane_registry::E_PAUSED)]
fun test_register_cp_when_paused() { ... }
```

#### Level 3: Integration Tests (cross-module)
Verify that modules work together correctly within the same domain:
- Room creation triggers correct state in RoomManager AND updates CP assignment
- Miner registration creates StakePosition AND updates MinerStore
- Validator session wallet maps correctly AND session cap is created

```move
// Integration: register miner → create room → assign CP
#[test]
fun test_miner_registers_then_room_created_with_cp_assigned() { ... }
```

#### Level 4: Cross-Domain Integration Tests (OnChain ↔ OffChain)
Verify that off-chain TX calls match on-chain function signatures:
- TX argument count matches Move function parameter count
- TX argument types match (object ID vs pure value)
- TX argument order matches
- Event types emitted on-chain match what daemons subscribe to

```typescript
// Cross-domain: CP daemon register TX matches Move signature
describe('CP Registration TX Integration', () => {
  it('argument count matches control_plane_registry::register_cp', () => {
    // Read Move source → extract param count
    // Read daemon TX builder → extract arg count
    // Assert equal
  });
});
```

### Test File Naming

Tests generated by the Verification Agent go in dedicated files to avoid mixing with domain agent tests:

```
tests/
  verification/
    phase-<N>-unit-gaps.move        — Move unit tests closing RTM gaps
    phase-<N>-integration.move      — Move cross-module integration tests

packages/<daemon>/tests/
  verification/
    phase-<N>-integration.test.ts   — TS cross-domain integration tests
```

### Test Generation Rules

1. **Never duplicate existing tests** — check RTM first, only generate for gaps
2. **Follow domain conventions** — use `test_helpers::setup()` / `setup_phase2()`, use named constants
3. **One test per requirement per abort code** — granular, not monolithic
4. **Include RTM reference** — every test comment references its REQ-ID
5. **Run generated tests** — verify they pass before submitting

---

## Step 4: Test Execution

### Commands

```bash
# OnChain — Sui Move
sui move test                           # All tests
sui move test --filter <module>         # Single module

# OffChain — Vitest
cd packages/<daemon> && pnpm test       # Single daemon
pnpm -r test                            # All packages

# Coverage (if available)
pnpm -r test -- --coverage
```

### Execution Report

After running all tests, produce:

```
TEST EXECUTION REPORT — Phase <N>
Date: <YYYY-MM-DD>

MOVE TESTS:
  Total: <N>
  Passed: <N>
  Failed: <N>
  Failed tests:
    - <module>::<test_name> — <error message>

VITEST (per package):
  @dvconf/shared:
    Total: <N> | Passed: <N> | Failed: <N>
  @dvconf/signaling:
    Total: <N> | Passed: <N> | Failed: <N>
  @dvconf/cp-daemon:
    Total: <N> | Passed: <N> | Failed: <N>
  @dvconf/validator-daemon:
    Total: <N> | Passed: <N> | Failed: <N>

OVERALL: ALL PASS | <N> FAILURES
```

### Failure Handling

- **Test failure from domain agent's code**: Report to domain agent with file, test name, and error. Domain agent fixes.
- **Test failure from Verification Agent's generated test**: Verification Agent fixes their own test first. If the test is correct and code is wrong, report to domain agent.
- **Flaky test**: Mark as `[FLAKY]` in report, investigate root cause, don't block on flaky tests.

### Bug Logging

When the Verification Agent finds gaps or failures, **log each to the bug tracker**:

1. Determine the module: Move files → `.planning/bugs/onchain.md`, daemon files → `.planning/bugs/offchain.md`, client files → `.planning/bugs/client.md`
2. Append a bug entry for each test failure or integration mismatch:

```markdown
### BUG-<ON|OFF|FE>-<NNN>: <gap/failure title>
- **Level**: ERROR (test failure, integration mismatch) | WARN (weak test, missing boundary) | DEBUG (coverage gap, needs investigation)
- **Phase**: Phase <N>
- **Found by**: Verification
- **Module/File**: `<file path>::<function>`
- **Runtime error**: <actual test error output or "N/A">
- **Description**: <what the gap is and which REQ-ID it affects>
- **Status**: OPEN
- **Fixed by**: pending
```

3. Cross-domain integration mismatches (CRITICAL findings) are logged as ERROR level.
4. When domain agent fixes and tests pass on re-run, update status to FIXED.

---

## Step 5: Cross-Domain Integration Validation

This is the Verification Agent's unique contribution that NO other agent does.

### What to Validate

For every Integration Contract in the ADD:

```
CROSS-DOMAIN VALIDATION — Phase <N>
Date: <YYYY-MM-DD>

CONTRACT: OffChain calls OnChain control_plane_registry::register_cp
  Move signature: register_cp(registry: &mut CPRegistry, cap: &ControlPlaneCap, stake: &StakePosition, ctx: &mut TxContext)
  Daemon TX args: [cpRegistryId, capId, stakePositionId]
  Arg count:  Move=4 (3 + ctx) vs Daemon=3 ✅ MATCH (ctx is implicit)
  Arg types:  registry=ObjectID ✅, cap=ObjectID ✅, stake=ObjectID ✅
  Arg order:  registry→cap→stake ✅ MATCH
  Verdict:    PASS

CONTRACT: OffChain subscribes to MinerRegistered event
  Move event: registration::MinerRegistered { miner_id, region, bandwidth_mbps }
  Daemon handler: expects { minerId, region, bandwidthMbps }
  Field mapping: miner_id→minerId ✅, region→region ✅, bandwidth_mbps→bandwidthMbps ✅
  Verdict:    PASS

CONTRACT: OffChain calls OnChain room_manager::create_room
  Move signature: create_room(rm: &mut RoomManager, ...)
  Daemon TX args: [roomManagerId, ...]
  ...
  Verdict:    FAIL — arg[2] type mismatch: Move expects u64, daemon sends string
```

### Validation Process

1. Read the ADD Integration Contracts section
2. For each contract, read BOTH sides (Move source + TS source)
3. Compare signatures, types, order, event payloads
4. Report matches and mismatches
5. Any mismatch is a **CRITICAL** finding — report to both domain agents via Contract Change Protocol

---

## Interaction with Other Agents

| Scenario | Verification Agent does | Other agent does |
|---|---|---|
| **Phase completing** | Builds RTM, finds gaps, generates tests, runs all suites | Domain agents have already submitted code + their tests |
| **Gap found** | Reports gap with REQ-ID, generates test, may find code bug | Domain agent fixes code if test reveals bug |
| **Cross-domain mismatch** | Reports mismatch to both domains, triggers CC protocol | Domain agents update their code per CC notice |
| **Test failure** | Reports failure with context | Domain agent fixes if code is wrong; Verification fixes if test is wrong |
| **On-demand coverage check** | Builds RTM for specific module, reports coverage | Requesting agent reads coverage report |
| **New phase starting** | Reviews previous phase RTM for patterns | Architect includes integration points in ADD |

---

## Relationship to Other Review Agents

```
Domain Agent writes code + tests
  → QC reviews code QUALITY (rules, invariants, style)     — "Is the code correct?"
  → Verification reviews COVERAGE (requirements, gaps, E2E) — "Is everything tested?"
  → Architect reviews STRUCTURE (boundaries, dependencies)   — "Is it well-designed?"
```

- **QC** and Verification are complementary, not overlapping
- QC checks "does this test use named constants?" — Verification checks "does a test exist for REQ-07?"
- QC reads code — Verification reads requirements AND code
- Both must pass before phase completion

---

## DVConf-Specific Rules

### Sui Move Test Patterns

- Use `test_helpers::setup()` for Phase 1 tests, `setup_phase2()` for Phase 2+
- Use `test_helpers::mint_to()` for creating test coins
- Every `#[expected_failure]` test with `Coin<T>` return must bind + transfer
- All assertions use named constants from `constants.move` or `test_helpers` accessors

### OffChain Test Patterns

- Use `vi.hoisted` mock pattern for Sui SDK mocking
- Mock `SuiClient` methods, not the entire module
- Test TX argument construction separately from execution
- Use `describe` blocks per Move function being called

### Minimum Coverage Standard

Before a phase can be marked complete:
- **100% REQ-ID coverage** — every requirement has at least one test
- **100% success criteria coverage** — every criterion has proof
- **100% abort code coverage** — every `E_*` constant has an `#[expected_failure]` test
- **All Integration Contracts validated** — cross-domain signature match confirmed
- **All test suites pass** — zero failures (flaky tests investigated)

### Test Execution is Non-Negotiable

The Verification Agent MUST run tests, not just review test code. Reading a test file and saying "looks correct" is not verification. Execute `sui move test` and `pnpm test`, report actual results.
