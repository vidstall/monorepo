DESIGN PROPOSAL -- OnChain: RoomManager Assignment Extension + Tech Debt Closure
Author: OnChain Agent
Phase: 14
Date: 2026-03-12

---

## Task 1: Extend RoomManager with Relay/Signaling Assignment

### PURPOSE

Extend RoomInfo to track which relay and signaling node are assigned to a room, enabling the Control Plane daemon to write assignments on-chain and clients/validators to discover them via devInspect.

### OWNS

- `assigned_relay: Option<ID>` and `assigned_signaling: Option<ID>` fields on `RoomInfo`
- `assign_relay_and_signaling()` package-gated mutation function
- `get_room_assignment()` public read accessor for devInspect queries
- `RoomAssigned` event

### STRUCTS / TYPES

```move
// Existing struct -- extended with two new fields
public struct RoomInfo has store, copy, drop {
    creator:             address,
    status:              u8,
    relay_mode:          u8,
    created_at:          u64,
    closed_at:           u64,
    assigned_relay:      Option<ID>,     // NEW -- set by CP via assign_relay_and_signaling
    assigned_signaling:  Option<ID>,     // NEW -- set by CP via assign_relay_and_signaling
}

// New event
public struct RoomAssigned has copy, drop {
    room_id:       ID,
    relay_id:      ID,
    signaling_id:  ID,
}
```

### PUBLIC API

```move
/// Package-gated: assigns relay + signaling to a room in PENDING status.
/// Called by the CP daemon integration module (via PTB in off-chain).
/// Aborts E_NOT_FOUND (502) if room does not exist.
/// Aborts E_ALREADY_CLOSED (503) if room is CLOSED.
public(package) fun assign_relay_and_signaling(
    manager: &mut RoomManager,
    room_id: ID,
    relay_id: ID,
    signaling_id: ID,
)

/// Public read accessor for devInspect -- returns (assigned_relay, assigned_signaling).
/// Aborts E_NOT_FOUND (502) if room does not exist.
public fun get_room_assignment(
    manager: &RoomManager,
    room_id: ID,
): (Option<ID>, Option<ID>)

/// Field accessors on RoomInfo
public fun room_assigned_relay(r: &RoomInfo): Option<ID>
public fun room_assigned_signaling(r: &RoomInfo): Option<ID>
```

**Design decision -- `public(package)` for `assign_relay_and_signaling`**: This function must be callable from a PTB. However, since only the CP daemon should invoke it, and the CP daemon builds a PTB that calls the package's own entry functions, `public(package)` prevents external packages from calling it while allowing the package's own entry points to use it. If OffChain needs a standalone entry function, we can add a thin `entry fun` wrapper gated by `CpCap` in the same module or a new integration module. This is an open question for Architect review.

**REVISION**: After reviewing the off-chain integration pattern (CP daemon builds a PTB calling Move functions directly), the CP daemon needs a `public` or `entry` function it can call in its PTB. Since `public(package)` is not callable from PTBs originating outside the package, we need one of:
1. A `public fun assign_relay_and_signaling(...)` gated by `CpCap` -- ensures only registered CPs can assign.
2. Keep as `public(package)` and add a separate `entry fun` in the same module.

**Recommendation**: Option 1 -- make it `public fun` with `CpCap` gating. This follows the existing pattern where relay/validator/signaling registries use cap-gated public functions. The CP daemon already holds a `CpCap` from registration.

```move
/// Public entry: assigns relay + signaling to a room. CpCap required.
/// Room must exist and not be CLOSED.
public fun assign_relay_and_signaling(
    net_reg: &NetworkRegistry,
    manager: &mut RoomManager,
    _cap: &CpCap,
    room_id: ID,
    relay_id: ID,
    signaling_id: ID,
)
```

### DEPENDS ON

