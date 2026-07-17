---
name: dvconf:execute-phase
description: Execute a DVConf phase — routes tasks to domain agents per AGENT_ROUTING.md, spawns QC review after each task, tracks progress in STATE.md. Run after design-phase is approved.
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, Agent, WebSearch, WebFetch, mcp__context7__resolve-library-id, mcp__context7__query-docs
argument-hint: "[phase-number]"
---

# Execute Phase — DVConf Workflow

You are executing Phase $ARGUMENTS of the DVConf project.

**Prerequisite**: The ADD for this phase must be PM-approved (check `docs/architecture/phases/phase-$ARGUMENTS-ADD.md` exists). If no ADD exists and the phase is small (gap closure, tech debt), you may proceed without one — use the PLAN.md directly.

## Step 1: Load Context

Read these files:
1. `.planning/AGENT_ROUTING.md` — routing table and execution rules
2. The PLAN.md for Phase $ARGUMENTS (find in `.planning/phases/`)
3. `docs/architecture/phases/phase-$ARGUMENTS-ADD.md` — approved architecture (if exists)
4. `.planning/STATE.md` — current progress
5. `.planning/REQUIREMENTS.md` — requirement definitions

## Step 1.5: Resolve Active Wave (v4.0+ — backward-compat, renamed S47 from "Resolve Active Milestone")

For phases under v4.0 Wave clustering (S40 codified, S47 renamed from "milestone clustering" to avoid confusion with QuangFlow feature-level `plans/{slug}/milestone-N/`):

1. Glob `docs/00-meta/waves/wave-*.md` from workspace root
2. For each Wave file, check whether Phase `$ARGUMENTS` falls within its declared scope (frontmatter `phases-in-scope:` field OR a body section listing phase IDs)
3. If **match** → log `active-milestone: W{N}` (field name preserved for Dataview stability per S47; value uses Wave shorthand W{N} parsed from filename `wave-{N}-*.md`) to `.planning/STATE.md` under the current phase entry
4. If **no match** (e.g., Phase 1-14 v1.0-v3.0 phase plans with no Wave metadata) → fall-through to phase-only routing (legacy backward-compat preserved)

**Routing impact**: Once `active-milestone` is logged (S47: Dataview field name kept, value carries Wave code W0-W4), downstream domain agents must include it in their funnel JSON output (per `.claude/HARNESS.md` § Output format) so cross-domain CC and PM audit trails can correlate by Wave.

**Acceptance test fixtures**:
- `/dvconf:execute-phase 14` → no Wave declares phase 14 → glob produces no match → STATE.md unchanged from legacy behavior
- Hypothetical phase tagged in `wave-0-foundation.md` (`phases-in-scope: [0]`) → STATE logs `active-milestone: W0` and propagates to funnel JSON

## Step 2: Determine Execution Order

From the PLAN.md:
- Identify task dependencies
- Group independent tasks for parallel execution
- Tasks in different domains with no shared files can run in parallel
- Tasks with dependencies must run sequentially

## Step 3: Execute Tasks

For each task (in order), spawn the correct domain agent using the Agent tool:

**Routing** (from AGENT_ROUTING.md):
- `.move` files → OnChain Agent → read `docs/skills/ONCHAIN_AGENT_SKILL.md`
- `.ts` files in `packages/` → OffChain Agent → read `docs/skills/OFFCHAIN_AGENT_SKILL.md`
- React components → FE Agent → read `docs/skills/FE_AGENT_SKILL.md`

**Agent spawn prompt template:**
```
Read <skill-file> in full before starting.
Read the ADD: docs/architecture/phases/phase-<N>-ADD.md (if exists).

Task: <task description from PLAN.md>
Requirements: <REQ-IDs>
Files to create/modify: <file list>

Follow all coding standards from your skill file.
Apply the Change Reversal Protocol if editing existing files.
Log any Design Notes (decisions, deviations) inline as comments.
```

**Parallel execution**: When tasks are independent (different domains, no shared files), launch multiple agents simultaneously using parallel Agent tool calls.

## Step 4: QC Review (After Each Task)

After each domain agent completes a task, spawn the QC Agent:

```
Read docs/skills/QC_AGENT_SKILL.md in full.
Read .planning/AGENT_ROUTING.md for error code namespaces.

Review the changes made by the <domain> Agent for Task <N>: <task name>.
Check the diff of modified files.
Apply the full QC checklist for the <domain> domain.
Check Change Reversal Protocol compliance if existing files were edited.

Output your review in the QC REVIEW format.
```

Use subagent_type: "QC Agent" for QC reviews.

**Handle QC result:**
- **QC APPROVED** → mark task complete, proceed to next task
- **QC REJECTED** → log each [C*] and [N*] issue to `.planning/bugs/<module>.md` as OPEN bugs (use `BUG-ON-`/`BUG-OFF-`/`BUG-FE-` prefix per domain), then re-spawn domain agent to fix, then re-run QC. When QC approves after fix, update bug status to FIXED with the task reference.

**Bug logging format** (see `.planning/bugs/README.md` for full spec):
```
### BUG-<MODULE>-<NNN>: <issue title from QC>
- **Level**: ERROR (for [C*]) | WARN (for [N*])
- **Phase**: Phase $ARGUMENTS
- **Found by**: QC
- **Module/File**: <file:line from QC report>
- **Runtime error**: <error message or abort code if applicable>
- **Description**: <QC issue description>
- **Status**: OPEN
- **Fixed by**: pending
```

## Step 5: Track Progress

After each task completes (QC approved):
- Update `.planning/STATE.md` with task completion
- Report progress to user: "Task N/M complete: <task name>"

## Step 6: Phase Complete

When all tasks pass QC:
- Update `.planning/STATE.md` to mark the phase tasks as done
- Report to user: "All Phase $ARGUMENTS tasks complete and QC approved."
- Suggest next step: `/dvconf:verify-phase $ARGUMENTS`

## Parallel Execution Rules

From AGENT_ROUTING.md:
1. Tasks with **no data dependencies** and in **different domains** can run in parallel
2. Each parallel task gets its **own QC review** (never batch QC)
3. If Task B depends on Task A's output, run sequentially
4. If both tasks modify the same file, run sequentially
5. If QC rejects a task, fix must complete before next task starts
