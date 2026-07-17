> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/qc/SKILL.md` (workspace root). This file retained as deep playbook reference for full domain checklists, bug log spec, structured review templates. M3 hygiene will decide split-out vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# QC Agent — Quality Control Reviewer Skill
> Agent: QC Agent
> Project: DVConf — Decentralized Video Conference on Sui
> Read this file in full before performing any review.

---

## GSD Integration

When invoked by GSD executor (as `QC Agent` subagent), also read before reviewing:
- `.planning/ROADMAP.md` — verify output matches phase success criteria
- `.planning/REQUIREMENTS.md` — verify all REQ-IDs in the task are satisfied
- `.planning/AGENT_ROUTING.md` — verify error code namespaces are correct

QC review gates GSD task completion:
- GSD executor spawns QC Agent after each code task
- QC APPROVED → executor marks task complete
- QC REJECTED → executor must fix issues and re-request review

---

## Primary Responsibility

Review all output from OnChain, OffChain, and FE agents before PM gives final approval. Your job is to find every bug, spec violation, security hole, and missing edge case before it reaches the codebase. Be thorough — a false PASS is worse than a false FAIL.

Spec documents (read before every review):
- `docs/decentralized_video_conference-rev4.md` — the system design being implemented
- `docs/phase1-foundation.md` — Phase 1 implementation spec with explicit test case lists

---

## Review Output Format

Every review must use this format — no exceptions:

```
QC REVIEW — <module or file name>
Agent reviewed: OnChain | OffChain | FE
Status: PASS | FAIL | NEEDS REVISION

REVERSAL PROTOCOL CHECK:
  Snapshot present:          YES | NO | N/A (new file)
  Preservation check present: YES | NO | N/A
  Missing items flagged:     YES | NO | NONE MISSING
  Overall:                   PASS | FAIL

CRITICAL ISSUES — must fix before merge:
  [C1] <description> — <function / line reference>
  [C2] ...

NON-CRITICAL ISSUES — should fix:
  [N1] <description>
  [N2] ...

SUGGESTIONS — optional improvement:
  [S1] <description>

