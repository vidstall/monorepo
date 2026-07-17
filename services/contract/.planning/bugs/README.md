# Bug Log — DVConf

> Structured bug tracking with severity levels, organized by module.
> Last updated: 2026-03-12

---

## How to File a Bug

Any agent (QC, Verification, Architect, domain agents) or user can log bugs.
Append a new entry to the appropriate module file:

| Module | File | Prefix |
|--------|------|--------|
| Sui Move contracts | `onchain.md` | `BUG-ON-` |
| Node.js daemons | `offchain.md` | `BUG-OFF-` |
| React client | `client.md` | `BUG-FE-` |

---

## Severity Levels

| Level | When to use |
|-------|------------|
| **ERROR** | Crash, abort, data corruption, security vulnerability — blocks functionality |
| **WARN** | Incorrect behavior that doesn't crash — wrong output, missed edge case |
| **INFO** | Minor issue — cosmetic, naming inconsistency, missing validation |
| **DEBUG** | Diagnostic note — unexpected behavior during testing, needs investigation |

---

## Entry Format

```markdown
### BUG-<MODULE>-<NNN>: <short title>
- **Level**: ERROR | WARN | INFO | DEBUG
- **Phase**: Phase <N>
- **Found by**: QC | Verification | Architect | User | <agent name>
- **Module/File**: `<file path>:<line>` (or `<file path>::<function>`)
- **Runtime error**: <actual error message, abort code, stack trace, or "N/A">
- **Description**: <what happened, steps to reproduce if applicable>
- **Status**: OPEN | IN_PROGRESS | FIXED | WONT_FIX
- **Fixed by**: <commit hash> | pending
```

---

## Rules

1. **Numbering is per-module** — `BUG-ON-001`, `BUG-OFF-001`, `BUG-FE-001` are independent sequences
2. **Never delete entries** — mark as FIXED or WONT_FIX, keep for history
3. **QC agents log automatically** — when QC rejects a task, critical/non-critical issues become bug entries
4. **Verification Agent logs automatically** — test failures and integration mismatches become bug entries
5. **Architect logs automatically** — drift findings and tech debt discoveries become bug entries
6. **Status updates** — when a dev fixes a bug, update status to FIXED and add commit hash
