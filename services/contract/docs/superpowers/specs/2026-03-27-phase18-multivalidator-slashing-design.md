# Phase 18: Multi-Validator Assignment + Slashing Fix — Design Spec

**Date:** 2026-03-27
**Status:** Approved
**Branch:** `feat/v4.0-decentralized-consensus`
**Scope:** Close MVAL-01–04 requirements + Spec Gap #2 (slashing)

## Context

Phase 17 (CP Voting Consensus) already built most multi-validator infrastructure:
- `RoomInfo.assigned_validators: vector<ID>` tracks validators per room
- PVR proposals include `validator_ids`, finalization populates them
- `distribute_rewards()` computes median across proofs + accuracy-weighted validator splits
- CP daemon builds proposals with validator selections

What remains: the `RoomAssigned` event doesn't include `validator_ids`, so validators can't detect their assignment. The validator daemon watches ALL rooms instead of filtering. And the slashing path is a no-op.

## Change 1: Add `validator_ids` to `RoomAssigned` Event

**Repo:** dvconf-contracts
**File:** `sources/registry/room_manager.move`

### What
Add `validator_ids: vector<ID>` field to the `RoomAssigned` event struct.

### Where it's emitted (3 sites)
1. **Consensus finalize** (~line 398): `winner.validator_ids` is available — pass it directly.
2. **`finalize_room` fallback** (~line 536): `winner.validator_ids` also available.
3. **`assign_relay_and_signaling` admin fallback** (~line 572): No validators assigned in admin path — emit empty vector.

### Impact
- All consumers of `RoomAssigned` events gain visibility into which validators are assigned.
- Existing tests that check `RoomAssigned` events need the new field in assertions.

## Change 2: Two-Step Relay Slashing

**Repo:** dvconf-contracts
**Files:** `sources/registry/economic_layer.move`, `sources/core/constants.move` (already has `SLASH_PERCENTAGE_BPS`)

### Why two-step?
`StakePosition` is an owned object (`has key` only). In Sui, only the owner can pass their owned object as `&mut` in a transaction. `distribute_rewards` is a crank (callable by anyone), so it cannot receive the relay's StakePosition. Making StakePosition shared would require updating ~60 test sites — too invasive for a gap closure.

### Step 1: Record slash in `distribute_rewards` (no signature change)

In the slash path (quality_multiplier == 0), calculate the real slash amount and record it:
```move
// Calculate slash from relay's registered stake amount (stored in RelayNodeInfo)
let relay_info = relay_registry::borrow_info(relay_reg, relay_miner_id);
let relay_stake_amount = relay_registry::info_stake_amount(relay_info);
let slash_amount = relay_stake_amount * constants::slash_percentage_bps() / constants::basis_points();

escrow.slash_amount = slash_amount;
escrow.slash_relay_miner_id = relay_miner_id;
escrow.slash_quality = quality_multiplier;

// Store other assigned relays (excluding the slashed one) for slash distribution
let all_relays = room_manager::room_assigned_relays(room_info);
let mut other_relays = vector::empty<ID>();
let mut i = 0;
while (i < vector::length(&all_relays)) {
    let r = *vector::borrow(&all_relays, i);
    if (r != relay_miner_id) { other_relays.push_back(r); };
    i = i + 1;
};
escrow.slash_other_relays = other_relays;
```

- Emit `RelaySlashed` with actual `slash_amount` (not 0)
- Relay reputation still set to 0
- Escrow still refunded to creator
- `distribute_rewards` signature **unchanged** — no breaking change

### Step 2: New `pay_slash` function with proportional distribution

The slashed coin is split between the room creator and other relays, proportional to quality:

```
creator_share = slash_amount × (10000 - quality) / 10000
relay_share   = slash_amount × quality / 10000
```

| Quality | Creator | Other relays | Rationale |
|---------|---------|--------------|-----------|
| 10000 (excellent) | 0% | 100% | Quality held — other relays absorbed work |
| 7500 (good) | 25% | 75% | Slight degradation |
| 5000 (acceptable) | 50% | 50% | Noticeable degradation |
| 0 (failure) | 100% | 0% | Total failure — creator fully compensated |

