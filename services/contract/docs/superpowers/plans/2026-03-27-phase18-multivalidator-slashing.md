# Phase 18: Multi-Validator Assignment + Slashing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce multi-validator assignment filtering, add real stake slashing with proportional distribution, and close the last on-chain enforcement gaps.

**Architecture:** On-chain changes in economic_layer (slash recording, pay_slash, assignment check) and room_manager (event field). Off-chain changes in validator daemon (assignment filtering) and shared types. No signature changes to distribute_rewards — slash uses a two-step record-then-pay pattern.

**Tech Stack:** Sui Move (contracts + tests), TypeScript/Vitest (daemon tests)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `sources/registry/economic_layer.move` | Add escrow slash fields, record slash in distribute_rewards, add pay_slash, enforce assignment in submit_session_proof |
| Modify | `sources/registry/room_manager.move` | Add validator_ids to RoomAssigned event |
| Modify | `tests/registry/economic_layer_tests.move` | 12 new tests for slash + assignment enforcement |
| Modify | `tests/registry/room_manager_tests.move` | Assert validator_ids in RoomAssigned event |
| Modify | `sources/registry/room_manager.move` (test_only) | Add set_assigned_relays_for_testing, set_assigned_validators_for_testing helpers |
| Modify | `packages/shared/src/types/events.ts` (dvconf-daemons) | Sync RoomAssigned type |
| Modify | `apps/validator-daemon/src/index.ts` (dvconf-daemons) | Filter by assignment |
| Modify | `apps/validator-daemon/src/__tests__/index.test.ts` (dvconf-daemons) | Assignment filtering tests |

---

### Task 1: Add slash fields to RoomEscrow + test helpers

**Files:**
- Modify: `sources/registry/economic_layer.move:58-65` (RoomEscrow struct)
- Modify: `sources/registry/economic_layer.move:130-137` (create_escrow constructor)
- Modify: `sources/registry/economic_layer.move:710-714` (read accessors)
- Modify: `sources/registry/economic_layer.move:722-735` (create_escrow_for_testing)
- Modify: `sources/registry/economic_layer.move:778-781` (destroy_escrow_for_testing)

- [ ] **Step 1: Add slash fields to RoomEscrow struct**

In `sources/registry/economic_layer.move`, add 4 fields after `distributed: bool`:

```move
    public struct RoomEscrow has key {
        id:          UID,
        room_id:     ID,
        creator:     address,
        escrow:      Balance<SUI>,
        proofs:      vector<SessionProof>,
        distributed: bool,
        // ── Slash tracking (Phase 18) ──
        slash_amount:          u64,
        slash_relay_miner_id:  ID,
        slash_quality:         u64,
        slash_other_relays:    vector<ID>,
    }
```

- [ ] **Step 2: Initialize slash fields in create_escrow**

In the `create_escrow` function (~line 130), add the new fields to the `RoomEscrow` constructor:

```move
        let escrow_obj = RoomEscrow {
            id: object::new(ctx),
            room_id,
            creator: ctx.sender(),
            escrow: coin::into_balance(payment),
            proofs: vector::empty(),
            distributed: false,
            slash_amount: 0,
            slash_relay_miner_id: object::id_from_address(@0x0),
            slash_quality: 0,
            slash_other_relays: vector::empty(),
        };
```

- [ ] **Step 3: Initialize slash fields in create_escrow_for_testing**

Same fields in the test helper (~line 728):

```move
        RoomEscrow {
            id: object::new(ctx),
            room_id,
            creator,
            escrow: coin::into_balance(payment),
            proofs: vector::empty(),
            distributed: false,
            slash_amount: 0,
            slash_relay_miner_id: object::id_from_address(@0x0),
            slash_quality: 0,
            slash_other_relays: vector::empty(),
        }
```

- [ ] **Step 4: Update destroy_escrow_for_testing destructure**

Update the destructure pattern (~line 779):

