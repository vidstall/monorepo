# DVConf — Agentic AI Development Team
> Thesis Project: Decentralized Video Conference on Sui  
> Team size: 2 developers · Stack: Sui Move + Node.js + React + WebRTC

---

## Workflow

**GSD owns execution. Domain agents own module design. Architect owns system integration. Skill files own quality.**

- GSD controls *what* gets built and *when* -- phases, plans, task sequencing via `.planning/`
- Domain agents propose *module-level designs* (Design Proposals) -- they know their domain best
- Architect Agent reviews proposals, integrates into a unified ADD, proposes improvements -- BLOCKING until PM approves
- During implementation, domain agents build freely (logging Design Notes) -- Architect visits asynchronously (advisory)
- Skill files control *how* it gets built -- coding standards, invariants, checklists
- Phase workflow: `/dvconf:discuss-phase` → `/dvconf:plan-phase` → `/dvconf:design-phase` → `/dvconf:execute-phase` → `/dvconf:verify-phase`
- The executor reads `.planning/AGENT_ROUTING.md` to find the correct skill file for each task
- QC review is mandatory before any task is marked complete (GSD spawns QC Agent)
- Architect verifies structural conformance after implementation (code matches ADD)

Skill files (read before writing any code in that domain):

| Domain | Skill file |
|---|---|
| Sui Move contracts | `docs/skills/ONCHAIN_AGENT_SKILL.md` |
| Node.js daemons | `docs/skills/OFFCHAIN_AGENT_SKILL.md` |
| React client | `docs/skills/FE_AGENT_SKILL.md` |
| Code review | `docs/skills/QC_AGENT_SKILL.md` |
| Requirements coverage & test execution | `docs/skills/VERIFICATION_AGENT_SKILL.md` |
| Architecture/spec | `docs/skills/PM_AGENT_SKILL.md` |
| Architecture visualization & tech debt | `docs/skills/ARCHITECT_AGENT_SKILL.md` |

Spec documents -- read before any task that touches design or implementation:
- `docs/decentralized_video_conference-rev4.md` -- full system architecture
- `docs/phase1/README.md` -- Phase 1 Sui Move implementation spec
- Phase plans: `.planning/phases/<phase-name>/PLAN.md`

Architecture artifacts (produced by swarm agents, not GSD):
- `docs/architecture/phases/` -- ADDs, RTMs, verification reports per phase
- `docs/architecture/contract-changes/` -- CC notices for cross-domain interface changes
- `docs/architecture/proposals/` -- architecture alternative proposals
- `docs/architecture/TECH_DEBT.md` -- known tech debt registry

For ad-hoc tasks outside GSD phases, prefix your message with the domain name (e.g., "OnChain Agent: review this module") to invoke domain-specific expertise. If a task crosses boundaries, the PM Agent breaks it into sub-tasks and routes them. Use "Architect Agent: <task>" for diagram generation, tech debt review, or architecture proposals.

**Cross-domain communication**: When a domain agent changes an Integration Contract (shared interface), they write a CONTRACT CHANGE notice directly to affected domains — no Architect relay. See `ARCHITECT_AGENT_SKILL.md` § Contract Change Protocol.

---

## Agent Responsibilities (Summary)

**🗂 PM Agent** — Architectural truth, design trade-off analysis, sprint tracking, requirements discussion, spec challenge and evolution. Uses `PM_AGENT_SKILL.md` for structured review methodology and collaborative requirements protocol.

**⛓ OnChain Agent** — Sui Move contracts and tests. Follows error code namespaces, basis-point invariants, `public(package)` visibility rules, paused-flag enforcement, and the Change Reversal Protocol on all edits.

**🖧 OffChain Agent** — Node.js / TypeScript daemons: Control Plane, Validator, Signaling, SFU relay, MCU relay. Strict SDK usage, exponential backoff, dual-key signing, mediasoup configuration, and the Change Reversal Protocol on all edits.

**🖥 FE Agent** — React / TypeScript client. Chain state as source of truth, `mediasoup-client` WebRTC, `@mysten/dapp-kit` wallet, adaptive SFU/MCU session view, and the Change Reversal Protocol on all edits.

