> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/onchain/SKILL.md` (workspace root). This file retained as deep playbook reference for Sui Move pitfalls + DVConf-specific ownership rules + Change Reversal Protocol details. M3 hygiene will decide split-out (extract sections to dedicated reference files) vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# OnChain Agent — Sui Move Engineer Skill
> Agent: OnChain Agent
> Project: DVConf — Decentralized Video Conference on Sui
> Read this file in full before writing or editing any `.move` file.

---

## GSD Integration

When invoked by GSD executor, also read before starting:
- `.planning/ROADMAP.md` — current phase goal and success criteria
- `.planning/REQUIREMENTS.md` — REQ-IDs this task covers (reference in commit messages)
- `.planning/AGENT_ROUTING.md` — error code namespace assignments for your module

After completing a task:
- Request QC Agent review (QC APPROVED required before task is marked complete)
- Run `sui move test` to confirm no regressions
- Reference REQ-IDs in commit message (e.g., "feat(relay_registry): implement REG-06, REG-07, REG-08")

---

## Primary Responsibility

Write correct, idiomatic Sui Move contracts that exactly match the spec. Security and correctness over convenience — always.

Spec documents (read before every task):
- `docs/decentralized_video_conference-rev4.md` — system architecture and full design
- `docs/phase1/README.md` — complete Phase 1 implementation spec

---

## Coding Standards

### Module & File Structure
- Follow the exact module/file structure defined in the spec — do not invent new files or rename modules
- One Move module per file, filename matches module name
- All source files go in `sources/`, all test files in `tests/`

### Error Code Namespaces
Every error constant must be a named `const`, never a magic number inline. Namespaces by module:

| Module | E_* starts at |
|---|---|
| `token.move` | 0 |
| `network_registry.move` | 100 |
| `staking.move` | 200 |
| `caps.move` | 300 |
| `registration.move` | 400 |
| `room_manager.move` | 500 |
| `control_plane_registry.move` | 510 |
| `relay_registry.move` | 520 |
| `validator_registry.move` | 530 |
| `user_registry.move` | 540 |
| `signaling_registry.move` | 600 |
| `economic_layer.move` | 650--664 |
| (reserved future) | 700--1099 |

### Arithmetic — Basis Points Only
- No floating point. Ever.
- All weights and ratios are basis points (integer, base 10_000)
- Scoring weights must sum to exactly 10_000 — validate with `assert!`
- Reward ratios must sum to exactly 10_000 — validate with `assert!`
- Check for u64 overflow on intermediate multiplications before they happen

### Visibility Rules
- Use `public(package)` for any constructor that must not be callable externally
- All Cap constructors (`new_user_cap`, `new_relay_cap`, `new_cp_cap`, `new_validator_cap`, `new_validator_session_cap`) are `public(package)` — never `public`
- Internal helpers that are not part of the module's public API use `fun` (no modifier)

### Invariants — Enforce at Every Entry Point
Every state-mutating `public` or `entry` function must check these before doing anything:
1. `assert!(!network_registry::is_paused(registry), E_SYSTEM_PAUSED)` — circuit breaker
2. Ownership / capability check — correct Cap or AdminCap is in the call
3. Stake lock check where relevant — `assert!(!staking::is_locked(position), E_STAKE_LOCKED)`

### Staking Rules
- `StakePosition.locked` must be set to `true` before any session begins
- `withdraw_stake()` must abort with `E_STAKE_LOCKED` if `locked == true` — no exceptions
- `add_stake()` is always allowed regardless of lock state (topping up is safe)

### Slash Rules
- `slash()` always returns a `Coin<DVCONF>` to the caller
- The slash function itself never burns or redistributes — that is the economic layer's job (Phase 4)
- Never split more than the current balance — check `balance::value` before `balance::split`

### Validator Identity — Hard Rule
- The link between a validator's public wallet (A) and session wallet (B) must never appear on-chain during an active session
- `ValidatorSessionCap.parent_validator_id` is stored in the cap object which lives in the validator's wallet — it is never passed as an argument to any function that emits an event or writes to a shared object during the session
- `destroy_session_cap()` must be called atomically in the same transaction as proof submission — no separate transactions

### Object Lifecycle
- When consuming an object (e.g. `StakePosition` on withdraw, `ValidatorSessionCap` on proof), always call `object::delete(id)` — forgetting leaks UIDs
- Shared objects: use `transfer::share_object()` in `init` — never share after the fact in a separate transaction
- Owned objects: use `transfer::transfer()` or `transfer::public_transfer()` as appropriate

---

## Deliverable Format

Every task delivery must include both files:

```
// ── file: sources/<module_name>.move ──────────────────────────
<full compilable Move module>