| Module | Reason |
|---|---|
| `std::option` | `Option<ID>` for the two new fields |
| `network_registry` | Pause check in public entry function |
| `caps::CpCap` | Gating the assign function to registered CPs only |

No new module dependencies beyond what `room_manager.move` already imports, except `caps` (for `CpCap`).

### ERROR CODES

No new error codes required. Reuses existing:
- `E_PAUSED (500)` -- pause check on assign
- `E_NOT_FOUND (502)` -- room does not exist
- `E_ALREADY_CLOSED (503)` -- room is already closed (cannot assign to closed room)

### EVENTS EMITTED

| Event | When |
|---|---|
| `RoomAssigned { room_id, relay_id, signaling_id }` | When `assign_relay_and_signaling()` succeeds |

### TESTS PLANNED

1. **test_assign_relay_and_signaling** -- Create a PENDING room, assign relay + signaling, verify accessors return correct IDs.
2. **test_assign_nonexistent_room_aborts_502** -- Call assign on a non-existent room_id, expect abort 502.
3. **test_assign_closed_room_aborts_503** -- Create a CLOSED room, attempt assign, expect abort 503.
4. **test_get_room_assignment_returns_none_before_assign** -- Create a room, call `get_room_assignment`, verify both are `option::none()`.
5. **test_get_room_assignment_returns_values_after_assign** -- Create room, assign, call `get_room_assignment`, verify both IDs match.

Note: Tests will use `add_room_for_testing()` with known room IDs (the existing pattern from economic_layer_tests). The `assign_relay_and_signaling` function is `public` (CpCap-gated), so tests can call it directly using a test CpCap.

### CHANGES TO TEST HELPERS

`add_room_for_testing()` must be updated to initialize the two new `Option<ID>` fields with `option::none()`. This is backward-compatible -- all existing tests that call `add_room_for_testing` will continue to work unchanged since the new fields default to `none`.

### OPEN QUESTIONS

> Should `assign_relay_and_signaling` be restricted to PENDING rooms only, or also allow READY/ACTIVE rooms (for reassignment on failover)?

**Proposed resolution**: For Phase 14, restrict to non-CLOSED rooms (allow PENDING, READY, ACTIVE). This supports both initial assignment (PENDING) and future failover reassignment (ACTIVE in v3). The check is simply `status != CLOSED`, which is already the pattern used by `close_room()`.

> Should the function verify that `relay_id` and `signaling_id` actually exist in their registries?

**Proposed resolution**: No. The CP daemon is trusted (CpCap-gated) and performs scoring against live registry data before assigning. Adding on-chain cross-registry lookups would increase gas cost and coupling. The IDs are informational references, not ownership claims.

---

## Task 2: Close Tech Debt

### TD-P11-04: Signaling Cleanup on Unregister

#### PURPOSE

When a miner unregisters via `registration::unregister()`, their signaling registry entry (if any) should be cleaned up automatically, preventing orphaned entries.

#### OWNS

- `signaling_registry::remove_if_registered()` -- new package-gated helper
- Modified `registration::unregister()` -- adds SignalingRegistry cleanup call

#### STRUCTS / TYPES

No new structs.

#### PUBLIC API

```move
// signaling_registry.move -- new function
/// Silently removes a signaling node entry if one exists for the given miner_id.
/// No-op if the miner is not registered as a signaling node.
/// Package-gated: only callable from within dvconf package (registration.move).
public(package) fun remove_if_registered(
    registry: &mut SignalingRegistry,
    miner_id: ID,
)
```

```move
// registration.move -- MODIFIED signature
public fun unregister(
    store: &mut MinerStore,
    signaling_reg: &mut SignalingRegistry,   // NEW parameter
    position: StakePosition,
    ctx: &mut TxContext
)
```

#### BREAKING CHANGE ANALYSIS -- `registration::unregister()`

**Before**:
```move
public fun unregister(
    store: &mut MinerStore,
    position: StakePosition,
    ctx: &mut TxContext
)
```