```move
    public fun destroy_escrow_for_testing(escrow: RoomEscrow) {
        let RoomEscrow {
            id, room_id: _, creator: _, escrow: bal, proofs: _,
            distributed: _, slash_amount: _, slash_relay_miner_id: _,
            slash_quality: _, slash_other_relays: _,
        } = escrow;
        object::delete(id);
        balance::destroy_for_testing(bal);
    }
```

- [ ] **Step 5: Add read accessors for slash fields**

After the existing accessors (~line 714):

```move
    public fun escrow_slash_amount(e: &RoomEscrow): u64          { e.slash_amount }
    public fun escrow_slash_quality(e: &RoomEscrow): u64         { e.slash_quality }
    public fun escrow_slash_relay_id(e: &RoomEscrow): ID         { e.slash_relay_miner_id }
    public fun escrow_slash_other_relays(e: &RoomEscrow): vector<ID> { e.slash_other_relays }
```

- [ ] **Step 6: Add new error codes**

After `E_RELAY_NOT_REGISTERED = 661`, add:

```move
    const E_VALIDATOR_NOT_ASSIGNED: u64 = 662;
    const E_NO_SLASH_PENDING: u64      = 663;
    const E_WRONG_STAKE: u64           = 664;
```

- [ ] **Step 7: Run tests to verify nothing breaks**

Run: `sui move test --silence-warnings`

Expected: All 200 existing tests pass. No new tests yet — just structural changes.

- [ ] **Step 8: Commit**

```bash
git add sources/registry/economic_layer.move
git commit -m "feat(economic_layer): add slash tracking fields to RoomEscrow

Add slash_amount, slash_relay_miner_id, slash_quality, slash_other_relays
fields to RoomEscrow struct for two-step relay slashing (Phase 18).
Initialize to zero/empty in both production and test constructors.
Add read accessors and error codes E_VALIDATOR_NOT_ASSIGNED (662),
E_NO_SLASH_PENDING (663), E_WRONG_STAKE (664)."
```

---

### Task 2: Wire slash recording into distribute_rewards

**Files:**
- Modify: `sources/registry/economic_layer.move:345-372` (slash path in distribute_rewards)

- [ ] **Step 1: Write the test — slash records real amount**

In `tests/registry/economic_layer_tests.move`, add after the last test:

```move
    // ══════════════════════════════════════════════════════════
    // TEST: Slash path records real slash_amount (Phase 18)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_slash_records_amount() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Both validators report 20% packet loss (2000 bps) → quality_multiplier = 0
        let escrow_amount = 1_000_000u64;
        h::mint_to(&mut scenario, escrow_amount, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 50000, 0, 300, 50, 2000, 20, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id(),
                1000, 50000, 0, 300, 50, 1500, 20, 0,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Distribute (triggers slash path)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let sig_reg = ts::take_shared<SignalingRegistry>(&scenario);

            economic_layer::distribute_rewards(
                &net_reg, &mut escrow, &room_mgr,
                &mut relay_reg, &mut val_reg,
                &cp_reg, &sig_reg,
                ts::ctx(&mut scenario),
            );

            // Slash amount should be 10% of relay's registered stake
            // Relay stake = h::relay_stake() = 250_000_000 (0.25 SUI)
            // SLASH_PERCENTAGE_BPS = 1000 (10%)
            // Expected: 250_000_000 * 1000 / 10000 = 25_000_000
            let expected_slash = h::relay_stake() * constants::slash_percentage_bps() / constants::basis_points();
            assert!(economic_layer::escrow_slash_amount(&escrow) == expected_slash);
            assert!(economic_layer::escrow_slash_quality(&escrow) == 0); // quality was 0

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sui move test --filter test_slash_records_amount`

