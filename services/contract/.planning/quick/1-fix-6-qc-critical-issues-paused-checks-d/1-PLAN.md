---
phase: quick-fix-qc-critical
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - sources/registry/user_registry.move
  - sources/registry/relay_registry.move
  - sources/registry/validator_registry.move
  - sources/registry/room_manager.move
  - tests/registry/user_registry_tests.move
  - tests/registry/relay_registry_tests.move
  - tests/registry/room_manager_tests.move
autonomous: true
requirements: []

must_haves:
  truths:
    - "update_profile() checks is_paused() before mutating state"
    - "update_mode() checks is_paused() before mutating state"
    - "register_relay() has no dead code assignments"
    - "SessionWalletAssigned event does NOT emit miner_id (identity hidden)"
    - "has_session_wallet() is public(package) to block external probing"
    - "close_room() aborts E_NOT_FOUND(502) when room does not exist"
    - "set_room_status() aborts E_NOT_FOUND(502) when room does not exist"
    - "All 77 existing tests still pass after changes"
  artifacts:
    - path: "sources/registry/user_registry.move"
      provides: "update_profile with net_reg param and paused guard"
    - path: "sources/registry/relay_registry.move"
      provides: "update_mode with net_reg param and paused guard, no dead let mode ="
    - path: "sources/registry/validator_registry.move"
      provides: "SessionWalletAssigned without miner_id, has_session_wallet package-only"
    - path: "sources/registry/room_manager.move"
      provides: "E_NOT_FOUND used for existence checks in close_room and set_room_status"
  key_links:
    - from: "update_profile"
      to: "network_registry::is_paused"
      via: "assert!(!network_registry::is_paused(net_reg), E_PAUSED)"
    - from: "update_mode"
      to: "network_registry::is_paused"
      via: "assert!(!network_registry::is_paused(net_reg), E_PAUSED)"
---

<objective>
Fix 6 QC-critical issues across 4 Phase 2 registry modules. All issues violate Source of Truth rules or produce incorrect error semantics. Tests are updated to match new signatures and new paused-guard tests are added.

Purpose: QC APPROVED status cannot be granted with these open critical issues. Fixes are required before Phase 3 planning proceeds.
Output: 4 corrected .move source files, 3 corrected/extended test files, all 77+ tests passing.
</objective>

<execution_context>
@C:/Users/alienware x17r2/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@docs/skills/ONCHAIN_AGENT_SKILL.md

Key error namespaces:
- room_manager:       500=E_PAUSED, 501=E_NOT_CREATOR, 502=E_NOT_FOUND, 503=E_ALREADY_CLOSED
- relay_registry:     520=E_NOT_RELAY, 521=E_ALREADY_REGISTERED, 522=E_NOT_REGISTERED, 523=E_PAUSED, 524=E_NOT_OPERATOR, 525=E_INVALID_MODE
- validator_registry: 530=E_NOT_VALIDATOR, 531=E_ALREADY_REGISTERED, 532=E_NOT_REGISTERED, 533=E_PAUSED, 534=E_SESSION_EXISTS, 535=E_NO_SESSION
- user_registry:      540=E_ALREADY_REGISTERED, 541=E_NOT_REGISTERED, 542=E_PAUSED
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix sources — paused guards, dead code, event identity leak, error codes</name>
  <files>
    sources/registry/user_registry.move
    sources/registry/relay_registry.move
    sources/registry/validator_registry.move
    sources/registry/room_manager.move
  </files>
  <action>
Apply the Change Reversal Protocol before editing each file: note current state, make minimal targeted edit, verify only that edit changed.

**C1 — user_registry.move `update_profile` (line 85):**
Add `net_reg: &NetworkRegistry` as the first parameter (after the implicit self pattern, before `registry`).
Insert `assert!(!network_registry::is_paused(net_reg), E_PAUSED);` as the first line of the function body, before the sender check.
Final signature:
```move
public fun update_profile(
    net_reg: &NetworkRegistry,
    registry: &mut UserRegistry,
    display_name: vector<u8>,
    ctx: &mut TxContext,
)
```

