# Agent Routing — DVConf Multi-Agent Dispatch

> **REWRITTEN 2026-05-23** (agent-harness-env M2 Phase 3, REQ-HARNESS-007). Canonical mapping moved to workspace `.claude/HARNESS.md` §2. This file now scopes to dvconf-contracts-specific routing concerns (error namespaces, GSD phase lifecycle, mandatory gates). Legacy `gsd-executor` / `QC Agent` / `PM Agent` subagent_type vocabulary RETIRED.

## Source-of-truth pointers

- **Workspace dispatch hub**: `.claude/HARNESS.md` — 4-field contract template + subagent_type mapping + skill frontmatter spec (M1 ship)
- **Workspace file ownership matrix**: workspace root `CLAUDE.md` (M1 ship)
- **Workspace role skills (auto-load)**: `.claude/skills/{onchain,offchain,fe,qc,architect,pm,verification}/SKILL.md` (M2 ship)
- **Deep playbooks (subrepo, banner-pointed)**: `dvconf-contracts/docs/skills/{ROLE}_AGENT_SKILL.md`
- **Subrepo agent companions (CHECKPOINT + DECISIONS protocol)**: `dvconf-contracts/.claude/agents/{role}-agent.md`

## Architecture

```
PRD (decentralized_video_conference-rev4.md)
  └── GSD Process Layer (phases, plans, state, verification — this subrepo)
        └── Workspace Dispatch Layer (.claude/HARNESS.md — canonical)
              └── Role Skills (.claude/skills/{role}/SKILL.md — auto-load)
                    ├── OnChain   → Sui Move contracts
                    ├── OffChain  → Node.js daemons
                    ├── FE        → React client
                    ├── QC        → Code quality review gate
                    ├── Verification → Requirements coverage + test execution
                    ├── PM        → Coordination + STATUS + architectural truth
                    └── Architect → Design integration + tech debt + diagrams
```

GSD owns *what + when*. HARNESS.md owns *how dispatched*. Domain skills own *what good output looks like*.

## Routing table

> Canonical mapping per `.claude/HARNESS.md` §2. This table mirrors for dvconf-contracts task routing.

| Task pattern | Workspace Skill | Subagent type (Primary) | Fallback |
|---|---|---|---|
| `.move` files (source, test, edit) | `.claude/skills/onchain/SKILL.md` | `general-purpose` | — |
| `.ts` files in `packages/`, `apps/` (daemons) | `.claude/skills/offchain/SKILL.md` | `general-purpose` | — |
| React components, hooks, client code | `.claude/skills/fe/SKILL.md` | `general-purpose` | — |
| Code quality review (any domain) | `.claude/skills/qc/SKILL.md` | `superpowers:code-reviewer` | `quangflow:tech-lead` |
| Architecture, spec gaps, cross-boundary | `.claude/skills/pm/SKILL.md` | `quangflow:pm` | `general-purpose` |
| Requirements coverage, test generation/exec | `.claude/skills/verification/SKILL.md` | `quangflow:tester` | `general-purpose` |
| Design proposal review, ADD, diagrams, tech debt | `.claude/skills/architect/SKILL.md` | `quangflow:domain-engineer` | `general-purpose` |

Universal escape = `general-purpose` (built-in, always available, no plugin dep).

**Per CASE 2 (agent-harness-env M2 Phase 1 gate)**: skill auto-discovery surfaces only the `description` field to subagents. Main agent inline-injects SKILL.md body + relevant anchor doc content via dispatch prompts.

## Path patterns for OffChain routing

```
dvconf-daemons/packages/shared/        → @dvconf/shared types, constants, SDK helpers
dvconf-daemons/apps/signaling/         → Signaling daemon (WebSocket, ICE relay)
dvconf-daemons/apps/cp-daemon/         → Control Plane daemon (event sub, scoring, heartbeat)
dvconf-daemons/apps/validator-daemon/  → Validator daemon (session wallet, measurements, proofs)
dvconf-daemons/apps/relay/             → Relay nodes (SFU + MCU mediasoup)
```

## GSD Phase Lifecycle

```
/dvconf:discuss-phase <N>
  └── Reads ROADMAP, REQUIREMENTS, STATE, PROJECT, PRD, Open Questions
  └── Produces .planning/phases/phase-<N>-*/CONTEXT.md

/dvconf:plan-phase <N>
  └── Produces .planning/phases/phase-<N>-*/PLAN.md with task breakdown

/dvconf:design-phase <N>  (BLOCKING — no code until ADD approved)
  └── Domain skills (.claude/skills/{onchain,offchain,fe}) write Design Proposals (parallel)
  └── Architect skill reviews ALL proposals → unified ADD
  └── PM skill reviews ADD → APPROVE / NEEDS REVISION

/dvconf:execute-phase <N>  (post REQ-HARNESS-009: wave-aware, renamed S47 from "milestone-aware")
  └── Reads docs/00-meta/waves/wave-{N}-*.md if active (log active-milestone — Dataview field name preserved, value carries Wave code W0-W4)
  └── Routes tasks to domain skills per this table
  └── Spawns QC skill per task (mandatory gate)
  └── Architect skill visits asynchronously (advisory non-blocking)

/dvconf:verify-phase <N>  (BLOCKING)
  └── Verification skill builds RTM + runs all suites
  └── Architect skill verifies code against ADD
  └── feature-M3 ship: CitationAgent at Wave/feature-milestone boundary (REQ-HARNESS-011; "milestone boundary" name preserved generically — applies to both workspace Waves and QuangFlow feature milestones)
```

## Mandatory Gates

### QC Gate (per task)

