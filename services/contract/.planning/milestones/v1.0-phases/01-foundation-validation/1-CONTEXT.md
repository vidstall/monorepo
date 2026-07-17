# Phase 1: Foundation Validation - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Re-review all 8 existing foundation modules against the spec, fix any QC findings, confirm all 34 tests pass, then deploy to Sui testnet and record object IDs. No new feature code — this is validation and deployment only.

</domain>

<decisions>
## Implementation Decisions

### QC Review Scope
- Full spec compliance review: every module checked against `docs/phase1-foundation.md` and `docs/decentralized_video_conference-rev4.md`
- Verify all error codes match the namespace table (100s network_registry, 200s staking, 300s miner_store, 400s registration)
- Verify all cap constructors are `public(package)` with no external minting paths
- Verify paused-flag enforcement on all state-mutating entry points
- Verify basis-point invariants (weights sum to 10,000, ratios sum to 10,000)
- Code quality issues (naming, comments, dead code) are noted but only fixed if they violate spec correctness
- QC Agent uses `docs/skills/QC_AGENT_SKILL.md` checklist

### Testnet Deployment
- Use existing testnet address: `0x3357c00f615f4cc1d89e0b580603ff9f474ee88bff89aecf587caf9075f5d306`
- Get gas from faucet: `https://faucet.testnet.sui.io/`
- Deploy command: `sui client publish --gas-budget 100000000`
- Record object IDs in a `.env.testnet` file at project root (PackageId, NetworkRegistry, MinerStore, TreasuryCap)
- Also update `.planning/PROJECT.md` context section with deployed IDs

### Post-Deploy Verification
- Confirm publish transaction succeeded (check explorer or CLI output)
- No on-chain smoke tests in this phase — that's Phase 2 territory when registries exist
- Record the publish transaction digest for reference

### Claude's Discretion
- Order of module review (any order is fine as long as all 8 are covered)
- Exact format of `.env.testnet` entries
- Whether to batch-fix QC findings or fix-as-found

</decisions>

<specifics>
## Specific Ideas

- The 8 modules to review: `constants.move`, `token.move`, `network_registry.move`, `caps.move`, `cp_queries.move`, `miner_store.move`, `staking.move`, `registration.move`
- Test files: `helpers.move`, `network_registry_tests.move`, `registration_tests.move`, `cp_queries_tests.move`
- Previous QC review found C1 + C2 issues which were fixed — re-review should confirm those fixes held

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/helpers.move`: shared `setup()`, `mint_to()`, `do_register()` — used by all test files
- Error code constants already defined in each module — verify against namespace table

### Established Patterns
- `public(package)` for all cap constructors and internal functions
- Basis-point math (u64) throughout — no floating point
- `StakePosition` has `key` only (no `store`) — transfer via `staking::transfer_to()`
- `miner_store::validator_set()` is `public(package)` — external access only via `cp_queries`

### Integration Points
- Phase 2 registries will depend on: `NetworkRegistry` (config), `MinerStore` (validator tracking), `AdminCap` / `RelayCap` (access control)
- Deployed object IDs from this phase are inputs to Phase 2 deployment

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-foundation-validation*
*Context gathered: 2026-03-04*