**After**:
```move
public fun unregister(
    store: &mut MinerStore,
    signaling_reg: &mut SignalingRegistry,
    position: StakePosition,
    ctx: &mut TxContext
)
```

**Impact assessment**:

| Caller | Location | Action Required |
|---|---|---|
| `registration_tests.move` | `tests/miner/registration_tests.move` | Add `SignalingRegistry` shared object to all `unregister()` calls. Tests already use `setup()` which does NOT init signaling_registry -- must be updated to use `setup_phase2()` or add `signaling_registry::init_for_testing()` to `setup()`. |
| OffChain daemon (auto-unregister) | `dvconf-daemons/apps/*/src/chain.ts` | PTB must pass `SignalingRegistry` object ID as additional argument. CC notice required. |
| No other on-chain callers | -- | -- |

**Migration complexity**: SMALL. Two call sites in tests, one in daemon code. The test change is mechanical (add shared object param). The daemon change requires a CC notice to OffChain Agent.

**Alternative considered**: Add a separate `cleanup_signaling(store, signaling_reg, position, ctx)` function called independently after `unregister()`. Rejected because it creates a two-TX cleanup flow that can leave orphaned state if the second TX fails.

#### DEPENDS ON

| Module | Reason |
|---|---|
| `signaling_registry` | New import in `registration.move` for cleanup |
| `table`, `vec_set` | Used inside `remove_if_registered` implementation |

#### ERROR CODES

No new error codes. `remove_if_registered` is a silent no-op if not registered.

#### EVENTS EMITTED

| Event | When |
|---|---|
| `SignalingUnregistered` | When `remove_if_registered` finds and removes an entry (reuses existing event type) |

Note: The existing `SignalingUnregistered` event is emitted to maintain observability for off-chain daemons tracking signaling node lifecycle.

---

### TD-P13-02: Missing E_ROOM_NOT_FOUND Test

#### PURPOSE

Add a test that verifies `economic_layer::create_escrow()` aborts with `E_ROOM_NOT_FOUND (652)` when called with a non-existent room ID.

#### TEST

```move
#[test]
#[expected_failure(abort_code = 652)]
fun test_create_escrow_room_not_found() {
    let mut scenario = h::setup_phase3();

    // Mint tokens for escrow deposit
    h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

    ts::next_tx(&mut scenario, CREATOR);
    {
        let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
        let room_mgr = ts::take_shared<RoomManager>(&scenario);
        let coin = ts::take_from_sender<coin::Coin<TOKEN>>(&scenario);

        // Use a fake room_id that does not exist in RoomManager
        let fake_room_id = object::id_from_address(@0xDEAD);
        economic_layer::create_escrow(
            &net_reg, &room_mgr, fake_room_id, coin, ts::ctx(&mut scenario),
        );

        ts::return_shared(net_reg);
        ts::return_shared(room_mgr);
    };

    ts::end(scenario);
}
```

Pattern follows existing test style: `setup_phase3()`, mint tokens, call with invalid input, expect abort code.

---

### TD-P13-03: Missing E_PAUSED Tests

#### PURPOSE

Add tests verifying that `create_escrow`, `submit_session_proof`, and `distribute_rewards` all abort with `E_PAUSED (650)` when the network is paused.

#### TESTS

Three new tests, all following the same pattern: setup, pause the network via AdminCap, attempt the operation, expect abort 650.

```move
#[test]
#[expected_failure(abort_code = 650)]
fun test_create_escrow_paused() {
    // setup_phase3() + setup_room_pending() + pause network
    // call create_escrow -> abort 650
}

#[test]
#[expected_failure(abort_code = 650)]
fun test_submit_session_proof_paused() {
    // setup_phase3() + pause network
    // call submit_session_proof with minimal args -> abort 650 (paused check is first)
}

#[test]
#[expected_failure(abort_code = 650)]
fun test_distribute_rewards_paused() {
    // setup_phase3() + setup escrow + pause network
    // call distribute_rewards -> abort 650 (paused check is first)
}
```

