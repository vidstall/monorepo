# Phase 5 Plan: Formal Verification & Phase 2 Deploy
Date: 2026-03-07

## Goal
Missing VERIFICATION.md files for Phases 1-2 are generated, and Phase 2 registries are deployed to testnet

## Success Criteria
1. Phase 1 VERIFICATION.md exists with all 12 FOUND requirements verified
2. Phase 2 VERIFICATION.md exists with all 15 REG requirements verified
3. Phase 2 registries deployed to testnet with object IDs recorded in .env.testnet

## Requirements Covered
FOUND-03, FOUND-12, REG-15

## Tasks

### Task 1: Generate Phase 1 RTM
- **Agent**: Verification
- **Files**: `docs/architecture/phases/phase-1-RTM.md`
- **Requirements**: FOUND-03, FOUND-12
- **Depends on**: None
- **Description**: Build a Requirements Traceability Matrix mapping all 12 FOUND requirements (FOUND-01 through FOUND-12) to specific test functions and source code evidence. Follow the format of `phase-4-RTM.md`. Map each requirement to tests in `tests/core/`, `tests/miner/`, `tests/access/`. Include gap analysis (expect no gaps — Phase 1 was QC-approved). Run `sui move test` and include test execution report with all 79 tests passing.

### Task 2: Generate Phase 2 RTM
- **Agent**: Verification
- **Files**: `docs/architecture/phases/phase-2-RTM.md`
- **Requirements**: REG-15
- **Depends on**: None
- **Description**: Build a Requirements Traceability Matrix mapping all 15 REG requirements (REG-01 through REG-15) to specific test functions and source code evidence. Follow the format of `phase-4-RTM.md`. Map each requirement to tests in `tests/registry/`. Include cross-module validation where relevant (e.g., REG-12 independent shared objects, REG-14 paused flag enforcement across all registries, REG-15 event emission). Include gap analysis and test execution report.

### Task 3: Write Phase 2 deploy script
- **Agent**: OffChain
- **Files**: `scripts/deploy-phase2.ts`
- **Requirements**: (supports SC-3)
- **Depends on**: None
- **Description**: Write a TypeScript deploy script that:
  1. Reads `.env.testnet` for existing Phase 1 object IDs (PackageId, AdminCap, UpgradeCap)
  2. Runs `sui client upgrade` to publish the updated package with Phase 2 modules
  3. Calls `create(&AdminCap)` on each of the 5 registries (UserRegistry, ValidatorRegistry, RelayRegistry, ControlPlaneRegistry, RoomManager)
  4. Extracts new object IDs from TX effects
  5. Appends registry object IDs to `.env.testnet`
  - **Do NOT execute the script** — prepare it for future manual use only
  - Use `@mysten/sui` SDK, follow patterns from existing daemon code

### Task 4: Update REQUIREMENTS.md traceability
- **Agent**: Verification
- **Files**: `.planning/REQUIREMENTS.md`
- **Requirements**: FOUND-03, FOUND-12, REG-15
- **Depends on**: Task 1, Task 2
- **Description**: After RTMs confirm full coverage, update the traceability table in REQUIREMENTS.md to mark FOUND-03, FOUND-12, and REG-15 as satisfied (change from "Pending" to "Done" with phase reference). Also update any deferred notes in CONTEXT.md (e.g., TD-005 resolution in TECH_DEBT.md if applicable).

## Execution Order

```
Task 1 (Phase 1 RTM)  ──┐
Task 2 (Phase 2 RTM)  ──┼──→ Task 4 (Update REQUIREMENTS.md)
Task 3 (Deploy script) ──┘    (independent, can run in parallel with 1 & 2)
```

- **Parallel**: Tasks 1, 2, and 3 are fully independent (different files, different concerns)
- **Sequential**: Task 4 depends on Tasks 1 and 2 completing (needs RTM results to confirm coverage)

## Risks & Open Questions

- **No risks identified** — this phase is documentation + scripting only, no production code changes
- **Deploy script is write-only** — actual testnet deployment deferred until user explicitly requests it
- **Test count**: Currently 79 Move tests. RTMs must confirm all pass. If any fail, investigate before proceeding.