// ── file: tests/<module_name>_tests.move ──────────────────────
<full test file — all spec cases + additional edge cases>
```

**Tests are not optional.** If the spec lists test cases, implement every one. Add extra tests wherever a security invariant exists that the spec doesn't explicitly test.

---

## Change Reversal Protocol — MANDATORY for Edits to Existing Files

This protocol applies any time you are modifying a `.move` file that already has content. New files are exempt.

### Step 1 — Snapshot BEFORE touching anything

Output this block before writing a single line of changed code:

```
📸 SNAPSHOT — sources/<module>.move
Affected functions / constants: <comma-separated list>

BEFORE:
  public fun stake(registry: &NetworkRegistry, coin: Coin<DVCONF>, role: Role, ctx: &mut TxContext): StakePosition { ... }
  public fun withdraw_stake(position: StakePosition, ctx: &mut TxContext): Coin<DVCONF> { ... }
  const E_INSUFFICIENT_STAKE: u64 = 200;
```

Include the full signature of every function being touched. Body can be `{ ... }`.

### Step 2 — Preservation Check AFTER the edit

Immediately after outputting the changed code, output:

```
✅ PRESERVATION CHECK
  stake()              — exists: YES · signature changed: YES — added relay_mode validation
  withdraw_stake()     — exists: YES · behavior unchanged
  E_INSUFFICIENT_STAKE — exists: YES · value unchanged
  [MISSING] add_stake  — ⚠️ present in snapshot, now absent. Was this intentional?
```

Every item from the snapshot must appear in this check. Status must be one of:
- `exists: YES · behavior unchanged`
- `exists: YES · behavior changed: <one-line reason>`
- `exists: YES · signature changed: <one-line reason>`
- `[MISSING] <name> — ⚠️ present in snapshot, now absent`

### Step 3 — Reversal Warning on Missing Items

If **any** item from the snapshot is missing after the edit, STOP immediately and do not finalize:

```
🚨 REVERSAL WARNING
  add_stake() was present in the snapshot and is now absent.
  Callers that will break: staking_tests.move ~line 47, Phase 3 escrow module (future).
  Was this deletion intentional?
  → Reply YES to confirm and finalize.
  → Reply NO to restore add_stake() before proceeding.
```

Do not proceed until you receive an explicit YES or NO from the developer.

### Step 4 — Revert on Demand

If the developer says "revert", "undo", or "roll back":
1. Output the heading: `⏪ REVERTING — sources/<module>.move`
2. Output the complete file reconstructed from the BEFORE snapshot
3. Confirm: `✅ Reverted. The file is now identical to the pre-edit state.`

---

## Common Sui Move Pitfalls — Check Before Submitting

- `object::id_from_address(@0x0)` is a placeholder — flag it clearly with `// TODO: set in Phase 2 registration` so it's never forgotten
- `coin::into_balance` consumes the coin — never use it and then try to read `coin::value` after
- `balance::split` panics if `amount > balance::value` — always check first
- `transfer::public_freeze_object` is irreversible — only call it on metadata, never on mutable state
- `public struct X has drop {}` one-time witness types must be used exactly once in `init` and never stored
- `sui::table` entries must be explicitly removed before the Table itself can be deleted

---

## DVConf-Specific Rules — Move Ownership Pitfalls

Lessons confirmed during Phase 1. Every rule here reflects a real mistake that occurred.

### has key vs has key + store — the transfer_to pattern

A struct with only `has key` (no `store`) **cannot** be transferred using `transfer::public_transfer` or `transfer::transfer` from outside its defining module. The Move compiler will reject the call.

`StakePosition` is `has key` only — it is an owned object that must never leak to external callers without going through a controlled handoff.

The required pattern is a package-private transfer helper **in the same module as the type**:

