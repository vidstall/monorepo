# CC-001 — `registration::apply_voted_role` signature change (F47 Phase 1.5)

> **Type**: Backward-INCOMPATIBLE ABI change (Move entry signature).
> **Origin**: F47 role-revote-pool Phase 1.5 (REQ-RV-005 / RV-006).
> **Date**: 2026-05-30 (S66).
> **Status**: All call sites updated in the same change set (contracts + daemons + client).

## What changed

`registration::apply_voted_role` gained **4 role-registry parameters** so the entry can
remove the miner's stale OLD-role registry entry on a genuine role transition (mirrors
`unregister`'s cross-registry cleanup). It also added an apply-side Q5 CP-migration guard
and a `RoleTransitioned` event — neither affects the ABI.

### Before (5 PTB objects + auto ctx)

```
apply_voted_role(registry, store, vote_box, cap, stake, ctx)
```

### After (9 PTB objects + auto ctx)

```
apply_voted_role(
    registry,        // &NetworkRegistry         (1)
    store,           // &mut MinerStore           (2)
    vote_box,        // &mut RoleVoteBox          (3)
    signaling_reg,   // &mut SignalingRegistry    (4)  NEW
    relay_reg,       // &mut RelayRegistry        (5)  NEW
    validator_reg,   // &mut ValidatorRegistry    (6)  NEW
    cp_reg,          // &mut ControlPlaneRegistry (7)  NEW
    cap,             // &mut MinerCap             (8)
    stake,           // &mut StakePosition        (9)
    ctx,             // &TxContext (auto-injected, NOT a PTB arg)
)
```

The 4 new objects are inserted **between `vote_box` and `cap`**. Any client/daemon that
builds the PTB `arguments[]` array must match this order exactly.

## moveCall sites that MUST match the deployed package

| # | Site | Form | Status |
|---|------|------|--------|
| 1 | `dvconf-daemons/packages/shared/src/chain/role-assignment.ts` (`applyVotedRole` wrapper — used by all 4 daemons via `auto-register.ts`) | raw `tx.moveCall(arguments[])` | ✅ updated to 9 args |
| 2 | `dvconf-client/src/components/dashboard/RegisterMinerPanel.tsx` (browser-wallet voting-mode register flow) | raw `applyTx.moveCall(arguments[])` | ✅ updated to 9 args |

> The 4 daemon `auto-register.ts` call sites (relay / cp-daemon / validator-daemon / signaling)
> go **through** the shared wrapper and source the registry IDs from `config` internally, so
> their `applyVotedRole(...)` calls are unchanged. There are exactly **2** raw moveCall sites.

## Deploy sequencing (lockstep — required)

Because both TS sites now pass 9 objects while the **currently-deployed** package still exposes
the 5-arg function, a partial rollout breaks every voting-mode role application with an opaque
PTB arity error. Sequence the release as one unit:

1. Publish the new Move package (`dvconf-contracts`).
2. Update `config`/env `PACKAGE_ID` everywhere.
3. Deploy daemons (`@dvconf/shared` rebuilt) **and** rebuild/redeploy the client bundle.

No code path is safe until all three land against the same published `PACKAGE_ID`.

## Related

- `docs/20-decisions/ADR-0008-role-revote-mechanism.md` — F47 mechanism + `RoleTransitioned` schema lock.
- `plans/role-revote-pool/milestone-1/ROADMAP.md` Phase 1.5.
- `plans/role-revote-pool/milestone-1/STATUS.md` row 1.5.
