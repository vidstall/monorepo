# Phase 1: Foundation Validation - Research

**Researched:** 2026-03-04
**Domain:** Sui Move contract validation and testnet deployment
**Confidence:** HIGH

## Summary

Phase 1 is a validation-and-deploy phase, not an implementation phase. All 8 source modules and 3 test files (34 tests total) already exist and pass. The work consists of two distinct activities: (1) a QC Agent re-review of every module against the Phase 1 spec (`docs/phase1/`) and the system architecture spec (`docs/decentralized_video_conference-rev4.md`), fixing any findings that affect correctness, and (2) deploying the package to Sui testnet via `sui client publish` and recording the resulting object IDs.

The previous QC review found issues C1 and C2 which were fixed. The re-review must confirm those fixes held and check for any regressions. No new features are being added.

**Primary recommendation:** Run QC review using the full OnChain checklist from `docs/skills/QC_AGENT_SKILL.md`, fix only spec-correctness issues, then deploy to testnet and capture object IDs in `.env.testnet`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Full spec compliance review: every module checked against `docs/phase1-foundation.md` and `docs/decentralized_video_conference-rev4.md`
- Verify all error codes match the namespace table (100s network_registry, 200s staking, 300s miner_store, 400s registration)
- Verify all cap constructors are `public(package)` with no external minting paths
- Verify paused-flag enforcement on all state-mutating entry points
- Verify basis-point invariants (weights sum to 10,000, ratios sum to 10,000)
- Code quality issues (naming, comments, dead code) are noted but only fixed if they violate spec correctness
- QC Agent uses `docs/skills/QC_AGENT_SKILL.md` checklist
- Use existing testnet address: `0x3357c00f615f4cc1d89e0b580603ff9f474ee88bff89aecf587caf9075f5d306`
- Get gas from faucet: `https://faucet.testnet.sui.io/`
- Deploy command: `sui client publish --gas-budget 100000000`
- Record object IDs in a `.env.testnet` file at project root (PackageId, NetworkRegistry, MinerStore, TreasuryCap)
- Also update `.planning/PROJECT.md` context section with deployed IDs
- Confirm publish transaction succeeded (check explorer or CLI output)
- No on-chain smoke tests in this phase -- that is Phase 2 territory when registries exist
- Record the publish transaction digest for reference

### Claude's Discretion
- Order of module review (any order is fine as long as all 8 are covered)
- Exact format of `.env.testnet` entries
- Whether to batch-fix QC findings or fix-as-found

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FOUND-01 | DVCONF fungible token deployed on Sui with treasury cap | Verified `token.move` exists in `sources/core/`; deploy captures TreasuryCap object ID |
| FOUND-02 | NetworkRegistry singleton stores global config | Verified `network_registry.move` exists; deploy captures NetworkRegistry shared object ID |
| FOUND-03 | Scoring weights sum to 10,000 basis points; reward ratios sum to 10,000 | QC checklist item: arithmetic invariants; verified in `docs/phase1/flows.md` UC6 |
| FOUND-04 | Node registration requires minimum stake (aborts E_INSUFFICIENT_STAKE) | QC checklist: error codes; UC1 flow shows abort 400 path |
| FOUND-05 | Registered nodes can top up stake and withdraw (when unlocked) | QC checklist: stake lock enforcement; UC2/UC3 flows |
| FOUND-06 | Unregister aborts with E_STAKE_LOCKED if locked, E_NOT_OWNER if not owner | QC checklist: error codes 401, 402; UC3 flow |
| FOUND-07 | All cap constructors are public(package) -- no external cap minting | QC checklist: visibility & access control section |
| FOUND-08 | Registration and top_up_stake abort E_PROTOCOL_PAUSED when paused | QC checklist: invariant enforcement; UC1/UC2 flows show abort 403 |
| FOUND-09 | MinerStore tracks validator set with package-private access | QC checklist: visibility rules; `miner_store::validator_set()` is `public(package)` |
| FOUND-10 | CP queries module provides external read access to validator set | Verified `cp_queries.move` exists; UC5 flow documents the query pattern |
| FOUND-11 | All error codes match namespace table | QC checklist: error codes section; namespace table in `docs/phase1/README.md` |
| FOUND-12 | All 34 existing tests pass with no regressions | Test count verified: 9 + 18 + 7 = 34; command: `sui move test` |
</phase_requirements>

