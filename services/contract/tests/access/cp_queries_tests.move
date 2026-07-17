/// UC5 — Control Plane query tests
#[test_only]
module dvconf::cp_queries_tests {
    use sui::test_scenario as ts;
    use sui::vec_set;
    use dvconf::constants;
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::caps::ControlPlaneCap;
    use dvconf::cp_queries;
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::registration;
    use dvconf::test_helpers;

    // ── UC5: CP QUERIES ──────────────────────────────────────────────────

    #[test]
    fun test_cp_queries_relay_set() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),    test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let relay_set = cp_queries::get_relay_set(&cp_cap, &store);
            assert!(vec_set::length(relay_set) == 1);

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_cp_queries_check_assignable() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),    test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Capture relay's miner_id
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        let relay_miner_id;
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            relay_miner_id = staking::miner_id(&pos);
            ts::return_to_sender(&scenario, pos);
        };

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let (assignable, load, max, bw) =
                cp_queries::check_assignable(&cp_cap, &store, relay_miner_id);

            assert!(assignable == true);
            assert!(load == 0);
            assert!(max  == test_helpers::default_max_concurrent());
            assert!(bw   == test_helpers::default_bandwidth_mbps());

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_cp_queries_get_profile() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),    test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        let relay_miner_id;
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            relay_miner_id = staking::miner_id(&pos);
            ts::return_to_sender(&scenario, pos);
        };

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let (owner, role, _ep, _str, reputation, active) =
                cp_queries::get_profile(&cp_cap, &store, relay_miner_id);

            assert!(owner      == test_helpers::relay_1());
            assert!(role       == miner_store::role_relay());
            assert!(reputation == constants::default_initial_reputation());
            assert!(active     == true);

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_cp_queries_check_not_assignable_when_inactive() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),    test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Relay goes offline
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            registration::set_active(&mut store, &pos, false, ts::ctx(&mut scenario));
            ts::return_to_sender(&scenario, pos);
            ts::return_shared(store);
        };

        // Capture relay miner_id
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        let relay_miner_id;
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            relay_miner_id = staking::miner_id(&pos);
            ts::return_to_sender(&scenario, pos);
        };

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let (assignable, _load, _max, _bw) =
                cp_queries::check_assignable(&cp_cap, &store, relay_miner_id);

            assert!(assignable == false); // inactive → not assignable

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_cp_queries_check_not_assignable_when_full() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),    test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());

        // Fill the relay to max_concurrent (100 from do_register defaults)
        ts::next_tx(&mut scenario, test_helpers::relay_1());
        {
            let registry = ts::take_shared<NetworkRegistry>(&scenario);
            let mut store = ts::take_shared<MinerStore>(&scenario);
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            registration::update_load(&registry, &mut store, &pos, 100, ts::ctx(&mut scenario));
            ts::return_to_sender(&scenario, pos);
            ts::return_shared(registry);
            ts::return_shared(store);
        };

        ts::next_tx(&mut scenario, test_helpers::relay_1());
        let relay_miner_id;
        {
            let pos = ts::take_from_sender<StakePosition>(&scenario);
            relay_miner_id = staking::miner_id(&pos);
            ts::return_to_sender(&scenario, pos);
        };

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let (assignable, load, max, _bw) =
                cp_queries::check_assignable(&cp_cap, &store, relay_miner_id);

            assert!(assignable == false); // load == max → not assignable
            assert!(load == max);

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_cp_queries_validator_set() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),  test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::val_1(), test_helpers::validator_stake());

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let val_set = cp_queries::get_validator_set(&cp_cap, &store);
            assert!(vec_set::length(val_set) == 1);

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }

    #[test]
    fun test_cp_queries_get_counts() {
        let mut scenario = test_helpers::setup();
        test_helpers::do_register(&mut scenario, test_helpers::cp_1(),    test_helpers::cp_stake());
        test_helpers::do_register(&mut scenario, test_helpers::relay_1(), test_helpers::relay_stake());
        test_helpers::do_register(&mut scenario, test_helpers::val_1(),   test_helpers::validator_stake());
        test_helpers::do_register(&mut scenario, test_helpers::user_1(),  test_helpers::user_stake());

        ts::next_tx(&mut scenario, test_helpers::cp_1());
        {
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            let store  = ts::take_shared<MinerStore>(&scenario);

            let (cps, relays, validators, users) =
                cp_queries::get_counts(&cp_cap, &store);

            assert!(cps        == 1);
            assert!(relays     == 1);
            assert!(validators == 1);
            assert!(users      == 1);

            ts::return_to_sender(&scenario, cp_cap);
            ts::return_shared(store);
        };

        ts::end(scenario);
    }
}