```move
public fun pay_slash(
    escrow: &mut RoomEscrow,
    relay_stake: &mut StakePosition,
    relay_reg: &mut RelayRegistry,
    ctx: &mut TxContext,
) {
    assert!(escrow.slash_amount > 0, E_NO_SLASH_PENDING);
    assert!(staking::miner_id(relay_stake) == escrow.slash_relay_miner_id, E_WRONG_STAKE);

    let coin = staking::slash(relay_stake, escrow.slash_amount, ctx);
    let total = coin::value(&coin);
    let bp = constants::basis_points(); // 10000

    // Proportional split based on quality at distribution time
    let quality = escrow.slash_quality;
    let relay_total = total * quality / bp;
    let creator_total = total - relay_total; // remainder to creator (avoids rounding loss)

    // Distribute relay share equally among other assigned relays
    let other_relays = &escrow.slash_other_relays;
    let num_others = vector::length(other_relays);
    if (relay_total > 0 && num_others > 0) {
        let per_relay = relay_total / num_others;
        let mut i = 0;
        while (i < num_others) {
            let relay_id = *vector::borrow(other_relays, i);
            let info = relay_registry::borrow_info(relay_reg, relay_id);
            let operator = relay_registry::info_operator(info);
            if (per_relay > 0) {
                let r_coin = coin::split(&mut coin, per_relay, ctx);
                transfer::public_transfer(r_coin, operator);
            };
            i = i + 1;
        };
    };

    // Remainder (creator share + rounding dust) to room creator
    if (coin::value(&coin) > 0) {
        transfer::public_transfer(coin, escrow.creator);
    } else {
        coin::destroy_zero(coin);
    };

    // Restore base reputation so relay can operate again
    relay_registry::set_reputation(relay_reg, escrow.slash_relay_miner_id, bp);

    escrow.slash_amount = 0;
}
```

Called by the relay operator with their own StakePosition (no ownership issue).

### Why the relay will pay
- Reputation = 0 after slash → zero future room assignments → zero income
- `pay_slash` restores reputation → relay can earn again
- Rational operator always pays (cost: 10% of stake; benefit: resume earning)
- If they rage-quit: system recorded the obligation, relay can't work — acceptable outcome

### Fallback: no other relays in room
If `slash_other_relays` is empty (single-relay room), 100% goes to creator regardless of quality. The proportional split only activates when there ARE other relays to compensate.

### New fields on RoomEscrow
- `slash_amount: u64` (0 = no pending slash)
- `slash_relay_miner_id: ID`
- `slash_quality: u64` (quality_multiplier at distribution time)
- `slash_other_relays: vector<ID>` (other assigned relays, excluding the slashed one)

### New error codes
- `E_NO_SLASH_PENDING = 663`
- `E_WRONG_STAKE = 664`

### Constants (already exist)
- `SLASH_PERCENTAGE_BPS = 1_000` (10% of stake)
- `slash_percentage_bps()` accessor exists

## Change 3: Validator Daemon Assignment Filtering

**Repo:** dvconf-daemons
**File:** `apps/validator-daemon/src/index.ts`

### Current behavior (broken)
- `RoomCreated` → immediately adds room to `activeRooms` → measures ALL rooms
- `RoomAssigned` → only extracts `relay_ids[0]` for relay endpoint

### New behavior
- `RoomCreated` → do NOT add to activeRooms (just log)
- `RoomAssigned` → check if own `validatorMinerId` is in `parsed.validator_ids`
  - If YES: add to `activeRooms` with relay info, start measuring
  - If NO: ignore (not assigned to this room)
- `RoomClosed` → only handle if room is in `activeRooms`

### ActiveRoom interface update
```typescript
export interface ActiveRoom {
  escrowId?: string;
  relayMinerId?: string;
  assigned?: boolean;  // NEW: true if this validator is assigned
}
```

## Change 4: Sync `RoomAssigned` TypeScript Type

**Repo:** dvconf-daemons
**File:** `packages/shared/src/types/events.ts`

### Current (stale)
```typescript
export interface RoomAssigned {
  room_id: string;
  relay_ids: string[];
  signaling_id: string;
}
```

### Updated (matches on-chain)
```typescript
export interface RoomAssigned {
  room_id: string;
  relay_ids: string[];
  signaling_id: string;
  relay_mode: number;
  verified_score: string;
  consensus_reached: boolean;
  winning_cp: string;
  validator_ids: string[];
}
```

## Tests

