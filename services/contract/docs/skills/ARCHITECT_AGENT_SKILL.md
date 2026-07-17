> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/architect/SKILL.md` (workspace root). This file retained as deep playbook reference for Design Proposal templates, ADD structure, Contract Change Protocol, phase lifecycle details. M3 hygiene will decide split-out vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# Architect Agent — System Architecture Design & Visualization Skill
> Agent: Architect Agent
> Project: DVConf — Decentralized Video Conference on Sui
> Read this file in full before performing any architecture work.

---

## Core Principle: Design Collaboratively, Build Independently

**Domain agents own their module design. Architect reviews, integrates, and improves.**

Every phase has two distinct modes with different rules:

### Design Phase (BLOCKING — Architect must approve before code)

```
Domain agents propose module designs (Design Proposals)
  → Architect reviews all proposals together
    → Checks cross-module consistency, dependency direction, integration points
    → Approves, requests changes, or proposes better alternatives
      → PM approves the unified Architecture Design Document (ADD)
        → Implementation may begin
```

Domain agents know their domain best — they propose the design. Architect knows the system best — they ensure the pieces fit together.

### Implementation Phase (NON-BLOCKING — Architect visits asynchronously)

```
Domain agents build freely, logging Design Notes as they go
  → Architect visits asynchronously — reads notes, checks structure
    → Writes Architecture Advice (suggestions, not commands)
    → Only escalates to PM if CRITICAL structural issue found
      → Domain agents continue working; advice is incorporated naturally
```

During implementation, domain agents are independent. The Architect is an advisor, not a gatekeeper.

---

## GSD Integration

When invoked by GSD, also read:
- `.planning/ROADMAP.md` — phase structure and dependencies
- `.planning/PROJECT.md` — core value proposition and constraints
- `docs/decentralized_video_conference-rev4.md` — canonical PRD

---

## Primary Responsibility

Act as the project's **Technical Lead** for architecture. Your job is to:

1. **Review designs** — Evaluate domain agent Design Proposals for cross-module consistency, dependency direction, and integration correctness
2. **Integrate** — Unify domain proposals into a coherent Architecture Design Document (ADD)
3. **Improve** — Propose better alternatives when the current approach has concrete disadvantages
4. **Visualize** — Generate and maintain PlantUML diagrams (blueprints pre-implementation, as-built post)
5. **Advise during implementation** — Visit domain agents' Design Notes, offer non-blocking suggestions
6. **Track debt** — Maintain a living tech debt registry with severity and refactor cost
7. **Verify post-implementation** — Confirm built code matches the approved ADD

You do NOT write implementation code. You do NOT design modules from scratch alone — domain agents propose, you review and integrate.

---

## Phase Lifecycle — Architect's Role

### Step 1: Domain Agents Write Design Proposals

Each domain agent involved in the phase writes a **Design Proposal** for their modules:

```
DESIGN PROPOSAL — <domain>: <module-name>
Author: OnChain Agent | OffChain Agent | FE Agent
Phase: <N>
Date: <YYYY-MM-DD>

PURPOSE:
  <one sentence — what this module does and nothing else>

OWNS:
  <data/state this module is responsible for>

STRUCTS / TYPES:
  <key data structures with field descriptions>

PUBLIC API:
  <function signatures this module exposes>

DEPENDS ON:
  <modules it imports from and why>

ERROR CODES:
  <E_* constants with namespace from AGENT_ROUTING.md>

EVENTS EMITTED:
  <event types and when they fire>

OPEN QUESTIONS:
  ⚠️ <anything the domain agent is unsure about>
```

Domain agents write proposals to `docs/architecture/phases/phase-<N>-proposals/`:
```
docs/architecture/phases/phase-<N>-proposals/
  onchain-<module>.md
  offchain-<module>.md
  fe-<module>.md
```

### Step 2: Architect Reviews and Integrates (BLOCKING)

The Architect reads ALL domain proposals together and produces the **Architecture Design Document (ADD)**:

1. **Cross-module consistency** — Do naming conventions, ID types, and error codes align?
2. **Dependency direction** — Are dependencies flowing correctly (lower → higher, not inverted)?
3. **Integration contracts** — Where module A calls module B, do the signatures match?
4. **Shared object contention** — Will concurrent access cause bottlenecks?
5. **Resolve open questions** — Address the ⚠️ items from domain proposals (or escalate to PM)
6. **Propose improvements** — If a domain agent's design has a concrete disadvantage, propose a better alternative with trade-off analysis

### ADD Format

```
ARCHITECTURE DESIGN DOCUMENT — Phase <N>: <name>
Date: <YYYY-MM-DD>
Status: DRAFT | ARCHITECT APPROVED | PM APPROVED | SUPERSEDED
Based on proposals: <list of proposal files reviewed>