**C2 — relay_registry.move `update_mode` (line 145):**
Add `net_reg: &NetworkRegistry` as the first parameter.
Insert `assert!(!network_registry::is_paused(net_reg), E_PAUSED);` as the first line of the function body, before the role check.
Final signature:
```move
public fun update_mode(
    net_reg: &NetworkRegistry,
    registry: &mut RelayRegistry,
    cap: &MinerCap,
    new_mode: u8,
    _ctx: &mut TxContext,
)
```

**C3 — relay_registry.move `register_relay` (line 98):**
Remove ONLY this line (the dead assignment):
```move
let mode = staking::role(stake); // relay mode comes from stake position's stored role context
```
Also remove or clean the comment on the following line if it now makes no sense. The `staking` import may now be unused for `role` — check if `staking::amount` is still used (it is, line 104). The `use dvconf::staking::{Self, StakePosition}` import stays because `StakePosition` type and `staking::amount` are still referenced.

**C4 — validator_registry.move `SessionWalletAssigned` event:**
Change the event struct from:
```move
public struct SessionWalletAssigned has copy, drop {
    miner_id:       ID,
    session_wallet: address,
}
```
to:
```move
public struct SessionWalletAssigned has copy, drop {
    session_wallet: address,
}
```
Update the `event::emit` call in `assign_session_wallet` (line 126) from:
```move
event::emit(SessionWalletAssigned { miner_id, session_wallet });
```
to:
```move
event::emit(SessionWalletAssigned { session_wallet });
```
Change `has_session_wallet` visibility from `public fun` to `public(package) fun`:
```move
public(package) fun has_session_wallet(r: &ValidatorRegistry, wallet: address): bool {
    table::contains(&r.session_wallets, wallet)
}
```

**C5 — room_manager.move `close_room` (line 137):**
Change the existence check abort code from `E_ALREADY_CLOSED` to `E_NOT_FOUND`:
```move
assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
```
The second assert on `info.status != constants::room_status_closed()` keeps `E_ALREADY_CLOSED` — do NOT change it.
Also remove the `#[allow(unused_const)]` attribute from `E_NOT_FOUND` since it is now used.

**C6 — room_manager.move `set_room_status` (line 177):**
Change the existence check abort code from `E_ALREADY_CLOSED` to `E_NOT_FOUND`:
```move
assert!(table::contains(&manager.rooms, room_id), E_NOT_FOUND);
```
  </action>
  <verify>
    <automated>cd C:/Thesis/dvconf/dvconf-contracts && sui move build --silence-warnings 2>&1 | tail -5</automated>
  </verify>
  <done>
`sui move build` succeeds with no errors. All 4 source files compile cleanly. Dead code line is gone. Paused guards present in update_profile and update_mode. SessionWalletAssigned has only session_wallet field. has_session_wallet is public(package). Both existence checks in room_manager use E_NOT_FOUND(502).
  </done>
</task>

<task type="auto">
  <name>Task 2: Update tests — signatures, paused guard tests, error code correction</name>
  <files>
    tests/registry/user_registry_tests.move
    tests/registry/relay_registry_tests.move
    tests/registry/room_manager_tests.move
  </files>
  <action>
Apply the Change Reversal Protocol before editing each test file.

**user_registry_tests.move:**

1. Find `test_update_profile` — add `net_reg` as first argument to the `update_profile(...)` call. Pass the shared `NetworkRegistry` object (same one used in `register_user` calls in the same test).

2. Find `test_update_profile_not_registered` — same signature fix: add `net_reg` as first argument to `update_profile(...)`.