## Standard Stack

### Core
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| Sui CLI | latest (testnet branch) | Build, test, publish Move packages | Official toolchain |
| Sui Move | 2024.beta edition | Smart contract language | Defined in Move.toml |
| Sui Framework | framework/testnet rev | Standard library dependency | Defined in Move.toml |

### Supporting
| Tool | Purpose | When to Use |
|------|---------|-------------|
| Sui Testnet Faucet | Get SUI gas tokens for deployment | Before `sui client publish` |
| Sui Explorer | Verify published package and objects | After deployment to confirm success |

### Package Configuration (Move.toml)
```toml
[package]
name = "dvconf_contracts"
version = "0.1.0"
edition = "2024.beta"

[dependencies]
Sui = { git = "https://github.com/MystenLabs/sui.git", subdir = "crates/sui-framework/packages/sui-framework", rev = "framework/testnet" }

[addresses]
dvconf = "0x0"
```

The `dvconf = "0x0"` address is the standard placeholder that gets replaced with the actual package address on publish.

## Architecture Patterns

### Existing Project Structure (Verified)
```
sources/
  core/
    constants.move          -- all numeric parameters
    token.move              -- DVCONF fungible coin + TreasuryCap
    network_registry.move   -- singleton governance config + AdminCap
  access/
    caps.move               -- ControlPlaneCap, MinerCap
    cp_queries.move         -- CP-gated read queries into MinerStore
  miner/
    miner_store.move        -- shared store of miner profiles + role sets
    staking.move            -- StakePosition object (owned, per miner)
    registration.move       -- public entry points for miner lifecycle

tests/
    helpers.move                        -- shared setup(), mint_to(), do_register()
    core/network_registry_tests.move    -- UC6 governance (9 tests)
    miner/registration_tests.move       -- UC1-4 register/unregister/update (18 tests)
    access/cp_queries_tests.move        -- UC5 CP queries (7 tests)
```

### QC Review Pattern
The QC Agent follows a structured checklist defined in `docs/skills/QC_AGENT_SKILL.md`. The review covers:
1. Reversal Protocol compliance (N/A for review-only, relevant if fixes needed)
2. Compilation and structure
3. Error codes (named constants, correct namespace, documented in README)
4. Arithmetic (basis-point sums)
5. Visibility and access control
6. Invariant enforcement (paused flag, stake lock, slash returns Coin)
7. Object lifecycle
8. Test assertions (no magic numbers)

### Deployment Pattern
The `sui client publish` command:
1. Compiles all modules
2. Publishes the package to the active network
3. Runs all `init` functions (which create shared objects like NetworkRegistry, MinerStore and transfer owned objects like AdminCap, TreasuryCap)
4. Returns a structured output with sections: Transaction Data, Transaction Effects, Object Changes, Balance Changes
5. The "Object Changes > Published Objects" section contains the PackageID
6. The "Object Changes > Created Objects" section lists all objects with their ObjectID, Owner type (Shared/Account Address), and ObjectType