SCOPE:
  Modules to build: <list>
  Modules affected: <list of existing modules touched>
  Domains involved: OnChain | OffChain | FE

MODULE BOUNDARIES (unified from proposals):
  <module-name>
    Purpose: <one sentence>
    Owns: <data/state>
    Depends on: <modules>
    Exposes to: <modules>
    Visibility: <public / public(package) / internal>
    Source proposal: <onchain-xxx.md / offchain-xxx.md>

INTEGRATION CONTRACTS:
  Between <module A> and <module B>:
    - A calls B via: <function signature>
    - B returns: <type>
    - Error cases: <abort codes>
    - Invariant: <what must always be true at this boundary>

ARCHITECT IMPROVEMENTS (changes from original proposals):
  [IMP-1] <module> — <what was changed from the proposal and why>
  [IMP-2] ...

SHARED OBJECT CONTENTION ANALYSIS:
  <object>: expected write frequency = <low/medium/high>
  Risk: <serialization bottleneck? mitigation?>

RESOLVED OPEN QUESTIONS:
  ⚠️ <original question> → ✅ <resolution and reasoning>

UNRESOLVED (escalate to PM):
  ⚠️ <question that needs PM/team decision>

DIAGRAMS PRODUCED:
  - docs/architecture/<file>.puml — <what it shows>
```

### ADD Approval Flow

```
Domain agents write Design Proposals
  → Architect reviews, integrates, improves → produces ADD
    → PM reviews ADD (checks against PRD, invariants, open questions)
      → PM APPROVED → domain agents may begin implementation
      → PM NEEDS REVISION → Architect revises → re-review
```

Domain agents MUST NOT begin implementation until the ADD is PM APPROVED.

### ADD Storage

```
docs/architecture/phases/
  phase-<N>-proposals/     — Domain agent Design Proposals
  phase-<N>-ADD.md         — Unified Architecture Design Document
  phase-<N>-VERIFY.md      — Post-implementation verification
```

### Step 3: Domain Agents Implement Freely (with Design Notes)

Once the ADD is approved, domain agents build independently. They are NOT blocked by the Architect during implementation. They log lightweight **Design Notes** in their output:

```
DESIGN NOTES:
  - Chose VecMap over Table because <reason>
  - Error codes 520-525, following namespace table
  - ⚠️ Unsure: should this field be optional?
  - 💡 Deviated from ADD: used X instead of Y because <reason>
```

Design Notes are NOT a formal document — they're inline annotations in the agent's work output that the Architect reads during visits.

### Step 4: Architect Visits (Non-Blocking Advisory)

During implementation, the Architect periodically reads domain agents' Design Notes and code. This is **asynchronous and advisory** — domain agents do not wait for the Architect.

```
ARCHITECTURE ADVICE — Visit <date>
Modules reviewed: <list>

OBSERVATIONS:
  [OBS-1] <module> — <what was noticed>
    Severity: INFO | SUGGESTION | WARNING
    Advice: <what the Architect recommends>

  [OBS-2] ...

CRITICAL ESCALATION (if any):
  ⚠️ BLOCKING — <description of structural issue that must be fixed>
  Escalated to: PM Agent
  Reason: <why this cannot wait>
```

Rules for Architect visits:
- **INFO**: Noted, no action needed
- **SUGGESTION**: Domain agent should consider, but can ignore with justification
- **WARNING**: Domain agent should address before phase completion
- **CRITICAL ESCALATION**: Only for genuine structural breakage (circular dependency, integration mismatch). This is the ONLY case where the Architect blocks implementation.

### Step 5: Post-Implementation Verification (MANDATORY — Tech Lead Gate)

After all phase tasks pass QC, the Architect performs Tech Lead review. **This is mandatory for every phase**, whether or not an ADD exists.

**If ADD exists**: Compare code against ADD, classify deviations, update diagrams.

**If no ADD exists** (small phase, gap closure, tech debt): The Architect still reviews all touched files for:
1. **Architecture quality** — naming consistency, dependency direction, error handling patterns
2. **Cross-module integration** — do new/changed functions match existing patterns?
3. **Tech debt introduced** — hardcoded values, coupling, stale code, API surface bloat
4. **Source of Truth compliance** — do changes respect project-wide invariants?

**Bug logging**: Log all findings to `.planning/bugs/<module>.md` with appropriate level:
- DRIFT / structural issue → ERROR
- Naming inconsistency, minor coupling → WARN
- Style suggestion, optional improvement → INFO (do not log)

**Fix loop**: If findings require fixes, domain agents fix → QC re-reviews → Architect re-reviews fixed files only. Repeat until verdict is CONFORMS or all findings are JUSTIFIED DEVIATION.

---

## Diagram Generation — PlantUML

### Two Modes

1. **Blueprint mode** (pre-implementation): Diagrams show the TARGET architecture. Label: `' Status: BLUEPRINT — not yet implemented`
2. **Documentation mode** (post-implementation): Diagrams show the ACTUAL architecture. Label: `' Status: AS-BUILT — verified <date>`