```move
// In staking.move — the only correct way to move StakePosition to a recipient
public(package) fun transfer_to(position: StakePosition, recipient: address) {
    transfer::transfer(position, recipient);
}
```

`registration.move` then calls `staking::transfer_to(stake_pos, sender)` — it does not attempt its own `transfer::transfer`. This is the pattern for any `has key`-only object in this codebase.

**Rule**: If you define a struct with `has key` but not `store`, you must also provide a `public(package) fun transfer_to()` in the same module. Do not leave the transfer responsibility to the caller's module.

---

### Coin<T> in expected-failure tests

`Coin<TOKEN>` has no `drop` ability. In a `#[expected_failure]` test, if the function under test **returns** a `Coin<T>` and the test expects an abort, the test still compiles with the return value on the stack — but the abort means the line that would consume the coin is never reached.

The Move VM will flag this as an unused value error at test compilation time.

**Wrong pattern**:
```move
#[test]
#[expected_failure(abort_code = registration::E_PROTOCOL_PAUSED)]
fun test_register_fails_when_paused(ctx: &mut TxContext) {
    let coin = registration::register(..., ctx); // returns Coin<TOKEN> on abort — compiler rejects
}
```

**Correct pattern** — bind the return value and immediately transfer it so the type checker is satisfied:
```move
#[test]
#[expected_failure(abort_code = registration::E_PROTOCOL_PAUSED)]
fun test_register_fails_when_paused(ctx: &mut TxContext) {
    let coin = registration::register(..., ctx);
    transfer::public_transfer(coin, @0x1); // never reached — but the type is discharged
}
```

**Rule**: In every `#[expected_failure]` test that calls a function returning `Coin<T>`, always bind the return value and add `transfer::public_transfer(coin, @0x1)` on the next line.

---

### table::contains guard before table::borrow_mut

Every mutation helper that takes a `miner_id` and calls `table::borrow_mut` on the profiles table **must** first assert `table::contains`. Forgetting this produces a runtime abort with no custom error code — the error message from the Move runtime is uninformative and the abort code will not match the namespace table.

**Wrong pattern**:
```move
public(package) fun borrow_profile_mut(store: &mut MinerStore, id: ID): &mut MinerProfile {
    table::borrow_mut(&mut store.profiles, id) // aborts with generic error if id missing
}
```

**Correct pattern**:
```move
public(package) fun borrow_profile_mut(store: &mut MinerStore, id: ID): &mut MinerProfile {
    assert!(table::contains(&store.profiles, id), E_NOT_REGISTERED); // abort 300
    table::borrow_mut(&mut store.profiles, id)
}
```

**Rule**: Every function that calls `table::borrow` or `table::borrow_mut` must call `table::contains` first and abort with the module's `E_NOT_REGISTERED` (300) constant.

---

### Full-replace semantics for structs with multiple fields

When an update function replaces a struct that has multiple fields (e.g., `Endpoint` has `ip`, `port`, `stun_url`, `turn_url`, `turn_credential_hash`), the function must accept **all fields** and replace the entire struct atomically.

Accepting only a subset of fields silently destroys the un-passed fields — this is not a compile error, it is a data loss bug.

`update_endpoint` in Phase 1 required all five `Endpoint` fields:
```
ip, port, stun_url, turn_url, turn_credential_hash
```

**Rule**: Any function that reconstructs and replaces a multi-field struct must accept every field of that struct as a parameter. Partial-update functions (e.g. only changing `ip`) must use a dedicated setter that reads-modify-writes the existing struct, not a replacement constructor.

---

### Error constants — namespace table is mandatory

Every new `const E_*` you add to any `.move` file must be added to the Error Code Namespace table in this skill file AND the project `README.md` **in the same edit session**. This is not optional cleanup — it is part of the definition of "done" for any PR that introduces a new error code.

If you are adding a constant that is defined now but will not abort at runtime until a future phase, add it to the table anyway and annotate with the phase it activates:

```move
#[allow(unused_const)]
const E_STAKE_LOCKED: u64 = 201; // reserved; activated in Phase 3 session-lock enforcement
```

The `#[allow(unused_const)]` attribute suppresses the compiler warning. The comment is required so the next agent knows it is intentional.

**Rule**: New error constant → namespace table entry → same PR. No exceptions.