### Move tests (new)
1. **Slash records amount**: Create escrow → submit bad proofs (high packet loss) → distribute → assert `escrow.slash_amount > 0` and `RelaySlashed` event has real amount
2. **pay_slash quality=0 single relay**: All slashed coin to creator (100%), no other relays
3. **pay_slash quality=0 multi relay**: No other relays to pay (quality=0 → 100% creator), other relays get nothing
4. **pay_slash quality=5000 multi relay**: Creator gets 50%, other relays split 50% equally
5. **pay_slash quality=10000 multi relay**: Creator gets 0%, other relays get 100%
6. **pay_slash no other relays fallback**: Even with quality > 0, if single-relay room → 100% to creator
7. **pay_slash restores reputation**: After `pay_slash`, relay reputation restored to base (10000)
8. **pay_slash wrong stake aborts**: Pass mismatched StakePosition → expect abort 664
9. **pay_slash no pending aborts**: Call when `slash_amount == 0` → expect abort 663
10. **Normal path unaffected**: Good quality proofs → `slash_amount` stays 0, existing distribution works
11. **RoomAssigned event validator_ids**: Assert field populated after consensus finalize
12. **submit_session_proof rejects unassigned validator**: Validator not in `assigned_validators` → abort 662

### Daemon tests (updated)
1. **Assignment filtering**: RoomAssigned with own ID → added to activeRooms; without → ignored
2. **RoomCreated no longer auto-adds**: Verify room not in activeRooms until RoomAssigned

## Files Changed (summary)

| Repo | File | Change |
|------|------|--------|
| contracts | `sources/registry/room_manager.move` | Add `validator_ids` to `RoomAssigned` event |
| contracts | `sources/registry/economic_layer.move` | Two-step slash (`pay_slash`), assignment check in `submit_session_proof`, new error codes |
| contracts | `tests/registry/economic_layer_tests.move` | 8 new tests (slash, pay_slash, assignment enforcement) |
| contracts | `tests/registry/room_manager_tests.move` | Assert `validator_ids` in event |
| daemons | `packages/shared/src/types/events.ts` | Sync `RoomAssigned` fields |
| daemons | `apps/validator-daemon/src/index.ts` | Filter by assignment |
| daemons | `apps/validator-daemon/src/__tests__/index.test.ts` | Assignment filtering tests |

## Change 6: Enforce Validator Assignment in `submit_session_proof`

**Repo:** dvconf-contracts
**File:** `sources/registry/economic_layer.move`

### What
After resolving `validator_miner_id` from the session wallet, assert that the validator is in the room's `assigned_validators` list. Currently any registered validator can submit a proof for any room.

### Where
After line ~193 (lookup_session_wallet), before the duplicate check:
```move
// Verify validator is assigned to this room
let room_info = room_manager::borrow_room(room_mgr, escrow.room_id);
let assigned = room_manager::room_assigned_validators(room_info);
let mut found = false;
let mut i = 0;
while (i < vector::length(&assigned)) {
    if (*vector::borrow(&assigned, i) == validator_miner_id) {
        found = true;
        break
    };
    i = i + 1;
};
assert!(found, E_VALIDATOR_NOT_ASSIGNED);
```

### New error code
`E_VALIDATOR_NOT_ASSIGNED = 662`

### Impact
- `submit_session_proof` signature gains `room_mgr: &RoomManager` parameter
- Daemon PTB for proof submission must pass `roomManagerId`
- Existing tests that submit proofs via `add_proof_for_testing` are unaffected (test helper bypasses)

## Future Work (Thesis Conclusion)

Document these as concrete next steps that strengthen the validator trust model:

### 1. Raise `MIN_VALIDATORS_PER_ROOM` to 3+
Currently set to 2. With 2 validators, both must collude to corrupt the median — possible but detectable. With 3+, majority collusion becomes significantly harder: an attacker must control >50% of randomly assigned validators for a specific room. The constant exists in `constants.move` (`DEFAULT_MIN_VALIDATORS_PER_ROOM`); changing it is a one-line governance update. Deferred because thesis test networks rarely have 3+ validators running simultaneously.

### 2. Slash validators for consistent median deviation
Currently only relays are slashed. Validators who consistently report values far from the median across multiple rooms should face stake penalties. Implementation: track per-validator accuracy scores over a sliding window (e.g., last 10 rooms). If average accuracy drops below a threshold (e.g., 3000 bps), trigger a validator slash via the same two-step `pay_slash` pattern used for relays. This closes the "lazy validator" attack where a validator submits random data to collect rewards without actually measuring.

## Out of Scope
- Gaps 1, 3–8 from SPEC-VS-IMPL.md (documentation only — handled in thesis writing)
- Client changes (already reads `assigned_validators`)
- Validator selection algorithm in CP daemon (already implemented in Phase 17)