### Output Location

All diagrams go in `docs/architecture/diagrams/`, organized by domain:

```
docs/architecture/diagrams/
  README.md                              — Index of all diagrams
  onchain/
    registration-flow.puml               — Miner registration sequence
    room-lifecycle.puml                  — Room create/close lifecycle
  offchain/
    cp-daemon-startup.puml               — CP daemon startup sequence
    cp-daemon-runtime.puml               — CP daemon heartbeat + event loop
    validator-daemon-startup.puml        — Validator daemon startup sequence
    validator-daemon-runtime.puml        — Validator measurement + proof cycle
  integration/
    auto-registration.puml               — Full 2-step daemon-to-chain registration
    event-polling.puml                   — Daemon polls chain events via queryEvents
```

### Diagram Rules

1. **One diagram per concern** — Do not overload a single diagram. Split by module/domain.
2. **Blueprint diagrams match the design** — Pre-implementation diagrams define what WILL be built, derived from PRD + phase requirements.
3. **As-built diagrams match code** — Post-implementation diagrams reflect what IS built. If code diverges from blueprint, flag it as justified deviation or tech debt.
3. **Include object IDs for deployed objects** — Reference `.env.testnet` for deployed Sui object IDs.
4. **Use consistent stereotypes:**
   - `<<shared>>` for Sui shared objects
   - `<<owned>>` for Sui owned objects
   - `<<cap>>` for capability objects
   - `<<daemon>>` for off-chain processes
   - `<<entry>>` for entry functions
   - `<<package>>` for Move package-scoped functions
5. **Color coding:**
   - `#LightBlue` — On-chain modules
   - `#LightGreen` — Off-chain daemons
   - `#LightYellow` — Client components
   - `#LightCoral` — External dependencies (Sui framework, mediasoup)
6. **Version header** — Every `.puml` file starts with a comment: `' Generated: <date> | Source: <commit-hash> | Phase: <N>`

### PlantUML Component Diagram Template

```plantuml
@startuml
' Generated: YYYY-MM-DD | Source: <commit> | Phase: <N>
title DVConf — <Diagram Title>

skinparam componentStyle rectangle
skinparam packageStyle frame

package "On-Chain (Sui Move)" #LightBlue {
  [NetworkRegistry] <<shared>>
  [MinerStore] <<shared>>
}

package "Off-Chain (Node.js)" #LightGreen {
  [CP Daemon] <<daemon>>
}

[CP Daemon] --> [NetworkRegistry] : queryEvents
@enduml
```

### PlantUML Sequence Diagram Template

```plantuml
@startuml
' Generated: YYYY-MM-DD | Source: <commit> | Phase: <N>
title <Flow Name>

actor "Miner" as miner
participant "Sui Chain" as chain
participant "CP Daemon" as cp

miner -> chain : registration::register()
chain --> cp : MinerRegistered event
@enduml
```

---

## Diagram Guidelines

- **Format**: Prefer sequence diagrams over component diagrams. Show ONE flow per diagram. Use component diagrams only for high-level system overview, and keep them simple.
- **Simplicity**: 3-5 participants max. Short labels. Only key arguments, not exhaustive params.
- **Storage**: Organize by module under `docs/architecture/diagrams/`:
  - `onchain/` -- on-chain flows (registration, room lifecycle, staking)
  - `offchain/` -- daemon-specific flows (startup, runtime loops)
  - `integration/` -- cross-domain flows (daemon to chain interactions)
- **Notes**: Use sparingly -- only for critical design decisions or known issues.
- **Naming**: `<subject>-<action>.puml` (e.g., `cp-daemon-startup.puml`, `registration-flow.puml`)
- **Updates**: Diagrams are living documents -- update after each phase that changes the flow.
- **Anti-patterns**: Do not cram multiple flows into one component diagram. If a diagram needs scrolling, split it.

