# Phase 5: Formal Verification & Phase 2 Deploy - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

## Phase Boundary

Phase 5 closes documentation gaps from the v1.0 audit: Phases 1 and 2 were UAT-verified (10/10 each) but never got formal VERIFICATION.md files with RTMs. This phase generates those verification docs and prepares a deploy script for Phase 2 testnet deployment. The actual testnet deploy is deferred until the user explicitly requests it — local testing only.

## Implementation Decisions

### Verification Docs
- Generate `phase-1-RTM.md` and `phase-2-RTM.md` in `docs/architecture/phases/`
- Map every FOUND-XX and REG-XX requirement to specific test functions and source code evidence
- Follow the format established by `phase-4-RTM.md` (cross-domain validation, test coverage matrix, gap analysis, test execution report)
- Run `sui move test` to confirm all 79 tests still pass and report results

### Deploy Script
- Write a TypeScript deploy script that automates: `sui client upgrade` → call `create(&AdminCap)` on each of the 5 registries
- Store in project root or a `scripts/` directory
- Script records new object IDs and appends them to `.env.testnet`
- **Do NOT execute** the deploy — only prepare the script for future use

### Claude's Discretion
- RTM format details (table structure, evidence level) — follow phase-4-RTM.md as template
- Deploy script location and naming
- Whether to split verification into two separate docs or one combined doc

## Specific Ideas

- Phase 1 requirements (FOUND-01 through FOUND-12): map to tests in `tests/core/`, `tests/miner/`, `tests/access/`
- Phase 2 requirements (REG-01 through REG-15): map to tests in `tests/registry/`
- Phase 4 RTM is a good template: `docs/architecture/phases/phase-4-RTM.md`
- Each registry has `create(&AdminCap)` entry point for post-upgrade initialization
- Deploy script needs: UpgradeCap ID, AdminCap ID, package ID (all in `.env.testnet`)

## Existing Code Insights

### Reusable Assets
- `.env.testnet` — Phase 1 object IDs already recorded
- `docs/architecture/phases/phase-4-RTM.md` — RTM template to follow
- `tests/helpers.move` — shared test setup functions (`setup()`, `setup_phase2()`)
- All 79 Move tests passing (confirmed 2026-03-07)

### Established Patterns
- Error code namespaces: 100-404 (Phase 1), 500-542 (Phase 2)
- All registries use `create(&AdminCap)` for post-upgrade initialization + `init_for_testing()` for tests
- Phase 1 deployed via `sui client publish`, not `test-publish`
- Gas budget: 500M MIST needed for publish (~0.114 SUI actual)

### Integration Points
- Deploy script reads `.env.testnet` for existing object IDs
- Deploy script appends new registry object IDs to `.env.testnet`
- Daemons (sibling repo `dvconf-daemons`) will consume the new object IDs

## Deferred Ideas

- **Testnet deploy execution**: deferred until user explicitly requests it (testnet is slow/expensive)
- **REQUIREMENTS.md checkbox updates**: mark FOUND-03, FOUND-12, REG-15 as satisfied after verification docs exist
- **TD-005 resolution note**: Phase 4 resolved it, but TECH_DEBT.md still lists it as active — update during this phase

## Revision Log

- **2026-03-07 (initial):** Context gathered via /dvconf:discuss-phase