Expected: FAIL — `escrow_slash_amount` returns 0 (current code doesn't set it).

- [ ] **Step 3: Implement slash recording in distribute_rewards**

In `sources/registry/economic_layer.move`, replace the slash path (lines ~345-372) with:

```move
        if (quality_multiplier == 0) {
            // Slash path: poor quality — record slash for two-step enforcement
            relay_registry::set_reputation(relay_reg, relay_miner_id, 0);

            // Calculate slash from relay's registered stake amount
            let relay_info = relay_registry::borrow_info(relay_reg, relay_miner_id);
            let relay_stake_amount = relay_registry::info_stake_amount(relay_info);
            let slash_amount = relay_stake_amount * constants::slash_percentage_bps() / bp;

            // Store other assigned relays (excluding the slashed one) for pay_slash distribution
            let all_relays = room_manager::room_assigned_relays(room_info);
            let mut other_relays = vector::empty<ID>();
            let mut r = 0;
            while (r < vector::length(&all_relays)) {
                let rid = *vector::borrow(&all_relays, r);
                if (rid != relay_miner_id) { other_relays.push_back(rid); };
                r = r + 1;
            };

            escrow.slash_amount = slash_amount;
            escrow.slash_relay_miner_id = relay_miner_id;
            escrow.slash_quality = quality_multiplier;
            escrow.slash_other_relays = other_relays;

            event::emit(RelaySlashed {
                room_id,
                relay_miner_id,
                slash_amount,
            });

            // Refund escrow to creator (they got bad service)
            let escrow_value = balance::value(&escrow.escrow);
            if (escrow_value > 0) {
                let remainder_coin = coin::from_balance(
                    balance::split(&mut escrow.escrow, escrow_value), ctx,
                );
                transfer::public_transfer(remainder_coin, escrow.creator);
            };

            escrow.distributed = true;

            event::emit(RewardsDistributed {
                room_id,
                relay_reward: 0,
                validator_pool: 0,
                cp_pool: 0,
                signaling_pool: 0,
                remainder: escrow_value,
            });
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sui move test --filter test_slash_records_amount`

Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `sui move test --silence-warnings`

Expected: All tests pass (existing slash test `test_slash_returns_escrow_to_creator` should still pass since escrow refund behavior is unchanged).

- [ ] **Step 6: Commit**

```bash
git add sources/registry/economic_layer.move tests/registry/economic_layer_tests.move
git commit -m "feat(economic_layer): record real slash amount in distribute_rewards

Slash path now calculates slash_amount from relay's registered stake
(stake_amount * SLASH_PERCENTAGE_BPS / 10000) and records it in the
escrow along with quality and other relay IDs for proportional
distribution in pay_slash. RelaySlashed event now emits real amount."
```

---

### Task 3: Implement pay_slash with proportional distribution

**Files:**
- Modify: `sources/registry/economic_layer.move` (add pay_slash function)
- Modify: `sources/registry/room_manager.move` (add test helpers)
- Modify: `tests/registry/economic_layer_tests.move` (6 new tests)

- [ ] **Step 1: Add test helper — set_assigned_relays_for_testing**

In `sources/registry/room_manager.move`, after `set_assigned_signaling_for_testing` (~line 756):

```move
    #[test_only]
    /// Set assigned relays for a room (for testing slash distribution).
    public fun set_assigned_relays_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        relay_ids: vector<ID>,
    ) {
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.assigned_relays = relay_ids;
    }

    #[test_only]
    /// Set assigned validators for a room (for testing assignment enforcement).
    public fun set_assigned_validators_for_testing(
        manager: &mut RoomManager,
        room_id: ID,
        validator_ids: vector<ID>,
    ) {
        let info = table::borrow_mut(&mut manager.rooms, room_id);
        info.assigned_validators = validator_ids;
    }
```

- [ ] **Step 2: Add a test helper — set_slash_for_testing**

In `sources/registry/economic_layer.move`, in the test_only section:

```move
    #[test_only]
    /// Set slash fields on an escrow for testing pay_slash.
    public fun set_slash_for_testing(
        escrow: &mut RoomEscrow,
        slash_amount: u64,
        relay_miner_id: ID,
        quality: u64,
        other_relays: vector<ID>,
    ) {
        escrow.slash_amount = slash_amount;
        escrow.slash_relay_miner_id = relay_miner_id;
        escrow.slash_quality = quality;
        escrow.slash_other_relays = other_relays;
    }
```

- [ ] **Step 3: Write tests for pay_slash**

Add to `tests/registry/economic_layer_tests.move`. Define a second relay address and ID at the top of the test module:

```move
    const RELAY_OP_2: address = @0xB2;  // second relay operator
    fun relay_id_2(): ID { object::id_from_address(@0x2002) }
```

Then add the test helper to register a second relay and create a StakePosition:

```move
    /// Register two relays for multi-relay slash tests.
    fun setup_two_relays(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(scenario),
            );
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(scenario),
            );
            ts::return_shared(relay_reg);
        };
    }
```

**Test: pay_slash quality=0 single relay room (100% to creator)**

```move
    #[test]
    fun test_pay_slash_quality_zero_single_relay() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Create escrow with slash recorded (quality=0, no other relays)
        let slash_amount = 25_000_000u64; // 10% of 0.25 SUI
        h::mint_to(&mut scenario, 1_000_000, CREATOR); // escrow funds (irrelevant for this test)

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::set_slash_for_testing(
                &mut escrow, slash_amount, relay_id(), 0, vector::empty(),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create relay StakePosition for slash
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let stake = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(stake);
        };

        // Relay operator calls pay_slash
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            // Slash amount cleared
            assert!(economic_layer::escrow_slash_amount(&escrow) == 0);
            // Stake reduced by slash_amount
            assert!(staking::amount(&stake) == 250_000_000 - slash_amount);

            ts::return_shared(escrow);
            ts::return_shared(stake);
            ts::return_shared(relay_reg);
        };

        // Creator received the slashed coin (quality=0, no other relays → 100% to creator)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == slash_amount);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }
```

**Test: pay_slash quality=5000 multi relay room (50/50 split)**

```move
    #[test]
    fun test_pay_slash_quality_5000_multi_relay() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_two_relays(&mut scenario);
        // Register validators too
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_1(), VAL_OP_1, h::validator_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(val_reg);
        };

        let slash_amount = 25_000_000u64;

        h::mint_to(&mut scenario, 1_000_000, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            // quality=5000, one other relay (relay_id_2)
            economic_layer::set_slash_for_testing(
                &mut escrow, slash_amount, relay_id(), 5000, vector[relay_id_2()],
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create relay StakePosition
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let stake = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(stake);
        };

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            assert!(economic_layer::escrow_slash_amount(&escrow) == 0);

            ts::return_shared(escrow);
            ts::return_shared(stake);
            ts::return_shared(relay_reg);
        };

        // Relay 2 (RELAY_OP_2) gets 50% = 12_500_000
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 12_500_000);
            ts::return_to_sender(&scenario, coin);
        };

        // Creator gets remainder (50% = 12_500_000)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 12_500_000);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }
```

**Test: pay_slash wrong stake aborts**

```move
    #[test]
    #[expected_failure(abort_code = 664)]
    fun test_pay_slash_wrong_stake_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        h::mint_to(&mut scenario, 1_000_000, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            // Slash targets relay_id()
            economic_layer::set_slash_for_testing(
                &mut escrow, 25_000_000, relay_id(), 0, vector::empty(),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create stake for a DIFFERENT relay (relay_id_2)
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP_2);
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let stake = staking::create_for_testing(
                RELAY_OP_2, relay_id_2(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(stake);
        };

        // Try pay_slash with wrong stake → abort 664
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            ts::return_shared(escrow);
            ts::return_shared(stake);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }
```

**Test: pay_slash no pending aborts**

```move
    #[test]
    #[expected_failure(abort_code = 663)]
    fun test_pay_slash_no_pending_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        h::mint_to(&mut scenario, 1_000_000, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            // No slash set (slash_amount = 0)
            economic_layer::share_escrow_for_testing(escrow);
        };

        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let stake = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(stake);
        };

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            ts::return_shared(escrow);
            ts::return_shared(stake);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `sui move test --filter test_pay_slash`

Expected: FAIL — `pay_slash` function doesn't exist yet.

- [ ] **Step 5: Implement pay_slash**

In `sources/registry/economic_layer.move`, add after `distribute_rewards` (before the PACKAGE FUNCTIONS section):

```move
    /// Pay a recorded slash obligation. Called by the relay operator.
    ///
    /// Deducts slash_amount from the relay's StakePosition and distributes
    /// the slashed Coin proportionally based on quality at distribution time:
    ///   - creator_share = slash × (10000 - quality) / 10000
    ///   - relay_share   = slash × quality / 10000  (split equally among other relays)
    ///
    /// If no other relays exist in the room, 100% goes to the creator.
    /// Restores relay reputation to base (10000) after payment.
    public fun pay_slash(
        escrow:      &mut RoomEscrow,
        relay_stake: &mut staking::StakePosition,
        relay_reg:   &mut RelayRegistry,
        ctx:         &mut TxContext,
    ) {
        assert!(escrow.slash_amount > 0, E_NO_SLASH_PENDING);
        assert!(
            staking::miner_id(relay_stake) == escrow.slash_relay_miner_id,
            E_WRONG_STAKE,
        );

        let mut coin = staking::slash(relay_stake, escrow.slash_amount, ctx);
        let total = coin::value(&coin);
        let bp = constants::basis_points();
        let quality = escrow.slash_quality;

        // Proportional split: higher quality → more to other relays
        let relay_total = total * quality / bp;
        let num_others = vector::length(&escrow.slash_other_relays);

        // Distribute relay share equally among other assigned relays
        if (relay_total > 0 && num_others > 0) {
            let per_relay = relay_total / num_others;
            let mut i = 0;
            while (i < num_others) {
                let other_id = *vector::borrow(&escrow.slash_other_relays, i);
                let info = relay_registry::borrow_info(relay_reg, other_id);
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
        relay_registry::set_reputation(
            relay_reg, escrow.slash_relay_miner_id, bp,
        );

        escrow.slash_amount = 0;
    }
```

Also add the `use dvconf::staking` import if not already present at the top of the module.

- [ ] **Step 6: Add share_for_testing to staking module**

In `sources/miner/staking.move`, in the test_only section (after `create_for_testing`):

```move
    #[test_only]
    /// Share a StakePosition for testing (makes it a shared object for pay_slash tests).
    public fun share_for_testing(position: StakePosition) {
        transfer::share_object(position);
    }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `sui move test --filter test_pay_slash`

Expected: All 4 pay_slash tests PASS.

- [ ] **Step 8: Run all tests**

Run: `sui move test --silence-warnings`

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add sources/registry/economic_layer.move sources/registry/room_manager.move sources/miner/staking.move tests/registry/economic_layer_tests.move
git commit -m "feat(economic_layer): implement pay_slash with proportional distribution

Two-step relay slashing: distribute_rewards records slash obligation,
relay operator calls pay_slash to deduct from stake. Slashed coin
split proportionally by quality: high quality → other relays get more
(they absorbed the work), low quality → creator compensated more.
Reputation restored after payment."
```

---

### Task 4: Enforce validator assignment in submit_session_proof

**Files:**
- Modify: `sources/registry/economic_layer.move:159-164` (submit_session_proof signature)
- Modify: `sources/registry/economic_layer.move:~193` (add assignment check)
- Modify: `tests/registry/economic_layer_tests.move` (new test)

- [ ] **Step 1: Write the failing test**

In `tests/registry/economic_layer_tests.move`:

```move
    #[test]
    #[expected_failure(abort_code = 662)]
    fun test_submit_proof_unassigned_validator_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Set assigned validators to ONLY val_id_1 (val_id_2 is NOT assigned)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_validators_for_testing(
                &mut manager, room_id(), vector[val_id_1()],
            );
            ts::return_shared(manager);
        };

        // Create escrow
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // val_id_2 tries to submit proof but is NOT assigned → should abort 662
        // Using add_proof_for_testing won't trigger the check since it bypasses.
        // We need to test via the actual submit path, but that requires ed25519 setup.
        // For this test, we add a package-visible check function and test it directly.
        // Alternative: add a test_only wrapper that checks assignment without signatures.
        ts::next_tx(&mut scenario, VAL_OP_2);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);

            // Use test helper that checks assignment without signature verification
            economic_layer::check_validator_assigned_for_testing(
                &escrow, &room_mgr, val_id_2(),
            );

            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
        };

        ts::end(scenario);
    }