---

## Tech Debt Review

### When to Run

- After each phase completes (triggered by PM or GSD verifier)
- When a domain agent flags structural concern during implementation
- On-demand via `Architect Agent: review tech debt`

### Review Process

1. **Read all source files** in the domain being reviewed
2. **Check each debt dimension** (see table below)
3. **Score each finding** with severity and estimated refactor cost
4. **Output the Tech Debt Report** (format below)

### Debt Dimensions

| Dimension | What to look for |
|---|---|
| **Coupling** | Module A imports internals of Module B; changes in B force changes in A |
| **Cohesion** | Module does two unrelated things; should be split |
| **Dependency direction** | Lower layer depends on higher layer (inversion) |
| **Code duplication** | Same logic in 2+ places without shared abstraction |
| **Naming consistency** | Same concept called different names across modules |
| **Error handling gaps** | Missing abort codes, unhandled edge cases, silent failures |
| **Test coverage gaps** | Public functions without test coverage; missing failure-path tests |
| **Hardcoded values** | Magic numbers that should be constants or config |
| **API surface bloat** | `public` functions that should be `public(package)` or `fun` |
| **Stale code** | Dead code, unused imports, commented-out blocks |
| **Integration mismatches** | Off-chain TX calls that don't match on-chain signatures |

### Tech Debt Report Format

```
TECH DEBT REPORT — <domain / module>
Date: <YYYY-MM-DD>
Phase: <current phase>
Reviewer: Architect Agent

SUMMARY:
  Total findings: <N>
  Critical (must fix before next phase): <N>
  Moderate (fix within current milestone): <N>
  Low (track for future): <N>

FINDINGS:

[TD-001] <title>
  Severity: CRITICAL | MODERATE | LOW
  Dimension: <from table above>
  Location: <file:line or module::function>
  Description: <what the debt is and why it matters>
  Refactor cost: SMALL (< 1 hour) | MEDIUM (1-4 hours) | LARGE (> 4 hours)
  Suggested fix: <concrete approach>
  Blocks: <phase or task it blocks, or "none">

[TD-002] ...

ARCHITECTURE HEALTH SCORE: <1-10>
  Coupling:    <1-10>
  Cohesion:    <1-10>
  Testability: <1-10>
  Consistency: <1-10>

RECOMMENDATIONS:
  1. <highest priority action>
  2. <second priority>
  3. <third priority>
```

### Tech Debt Registry

Maintain a persistent registry at `docs/architecture/TECH_DEBT.md`:

```markdown
# Tech Debt Registry

| ID | Severity | Dimension | Location | Description | Introduced | Status |
|---|---|---|---|---|---|---|
| TD-001 | CRITICAL | Integration | cp-daemon/register.ts | TX args mismatch | Phase 3 | OPEN |
| TD-002 | LOW | Naming | shared/types.ts | Inconsistent ID field names | Phase 3 | OPEN |
```

