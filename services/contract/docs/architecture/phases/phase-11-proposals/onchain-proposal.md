DESIGN PROPOSAL — OnChain: Phase 11 Signaling Registry
Author: OnChain Agent
Phase: 11
Date: 2026-03-11

---

PURPOSE:

Extend the DVConf on-chain protocol to support signaling nodes as a new staked
role. Signaling nodes route text messages (SDP, ICE candidates) between peers —
they carry no media. This proposal covers four tasks:

1. Add ROLE_SIGNALING = 4 to the role system (constants, thresholds, role
   determination).
2. Create a new SignalingRegistry module mirroring ControlPlaneRegistry for
   registration, heartbeat, load tracking, and unregistration.
3. Full test coverage for the SignalingRegistry module.
4. Fix two ownership bugs in relay_registry where `update_load()` and
   `update_mode()` fail to verify `ctx.sender() == info.operator`.

Rewards (SIG-05) and slashing (SIG-06) are OUT OF SCOPE — deferred to Phase 13
(Economic Layer).

---

OWNS:

- `sources/core/constants.move` — new constant + accessor (ROLE_SIGNALING, DEFAULT_SIGNALING_THRESHOLD)
- `sources/core/network_registry.move` — RoleThresholds struct expansion, update_role_thresholds signature change, init/init_for_testing changes
- `sources/miner/staking.move` — determine_role() and minimum_for_role() signaling tier
- `sources/miner/miner_store.move` — role_signaling() accessor, add_to_role_set/remove_from_role_set signaling branch
- `sources/registry/signaling_registry.move` — NEW module
- `tests/registry/signaling_registry_tests.move` — NEW test file
- `sources/registry/relay_registry.move` — ownership bug fix
- `tests/registry/relay_registry_tests.move` — new tests for ownership bug fix

---

STRUCTS / TYPES:

### constants.move — New Constants

```move
const ROLE_SIGNALING: u8 = 4;
const DEFAULT_SIGNALING_THRESHOLD: u64 = 250_000_000; // 0.25 DVCONF
```

### network_registry.move — RoleThresholds (changed)

```move
public struct RoleThresholds has store, copy, drop {
    cp_threshold:        u64,   // 2_000_000_000 (2 DVCONF)
    relay_threshold:     u64,   // 1_000_000_000 (1 DVCONF)
    validator_threshold: u64,   //   500_000_000 (0.5 DVCONF)
    signaling_threshold: u64,   //   250_000_000 (0.25 DVCONF) ← NEW
}
```

### signaling_registry.move — SignalingNodeInfo

```move
public struct SignalingNodeInfo has store, copy, drop {
    operator:       address,
    miner_id:       ID,
    stake_amount:   u64,
    last_heartbeat: u64,
    is_active:      bool,
    endpoint_url:   vector<u8>,   // full WebSocket URL, e.g. "wss://sig1.dvconf.io"
    region:         vector<u8>,   // e.g. "us-east"
    load:           u64,          // active WebSocket connection count
    registered_at:  u64,
}
```

### signaling_registry.move — SignalingRegistry

```move
public struct SignalingRegistry has key {
    id: UID,
    nodes:        Table<ID, SignalingNodeInfo>,   // miner_id -> info
    active_set:   VecSet<ID>,                     // active signaling node miner_ids
}
```

### signaling_registry.move — Events

```move
public struct SignalingRegistered has copy, drop {
    miner_id:     ID,
    operator:     address,
    endpoint_url: vector<u8>,
    region:       vector<u8>,
    stake_amount: u64,
}

public struct SignalingHeartbeat has copy, drop {
    miner_id: ID,
    epoch:    u64,
}

public struct SignalingLoadUpdated has copy, drop {
    miner_id: ID,
    new_load: u64,
}

public struct SignalingUnregistered has copy, drop {
    miner_id: ID,
    operator: address,
}
```

---

PUBLIC API:

### constants.move — New Accessors

```move
public fun role_signaling(): u8 { ROLE_SIGNALING }
public fun default_signaling_threshold(): u64 { DEFAULT_SIGNALING_THRESHOLD }
```

