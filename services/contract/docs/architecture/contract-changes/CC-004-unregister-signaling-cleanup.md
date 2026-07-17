# CONTRACT CHANGE -- CC-004

**Author:** OnChain Agent
**Phase:** 14, Task 02 (TD-P11-04)
**Date:** 2026-03-12

## WHAT CHANGED

**Module:** `registration::unregister`

**Before:**
```move
public fun unregister(
    store: &mut MinerStore,
    position: StakePosition,
    ctx: &mut TxContext,
)
```

**After:**
```move
public fun unregister(
    store: &mut MinerStore,
    signaling_reg: &mut SignalingRegistry,
    position: StakePosition,
    ctx: &mut TxContext,
)
```

**Reason:** TD-P11-04 cross-registry cleanup on unregister. When a miner unregisters, any signaling node entry associated with that miner is silently removed via `signaling_registry::remove_if_registered()`. This prevents orphaned signaling entries from persisting after unregistration.

## AFFECTED DOMAINS

- **OffChain** -- daemon code building unregister PTBs must add SignalingRegistry shared object ID as second argument (after MinerStore, before StakePosition).

## MIGRATION GUIDE

1. Add SignalingRegistry object ID to daemon config (`SIGNALING_REGISTRY_ID`)
2. In PTB construction, add `tx.object(config.signalingRegistryId)` as the second argument (after MinerStore, before StakePosition)

## BACKWARD COMPATIBLE

**NO** -- All callers of `registration::unregister()` must update their PTB construction to include the new `&mut SignalingRegistry` parameter.