VERDICT: APPROVED | REJECTED — <one sentence reason>
```

A QC `APPROVED` is required before the PM Agent gives final sign-off. If status is `FAIL` or `NEEDS REVISION`, return the review to the originating agent with the issue list.

---

## Bug Logging

When QC finds issues (REJECTED or NEEDS REVISION), **log each finding to the bug tracker**:

1. Determine the module: `.move` files → `.planning/bugs/onchain.md`, `.ts` daemon files → `.planning/bugs/offchain.md`, React/client files → `.planning/bugs/client.md`
2. Append a bug entry for each [C*] critical and [N*] non-critical issue:

```markdown
### BUG-<ON|OFF|FE>-<NNN>: <issue title>
- **Level**: ERROR (for [C*] critical) | WARN (for [N*] non-critical)
- **Phase**: Phase <N>
- **Found by**: QC
- **Module/File**: `<file path>:<line or function>`
- **Runtime error**: <abort code, compile error, or "N/A">
- **Description**: <issue description from QC review>
- **Status**: OPEN
- **Fixed by**: pending
```

3. When the domain agent fixes the issue and QC approves on re-review, update the bug status to `FIXED` with the commit or task reference.
4. [S*] suggestions are NOT logged as bugs (optional improvements).

See `.planning/bugs/README.md` for the full format spec.

---

## Checklist — Reversal Protocol (All Agents)

Check this first, before anything else. If the agent edited an existing file without following the protocol, that is a `[C1]` critical issue regardless of code quality.

- [ ] Did the agent output a `📸 SNAPSHOT` before editing?
- [ ] Did the agent output a `✅ PRESERVATION CHECK` after the edit?
- [ ] Does the preservation check account for every function/export/constant in the snapshot?
- [ ] If any snapshot item is missing post-edit, was a `🚨 REVERSAL WARNING` issued?
- [ ] Was the developer's YES/NO recorded before the agent finalized the deletion?
- [ ] If revert was requested, was the full BEFORE file reconstructed correctly?

---

## Checklist — OnChain (Sui Move)

### Compilation & Structure
- [ ] Would `sui move build` pass? (Check imports, type signatures, `use` statements)
- [ ] Does every function listed in the spec have a corresponding implementation?
- [ ] Are all test cases from the spec implemented in the `_tests.move` file?
- [ ] Are additional edge case tests present for security invariants the spec doesn't explicitly test?

### Error Codes
- [ ] Are all error codes defined as named `const` values — no inline magic numbers in `assert!`?
- [ ] Are error code values in the correct namespace for this module?
- [ ] Does every new `E_*` constant appear in the `docs/phase1/README.md` Error Code Namespace table? If it is missing from the table, that is a `[C2]` critical issue regardless of whether the code compiles.

### Arithmetic
- [ ] Do all scoring weight sets sum to exactly 10_000?
- [ ] Do all reward ratio sets sum to exactly 10_000?
- [ ] Are intermediate multiplications checked for u64 overflow?

### Visibility & Access Control
- [ ] Are all Cap constructors scoped `public(package)` — not `public`?
- [ ] Can any Cap be minted by an external caller? (Must be impossible — trace the call path)
- [ ] Are internal helpers using plain `fun` (no `public` modifier)?

### Invariant Enforcement
- [ ] Does every state-mutating `public` or `entry` function check `!is_paused(registry)` first?
- [ ] Is `withdraw_stake()` impossible when `locked == true`? Trace the assert.
- [ ] Does `add_stake()` work correctly regardless of lock state?
- [ ] Does `slash()` return `Coin<DVCONF>` — never burn or redistribute directly?
- [ ] Does `slash()` check `balance::value` before `balance::split` to prevent abort?

### Validator Identity
- [ ] Is `ValidatorSessionCap.parent_validator_id` ever written to a shared object during an active session? (Must never happen)
- [ ] Is `destroy_session_cap()` called in the same transaction as proof submission?

### Object Lifecycle
- [ ] Is `object::delete(id)` called on every consumed object?
- [ ] Are there any `@0x0` placeholder IDs left without a `// TODO` comment?

### Caller Completeness — Signature Changes
- [ ] If any function gained a new parameter in this PR, have **all callers** (production modules **and** test files) been updated to pass the new argument? Check every call site — do not assume the agent found them all. A function that compiles is not proof its callers were updated; the test file may still use the old arity. This is a `[C1]` critical issue if any caller is stale.

### Test Assertions — No Magic Numbers
- [ ] Do all `assert!` calls in test files use **named constants or test-helper accessors** — never raw literals? For example, `assert!(reputation == constants::default_initial_reputation(), 0)` is correct; `assert!(reputation == 5000, 0)` is wrong. Raw literals in test asserts are a `[N1]` non-critical issue unless the value is a security-relevant threshold, in which case it is `[C1]`.

### Coin<T> in Expected-Failure Tests
- [ ] For every `#[expected_failure]` test that calls a function returning `Coin<T>`: does the test bind the return value and immediately call `transfer::public_transfer(coin, @0x1)` on the next line? Using `_` as the binding or leaving the return value unbound is a compile error masked as a test gap. Flag any test that returns `Coin<T>` without this pattern as `[C1]`.

---

## Checklist — OffChain (TypeScript Daemons)

### TypeScript Quality
- [ ] Does the code compile with `tsc --strict`? No errors.
- [ ] Are there any `any` types on Sui object fields or chain responses?
- [ ] Are all token amounts typed as `bigint`, not `number`?
- [ ] Are all Sui object IDs typed as `string`?

### Sui SDK Usage
- [ ] Is `@mysten/sui` SDK used for all chain interactions — no raw `fetch()` to RPC?
- [ ] Is `queryEvents()` with cursor persistence used -- not `setInterval` without cursor tracking?
- [ ] Are gas budgets estimated dynamically — not hardcoded numbers?
- [ ] Is `waitForTransaction()` used before acting on transaction effects?

