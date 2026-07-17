#[test_only]
module dvconf::user_registry_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::user_registry::{Self, UserRegistry};

    // ── Happy path: register user ──
    #[test]
    fun test_register_user() {
        let mut scenario = h::setup_phase2();

        // User registers
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);

            user_registry::register_user(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));

            assert!(user_registry::total_users(&user_reg) == 1);
            assert!(user_registry::is_registered(&user_reg, h::user_1()));

            let profile = user_registry::borrow_profile(&user_reg, h::user_1());
            assert!(user_registry::display_name(profile) == b"Alice");
            assert!(user_registry::room_count(profile) == 0);

            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Happy path: update profile ──
    #[test]
    fun test_update_profile() {
        let mut scenario = h::setup_phase2();

        // Register first
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        // Update
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::update_profile(&net_reg, &mut user_reg, b"AliceV2", ts::ctx(&mut scenario));

            let profile = user_registry::borrow_profile(&user_reg, h::user_1());
            assert!(user_registry::display_name(profile) == b"AliceV2");

            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Duplicate registration aborts 540 ──
    #[test]
    #[expected_failure(abort_code = 540)]
    fun test_register_user_duplicate() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Alice2", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Update unregistered user aborts 541 ──
    #[test]
    #[expected_failure(abort_code = 541)]
    fun test_update_profile_not_registered() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::update_profile(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Register while paused aborts 542 ──
    #[test]
    #[expected_failure(abort_code = 542)]
    fun test_register_user_paused() {
        let mut scenario = h::setup_phase2();

        // Pause protocol
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Multiple users can register independently ──
    #[test]
    fun test_multiple_users() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::next_tx(&mut scenario, h::user_2());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Bob", ts::ctx(&mut scenario));

            assert!(user_registry::total_users(&user_reg) == 2);
            assert!(user_registry::is_registered(&user_reg, h::user_1()));
            assert!(user_registry::is_registered(&user_reg, h::user_2()));

            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── Update while paused aborts 542 ──
    #[test]
    #[expected_failure(abort_code = 542)]
    fun test_update_profile_paused() {
        let mut scenario = h::setup_phase2();

        // Register user while unpaused
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Alice", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        // Admin pauses the protocol
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // update_profile must abort E_PAUSED
        ts::next_tx(&mut scenario, h::user_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(&scenario);
            user_registry::update_profile(&net_reg, &mut user_reg, b"Alice2", ts::ctx(&mut scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }

    // ── is_registered returns false for unknown address ──
    #[test]
    fun test_is_registered_false() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::user_1());
        {
            let user_reg = ts::take_shared<UserRegistry>(&scenario);
            assert!(!user_registry::is_registered(&user_reg, h::user_1()));
            ts::return_shared(user_reg);
        };

        ts::end(scenario);
    }
}
