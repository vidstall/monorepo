#[test_only]
module dvconf::validator_registry_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::miner_store::MinerStore;
    use dvconf::caps::{Self, MinerCap, ControlPlaneCap};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::validator_registry::{Self, ValidatorRegistry};

    // ── Helper: register a validator miner and get its cap + stake ──
    fun register_validator_miner(scenario: &mut ts::Scenario) {
        h::do_register(scenario, h::val_1(), h::validator_stake());
    }

    // ── Happy path: register validator in registry ──
    #[test]
    fun test_register_validator() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            assert!(validator_registry::active_count(&val_reg) == 1);
            assert!(validator_registry::is_registered(&val_reg, miner_id));

            let info = validator_registry::borrow_info(&val_reg, miner_id);
            assert!(validator_registry::info_operator(info) == h::val_1());
            assert!(validator_registry::info_stake_amount(info) == h::validator_stake());
            assert!(validator_registry::info_session_count(info) == 0);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Wrong role aborts 530 ──
    #[test]
    #[expected_failure(abort_code = 530)]
    fun test_register_wrong_role() {
        let mut scenario = h::setup_phase2();
        // Register as relay (role=2), then try to register in validator registry
        h::do_register(&mut scenario, h::relay_1(), h::relay_stake());

        ts::next_tx(&mut scenario, h::relay_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Duplicate registration aborts 531 ──
    #[test]
    #[expected_failure(abort_code = 531)]
    fun test_register_duplicate() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        // First registration
        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Second registration — should abort
        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Register while paused aborts 533 ──
    #[test]
    #[expected_failure(abort_code = 533)]
    fun test_register_paused() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        // Pause
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Session wallet operations ──
    #[test]
    fun test_session_wallet_assign_and_reveal() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        // Register in validator registry
        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);

            // Assign session wallet (package-only, but test_only context)
            let session_wallet = @0xF1;
            validator_registry::assign_session_wallet(&mut val_reg, miner_id, session_wallet);
            assert!(validator_registry::has_session_wallet(&val_reg, session_wallet));

            // Reveal session wallet
            validator_registry::reveal_session_wallet(&mut val_reg, session_wallet);
            assert!(!validator_registry::has_session_wallet(&val_reg, session_wallet));

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── Reputation and session count ──
    #[test]
    fun test_set_reputation_and_increment_session() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);

            validator_registry::set_reputation(&mut val_reg, miner_id, 8_000);
            let info = validator_registry::borrow_info(&val_reg, miner_id);
            assert!(validator_registry::info_reputation(info) == 8_000);

            validator_registry::increment_session_count(&mut val_reg, miner_id);
            let info = validator_registry::borrow_info(&val_reg, miner_id);
            assert!(validator_registry::info_session_count(info) == 1);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── GAP-004: duplicate session wallet aborts 534 ──
    #[test]
    #[expected_failure(abort_code = 534)]
    fun test_assign_duplicate_session_wallet_aborts_534() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            let session_wallet = @0xF1;

            // First assignment succeeds
            validator_registry::assign_session_wallet(&mut val_reg, miner_id, session_wallet);
            // Second assignment with same address aborts E_SESSION_EXISTS
            validator_registry::assign_session_wallet(&mut val_reg, miner_id, session_wallet);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── GAP-005: reveal unknown session wallet aborts 535 ──
    #[test]
    #[expected_failure(abort_code = 535)]
    fun test_reveal_unknown_session_wallet_aborts_535() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::val_1());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);

            // Reveal a session wallet that was never assigned
            validator_registry::reveal_session_wallet(&mut val_reg, @0xF9);

            ts::return_shared(val_reg);
        };

        ts::end(scenario);
    }

    // ── is_registered returns false for unknown ID ──
    #[test]
    fun test_is_registered_false() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::val_1());
        {
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);
            assert!(!validator_registry::is_registered(&val_reg, fake_id));
            ts::return_shared(val_reg);
        };

        ts::end(scenario);
    }

    // ── REG-13 gap: borrow_info on unregistered validator aborts 532 ──
    // Verifies that E_NOT_REGISTERED (532) is in the 530-539 namespace as required.
    #[test]
    #[expected_failure(abort_code = 532)]
    fun test_borrow_info_unregistered_validator_aborts_532() {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::val_1());
        {
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let fake_id = object::id_from_address(@0xDEAD);

            // borrow_info asserts table.contains and aborts with E_NOT_REGISTERED (532)
            let _info = validator_registry::borrow_info(&val_reg, fake_id);

            ts::return_shared(val_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // F40 BUG FIX — last_heartbeat field, getter, and new
    // validator_registry::heartbeat() entry (M0 / TDD).
    // ══════════════════════════════════════════════════════════

    // ── F40: register_validator initialises info_last_heartbeat to current epoch ──
    #[test]
    fun test_register_validator_initializes_last_heartbeat() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            let miner_id = caps::miner_cap_miner_id(&cap);
            let info = validator_registry::borrow_info(&val_reg, miner_id);
            let registered_at = validator_registry::info_registered_at(info);
            let last_hb = validator_registry::info_last_heartbeat(info);
            assert!(last_hb == registered_at);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        ts::end(scenario);
    }

    // ── F40: validator_registry::heartbeat() updates last_heartbeat ──
    #[test]
    fun test_validator_heartbeat_updates_last_heartbeat() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        // Register validator
        ts::next_tx(&mut scenario, h::val_1());
        let miner_id;
        let initial_hb;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            miner_id = caps::miner_cap_miner_id(&cap);
            let info = validator_registry::borrow_info(&val_reg, miner_id);
            initial_hb = validator_registry::info_last_heartbeat(info);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Advance epochs
        ts::next_epoch(&mut scenario, h::val_1());
        ts::next_epoch(&mut scenario, h::val_1());
        ts::next_epoch(&mut scenario, h::val_1());

        // Heartbeat
        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            validator_registry::heartbeat(
                &net_reg, &mut val_reg, &cap, ts::ctx(&mut scenario),
            );

            let info = validator_registry::borrow_info(&val_reg, miner_id);
            let new_hb = validator_registry::info_last_heartbeat(info);
            assert!(new_hb > initial_hb);
            // registered_at is independent of heartbeat
            assert!(validator_registry::info_registered_at(info) == initial_hb);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ── F40: validator heartbeat aborts 533 when network is paused ──
    #[test]
    #[expected_failure(abort_code = 533)]
    fun test_validator_heartbeat_fails_when_paused() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);

        // Register validator
        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Pause
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Heartbeat — must abort with E_PAUSED (533)
        ts::next_tx(&mut scenario, h::val_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            validator_registry::heartbeat(
                &net_reg, &mut val_reg, &cap, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // CP-GATED SESSION WALLET ASSIGNMENT (bug fix)
    // ══════════════════════════════════════════════════════════

    // ── Happy path: CP assigns session wallet via entry function ──
    #[test]
    fun test_cp_assign_validator_session() {
        let mut scenario = h::setup_phase2();

        // Register validator miner + CP miner
        register_validator_miner(&mut scenario);
        h::do_register(&mut scenario, h::cp_1(), h::cp_stake());

        // Register validator in registry
        ts::next_tx(&mut scenario, h::val_1());
        let miner_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            miner_id = caps::miner_cap_miner_id(&cap);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // CP assigns session wallet
        let session_wallet = @0xBEEF;
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            validator_registry::assign_validator_session(
                &net_reg, &mut val_reg, &cp_cap, miner_id, session_wallet,
            );

            assert!(validator_registry::has_session_wallet(&val_reg, session_wallet));

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cp_cap);
        };

        ts::end(scenario);
    }

    // ── CP assign session wallet while paused aborts 533 ──
    #[test]
    #[expected_failure(abort_code = 533)]
    fun test_cp_assign_session_paused_aborts_533() {
        let mut scenario = h::setup_phase2();
        register_validator_miner(&mut scenario);
        h::do_register(&mut scenario, h::cp_1(), h::cp_stake());

        // Register validator
        ts::next_tx(&mut scenario, h::val_1());
        let miner_id;
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            let stake = ts::take_from_sender<StakePosition>(&scenario);

            validator_registry::register_validator(
                &net_reg, &mut val_reg, &cap, &stake, ts::ctx(&mut scenario),
            );
            miner_id = caps::miner_cap_miner_id(&cap);

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cap);
            ts::return_to_sender(&scenario, stake);
        };

        // Pause
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // CP tries to assign session wallet — should abort
        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            validator_registry::assign_validator_session(
                &net_reg, &mut val_reg, &cp_cap, miner_id, @0xBEEF,
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cp_cap);
        };

        ts::end(scenario);
    }

    // ── CP assign session wallet for unregistered validator aborts 532 ──
    #[test]
    #[expected_failure(abort_code = 532)]
    fun test_cp_assign_session_unregistered_aborts_532() {
        let mut scenario = h::setup_phase2();
        h::do_register(&mut scenario, h::cp_1(), h::cp_stake());

        ts::next_tx(&mut scenario, h::cp_1());
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let cp_cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            let fake_id = object::id_from_address(@0xDEAD);
            validator_registry::assign_validator_session(
                &net_reg, &mut val_reg, &cp_cap, fake_id, @0xBEEF,
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_to_sender(&scenario, cp_cap);
        };

        ts::end(scenario);
    }
}
