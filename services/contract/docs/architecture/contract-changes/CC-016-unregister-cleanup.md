# CC-016: Cross-Registry Cleanup on Unregister

**Date**: 2026-03-16
**Author**: OnChain Agent
**Affected Domains**: OnChain, OffChain (daemon TX calls)

## Summary

`registration::unregister()` signature expanded to accept all 4 role registries for cross-registry cleanup on miner unregistration.

## Before

```move
public fun unregister(
    store: &mut MinerStore,
    signaling_reg: &mut SignalingRegistry,
    position: StakePosition,
    ctx: &mut TxContext
)
```

## After

```move
public fun unregister(
    store: &mut MinerStore,
    signaling_reg: &mut SignalingRegistry,
    relay_reg: &mut RelayRegistry,
    validator_reg: &mut ValidatorRegistry,
    cp_reg: &mut ControlPlaneRegistry,
    position: StakePosition,
    ctx: &mut TxContext
)
```

## New Package Functions

Added `public(package) fun remove_if_registered(registry, miner_id)` to:
- `relay_registry.move`
- `validator_registry.move`
- `control_plane_registry.move`

These mirror the existing function in `signaling_registry.move`.

## Impact

- **OffChain daemons**: Any daemon that calls `unregister` must now pass the 3 additional registry object IDs (`RelayRegistry`, `ValidatorRegistry`, `ControlPlaneRegistry`) as transaction arguments.
- **Client**: If the client exposes unregister functionality, it must pass the additional objects.
- **On-chain**: No breaking changes to other modules; the new `remove_if_registered` functions are package-only.

## Rationale

Previously, unregistering a miner only cleaned up the SignalingRegistry. If a miner was registered in RelayRegistry, ValidatorRegistry, or ControlPlaneRegistry, those entries would become orphaned. This change ensures all role-specific entries are cleaned up atomically.