### network_registry.move — Changed Functions

```move
// Accessor for new threshold field
public fun signaling_threshold(t: &RoleThresholds): u64 { t.signaling_threshold }

// Updated signature — 4th parameter added
public fun update_role_thresholds(
    _: &AdminCap,
    registry: &mut NetworkRegistry,
    cp: u64, relay: u64, validator: u64, signaling: u64,
) {
    // Ordering invariant: cp >= relay >= validator >= signaling
    assert!(cp >= relay && relay >= validator && validator >= signaling, E_INVALID_THRESHOLD);
    registry.role_thresholds = RoleThresholds {
        cp_threshold: cp,
        relay_threshold: relay,
        validator_threshold: validator,
        signaling_threshold: signaling,
    };
}
```

`init()` and `init_for_testing()` updated to include `signaling_threshold: constants::default_signaling_threshold()` in the RoleThresholds construction.

### staking.move — Changed Functions

```move
// determine_role: signaling tier inserted BEFORE user fallback
public fun determine_role(stake_amount: u64, registry: &NetworkRegistry): u8 {
    let t = network_registry::role_thresholds(registry);
    if (stake_amount >= network_registry::cp_threshold(&t)) {
        miner_store::role_cp()
    } else if (stake_amount >= network_registry::relay_threshold(&t)) {
        miner_store::role_relay()
    } else if (stake_amount >= network_registry::validator_threshold(&t)) {
        miner_store::role_validator()
    } else if (stake_amount >= network_registry::signaling_threshold(&t)) {
        miner_store::role_signaling()    // ← NEW branch
    } else {
        miner_store::role_user()
    }
}

// minimum_for_role: signaling tier added
public fun minimum_for_role(role: u8, registry: &NetworkRegistry): u64 {
    let t = network_registry::role_thresholds(registry);
    if (role == miner_store::role_cp()) {
        network_registry::cp_threshold(&t)
    } else if (role == miner_store::role_relay()) {
        network_registry::relay_threshold(&t)
    } else if (role == miner_store::role_validator()) {
        network_registry::validator_threshold(&t)
    } else if (role == miner_store::role_signaling()) {
        network_registry::signaling_threshold(&t)    // ← NEW branch
    } else {
        0
    }
}
```

### miner_store.move — New Accessor + Role Set Changes

```move
// New role accessor
public fun role_signaling(): u8 { constants::role_signaling() }

// add_to_role_set: signaling branch added (uses user_miners set for now,
// or a new signaling_miners VecSet if MinerStore is extended)
// Decision: Add signaling_miners VecSet<ID> to MinerStore, plus
// signaling_count() and signaling_set() accessors.
```

NOTE: MinerStore gains a new field `signaling_miners: VecSet<ID>`. The
`add_to_role_set()` and `remove_from_role_set()` internal helpers gain an
`else if (role == constants::role_signaling())` branch routing to this set.
The `init()` and `init_for_testing()` functions are updated to initialize
`signaling_miners: vec_set::empty()`. New accessors:

```move
public fun signaling_count(store: &MinerStore): u64 { vec_set::length(&store.signaling_miners) }
public fun signaling_set(store: &MinerStore): &VecSet<ID> { &store.signaling_miners }
```

### signaling_registry.move — Full API