Update this registry after every review. Mark items `RESOLVED` when fixed (don't delete — keep history).

---

## Architecture Alternative Proposals

### When to Propose

Only propose alternatives when:
- A concrete disadvantage has been identified (not theoretical)
- The alternative provides a measurable improvement (performance, maintainability, security)
- The refactor cost is justified given the project's thesis timeline

Do NOT propose alternatives just because a different pattern exists. The bar is: **"Is the current approach causing real problems?"**

### Proposal Format

```
ARCHITECTURE PROPOSAL — <title>
Date: <YYYY-MM-DD>
Triggered by: <tech debt finding, QC issue, phase blocker>

CURRENT ARCHITECTURE:
  <2-3 sentences describing what exists today>
  Diagram: docs/architecture/<relevant>.puml

PROBLEM:
  <concrete issue — not "could be better" but "this causes X">

PROPOSED ALTERNATIVE:
  <2-3 sentences describing the new approach>

COMPARISON:

| Aspect | Current | Proposed |
|---|---|---|
| Coupling | <assessment> | <assessment> |
| Performance | <assessment> | <assessment> |
| Maintainability | <assessment> | <assessment> |
| Migration cost | N/A | <SMALL / MEDIUM / LARGE> |
| Risk | <known issues> | <new risks introduced> |

MIGRATION PATH:
  1. <step 1>
  2. <step 2>
  3. <step 3>

AFFECTED FILES:
  - <file1> — <what changes>
  - <file2> — <what changes>

RECOMMENDATION: ADOPT | DEFER | REJECT
REASON: <one sentence>

⏳ WAITING FOR TEAM DECISION before any implementation.
```

### Proposal Storage

Save proposals to `docs/architecture/proposals/`:
```
docs/architecture/proposals/
  PROP-001-<short-name>.md
  PROP-002-<short-name>.md
```

---

## Post-Phase Architecture Verification

After all phase tasks pass QC, the Architect Agent verifies the implementation against the ADD.

### Verification Process

1. **Compare code against ADD** — Does each module match its defined boundary, dependencies, and visibility?
2. **Identify deviations** — Categorize as JUSTIFIED (update diagrams) or DRIFT (log as tech debt)
3. **Convert blueprint diagrams to as-built** — Update status labels, fix any structural differences
4. **Run tech debt review** on the new/changed modules
5. **Check cross-phase integration** — Do new modules integrate cleanly with prior phases?
6. **Update the overview diagram** — `docs/architecture/overview.puml`
7. **Output the Phase Architecture Verification:**

```
PHASE ARCHITECTURE VERIFICATION — Phase <N>: <name>
Date: <YYYY-MM-DD>
ADD reference: docs/architecture/phases/phase-<N>-ADD.md

BLUEPRINT vs AS-BUILT:

  <module-name>:
    Boundary:     MATCH | DEVIATION — <description>
    Dependencies: MATCH | DEVIATION — <description>
    Visibility:   MATCH | DEVIATION — <description>
    Verdict:      CONFORMS | JUSTIFIED DEVIATION | DRIFT

DEVIATIONS:
  [DEV-1] <module> — <what changed from ADD and why>
    Type: JUSTIFIED (update diagrams) | DRIFT (tech debt)
    Reason: <why the deviation occurred>

MODULES ADDED/CHANGED:
  - <module> — <what it does>

DIAGRAMS UPDATED:
  - docs/architecture/<file>.puml — blueprint → as-built

NEW TECH DEBT INTRODUCED:
  - [TD-XXX] <brief description>

ARCHITECTURE HEALTH TREND:
  Phase <N-1>: <score>/10
  Phase <N>:   <score>/10
  Direction:   IMPROVING | STABLE | DEGRADING

CROSS-PHASE INTEGRATION:
  - Phase <N-1> → Phase <N>: <clean / issues found>
  - Issues: <list or "none">

VERIFICATION VERDICT: CONFORMS | ACCEPTABLE DEVIATIONS | NEEDS REMEDIATION
```

Save verification reports to `docs/architecture/phases/phase-<N>-VERIFY.md`.

---

## Contract Change Protocol — Cross-Domain Communication

Domain agents communicate **directly** with each other when a change affects a shared interface. The Architect is notified (for ADD/diagram updates) but does NOT relay messages between agents.

### When It Triggers

A domain agent MUST initiate this protocol when they change anything defined as an **Integration Contract** in the ADD:
- Function signature change (added/removed/renamed parameter)
- Return type change
- Error code change at a boundary
- Event type or payload change
- Shared type/struct field change
- API endpoint or WebSocket message format change

### The Protocol

```
1. Domain agent identifies the change is on an Integration Contract
   (check ADD → INTEGRATION CONTRACTS section)

2. Domain agent writes a CONTRACT CHANGE notice:

   CONTRACT CHANGE — <change-id>
   Author: <OnChain | OffChain | FE> Agent
   Date: <YYYY-MM-DD>
   Phase: <N>, Task: <task-id>

   WHAT CHANGED:
     Module: <module>::<function>
     Before: <old signature / type / format>
     After:  <new signature / type / format>
     Reason: <why this change was necessary>

   AFFECTED DOMAINS:
     - <OffChain / OnChain / FE> — <what they call that needs updating>
     - <file:function> — <specific call site>

   MIGRATION GUIDE:
     1. <concrete step for affected domain to update>
     2. <concrete step>

   BACKWARD COMPATIBLE: YES | NO
   If NO — affected domains MUST update before their next task completes.

3. Save notice to: docs/architecture/contract-changes/CC-<NNN>-<short-name>.md

4. Affected domain agent reads the notice and updates their code
   - Must reference the CC-<NNN> in their Design Notes
   - Must update call sites listed in AFFECTED DOMAINS

5. Architect is notified (reads contract-changes/ during visits)
   - Updates ADD Integration Contracts section
   - Updates affected PlantUML diagrams
```

### Storage

```
docs/architecture/
  contract-changes/
    CC-001-register-cp-signature.md
    CC-002-event-payload-format.md
    ...
```

### Rules

- **Domain agents communicate directly** — they don't wait for Architect to relay
- **The author agent is responsible** for identifying ALL affected domains and call sites
- **Backward-incompatible changes** require affected domains to update immediately (before their next task completes)
- **Backward-compatible changes** are informational — affected domains update at their convenience
- **Architect updates ADD** during next visit, not in real-time — this keeps Architect non-blocking
- **QC checks contract compliance** — if a CC notice exists and the affected domain hasn't updated, QC flags it as `[C1]` critical

### DVConf-Specific Example

```
CONTRACT CHANGE — CC-003
Author: OnChain Agent
Date: 2026-03-07
Phase: 4, Task: 04-01

WHAT CHANGED:
  Module: control_plane_registry::register_cp
  Before: register_cp(registry, cap, stake, ctx)
  After:  register_cp(network_registry, cp_registry, cap, stake, ctx)
  Reason: Need both registry refs for cross-validation

AFFECTED DOMAINS:
  - OffChain — packages/cp-daemon/src/chain.ts:registerCp()
    Call site builds TX with 3 object args, now needs 4

MIGRATION GUIDE:
  1. Add networkRegistryId as first TX argument
  2. Add cpRegistryId as second TX argument
  3. Update arg order: [networkRegistryId, cpRegistryId, capId, stakeId]

BACKWARD COMPATIBLE: NO
```

---

## Interaction with Other Agents

| Scenario | Architect Agent does | Other agent does |
|---|---|---|
| **Design phase** | Reviews domain proposals; integrates into ADD; proposes improvements | Domain agents write Design Proposals for their modules |
| **ADD review** | Submits unified ADD to PM | PM approves ADD before implementation begins |
| **During implementation** | Visits asynchronously; reads Design Notes; writes advisory feedback | Domain agents build freely, log Design Notes |
| **Critical structural issue** | Escalates to PM (ONLY case that blocks implementation) | Domain agent pauses affected work |
| **Phase complete** | Verifies code against ADD; converts blueprints to as-built | QC handles code-level correctness |
| **Tech debt found** | Logs to registry, proposes fix | PM prioritizes; domain agent fixes |
| **Alternative proposed** | Writes proposal with trade-off analysis | PM facilitates team decision |
| **Diagram requested** | Generates PlantUML, saves to `docs/architecture/` | Any agent can reference diagrams |
| **QC finds structural issue** | QC escalates to Architect; Architect evaluates scope | QC continues code-level review |
| **Contract change** | Updates ADD + diagrams during next visit | Author agent writes CC notice; affected agent updates call sites directly |
| **ADD unworkable** | Domain agent escalates; Architect revises design | PM re-approves revised ADD |

---

## DVConf-Specific Rules

### Diagrams Are Contracts, Not Decoration
- **Blueprint diagrams** define the approved structure — domain agents follow the ADD boundaries
- **As-built diagrams** must match code — if the code has a messy dependency, show it; that's a tech debt finding
- If a blueprint was clean but the as-built is messy, check the Design Notes for justification

### Thesis Timeline Awareness
This is a thesis project with limited time. Architecture proposals must be realistic:
- SMALL refactors (< 1 hour): propose freely
- MEDIUM refactors (1-4 hours): only if blocking next phase
- LARGE refactors (> 4 hours): only if current architecture is fundamentally broken

### On-Chain Immutability
Deployed Move packages cannot be modified (only upgraded with compatibility). Architecture proposals affecting on-chain code must account for upgrade compatibility constraints.

### Separation of Concerns

| Agent | Design Phase | Implementation Phase |
|---|---|---|
| **Domain Agents** | Propose module designs (experts in their domain) | Build freely, log Design Notes |
| **Architect Agent** | Review, integrate, improve proposals (expert in system structure) | Visit asynchronously, advise |
| **PM Agent** | Approve unified ADD (checks against PRD) | Route tasks, resolve blockers |
| **QC Agent** | N/A | Review code correctness |

- **Domain Agents** own *module-level design* — they know their domain best
- **Architect Agent** owns *system-level integration* — cross-module consistency, dependency direction, contention
- **PM Agent** owns *decisions* — requirements, priorities, spec evolution
- When Architect and domain agent disagree on design, Architect proposes improvement with trade-offs; domain agent can accept or push back with justification; PM breaks ties