```

- [ ] **Step 2: Add test helper for assignment check**

In `sources/registry/economic_layer.move`, test_only section:

```move
    #[test_only]
    /// Check if validator is assigned to the escrow's room (for testing).
    /// Aborts with E_VALIDATOR_NOT_ASSIGNED if not.
    public fun check_validator_assigned_for_testing(
        escrow: &RoomEscrow,
        room_mgr: &RoomManager,
        validator_miner_id: ID,
    ) {
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
    }
```

- [ ] **Step 3: Run test to verify it fails**

Run: `sui move test --filter test_submit_proof_unassigned`

Expected: FAIL — function doesn't exist.

- [ ] **Step 4: Add assignment check to submit_session_proof**

In `sources/registry/economic_layer.move`, update `submit_session_proof` signature to add `room_mgr`:

```move
    public fun submit_session_proof(
        net_reg:           &NetworkRegistry,
        escrow:            &mut RoomEscrow,
        room_mgr:          &RoomManager,         // NEW
        validator_reg:     &mut ValidatorRegistry,
        relay_reg:         &mut RelayRegistry,
        room_id:           ID,
        ...
```

After the `lookup_session_wallet` call (~line 193), before the duplicate check, add:

```move
        // Verify validator is assigned to this room (Phase 18)
        let room_info = room_manager::borrow_room(room_mgr, escrow.room_id);
        let assigned = room_manager::room_assigned_validators(room_info);
        let mut found = false;
        let mut vi = 0;
        while (vi < vector::length(&assigned)) {
            if (*vector::borrow(&assigned, vi) == validator_miner_id) {
                found = true;
                break
            };
            vi = vi + 1;
        };
        assert!(found, E_VALIDATOR_NOT_ASSIGNED);
```

- [ ] **Step 5: Run test to verify it passes**

Run: `sui move test --filter test_submit_proof_unassigned`

Expected: PASS

- [ ] **Step 6: Run all tests**

Run: `sui move test --silence-warnings`

Expected: All tests pass. Note: existing tests that call `submit_session_proof` use `add_proof_for_testing` which bypasses the check, so they are unaffected.

- [ ] **Step 7: Commit**

```bash
git add sources/registry/economic_layer.move sources/registry/room_manager.move tests/registry/economic_layer_tests.move
git commit -m "feat(economic_layer): enforce validator assignment in submit_session_proof

submit_session_proof now takes &RoomManager and asserts the submitting
validator is in the room's assigned_validators list. Rejects unassigned
validators with E_VALIDATOR_NOT_ASSIGNED (662). Prevents proof spam
from validators not assigned to the room."
```

---

### Task 5: Add validator_ids to RoomAssigned event

**Files:**
- Modify: `sources/registry/room_manager.move:103-111` (RoomAssigned struct)
- Modify: `sources/registry/room_manager.move:398-405` (consensus emit)
- Modify: `sources/registry/room_manager.move:536-544` (finalize_room emit)
- Modify: `sources/registry/room_manager.move:572-580` (admin fallback emit)

- [ ] **Step 1: Add field to RoomAssigned event struct**

```move
    public struct RoomAssigned has copy, drop {
        room_id:           ID,
        relay_ids:         vector<ID>,
        signaling_id:      ID,
        relay_mode:        u8,
        verified_score:    u64,
        consensus_reached: bool,
        winning_cp:        ID,
        validator_ids:     vector<ID>,  // NEW: assigned validators
    }
```

- [ ] **Step 2: Update emit site 1 — consensus finalize (~line 398)**

Add `validator_ids: winner.validator_ids,` to the event emit.

- [ ] **Step 3: Update emit site 2 — finalize_room fallback (~line 536)**

Add `validator_ids: winner.validator_ids,` to the event emit.

- [ ] **Step 4: Update emit site 3 — admin assign_relay_and_signaling (~line 572)**

Add `validator_ids: vector::empty(),` to the event emit (no validators in admin path).

- [ ] **Step 5: Run all tests**

Run: `sui move test --silence-warnings`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add sources/registry/room_manager.move
git commit -m "feat(room_manager): add validator_ids to RoomAssigned event

Validators can now detect their room assignment from on-chain events
by checking if their miner ID is in the validator_ids field."
```

---

### Task 6: Sync RoomAssigned TypeScript type

**Files:**
- Modify: `C:\Thesis\dvconf\dvconf-daemons\packages\shared\src\types\events.ts:118-122`

- [ ] **Step 1: Update RoomAssigned interface**

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

- [ ] **Step 2: Run daemon tests**

Run from `C:\Thesis\dvconf\dvconf-daemons`: `pnpm test`

Expected: All existing tests pass (the type is only used in event parsing, not in test assertions).

- [ ] **Step 3: Commit**

```bash
cd C:/Thesis/dvconf/dvconf-daemons
git add packages/shared/src/types/events.ts
git commit -m "fix(shared): sync RoomAssigned type with on-chain struct

Add missing fields: relay_mode, verified_score, consensus_reached,
winning_cp, validator_ids."
```

---

### Task 7: Validator daemon assignment filtering

**Files:**
- Modify: `C:\Thesis\dvconf\dvconf-daemons\apps\validator-daemon\src\index.ts:247-292`

- [ ] **Step 1: Write failing test — RoomAssigned filters by own validator ID**

In `apps/validator-daemon/src/__tests__/index.test.ts`, add:

```typescript
  it('RoomAssigned: adds room only when own validator ID is in validator_ids', async () => {
    state = await startDaemon({
      client: mockClient as any,
      mainKeypair,
      config: mockConfig,
    });

    const ownValidatorId = state.validatorMinerId;

    // Simulate RoomAssigned event WITH our validator ID
    const assignedEvent = {
      type: '0xpkg::room_manager::RoomAssigned',
      parsedJson: {
        room_id: 'room-assigned-to-us',
        relay_ids: ['0xrelay1'],
        signaling_id: '0xsig1',
        relay_mode: 0,
        verified_score: '1000',
        consensus_reached: true,
        winning_cp: '0xcp1',
        validator_ids: [ownValidatorId, '0xother-validator'],
      },
    };

    // Trigger the event callback
    const roomCallback = mockEventPollerStart.mock.calls
      .find((c: any) => c[0])?.[0];
    if (roomCallback) await roomCallback(assignedEvent);

    expect(state.activeRooms.has('room-assigned-to-us')).toBe(true);
    expect(state.activeRooms.get('room-assigned-to-us')?.relayMinerId).toBe('0xrelay1');
  });

  it('RoomAssigned: ignores room when own validator ID is NOT in validator_ids', async () => {
    state = await startDaemon({
      client: mockClient as any,
      mainKeypair,
      config: mockConfig,
    });

    const assignedEvent = {
      type: '0xpkg::room_manager::RoomAssigned',
      parsedJson: {
        room_id: 'room-not-for-us',
        relay_ids: ['0xrelay1'],
        signaling_id: '0xsig1',
        relay_mode: 0,
        verified_score: '1000',
        consensus_reached: true,
        winning_cp: '0xcp1',
        validator_ids: ['0xother-validator-1', '0xother-validator-2'],
      },
    };

    const roomCallback = mockEventPollerStart.mock.calls
      .find((c: any) => c[0])?.[0];
    if (roomCallback) await roomCallback(assignedEvent);

    expect(state.activeRooms.has('room-not-for-us')).toBe(false);
  });

  it('RoomCreated: does NOT auto-add room to activeRooms', async () => {
    state = await startDaemon({
      client: mockClient as any,
      mainKeypair,
      config: mockConfig,
    });

    const createdEvent = {
      type: '0xpkg::room_manager::RoomCreated',
      parsedJson: {
        room_id: 'new-room',
        creator: '0xcreator',
        relay_mode: 0,
      },
    };

    const roomCallback = mockEventPollerStart.mock.calls
      .find((c: any) => c[0])?.[0];
    if (roomCallback) await roomCallback(createdEvent);

    // Room should NOT be in activeRooms until RoomAssigned with our ID
    expect(state.activeRooms.has('new-room')).toBe(false);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `C:\Thesis\dvconf\dvconf-daemons`: `pnpm --filter validator-daemon test`

Expected: FAIL — current code adds all rooms.

- [ ] **Step 3: Update RoomCreated handler — stop auto-adding**

In `apps/validator-daemon/src/index.ts`, change the `RoomCreated` handler (~line 248-260):

```typescript
    if (event.type.endsWith('::RoomCreated')) {
      const parsed = event.parsedJson as unknown as RoomCreated;
      if (parsed.room_id) {
        // Phase 18: Don't auto-add. Wait for RoomAssigned with our validator ID.
        log.info(
          { roomId: parsed.room_id, creator: parsed.creator },
          `RoomCreated -- room=${parsed.room_id} (waiting for assignment)`,
        );
      }
    }
```

- [ ] **Step 4: Update RoomAssigned handler — filter by own validator ID**

Replace the `RoomAssigned` handler (~line 276-292):

```typescript
    if (event.type.endsWith('::RoomAssigned')) {
      const parsed = event.parsedJson as unknown as RoomAssigned;
      const relayId = parsed.relay_ids?.[0];
      const validatorIds: string[] = (parsed as any).validator_ids ?? [];

      // Phase 18: Only track rooms where we are an assigned validator
      if (parsed.room_id && relayId && validatorIds.includes(validatorMinerId)) {
        const room = activeRooms.get(parsed.room_id) ?? {};
        room.relayMinerId = relayId;

        if (!activeRooms.has(parsed.room_id)) {
          activeRooms.set(parsed.room_id, room);
        }

        log.info(
          { roomId: parsed.room_id, relayId },
          `RoomAssigned -- assigned to room=${parsed.room_id}, relay=${relayId}`,
        );
      } else if (parsed.room_id) {
        log.debug(
          { roomId: parsed.room_id, validatorIds, ownId: validatorMinerId },
          `RoomAssigned -- not assigned to room=${parsed.room_id}, ignoring`,
        );
      }
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pnpm --filter validator-daemon test`

Expected: All tests pass (new + existing).

- [ ] **Step 6: Commit**

```bash
cd C:/Thesis/dvconf/dvconf-daemons
git add apps/validator-daemon/src/index.ts apps/validator-daemon/src/__tests__/index.test.ts
git commit -m "feat(validator-daemon): filter rooms by assignment in RoomAssigned

Validator daemon now only tracks rooms where its miner ID appears in
the RoomAssigned event's validator_ids field. RoomCreated no longer
auto-adds rooms to the active measurement set."
```

---

### Task 8: Final verification + update spec coverage

**Files:**
- No new code — verification only

- [ ] **Step 1: Run all Move tests**

Run from `C:\Thesis\dvconf\dvconf-contracts`: `sui move test --silence-warnings`

Expected: All tests pass (200 existing + ~12 new).

- [ ] **Step 2: Run all daemon tests**

Run from `C:\Thesis\dvconf\dvconf-daemons`: `pnpm test`

Expected: All tests pass (49 existing + 3 new).

- [ ] **Step 3: Run client tests**

Run from `C:\Thesis\dvconf\dvconf-client`: `pnpm test`

Expected: All 14 tests pass (no changes to client).

- [ ] **Step 4: Update SPEC-VS-IMPL.md**

Update `plans/cp-voting-consensus/milestone-2/SPEC-VS-IMPL.md`:
- Gap #2 status: "CLOSED — two-step slash with proportional distribution implemented"
- Coverage: 95% → 97% (slashing gap closed)

- [ ] **Step 5: Commit**

```bash
cd C:/Thesis/dvconf/dvconf-contracts
git add plans/cp-voting-consensus/milestone-2/SPEC-VS-IMPL.md
git commit -m "docs: update spec coverage — slashing gap closed (97%)"
```