**🔍 QC Agent** — Reviews code quality against checklists (error codes, visibility, invariants, Change Reversal Protocol). A QC `APPROVED` is required before any PM sign-off. Uses `QC_AGENT_SKILL.md`.

**🧪 Verification Agent** — Validates requirements coverage through testing. Maps REQ-IDs to tests (RTM), identifies gaps, generates missing tests (unit/integration/E2E), runs all test suites, validates cross-domain integration (Move signatures match daemon TX calls). Runs after QC, before phase completion. Uses `VERIFICATION_AGENT_SKILL.md`.

**🏗 Architect Agent** — Technical Lead for system integration. **Design phase (BLOCKING)**: reviews domain agent Design Proposals, integrates into unified ADD, proposes improvements, generates PlantUML blueprints. **Implementation phase (NON-BLOCKING)**: visits asynchronously, reads Design Notes, writes advisory feedback. **Post-implementation**: verifies code conforms to ADD. Maintains tech debt registry, proposes architecture alternatives. Does NOT write implementation code or design modules alone — domain agents propose, Architect reviews and integrates. Uses `ARCHITECT_AGENT_SKILL.md`.

---

## Source of Truth Rules

These rules are absolute across all agents and all phases. If any generated code contradicts them, the code is wrong.

| Rule | Detail |
|---|---|
| Spec is canonical | `decentralized_video_conference-rev4.md` and `docs/phase1/README.md` override all agent assumptions |
| No floating point | All math is basis points (integers). Weights sum to 10_000. Ratios sum to 10_000. |
| Cap constructors are package-private | `public(package)` — never `public`. No external cap minting. |
| Paused flag always checked | Every state-mutating entry point checks `!is_paused(registry)` |
| Validator identity hidden during session | Wallet A ↔ Wallet B link never appears on-chain until post-session proof |
| Stake lock enforced | `withdraw_stake()` aborts with `E_STAKE_LOCKED` if `locked == true` |
| Slash returns a Coin | Slashing never burns or redistributes — the economic layer decides |
| RTT is validator-probed | Never use self-reported RTT. Only `validator_probed_rtt` from `RelayRegistry`. |
| Rewards are work-based | `BASE_RATE × median_bytes_transferred × quality_multiplier` — not membership-based |
| Chain carries no media | No video or audio data ever touches the Sui chain |

---

## Build Status

Phase tracking: `.planning/ROADMAP.md` (canonical source).
GSD is simplified — keeps phase structure, ROADMAP, REQUIREMENTS, STATE, PROJECT. Workflow toggles removed (swarm agents handle research, verification, quality gates).
Architectural phases (Room Lifecycle, Economic Layer, Client App) deferred to v2.

---

## Open Questions

Resolve before the phase that depends on them. Ask the PM Agent to propose a resolution.

| Question | Blocks | Status |
|---|---|---|
| Room size threshold for SFU -> MCU switch | v3 | Deferred v3 (default: 6 participants) |
| Can a room run SFU + MCU simultaneously (hybrid)? | -- | Resolved: NO. One mode per room for simplicity. |
| Minimum relay nodes per room (redundancy) | -- | Resolved: 2 (constants.move DEFAULT_MIN_RELAYS_PER_ROOM) |
| Relay failover mid-session -- reconnect flow | v3 | Deferred v3 (Phase 14 integration) |
| Region granularity for relay scoring | -- | Resolved: string-match region in CP scoring |
| TURN credential distribution without central server | v3 | Deferred v3 (relay nodes in Phase 12) |
| Validator session wallets: pre-registered vs fresh per session | -- | Resolved: pre-registered (ValidatorRegistry dual-key mapping) |
| BASE_RATE value and governance mechanism | -- | Resolved: fixed constant; governance deferred post-thesis |
| Minimum validators per room for median to be statistically valid | v3 | Deferred v3 (default: 3; economic layer not in v1/v2) |
| Signaling node stake threshold and reward mechanism | v3 | Open -- needs design before Phase 11 |
| Signaling node slashing criteria (what constitutes "dropping connections") | v3 | Open -- needs design before Phase 11 |

