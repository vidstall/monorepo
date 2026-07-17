/// Scarcity reward ratio tests — verifies compute_scarcity_ratios() and
/// distribute_rewards with dynamic splits.
///
/// Coverage:
///   SCAR-02: Uneven counts produce correct inverse-ratio splits
///   SCAR-03: Floor (500bp) and ceiling (8000bp) clamping
///   SCAR-04: Count-based, not stake-weighted (verified by test structure)
#[test_only]
module dvconf::scarcity_tests {
    use sui::test_scenario::{Self as ts};
    use sui::coin::{Self};
    use sui::sui::SUI;
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::economic_layer;
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::signaling_registry::{Self, SignalingRegistry};

    // ── Test IDs ──
    fun room_id(): ID   { object::id_from_address(@0x1001) }
    fun relay_id(): ID  { object::id_from_address(@0x2001) }
    fun val_id_1(): ID  { object::id_from_address(@0x3001) }
    fun val_id_2(): ID  { object::id_from_address(@0x3002) }

    const CREATOR: address = @0xE1;
    const RELAY_OP: address = @0xB1;
    const VAL_OP_1: address = @0xD1;
    const VAL_OP_2: address = @0xD2;
    const ESCROW_AMOUNT: u64 = 50_000_000;

    // ══════════════════════════════════════════════════════════
    // SCAR-02: compute_scarcity_ratios — equal counts
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_equal_counts() {
        // 5 of each type: all ratios should be ~2500bp (equal)
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(5, 5, 5, 5);
        assert!(r == 2500, 0);
        assert!(v == 2500, 1);
        assert!(c == 2500, 2);
        assert!(s == 2500, 3);
        assert!(r + v + c + s == 10_000, 4);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-02: compute_scarcity_ratios — zero total
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_zero_total() {
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(0, 0, 0, 0);
        assert!(r == 2500, 0);
        assert!(v == 2500, 1);
        assert!(c == 2500, 2);
        assert!(s == 2500, 3);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-02: Uneven counts — scarce type gets more
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_uneven_counts() {
        // 4 relays, 1 validator, 2 CPs, 1 signaling = 8 total
        // raw weights: relay=8/4=2, val=8/1=8, cp=8/2=4, sig=8/1=8
        // raw_total = 22
        // normalized: relay=2*10000/22=909, val=8*10000/22=3636, cp=4*10000/22=1818, sig=8*10000/22=3636
        // All within [500, 8000] so no clamping
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(4, 1, 2, 1);
        // Scarce types (validator, signaling with count=1) should have higher ratios
        assert!(v > r, 0);  // validator scarcer than relay
        assert!(s > r, 1);  // signaling scarcer than relay
        assert!(v > c, 2);  // validator scarcer than cp
        // Sum must equal 10,000
        assert!(r + v + c + s == 10_000, 3);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-03: Ceiling clamp — one type dominates
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_ceiling_clamp() {
        // 10 relays, 1 validator, 1 cp, 1 signaling = 13 total
        // raw: relay=13/10=1, val=13, cp=13, sig=13
        // raw_total = 40
        // normalized: relay=250, val=3250, cp=3250, sig=3250
        // relay below floor(500) → clamped to 500
        // After clamping + renorm, sum = 10000
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(10, 1, 1, 1);
        // Relay (abundant) should be at or near floor
        assert!(r >= 500, 0);
        // Scarce types should be higher
        assert!(v > r, 1);
        assert!(c > r, 2);
        assert!(s > r, 3);
        assert!(r + v + c + s == 10_000, 4);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-03: Floor clamp — type at zero count
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_floor_with_zero_count() {
        // 5 relays, 0 validators, 5 CPs, 5 signaling = 15 total
        // raw: relay=15/5=3, val=15/1=15 (max because 0→1), cp=3, sig=3
        // raw_total = 24
        // normalized: relay=1250, val=6250, cp=1250, sig=1250
        // All within [500, 8000]
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(5, 0, 5, 5);
        // Validator (0 count) should get the highest share
        assert!(v > r, 0);
        assert!(v > c, 1);
        assert!(v > s, 2);
        assert!(r + v + c + s == 10_000, 3);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-03: Extreme case — only 1 type has nodes
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_only_one_type() {
        // 10 relays, 0 others
        // raw: relay=10/10=1, val=10/1=10, cp=10/1=10, sig=10/1=10
        // raw_total = 31
        // normalized: relay=322, val=3225, cp=3225, sig=3225
        // relay below floor(500) → clamped to 500
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(10, 0, 0, 0);
        assert!(r >= 500, 0);  // floor
        assert!(v <= 8000, 1); // ceiling
        assert!(r + v + c + s == 10_000, 2);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-02: 1 of each → equal distribution
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_scarcity_one_each() {
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(1, 1, 1, 1);
        assert!(r == 2500, 0);
        assert!(v == 2500, 1);
        assert!(c == 2500, 2);
        assert!(s == 2500, 3);
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-03: Bounds invariant — every share in [floor, ceiling],
    //          shares sum to exactly 10_000 (E4-1b property tests)
    // ══════════════════════════════════════════════════════════

    /// SCAR-03 invariant: each share within [scarcity_floor_bps,
    /// scarcity_ceiling_bps] and the four shares sum to basis_points().
    fun assert_bounds_and_sum(r: u64, v: u64, c: u64, s: u64) {
        let floor = constants::scarcity_floor_bps();
        let ceiling = constants::scarcity_ceiling_bps();
        assert!(r >= floor, 100);
        assert!(r <= ceiling, 101);
        assert!(v >= floor, 102);
        assert!(v <= ceiling, 103);
        assert!(c >= floor, 104);
        assert!(c <= ceiling, 105);
        assert!(s >= floor, 106);
        assert!(s <= ceiling, 107);
        assert!(r + v + c + s == constants::basis_points(), 108);
    }

    #[test]
    fun test_scarcity_bounds_pass2_floor_breach() {
        // (2, 4, 17, 27): normalize -> (6250, 3000, 500, 250); sig clamps to
        // floor; pass-2 redistribution then recomputes cp = 2*9500/39 = 487,
        // BELOW the 500 floor unless the redistributed share is re-clamped.
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(2, 4, 17, 27);
        assert_bounds_and_sum(r, v, c, s);
    }

    #[test]
    fun test_scarcity_bounds_all_clamped_ceiling_breach() {
        // (2, 27, 27, 50): normalize -> (8688, 491, 491, 327) — all four
        // shares clamp; the exact-sum remainder (10_000 - 1_500 = 8_500) must
        // land on a share with ceiling slack, not unconditionally on relay
        // (8_500 > 8_000 ceiling).
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(2, 27, 27, 50);
        assert_bounds_and_sum(r, v, c, s);
    }

    #[test]
    fun test_scarcity_bounds_degenerate_sweep() {
        // Zero-count mixes
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(0, 3, 3, 3);
        assert_bounds_and_sum(r, v, c, s);
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(0, 0, 1, 100);
        assert_bounds_and_sum(r, v, c, s);
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(0, 30, 30, 60);
        assert_bounds_and_sum(r, v, c, s);
        // All-equal counts
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(7, 7, 7, 7);
        assert_bounds_and_sum(r, v, c, s);
        // One-dominant count, each position
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(100, 1, 1, 1);
        assert_bounds_and_sum(r, v, c, s);
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(1, 100, 1, 1);
        assert_bounds_and_sum(r, v, c, s);
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(1, 1, 100, 1);
        assert_bounds_and_sum(r, v, c, s);
        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(1, 1, 1, 100);
        assert_bounds_and_sum(r, v, c, s);
    }

    #[test]
    fun test_scarcity_bounds_grid_sweep() {
        // Reviewer follow-up (E4-1b GO, finding 3): exhaustive sweep over a
        // clamp-rich grid — every count mix from {0, 1, 30}^4 (81 combos:
        // all-zero early return, floor clamps, ceiling clamps, all-clamped
        // mixes) upholds the SCAR-03 invariant. A plain 0..=N cube both
        // exceeds the test VM's execution bound at useful N AND never clamps
        // for counts <= 3, so a skewed grid covers strictly more behavior.
        let grid = vector[0u64, 1, 30];
        let mut a = 0;
        while (a < 3) {
            let mut b = 0;
            while (b < 3) {
                let mut c2 = 0;
                while (c2 < 3) {
                    let mut d = 0;
                    while (d < 3) {
                        let (r, v, c, s) = economic_layer::compute_scarcity_ratios(
                            grid[a], grid[b], grid[c2], grid[d],
                        );
                        assert_bounds_and_sum(r, v, c, s);
                        d = d + 1;
                    };
                    c2 = c2 + 1;
                };
                b = b + 1;
            };
            a = a + 1;
        };
    }

    // ══════════════════════════════════════════════════════════
    // SCAR-02: distribute_rewards uses scarcity ratios
    //          (integration with economic_layer)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_distribute_rewards_uses_scarcity_ratios() {
        let mut scenario = h::setup_phase3();

        // Setup CLOSED room
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), CREATOR,
                constants::room_status_closed(),
                constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

        // Setup relay and validators
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        // RO-023b: per-relay loop iterates room_assigned_relays — assign the relay.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id()],
            );
            ts::return_shared(manager);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_1(), VAL_OP_1, h::validator_stake(), ts::ctx(&mut scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_2(), VAL_OP_2, h::validator_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(val_reg);
        };

        // Create escrow with proofs (excellent quality)
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Distribute rewards — should use scarcity ratios
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

            assert!(economic_layer::escrow_is_distributed(&escrow));
            // Escrow balance should be 0 (all distributed)
            assert!(economic_layer::escrow_balance(&escrow) == 0);

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

    // ══════════════════════════════════════════════════════════
    // CP pool routed to assigned CP operator
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_cp_pool_routes_to_assigned_cp() {
        let mut scenario = h::setup_phase3();

        let cp_id = object::id_from_address(@0xC001);

        // Setup CLOSED room with assigned_cp
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), CREATOR,
                constants::room_status_closed(),
                constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            // Set assigned_cp
            room_manager::set_assigned_cp_for_testing(&mut manager, room_id(), cp_id);
            ts::return_shared(manager);
        };

        // Register the CP in ControlPlaneRegistry so borrow_info works
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            control_plane_registry::add_cp_for_testing(
                &mut cp_reg, cp_id, h::cp_1(), h::cp_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(cp_reg);
        };

        // Setup relay and validators
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        // RO-023b: the per-relay distribution loop iterates room_assigned_relays
        // (the canonical "who was supposed to serve" set), so the room must have
        // the relay assigned for it to be paid. Production always assigns relays
        // via pairing before close; this mirrors that.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id()],
            );
            ts::return_shared(manager);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_1(), VAL_OP_1, h::validator_stake(), ts::ctx(&mut scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_2(), VAL_OP_2, h::validator_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(val_reg);
        };

        // Create escrow with proofs
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Distribute — CP pool should go to h::cp_1() (the CP operator)
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

            assert!(economic_layer::escrow_is_distributed(&escrow));

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        // Verify CP operator received funds
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let cp_coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&cp_coin) > 0, 0);
            ts::return_to_sender(&scenario, cp_coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // Signaling pool routed to assigned signaling operator
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_signaling_pool_routes_to_assigned_signaling() {
        let mut scenario = h::setup_phase3();

        let sig_id = object::id_from_address(@0xF001);

        // Setup CLOSED room with assigned_signaling
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), CREATOR,
                constants::room_status_closed(),
                constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            // Set assigned signaling
            room_manager::set_assigned_signaling_for_testing(&mut manager, room_id(), sig_id);
            ts::return_shared(manager);
        };

        // Register signaling in SignalingRegistry
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut sig_reg = ts::take_shared<SignalingRegistry>(&scenario);
            signaling_registry::add_signaling_for_testing(
                &mut sig_reg, sig_id, h::sig_1(), ts::ctx(&mut scenario),
            );
            ts::return_shared(sig_reg);
        };

        // Setup relay and validators
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        // RO-023b: per-relay loop iterates room_assigned_relays — assign the relay.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id()],
            );
            ts::return_shared(manager);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_1(), VAL_OP_1, h::validator_stake(), ts::ctx(&mut scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_2(), VAL_OP_2, h::validator_stake(), ts::ctx(&mut scenario),
            );
            ts::return_shared(val_reg);
        };

        // Create escrow with proofs
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Distribute
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

            assert!(economic_layer::escrow_is_distributed(&escrow));

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        // Verify signaling operator received funds
        ts::next_tx(&mut scenario, h::sig_1());
        {
            let sig_coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&sig_coin) > 0, 0);
            ts::return_to_sender(&scenario, sig_coin);
        };

        ts::end(scenario);
    }
}