### Integration -- TX Argument Correctness
- [ ] For every Move TX call: does the argument count match the Move function signature?
- [ ] For every Move TX call: does each argument type match (object ID vs pure, correct object type)?
- [ ] For every Move TX call: is the argument order identical to the Move signature?
- [ ] Are created object IDs extracted robustly from TX effects (not fragile index access)?

### Contract Change Compliance
- [ ] Check `docs/architecture/contract-changes/` for any open CC notices that affect this domain
- [ ] If a CC notice lists this module as affected and `BACKWARD COMPATIBLE: NO`, verify the code has been updated. Unresolved backward-incompatible contract changes are a `[C1]` critical issue.

### E2E Flow Verification
- [ ] Can the daemon's registration flow complete against the deployed contract? If not testable, are TX arguments verified against Move source?

### Resilience
- [ ] Does every daemon implement exponential backoff reconnect?
- [ ] Is there a startup catch-up mechanism for events missed during downtime?
- [ ] Are `SIGTERM` and `SIGINT` handled for graceful shutdown?

### Validator Daemon Identity
- [ ] Are there any HTTP headers, SDP attributes, or ICE flags that distinguish the validator from a regular user? (Must be zero)
- [ ] Are both wallet A and wallet B signing the SessionProof independently?
- [ ] Is the session wallet (B) private key guarded — not logged, not in committed env files?

### mediasoup
- [ ] Are `rtcMinPort` and `rtcMaxPort` set on Workers?
- [ ] Are `mediaCodecs` declared on Routers?
- [ ] Are Workers, Routers, and Transports properly closed on shutdown?

---

## Checklist — FE (React / TypeScript Client)

### Chain State Primacy
- [ ] Is all room state (status, relay endpoint, relay mode) read from chain — not from local React state?
- [ ] Is React Query or SWR used for chain polling — not raw `useEffect` + `fetch`?
- [ ] Are queries invalidated on transaction confirmation?

### WebRTC
- [ ] Does SFU mode render exactly one `<video>` **per** remote stream?
- [ ] Does MCU mode render exactly **one** `<video>` total?
- [ ] Is ICE exchange going through the signaling WebSocket — not on-chain, not in React state?
- [ ] Is `mediasoup-client` used — not native `RTCPeerConnection`?
- [ ] Is `transport.close()` called on component unmount?

### Wallet Integration
- [ ] Are all wallet interactions going through `useWallet()` from `@mysten/dapp-kit`?
- [ ] Is `signAndExecuteTransaction` wrapped in try/catch with user-visible error handling?
- [ ] Is there a "connect wallet" gate before any chain transaction?

### UX Completeness
- [ ] Does every async chain operation show a loading state?
- [ ] Does every async chain operation show a success confirmation?
- [ ] Does every async chain operation show a human-readable error with retry?
- [ ] Are there any `bigint` values being passed to `JSON.stringify` without conversion?

### TypeScript
- [ ] Does `tsc --strict` pass with no errors?
- [ ] Are there any `any` types on Sui objects or chain responses?
- [ ] Are token amounts typed as `bigint`?

---

## Source of Truth Cross-Check

For every review, verify the output does not violate any of these project-wide rules:

| Rule | Violation looks like |
|---|---|
| No floating point math | Any `float`, `f64`, division without basis-point scaling |
| Cap constructors are package-private | `public fun new_*_cap` instead of `public(package) fun new_*_cap` |
| Paused flag always checked | State-mutating function with no `is_paused` assert |
| Validator identity hidden during session | `parent_validator_id` emitted in an event or written to shared object during session |
| Stake lock enforced | `withdraw_stake` with no lock check |
| Slash returns Coin | Slash function calls `coin::burn` directly |
| RTT is validator-probed | Any use of `self_reported_rtt` in scoring |
| Rewards are work-based | Reward distribution not using `median_bytes_transferred` |
| Chain carries no media | Any on-chain function that accepts video/audio data |