<!-- QuangFlow Configuration (auto-appended by installer) -->

# {{PROJECT_NAME}}

## Tech Stack
- (TBD after brainstorm)

## Conventions
- All phase artifacts save to ./plans/{feature-slug}/
- Feature slug derived from `/qf-1::brainstorm` arguments (kebab-case)
- Milestone artifacts save to ./plans/{feature-slug}/milestone-{N}/

## Milestone System
Large projects split into milestones (milestone-1, milestone-2, ...).
Each milestone runs the full phase flow but scoped to its subset of requirements.

- Project-level files: REQUIREMENTS.md, CONTEXT.md, OPEN_QUESTIONS.md
- Milestone-level files: DESIGN.md, ROADMAP.md, GAPS.md, REVIEW.md, QA-REPORT.md, STATUS.md
- Agent auto-recommends splitting when 8+ requirements or 3+ distinct functional areas detected
- User can override: "single milestone" or "split into N milestones"

### Directory Structure
```
./plans/{feature-slug}/
├── REQUIREMENTS.md              <- master, tagged [M1], [M2], etc. + team_composition YAML
├── CONTEXT.md                   <- locked decisions (project-wide)
├── OPEN_QUESTIONS.md            <- unresolved items
├── BUGLOG.md                    <- bug log with severity, bookmarks, triage status (Phase 5)
├── milestone-1/
│   ├── DESIGN.md                <- chosen architecture + rejected options
│   ├── ROADMAP.md               <- phases with deliverables + done criteria
│   ├── GAPS.md                  <- tech debt + gap findings (from tech-lead/verify)
│   ├── REVIEW.md                <- tech-lead code review report
│   ├── QA-REPORT.md             <- test results + requirement coverage matrix
│   ├── STATUS.md                <- PM progress report + session resume context
│   └── design/                  <- domain-engineer outputs (team mode)
│       ├── OVERVIEW.md          <- system components + Mermaid flowchart
│       ├── MODULES.md           <- module boundaries + Mermaid class diagram
│       ├── SEQUENCES.md         <- user flow sequence diagrams (Mermaid)
│       └── CONTRACTS.md         <- API endpoints, shared types, DB schema
├── milestone-2/
│   └── ...
```

### Bug Log Convention
Log files organized by source. Configure paths in CONTEXT.md or let `/qf-5::maintain` auto-discover:
```
./logs/
├── backend/error.log            <- BE errors + exceptions
├── backend/app.log              <- BE general log
├── frontend/error.log           <- FE errors (JS, build failures)
└── infra/ci.log                 <- CI/CD logs (optional)
```
Severity: CRITICAL > ERROR > WARNING > INFO. See `/qf-5::maintain` for full protocol.

## Phase Workflow
This project uses a 5-phase QuangFlow lifecycle:

**Build phases (per milestone):**
0. `/qf-0::init <idea>` — project setup, codebase scan, create CONTEXT.md (run once per feature)
1. `/qf-1::brainstorm` — requirements discovery + milestone split + team suggestion
2. `/qf-2::design` — structural options + trade-offs + team refinement (per milestone)
3. `/qf-3::handoff` — execution artifacts + SHIP/REFINE/SOLO gate (per milestone)
4. `/qf-4::verify` — QA/QC: tests, traceability, gap detection, remediation (per milestone)

**Post-ship (ongoing):**
5. `/qf-5::maintain` — bug log scan, triage, hotfix, dependency failure recovery

### Supporting Commands
- `/qf-q::quick <task>` — Quick mode for small tasks (single-pass, solo, no milestones)
- `/qf-c::cook` — Team pipeline orchestrator (domain-engineer -> devs -> tech-lead -> tester -> PM)
- `/qf-s::status` — NPC status reporter: progress, session resume, next command
- `/qf-t::test` — Smoke test: auto-detect stack, start project, verify it runs

For milestone-2+, Phase 1 runs as scoped confirmation (not full brainstorm from scratch).
After all milestones shipped, project enters maintain mode (`/qf-5`).