### .env.testnet Format
```bash
# DVConf Testnet Deployment
# Published: <date>
# Transaction Digest: <digest>

SUI_NETWORK=testnet
PACKAGE_ID=0x...
NETWORK_REGISTRY_ID=0x...
MINER_STORE_ID=0x...
TREASURY_CAP_ID=0x...
ADMIN_CAP_ID=0x...
UPGRADE_CAP_ID=0x...
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Object ID extraction from publish output | Manual parsing of text output | `sui client publish --json` with jq/script | JSON output is machine-parseable; text output format can change |
| Testnet gas acquisition | Custom scripts | `curl --location --request POST 'https://faucet.testnet.sui.io/v1/gas' --header 'Content-Type: application/json' --data-raw '{"FixedAmountRequest":{"recipient":"<ADDRESS>"}}'` | Official faucet API |

## Common Pitfalls

### Pitfall 1: Gas Budget Too Low for Package Publish
**What goes wrong:** `sui client publish` fails with insufficient gas
**Why it happens:** Publishing a package with 8 modules costs more gas than a single transaction
**How to avoid:** Use `--gas-budget 100000000` (100M MIST = 0.1 SUI) -- already specified in user decisions
**Warning signs:** Transaction fails with gas-related error

### Pitfall 2: Wrong Active Environment
**What goes wrong:** Package published to devnet instead of testnet, or publish fails because CLI points at localnet
**Why it happens:** Sui CLI remembers the last active environment
**How to avoid:** Run `sui client active-env` before publishing; switch with `sui client switch --env testnet`
**Warning signs:** Object IDs not found on testnet explorer

### Pitfall 3: Faucet Rate Limiting
**What goes wrong:** Faucet returns error when requesting gas tokens
**Why it happens:** The Sui testnet faucet is rate-limited
**How to avoid:** Request gas well before the deployment step; if rate-limited, wait and retry. Each faucet request gives enough SUI for multiple publishes.
**Warning signs:** HTTP 429 or similar rate-limit response from faucet

### Pitfall 4: QC Fix Breaks Existing Tests
**What goes wrong:** A spec-correctness fix in a source module causes test failures
**Why it happens:** Tests may depend on the old (incorrect) behavior
**How to avoid:** Run `sui move test` after every fix. If a fix changes behavior, update the corresponding test in the same commit.
**Warning signs:** Test count drops below 34, or existing tests fail

### Pitfall 5: Missing UpgradeCap After Publish
**What goes wrong:** UpgradeCap object ID not recorded, making future package upgrades impossible
**Why it happens:** Focus on PackageId/NetworkRegistry/MinerStore and forgetting the UpgradeCap
**How to avoid:** Record ALL created object IDs from the publish output, especially UpgradeCap
**Warning signs:** Only 3-4 IDs in `.env.testnet` when there should be more

### Pitfall 6: Testnet Address Not Configured
**What goes wrong:** Publish uses a different address than the one with faucet gas
**Why it happens:** Sui CLI may have multiple addresses configured
**How to avoid:** Run `sui client active-address` and confirm it matches `0x3357...5d306`
**Warning signs:** "Insufficient gas" despite faucet request succeeding

## Code Examples

### Pre-Deployment Checklist Commands
```bash
# Verify all tests pass
sui move test --silence-warnings

# Verify active environment is testnet
sui client active-env

# Switch to testnet if needed
sui client switch --env testnet

# Verify active address matches the expected one
sui client active-address

# Request gas from faucet (if needed)
curl --location --request POST 'https://faucet.testnet.sui.io/v1/gas' \
  --header 'Content-Type: application/json' \
  --data-raw '{"FixedAmountRequest":{"recipient":"0x3357c00f615f4cc1d89e0b580603ff9f474ee88bff89aecf587caf9075f5d306"}}'

# Check balance
sui client gas
```

### Publish Command
```bash
# Publish to testnet with JSON output for easier parsing
sui client publish --gas-budget 100000000 --json

# Or human-readable output
sui client publish --gas-budget 100000000
```

### Post-Publish Verification
```bash
# Verify package exists on testnet
sui client object <PACKAGE_ID>