```move
/// AdminCap-gated constructor. Creates shared SignalingRegistry object.
public fun create(_: &AdminCap, ctx: &mut TxContext)

/// Register a signaling node. MinerCap must have role == ROLE_SIGNALING.
/// Checks: pause, role, duplicate.
/// Emits: SignalingRegistered
public fun register_signaling(
    net_reg: &NetworkRegistry,
    registry: &mut SignalingRegistry,
    cap: &MinerCap,
    stake: &StakePosition,
    endpoint_url: vector<u8>,
    region: vector<u8>,
    ctx: &mut TxContext,
)

/// Heartbeat — updates last_heartbeat, re-activates if inactive.
/// Checks: pause, registered.
/// Emits: SignalingHeartbeat
public fun heartbeat(
    net_reg: &NetworkRegistry,
    registry: &mut SignalingRegistry,
    cap: &MinerCap,
    ctx: &mut TxContext,
)

/// Update self-reported load (active connection count).
/// Checks: pause, registered, ownership (cap miner_id matches).
/// Emits: SignalingLoadUpdated
public fun update_load(
    net_reg: &NetworkRegistry,
    registry: &mut SignalingRegistry,
    cap: &MinerCap,
    new_load: u64,
    ctx: &mut TxContext,
)

/// Unregister a signaling node. Removes from table and active set.
/// Emits: SignalingUnregistered
public fun unregister_signaling(
    registry: &mut SignalingRegistry,
    cap: &MinerCap,
    ctx: &mut TxContext,
)

// ── Read Accessors ──

public fun active_signaling_count(r: &SignalingRegistry): u64
public fun is_registered(r: &SignalingRegistry, miner_id: ID): bool
public fun borrow_info(r: &SignalingRegistry, miner_id: ID): &SignalingNodeInfo

// Field accessors on SignalingNodeInfo
public fun info_operator(i: &SignalingNodeInfo): address
public fun info_miner_id(i: &SignalingNodeInfo): ID
public fun info_stake_amount(i: &SignalingNodeInfo): u64
public fun info_last_heartbeat(i: &SignalingNodeInfo): u64
public fun info_is_active(i: &SignalingNodeInfo): bool
public fun info_endpoint_url(i: &SignalingNodeInfo): vector<u8>
public fun info_region(i: &SignalingNodeInfo): vector<u8>
public fun info_load(i: &SignalingNodeInfo): u64
public fun info_registered_at(i: &SignalingNodeInfo): u64

// ── Test Only ──

#[test_only]
public fun init_for_testing(ctx: &mut TxContext)
```

### relay_registry.move — Bug Fix (Task 4)

`update_load()` — add ownership check after E_NOT_REGISTERED:

```move
public fun update_load(
    net_reg: &NetworkRegistry,
    registry: &mut RelayRegistry,
    cap: &MinerCap,
    new_load: u64,
    ctx: &mut TxContext,        // ← was _ctx, now used
) {
    assert!(!network_registry::is_paused(net_reg), E_PAUSED);
    let miner_id = caps::miner_cap_miner_id(cap);
    assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);
    assert!(caps::miner_cap_role(cap) == constants::role_relay(), E_NOT_RELAY);

    // BUG FIX: verify caller is the registered operator
    let info = table::borrow(&registry.nodes, miner_id);
    assert!(info.operator == ctx.sender(), E_NOT_OPERATOR);  // error 524

    *table::borrow_mut(&mut registry.loads, miner_id) = new_load;
    event::emit(RelayLoadUpdated { miner_id, new_load });
}
```

`update_mode()` — add ownership check after E_NOT_REGISTERED:

```move
public fun update_mode(
    net_reg: &NetworkRegistry,
    registry: &mut RelayRegistry,
    cap: &MinerCap,
    new_mode: u8,
    ctx: &mut TxContext,        // ← was _ctx, now used
) {
    assert!(!network_registry::is_paused(net_reg), E_PAUSED);
    assert!(caps::miner_cap_role(cap) == constants::role_relay(), E_NOT_RELAY);
    assert!(
        new_mode == constants::relay_mode_sfu() || new_mode == constants::relay_mode_mcu(),
        E_INVALID_MODE,
    );

    let miner_id = caps::miner_cap_miner_id(cap);
    assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

    // BUG FIX: verify caller is the registered operator
    let info = table::borrow(&registry.nodes, miner_id);
    assert!(info.operator == ctx.sender(), E_NOT_OPERATOR);  // error 524

    let info_mut = table::borrow_mut(&mut registry.nodes, miner_id);
    info_mut.mode = new_mode;
}
```

The `_ctx` parameter in both functions becomes `ctx` (used for `ctx.sender()`).
The existing `E_NOT_OPERATOR: u64 = 524` constant is already defined in
relay_registry.move but was never used — now it is.

---

DEPENDS ON:

