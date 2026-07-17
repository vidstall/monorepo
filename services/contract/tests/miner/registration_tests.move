/// UC1–UC4 — Miner registration lifecycle tests
#[test_only]
module dvconf::registration_tests {
    use sui::test_scenario as ts;
    use sui::coin;
    use sui::transfer;
    use sui::sui::SUI;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::caps::{Self, MinerCap, ControlPlaneCap};
    use dvconf::registration;
    use dvconf::test_helpers;
    use dvconf::signaling_registry::SignalingRegistry;
    use dvconf::relay_registry::RelayRegistry;
    use dvconf::validator_registry::ValidatorRegistry;
    use dvconf::control_plane_registry::ControlPlaneRegistry;

    // ── UC1: REGISTER ────────────────────────────────────────────────────

    #[test]
    fun test_register_as_relay() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // StakePosition in wallet with correct amount and role
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            assert!(staking::amount(&pos) == test_helpers::relay_stake());
            assert!(staking::role(&pos)   == miner_store::role_relay());
            assert!(staking::owner(&pos)  == test_helpers::relay_1());
            ts::return_to_sender(&scenario, pos);
        };

        // MinerCap (not ControlPlaneCap) in wallet
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            assert!(caps::miner_cap_role(&cap) == miner_store::role_relay());
            ts::return_to_sender(&scenario, cap);
        };

        // MinerStore counts updated
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let store = ts::take_shared<MinerStore>(&scenario);
            assert!(miner_store::total_registered(&store) == 1);
            assert!(miner_store::relay_count(&store)      == 1);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_register_as_cp() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(), test_helpers::cp_stake());

        // ControlPlaneCap in wallet
        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            ts::return_to_sender(&scenario, cap);
        };

        // Role = CP
        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            assert!(staking::role(&pos) == miner_store::role_cp());
            ts::return_to_sender(&scenario, pos);
        };

        // Store counts
        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let store = ts::take_shared<MinerStore>(&scenario);
            assert!(miner_store::cp_count(&store)    == 1);
            assert!(miner_store::relay_count(&store) == 0);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_register_as_validator() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::val_1(), test_helpers::validator_stake());

        ts::next_tx(&mut scenario, test_helpers::val_1());
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            assert!(staking::role(&pos) == miner_store::role_validator());
            ts::return_to_sender(&scenario, pos);
        };

        ts::next_tx(&mut scenario, test_helpers::val_1());
        {
            let store = ts::take_shared<MinerStore>(&scenario);
            assert!(miner_store::validator_count(&store) == 1);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_register_as_user() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::user_1(), test_helpers::user_stake());

        ts::next_tx(&mut scenario, test_helpers::user_1());
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            assert!(staking::role(&pos) == miner_store::role_user());
            ts::return_to_sender(&scenario, pos);
        };

        ts::next_tx(&mut scenario, test_helpers::user_1());
        {
            let store = ts::take_shared<MinerStore>(&scenario);
            assert!(miner_store::user_count(&store) == 1);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 403)] // E_PROTOCOL_PAUSED
    fun test_register_fails_when_paused() {
        let mut scenario = test_helpers::setup();

        // Admin pauses protocol
        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut registry, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        test_helpers::mint_to(&mut scenario, test_helpers::relay_stake(), test_helpers::relay_1());

        // Try to register — must abort
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            registration::register(
                &registry, &mut store, coin,
                b"1.2.3.4", 8080, b"", b"",
                b"us-east1", 500, 50, 4, b"",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 403)] // E_PROTOCOL_PAUSED
    fun test_top_up_fails_when_paused() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Admin pauses
        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut registry, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        test_helpers::mint_to(&mut scenario, test_helpers::relay_stake(), test_helpers::relay_1());

        // Try to top-up — must abort
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut pos = ts::take_from_sender<StakePosition>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            registration::top_up_stake(
                &registry, &mut store, &mut pos, coin,
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── UC2: TOP UP STAKE ────────────────────────────────────────────────

    #[test]
    fun test_top_up_upgrades_role() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // +0.25 SUI → total = 0.5 SUI = CP threshold
        test_helpers::mint_to(&mut scenario, test_helpers::relay_stake(), test_helpers::relay_1());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut pos = ts::take_from_sender<StakePosition>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            registration::top_up_stake(
                &registry, &mut store, &mut pos, coin,
                ts::ctx(&mut scenario),
            );

            assert!(staking::role(&pos)   == miner_store::role_cp());
            assert!(staking::amount(&pos) == test_helpers::cp_stake());

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let store = ts::take_shared<MinerStore>(&scenario);
            assert!(miner_store::cp_count(&store)    == 1);
            assert!(miner_store::relay_count(&store) == 0);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_top_up_no_role_change() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // +0.01 SUI → still relay (below CP threshold)
        test_helpers::mint_to(&mut scenario, 10_000_000, test_helpers::relay_1());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut pos = ts::take_from_sender<StakePosition>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            registration::top_up_stake(
                &registry, &mut store, &mut pos, coin,
                ts::ctx(&mut scenario),
            );

            assert!(staking::role(&pos)   == miner_store::role_relay());
            assert!(staking::amount(&pos) == test_helpers::relay_stake() + 10_000_000);

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── UC3: UNREGISTER ──────────────────────────────────────────────────

    #[test]
    fun test_unregister_returns_tokens() {
        let mut scenario = test_helpers::setup_phase2();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut signaling_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            let miner_id = staking::miner_id(&pos);

            registration::unregister(
                &mut store, &mut signaling_reg,
                &mut relay_reg, &mut val_reg, &mut cp_reg,
                pos, ts::ctx(&mut scenario),
            );

            assert!(!miner_store::has_profile(&store, miner_id));
            assert!(miner_store::total_registered(&store) == 0);
            assert!(miner_store::relay_count(&store)      == 0);

            ts::return_shared(store);
            ts::return_shared(signaling_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
        };

        // Tokens returned to wallet
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == test_helpers::relay_stake());
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 401)] // E_STAKE_LOCKED
    fun test_unregister_fails_when_locked() {
        let mut scenario = test_helpers::setup_phase2();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Lock the stake (simulates active session)
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let mut pos = ts::take_from_sender<StakePosition>(&scenario);
            staking::lock(&mut pos);
            assert!(staking::is_locked(&pos));
            ts::return_to_sender(&scenario, pos);
        };

        // Try to unregister — must abort
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut signaling_reg = ts::take_shared<SignalingRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::unregister(
                &mut store, &mut signaling_reg,
                &mut relay_reg, &mut val_reg, &mut cp_reg,
                pos, ts::ctx(&mut scenario),
            );

            ts::return_shared(store);
            ts::return_shared(signaling_reg);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
        };

        ts::end(scenario);
    }

    // ── UC4: UPDATE MINER INFO ───────────────────────────────────────────

    #[test]
    fun test_update_endpoint() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::update_endpoint(
                &registry, &mut store, &pos,
                b"10.0.0.1", 9090, b"stun://new", b"turn://new", b"new-cred",
                ts::ctx(&mut scenario),
            );

            let profile = miner_store::borrow_profile(&store, staking::miner_id(&pos));
            let ep = miner_store::profile_endpoint(profile);
            assert!(miner_store::endpoint_ip(&ep)                   == b"10.0.0.1");
            assert!(miner_store::endpoint_port(&ep)                 == 9090);
            assert!(miner_store::endpoint_turn_credential_hash(&ep) == b"new-cred");

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_update_strength() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Set a non-zero load first so we can verify it is preserved after update_strength
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            registration::update_load(&registry, &mut store, &pos, 7, ts::ctx(&mut scenario));
            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::update_strength(
                &registry, &mut store, &pos,
                b"eu-west1", 5000, 200, 16,
                ts::ctx(&mut scenario),
            );

            let profile = miner_store::borrow_profile(&store, staking::miner_id(&pos));
            let s = miner_store::profile_strength(profile);
            assert!(miner_store::strength_bandwidth(&s)  == 5000);
            assert!(miner_store::strength_max(&s)        == 200);
            assert!(miner_store::strength_load(&s)       == 7);    // load preserved

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_update_load() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::update_load(&registry, &mut store, &pos, 42, ts::ctx(&mut scenario));

            let profile = miner_store::borrow_profile(&store, staking::miner_id(&pos));
            let s = miner_store::profile_strength(profile);
            assert!(miner_store::strength_load(&s) == 42);

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_set_active_false() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::set_active(&mut store, &pos, false, ts::ctx(&mut scenario));

            let profile = miner_store::borrow_profile(&store, staking::miner_id(&pos));
            assert!(!miner_store::profile_active(profile));

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── UC1 extra: DOUBLE REGISTER ───────────────────────────────────────────

    #[test]
    #[expected_failure(abort_code = 404)] // E_ALREADY_REGISTERED
    fun test_double_register_fails() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Second registration by same address → must abort
        test_helpers::mint_to(&mut scenario, test_helpers::relay_stake(), test_helpers::relay_1());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            registration::register(
                &registry, &mut store, coin,
                b"1.2.3.4", 8080, b"", b"",
                b"us-east1", 500, 50, 4, b"",
                ts::ctx(&mut scenario),
            );

            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── UC2 extra: NON-OWNER TOP UP ──────────────────────────────────────────

    #[test]
    #[expected_failure(abort_code = 402)] // E_NOT_OWNER
    fun test_top_up_non_owner_fails() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // cp_1 tries to top up relay_1's position → must abort
        test_helpers::mint_to(&mut scenario, test_helpers::relay_stake(), test_helpers::cp_1());

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let mut pos = ts::take_from_address<StakePosition>(&scenario, test_helpers::relay_1());
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            registration::top_up_stake(
                &registry, &mut store, &mut pos, coin,
                ts::ctx(&mut scenario),
            );

            ts::return_to_address(test_helpers::relay_1(), pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── UC4 extra: PAUSED PROTOCOL BLOCKS SELF-UPDATE (F55) ──────────────────

    #[test]
    #[expected_failure(abort_code = 403)] // E_PROTOCOL_PAUSED
    fun test_update_endpoint_fails_when_paused() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Admin pauses protocol
        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut registry, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        // Try to update endpoint while paused — must abort
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::update_endpoint(
                &registry, &mut store, &pos,
                b"10.0.0.1", 9090, b"stun://new", b"turn://new", b"new-cred",
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 403)] // E_PROTOCOL_PAUSED
    fun test_update_strength_fails_when_paused() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Admin pauses protocol
        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut registry, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        // Try to update strength while paused — must abort
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::update_strength(
                &registry, &mut store, &pos,
                b"eu-west1", 5000, 200, 16,
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = 403)] // E_PROTOCOL_PAUSED
    fun test_update_load_fails_when_paused() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Admin pauses protocol
        ts::next_tx(&mut scenario, test_helpers::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut registry = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut registry, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(registry);
        };

        // Try to update load while paused — must abort
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);

            registration::update_load(
                &registry, &mut store, &pos, 42,
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── UC4 extra: NON-OWNER UPDATE ──────────────────────────────────────────

    #[test]
    #[expected_failure(abort_code = 402)] // E_NOT_OWNER
    fun test_update_endpoint_non_owner_fails() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // cp_1 tries to update relay_1's endpoint → must abort
        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_address<StakePosition>(&scenario, test_helpers::relay_1());

            registration::update_endpoint(
                &registry, &mut store, &pos,
                b"evil.ip", 1337, b"", b"", b"",
                ts::ctx(&mut scenario),
            );

            ts::return_to_address(test_helpers::relay_1(), pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    // ── STAKING: SLASH OVER BALANCE ──────────────────────────────────────────

    #[test]
    #[expected_failure(abort_code = 200)] // E_INSUFFICIENT_STAKE in staking
    fun test_slash_over_balance_fails() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let mut pos = ts::take_from_sender<StakePosition>(&scenario);

            // Slash more than the staked balance → must abort with 200
            let coin = staking::slash(&mut pos, test_helpers::relay_stake() + 1, ts::ctx(&mut scenario));
            // type-checker requires consumption; this line never executes due to expected abort above
            transfer::public_transfer(coin, test_helpers::relay_1());

            ts::return_to_sender(&scenario, pos);
        };

        ts::end(scenario);
    }
}