# Verify shared objects
sui client object <NETWORK_REGISTRY_ID>
sui client object <MINER_STORE_ID>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sui move publish` | `sui client publish` | Sui CLI restructure (2024) | Command moved under `client` subcommand |
| Manual gas budget guessing | `--gas-budget` with generous allocation | Ongoing | 100M MIST is safe for multi-module packages |
| `edition = "2024"` | `edition = "2024.beta"` | 2024 | This project uses beta edition features |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Sui Move Test (built into `sui move test`) |
| Config file | `Move.toml` (package definition) |
| Quick run command | `sui move test --silence-warnings` |
| Full suite command | `sui move test --silence-warnings` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | DVCONF token deployed with treasury cap | smoke (deploy) | `sui move test --filter token` | N/A (init function, tested via registration) |
| FOUND-02 | NetworkRegistry stores global config | unit | `sui move test --filter network_registry_tests` | Yes |
| FOUND-03 | Weights sum to 10,000; ratios sum to 10,000 | unit | `sui move test --filter network_registry_tests` | Yes |
| FOUND-04 | Registration requires minimum stake | unit | `sui move test --filter registration_tests` | Yes |
| FOUND-05 | Top up and withdraw work | unit | `sui move test --filter registration_tests` | Yes |
| FOUND-06 | Unregister aborts 401/402 | unit | `sui move test --filter registration_tests` | Yes |
| FOUND-07 | Cap constructors are public(package) | manual-only | QC review of source code | N/A (visibility is compile-time) |
| FOUND-08 | Registration/top_up abort 403 when paused | unit | `sui move test --filter registration_tests` | Yes |
| FOUND-09 | MinerStore tracks validator set (package-private) | manual-only | QC review of visibility modifiers | N/A |
| FOUND-10 | CP queries provides external read access | unit | `sui move test --filter cp_queries_tests` | Yes |
| FOUND-11 | Error codes match namespace table | manual-only | QC review cross-referencing `docs/phase1/README.md` | N/A |
| FOUND-12 | All 34 tests pass | unit | `sui move test --silence-warnings` | Yes |

### Sampling Rate
- **Per task commit:** `sui move test --silence-warnings`
- **Per wave merge:** `sui move test --silence-warnings`
- **Phase gate:** Full suite green + QC APPROVED + successful testnet publish

### Wave 0 Gaps
None -- existing test infrastructure covers all phase requirements. All 34 tests already exist and pass. No new test files needed for this validation-only phase.

## Open Questions

1. **Sui CLI version compatibility**
   - What we know: Move.toml uses `edition = "2024.beta"` and `rev = "framework/testnet"`
   - What is unclear: Whether the installed Sui CLI version matches the framework revision
   - Recommendation: Run `sui --version` before attempting publish; if version mismatch, update CLI

2. **Testnet environment setup**
   - What we know: Address `0x3357...5d306` is the target; faucet URL is known
   - What is unclear: Whether the testnet environment is already configured in the Sui CLI keystore
   - Recommendation: Verify with `sui client envs` and `sui client active-env` before deploying

3. **Objects created by init functions**
   - What we know: `token.move` creates TreasuryCap; `network_registry.move` creates NetworkRegistry (shared) and AdminCap; `miner_store.move` creates MinerStore (shared)
   - What is unclear: Exact list of all objects created -- need to trace every `init` function
   - Recommendation: Use `--json` output and capture ALL created objects, not just the expected ones

## Sources

### Primary (HIGH confidence)
- Project source files: 8 Move modules verified present in `sources/`
- Project test files: 3 test files + 1 helper verified present in `tests/`
- `docs/phase1/README.md` -- module map, error code namespace, cross-module invariants
- `docs/phase1/flows.md` -- UC1-UC6 interaction flows
- `docs/skills/QC_AGENT_SKILL.md` -- full QC review checklist
- `docs/skills/ONCHAIN_AGENT_SKILL.md` -- OnChain coding standards and protocols
- `Move.toml` -- package configuration and dependencies

### Secondary (MEDIUM confidence)
- [Sui Publish a Package docs](https://docs.sui.io/guides/developer/first-app/publish) -- publish command output format
- [Sui Get Coins from Faucet](https://docs.sui.io/guides/developer/getting-started/get-coins) -- faucet usage
- [Sui Client CLI reference](https://docs.sui.io/references/cli/client) -- CLI commands

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- project already has Move.toml with pinned dependencies; no new libraries needed
- Architecture: HIGH -- all code exists; no architectural decisions to make
- Pitfalls: HIGH -- deployment pitfalls are well-documented; QC process is defined by existing skill files
- Deployment: MEDIUM -- exact CLI output format may vary by Sui CLI version; `--json` flag recommended

**Research date:** 2026-03-04
**Valid until:** 2026-04-04 (stable -- validation phase with no new dependencies)