3. Add new test `test_update_profile_paused`:
```move
#[test]
#[expected_failure(abort_code = dvconf::user_registry::E_PAUSED)]
fun test_update_profile_paused() {
    let mut scenario = test_scenario::begin(@0xA);
    {
        network_registry::init_for_testing(scenario.ctx());
        user_registry::init_for_testing(scenario.ctx());
    };
    // Register user while unpaused
    scenario.next_tx(@0xA);
    {
        let mut net_reg = scenario.take_shared<NetworkRegistry>();
        let mut registry = scenario.take_shared<UserRegistry>();
        user_registry::register_user(&net_reg, &mut registry, b"Alice", scenario.ctx());
        test_scenario::return_shared(net_reg);
        test_scenario::return_shared(registry);
    };
    // Admin pauses the registry
    scenario.next_tx(@0xA);
    {
        let mut net_reg = scenario.take_shared<NetworkRegistry>();
        let cap = scenario.take_from_sender<AdminCap>();
        network_registry::set_paused(&cap, &mut net_reg, true);
        test_scenario::return_shared(net_reg);
        scenario.return_to_sender(cap);
    };
    // update_profile must abort E_PAUSED
    scenario.next_tx(@0xA);
    {
        let net_reg = scenario.take_shared<NetworkRegistry>();
        let mut registry = scenario.take_shared<UserRegistry>();
        user_registry::update_profile(&net_reg, &mut registry, b"Alice2", scenario.ctx());
        test_scenario::return_shared(net_reg);
        test_scenario::return_shared(registry);
    };
    scenario.end();
}
```
Adapt the exact test helper pattern to match what already exists in the file (check how other paused tests in the codebase call `set_paused` and take `AdminCap` — mirror that pattern exactly).

**relay_registry_tests.move:**

1. Find `test_update_mode` — add `net_reg` as first argument to the `update_mode(...)` call.

2. Find `test_update_mode_invalid` — add `net_reg` as first argument to the `update_mode(...)` call.

3. Add new test `test_update_mode_paused` following the same paused-guard pattern used in `test_update_profile_paused` above, adapted for relay: register a relay, pause the network, then call `update_mode(...)` and expect `E_PAUSED` (523).

**room_manager_tests.move:**

1. Find `test_close_nonexistent_room_aborts_503` (or similarly named test that expects abort 503 for a nonexistent room).
   Change its `expected_failure` abort_code from `503` / `E_ALREADY_CLOSED` to `502` / `E_NOT_FOUND`:
   ```move
   #[expected_failure(abort_code = dvconf::room_manager::E_NOT_FOUND)]
   ```
   Rename the test to `test_close_nonexistent_room_aborts_502` if the name encodes the code.
  </action>
  <verify>
    <automated>cd C:/Thesis/dvconf/dvconf-contracts && sui move test --silence-warnings 2>&1 | tail -10</automated>
  </verify>
  <done>
`sui move test` passes with at least 79 tests (77 existing + 2 new paused tests). No failures. No compilation errors. The renamed/updated test for 502 is present and green.
  </done>
</task>

</tasks>

<verification>
After both tasks complete:

```bash
cd C:/Thesis/dvconf/dvconf-contracts && sui move test --silence-warnings
```

Expected: All tests pass (79+). Zero compilation warnings about unused variables (dead `let mode =` is gone).

Manual spot-check:
- `grep "let mode = staking::role" sources/registry/relay_registry.move` returns no output
- `grep "miner_id" sources/registry/validator_registry.move | grep "SessionWalletAssigned"` returns no output
- `grep "public(package) fun has_session_wallet" sources/registry/validator_registry.move` returns a match
- `grep "E_NOT_FOUND" sources/registry/room_manager.move` returns 2 matches (close_room + set_room_status)
- `grep "net_reg" sources/registry/user_registry.move | grep "update_profile"` returns the parameter line
- `grep "net_reg" sources/registry/relay_registry.move | grep "update_mode"` returns the parameter line
</verification>

<success_criteria>
- C1 fixed: update_profile has net_reg param and paused guard
- C2 fixed: update_mode has net_reg param and paused guard
- C3 fixed: dead `let mode = staking::role(stake)` line removed from register_relay
- C4 fixed: SessionWalletAssigned emits only session_wallet (no miner_id); has_session_wallet is public(package)
- C5 fixed: close_room existence check uses E_NOT_FOUND(502)
- C6 fixed: set_room_status existence check uses E_NOT_FOUND(502)
- Test suite passes (79+ tests, zero failures)
- QC Agent review requested after task 2 completes
</success_criteria>

<output>
No SUMMARY.md required for quick fixes. After completion, request QC Agent review and update CLAUDE.md Phase 2 task statuses if QC approves.
</output>