For `submit_session_proof` and `distribute_rewards`, the pause check is the FIRST assert in both functions, so we can pass dummy/minimal arguments -- the function will abort before reaching any other validation. This means we do not need full relay/validator setup for these paused tests.

However, `distribute_rewards` requires `&mut RoomEscrow` and `&mut StakePosition` which are owned/shared objects that need to exist. We will use `create_escrow_for_testing()` to create a dummy escrow and a test `StakePosition`.

---

### DEPENDS ON (Task 2 overall)

| Module | Reason |
|---|---|
| `signaling_registry` | `remove_if_registered` new function |
| `registration` | Modified `unregister()` signature |
| `economic_layer` | Target of new tests (no code changes) |
| `economic_layer_tests` | New tests added |
| `registration_tests` | Updated for new `unregister()` signature |
| `test_helpers` | May need `setup()` update if registration_tests migrate to `setup_phase2()` |

### ERROR CODES (Task 2)

No new error codes introduced. All tested codes already exist:
- `E_ROOM_NOT_FOUND (652)` -- economic_layer
- `E_PAUSED (650)` -- economic_layer

### EVENTS EMITTED (Task 2)

No new event types. `SignalingUnregistered` reused from existing signaling_registry.

### OPEN QUESTIONS (Task 2)

> Should `remove_if_registered` emit a `SignalingUnregistered` event?

**Proposed resolution**: Yes. The event provides observability for OffChain daemons. Emitting the event from `remove_if_registered` maintains the same audit trail as explicit `unregister_signaling`. The event handler in the signaling daemon can use it to clean up local state.

> Should `registration_tests` migrate from `setup()` to `setup_phase2()` to get access to SignalingRegistry?

**Proposed resolution**: Yes. Since `unregister()` now requires `&mut SignalingRegistry`, all tests calling `unregister()` need the registry to exist. Migrating the test setup from `setup()` to `setup_phase2()` is the cleanest approach. Tests that do NOT call `unregister()` (e.g., `register`, `top_up_stake`) can stay on `setup()` if desired, but for consistency it is simpler to migrate the entire file to `setup_phase2()`.

---

## Summary of Files Changed

| File | Change Type | Description |
|---|---|---|
| `sources/registry/room_manager.move` | MODIFY | Add `assigned_relay`, `assigned_signaling` to RoomInfo; add `assign_relay_and_signaling()`, `get_room_assignment()`, `RoomAssigned` event, field accessors; update `add_room_for_testing()` |
| `sources/registry/signaling_registry.move` | MODIFY | Add `remove_if_registered()` package-gated helper |
| `sources/miner/registration.move` | MODIFY | Add `&mut SignalingRegistry` param to `unregister()`; add `use dvconf::signaling_registry` |
| `tests/registry/room_manager_tests.move` | MODIFY | Add 5 assignment tests |
| `tests/registry/economic_layer_tests.move` | MODIFY | Add 4 tests (1x E_ROOM_NOT_FOUND, 3x E_PAUSED) |
| `tests/miner/registration_tests.move` | MODIFY | Update `unregister()` calls with SignalingRegistry param |

## Contract Change Notices Required

A CC notice is required for the `registration::unregister()` signature change:

```
CONTRACT CHANGE -- CC-004
Author: OnChain Agent
Phase: 14, Task: 02
WHAT CHANGED:
  Module: registration::unregister
  Before: unregister(store, position, ctx)
  After:  unregister(store, signaling_reg, position, ctx)
  Reason: TD-P11-04 signaling cleanup on unregister
AFFECTED DOMAINS:
  - OffChain -- any daemon code that builds an unregister PTB
BACKWARD COMPATIBLE: NO
```

This CC notice will be written to `docs/architecture/contract-changes/CC-004-unregister-signaling-cleanup.md` during implementation.