| Dependency | Module | Reason |
|---|---|---|
| `dvconf::constants` | constants.move | ROLE_SIGNALING, DEFAULT_SIGNALING_THRESHOLD |
| `dvconf::network_registry` | network_registry.move | NetworkRegistry, AdminCap, is_paused(), role_thresholds(), signaling_threshold() |
| `dvconf::caps` | caps.move | MinerCap, miner_cap_miner_id(), miner_cap_role() |
| `dvconf::staking` | staking.move | StakePosition, amount() |
| `dvconf::miner_store` | miner_store.move | role_signaling() accessor |
| `sui::table` | Sui stdlib | Table storage for nodes |
| `sui::vec_set` | Sui stdlib | Active set tracking |
| `sui::event` | Sui stdlib | Event emission |

No new dependencies on caps.move — signaling nodes reuse MinerCap (role=4).
No changes to caps.move or registration.move are needed.

---

ERROR CODES:

### signaling_registry.move — Namespace 600-609

| Code | Constant | Description |
|---|---|---|
| 600 | `E_NOT_SIGNALING` | MinerCap role is not ROLE_SIGNALING (4) |
| 601 | `E_ALREADY_REGISTERED` | Signaling node already in registry |
| 602 | `E_NOT_REGISTERED` | Signaling node not found in registry |
| 603 | `E_PAUSED` | Network is paused (circuit breaker) |
| 604 | `E_NOT_OPERATOR` | ctx.sender() does not match registered operator |

Codes 605-609 are reserved for future use in this module.

### relay_registry.move — Existing Code (No New Constants)

| Code | Constant | Description | Status |
|---|---|---|---|
| 524 | `E_NOT_OPERATOR` | ctx.sender() does not match registered operator | Already defined, now ACTIVATED |

---

EVENTS EMITTED:

### signaling_registry.move

| Event | Fields | Emitted By |
|---|---|---|
| `SignalingRegistered` | `miner_id: ID, operator: address, endpoint_url: vector<u8>, region: vector<u8>, stake_amount: u64` | `register_signaling()` |
| `SignalingHeartbeat` | `miner_id: ID, epoch: u64` | `heartbeat()` |
| `SignalingLoadUpdated` | `miner_id: ID, new_load: u64` | `update_load()` |
| `SignalingUnregistered` | `miner_id: ID, operator: address` | `unregister_signaling()` |

---

OPEN QUESTIONS:

1. **MinerStore struct migration**: Adding `signaling_miners: VecSet<ID>` to
   MinerStore changes the struct layout. Since MinerStore is created in `init()`
   at first publish, a package upgrade cannot re-run `init()`. Options:
   (a) Add a migration function `migrate_v2(&AdminCap, &mut MinerStore)` that
       adds the field (requires dynamic field or versioned struct pattern).
   (b) Accept that on localnet/testnet we re-publish from scratch, and for
       mainnet we use a versioned struct approach.
   (c) Use a separate `Table` or dynamic field for signaling miners instead of
       a VecSet field.
   **Recommendation**: For thesis scope, option (b) — re-publish. Note this as
   tech debt for production.

2. **RoleThresholds struct migration**: Same issue as MinerStore. Adding
   `signaling_threshold` changes the struct. On upgrade, existing
   NetworkRegistry objects have the old 3-field layout.
   **Recommendation**: Same as above — re-publish for thesis. Document as tech
   debt.

3. **Should `unregister_signaling()` require a pause check?**: The
   ControlPlaneRegistry pattern does not have an `unregister` function at all.
   For signaling, allowing unregister even when paused is safer (lets operators
   exit). Proposed: no pause check on `unregister_signaling()`.

4. **Signaling load unit**: Load is defined as "active WebSocket connection
   count" (u64). Should we cap it or normalize it? Proposed: no cap — the
   client scoring algorithm handles relative comparison. Store raw count.

5. **update_load ownership in signaling_registry**: The plan says ownership
   check "via MinerCap". Since MinerCap is an owned object that only the
   operator's wallet holds, possession of the cap IS the ownership proof.
   However, for defense-in-depth (matching the relay_registry bug fix pattern),
   we should also assert `ctx.sender() == info.operator`. Proposed: do both —
   role check via cap, operator check via sender.