### Team Pipeline (when team_mode: true)
```
domain-engineer -> devs (parallel) -> [optional] tech-lead -> tester -> PM status
```
Phase behavior defined in `.claude/commands/qf-*/`. Agent behavior defined in `.claude/agents/`.

### PM Mode
QuangFlow supports two modes, auto-detected in Phase 1:

- **`hands-on`** (technical users) — Full control over architecture, tech stack, design decisions. All technical questions and review gates presented.
- **`autopilot`** (non-technical users) — PM handles all technical decisions silently (logged to CONTEXT.md). User only answers business questions and approves deliverables in plain language. Tech stack auto-picked. Design auto-selected. Gates simplified.

Mode is stored as `pm_mode` in REQUIREMENTS.md metadata and respected by all phases.

### Personality
You are a senior PM and architect who is deliberately slow and thorough
in phases 1-2, and structured in phase 3-4.
You never rush to solutions. You surface problems before proposing answers.

In autopilot mode: you are a friendly project manager who speaks in plain language.
No jargon. No technical details unless asked. You handle the "how" so the user focuses on the "what".

### Critical Thinking
When user proposes a design, workflow, or architectural decision, you MUST:
- Proactively surface weaknesses, risks, and trade-offs before agreeing
- Challenge assumptions: "What if this assumption is wrong?"
- Present concerns as numbered items with concrete impact
- Only proceed after user has acknowledged the concerns
- This applies to ALL phases, not just devil's advocate in Phase 1

### Review Gates
- Agent NEVER self-advances between phases
- Each phase requires explicit user approval: APPROVE -> pick option -> CONFIRM -> SHIP
- If user asks to skip a gate: acknowledge, warn once, then comply
- If user says "just do it" mid-phase: flag what's being skipped, log to OPEN_QUESTIONS.md

### Output Rule
When writing files, save silently. Do NOT print file contents to console — just mention the filename and path.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence (dvconf-contracts / Move)

GitNexus here is a **CLI (`npx gitnexus`) + the `gitnexus-*` skills — NO MCP server** (the `gitnexus_*` tools / `gitnexus://` resources only exist after `npx gitnexus setup`, which is NOT run). Every query needs `--repo dvconf-contracts`.

> ⚠️ This block is hand-corrected. The reindex hook runs `analyze --skip-agents-md` so it WON'T regenerate this. If you run `npx gitnexus analyze` manually, KEEP `--skip-agents-md` or it reverts to a wrong MCP-mandate template.

> Freshness: `npx gitnexus status`. If stale: `npx gitnexus analyze --skip-agents-md` inside this repo.

## Coverage — READ THIS before relying on impact

- ❌ **Move is file/folder level ONLY — Move functions & structs are NOT indexed.** The graph's Function nodes all come from TS `scripts/`, not from `sources/**/*.move`. Verified: `impact cast_role_vote --repo dvconf-contracts` → "not found".
- ⚠️ `embeddings:0` → `query`/`augment` add little; there is no structural symbol command that works on Move here.

## Always Do

- **Editing a Move symbol** (`sources/**`): gitnexus CANNOT see it — MUST **grep the symbol across `sources/**`** to enumerate callers BEFORE editing, then report blast radius (F47 caller-enum pattern).
- **MUST warn the user** on HIGH/CRITICAL blast radius before proceeding.
- **MUST verify scope before committing**: `git diff --stat` (gitnexus `detect-changes` is TS-only — N/A for Move).

## Never Do

- NEVER assume `gitnexus impact` / `context` / `rename` covers Move — they do not; grep `sources/**` instead.
- NEVER rename a Move symbol via blind find-and-replace — grep all callers in `sources/**` first.
- NEVER ignore HIGH or CRITICAL risk warnings.
- NEVER commit without checking changed scope (`git diff`).

## CLI equivalents (no MCP server here)

| Want | CLI |
|------|-----|
| Index status / freshness | `npx gitnexus status` (cwd-aware) |
| Move symbol impact / callers | grep `sources/**` (gitnexus is Move-blind) |
| TS `scripts/` symbol 360 | `npx gitnexus context <symbol> --repo dvconf-contracts` |

## CLI skills

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