Every code-producing task MUST pass QC review before completion:
1. Domain skill (onchain/offchain/fe) completes implementation
2. QC skill dispatched (`superpowers:code-reviewer` or fallback `quangflow:tech-lead`)
3. QC reviews against domain checklist (see `.claude/skills/qc/SKILL.md`)
4. QC APPROVED → task complete; QC REJECTED → domain fixes → re-review

### Verification Gate (phase completion)

After all tasks pass QC, Verification skill (`quangflow:tester`):
1. Builds RTM at `docs/architecture/phases/phase-<N>-RTM.md`
2. Identifies coverage gaps; generates gap-closers
3. Runs `sui move test` + `pnpm test` + cross-domain E2E
4. Validates cross-domain integration (Move ABI ↔ daemon TX calls)

### PM Gate (triggered on ambiguity)

PM skill invoked when:
- Task ambiguous or contradicts PRD
- Cross-domain boundaries unclear
- Architectural decision needed
- Spec gap discovered

### Architect Gate

Three touchpoints:
1. **Design Review** (BLOCKING) — PM approves ADD before any code
2. **Implementation Visits** (NON-BLOCKING) — advisory only; CRITICAL escalates to PM
3. **Post-Implementation Verification** (BLOCKING) — compare built vs ADD; flag drift as tech debt

## Cross-Domain Communication (Contract Change Protocol)

When a domain agent changes a shared Integration Contract:
- Write CONTRACT CHANGE notice (`CC-NNN`) to `docs/architecture/contract-changes/CC-NNN-<name>.md`
- Affected domains read + update; reference `CC-NNN` in Design Notes
- Backward-incompatible: affected domain MUST update before their next task completes
- Backward-compatible: affected domain updates at convenience
- QC check: if CC exists and affected domain hasn't updated → `[C1]` critical

## Error Code Namespaces

All error codes assigned and implemented. New modules must not collide.

| Module | E_* codes | Status |
|---|---|---|
| network_registry | 100–102 | Phase 1 (deployed) |
| staking | 200–202 | Phase 1 (deployed) |
| miner_store | 300 | Phase 1 (deployed) |
| registration | 400–404 | Phase 1 (deployed) |
| room_manager | 500–506 | Phase 2 (complete) |
| control_plane_registry | 510–515 | Phase 2 (complete) |
| relay_registry | 520–525 | Phase 2 (complete) |
| validator_registry | 530–535 | Phase 2 (complete) |
| user_registry | 540–542 | Phase 2 (complete) |
| signaling_registry | 600–604 | Phase 3 (complete) |
| economic_layer | 650–661 | Phase 3 (complete) |
| role_voting | 700–718 | mcu-relay-scarcity M1 (shipped) + F47 role-revote-pool (700-717 P1.0-1.3; 718 P1.4 governance). NOTE: 714 (E_CP_REVOTE_REQUIRES_MIGRATION) is ALSO asserted apply-side in `registration` (P1.5 RV-006 Q5 mirror) — same numeric, duplicated const kept in-sync, so consumers see one code per entry point |
| (reserved future) | 719–1099 | Unassigned |

## GSD Artifact Awareness

| File | Purpose | When to read |
|---|---|---|
| `.planning/ROADMAP.md` | Phase goals + success criteria | Before any phase work |
| `.planning/REQUIREMENTS.md` | REQ-IDs to implement | Before implementing any feature |
| `.planning/STATE.md` | Current phase/plan progress | Before + after task execution |
| `.planning/PROJECT.md` | Core value proposition, constraints | When making architectural decisions |
| `docs/decentralized_video_conference-rev4.md` | Full PRD — canonical | Before any implementation |
| `docs/architecture/phases/phase-<N>-ADD.md` | Approved architecture | Before implementing any phase task |
| `docs/architecture/phases/phase-<N>-RTM.md` | Requirements Traceability | When verifying phase completion |
| `docs/architecture/TECH_DEBT.md` | Tech debt registry | When planning new work or refactor |

## Parallel Execution Rules

GSD may run multiple agents in parallel when:
1. Tasks have NO data dependencies (don't touch same files)
2. Tasks are in DIFFERENT domains (OnChain + OffChain in parallel)
3. Each parallel task gets its OWN QC review

GSD must run sequentially when:
1. Task B depends on Task A's output (e.g., Move ABI change → daemon update)
2. Both tasks modify the same file
3. QC rejects a task — fix must complete before next starts

## Ad-Hoc Task Routing

For tasks outside GSD phases, prefix message with domain name:
- `OnChain: <task>` → routes via `.claude/skills/onchain/SKILL.md`
- `OffChain: <task>` → routes via `.claude/skills/offchain/SKILL.md`
- `FE: <task>` → routes via `.claude/skills/fe/SKILL.md`
- `QC: <task>` → routes via `.claude/skills/qc/SKILL.md`
- `Verification: <task>` → routes via `.claude/skills/verification/SKILL.md`
- `PM: <task>` → routes via `.claude/skills/pm/SKILL.md`
- `Architect: <task>` → routes via `.claude/skills/architect/SKILL.md`

Description match in the prompt triggers Claude Code skill auto-discovery; main agent inline-injects relevant context per CASE 2 fallback.

## See also

- `.claude/HARNESS.md` (workspace) — canonical dispatch contract + mapping
- `CLAUDE.md` (workspace root) — file ownership matrix
- `docs/00-meta/master-plan.md` (workspace) — dvconf SOT
- `docs/00-meta/waves/wave-0-foundation.md` — active dvconf Wave (renamed S47 from milestone-0-foundation)
- `plans/agent-harness-env/CONTEXT.md` (workspace) — harness env design decisions D1-D18
