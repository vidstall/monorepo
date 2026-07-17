/// Economic layer tests -- 17 tests covering escrow creation, proof submission,
/// reward distribution, quality multipliers, median computation, accuracy scoring,
/// and escrow remainder handling.
///
/// Tests use #[test_only] helpers to bypass ed25519 signature verification
/// (add_proof_for_testing) and to set up rooms/relays/validators with known IDs.
/// Integration tests (real validator daemon TXs) provide definitive ed25519 coverage.
#[test_only]
module dvconf::economic_layer_tests {
    use sui::test_scenario::{Self as ts};
    use sui::coin::{Self};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use sui::sui::SUI;
    use dvconf::network_registry::{NetworkRegistry};
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::user_registry::{Self, UserRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::control_plane_registry::ControlPlaneRegistry;
    use dvconf::signaling_registry::SignalingRegistry;
    use dvconf::staking;
    use dvconf::economic_layer;

    // ── Test addresses ──
    const CREATOR: address = @0xE1;   // h::user_1() -- room creator
    const RELAY_OP: address = @0xB1;  // h::relay_1() -- relay operator
    const VAL_OP_1: address = @0xD1;  // h::val_1() -- validator 1
    const VAL_OP_2: address = @0xD2;  // h::val_2() -- validator 2
    const OTHER:    address = @0xAA;  // uninvolved address

    const RELAY_OP_2: address = @0xB2;  // second relay operator

    // ── Deterministic IDs for test objects ──
    fun room_id(): ID   { object::id_from_address(@0x1001) }
    fun relay_id(): ID  { object::id_from_address(@0x2001) }
    fun relay_id_2(): ID { object::id_from_address(@0x2002) }
    fun val_id_1(): ID  { object::id_from_address(@0x3001) }
    fun val_id_2(): ID  { object::id_from_address(@0x3002) }

    // ── Escrow amount for tests ──
    const ESCROW_AMOUNT: u64 = 50_000_000; // 0.05 SUI

    // ══════════════════════════════════════════════════════════
    // HELPERS
    // ══════════════════════════════════════════════════════════

    /// Register the creator as a user and add a room in PENDING status.
    fun setup_room_pending(scenario: &mut ts::Scenario) {
        // Register user
        ts::next_tx(scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let mut user_reg = ts::take_shared<UserRegistry>(scenario);
            user_registry::register_user(&net_reg, &mut user_reg, b"Creator", ts::ctx(scenario));
            ts::return_shared(net_reg);
            ts::return_shared(user_reg);
        };

        // Add room with known ID in PENDING status
        ts::next_tx(scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(scenario);
            room_manager::add_room_for_testing(
                &mut manager,
                room_id(),
                CREATOR,
                constants::room_status_pending(),
                constants::relay_mode_sfu(),
                6, ts::ctx(scenario),
            );
            ts::return_shared(manager);
        };
    }

    /// Setup a room in CLOSED status (for distribute_rewards tests).
    fun setup_room_closed(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(scenario);
            room_manager::add_room_for_testing(
                &mut manager,
                room_id(),
                CREATOR,
                constants::room_status_closed(),
                constants::relay_mode_sfu(),
                6, ts::ctx(scenario),
            );
            ts::return_shared(manager);
        };
    }

    /// Register relay + validators in their registries with known IDs.
    fun setup_relay_and_validators(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(scenario),
            );
            ts::return_shared(relay_reg);
        };

        ts::next_tx(scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_1(), VAL_OP_1, h::validator_stake(), ts::ctx(scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_2(), VAL_OP_2, h::validator_stake(), ts::ctx(scenario),
            );
            ts::return_shared(val_reg);
        };
    }

    /// RO-023b/c: assign the single primary relay to the (already-created) room so
    /// the per-relay distribution loop evaluates it. Used by legacy single-relay
    /// distribute_rewards tests that register but never assigned the relay.
    fun assign_single_relay(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id()],
            );
            ts::return_shared(manager);
        };
    }

    /// Create a RoomEscrow with proofs injected (for distribute_rewards tests).
    /// Returns after sharing the escrow.
    fun setup_escrow_with_proofs(
        scenario: &mut ts::Scenario,
        bytes_1: u64,
        bytes_2: u64,
        loss_1: u64,
        loss_2: u64,
    ) {
        // RO-023b/c: distribute_rewards iterates room_assigned_relays. Assign the
        // single relay these legacy 2-proof tests attest (room exists from
        // setup_room_closed). Both proofs come from DISTINCT validators
        // (val_1, val_2) so the relay is covered (>= MIN_PROOFS_FOR_DISTRIBUTION).
        assign_single_relay(scenario);

        // Mint escrow funds
        h::mint_to(scenario, ESCROW_AMOUNT, CREATOR);

        ts::next_tx(scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(scenario),
            );

            // Add 2 proofs via test helper
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, bytes_1, 0, 300, 50, loss_1, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id(),
                1000, bytes_2, 0, 300, 50, loss_2, 10, 0, 0,
            );

            economic_layer::share_escrow_for_testing(escrow);
        };
    }

    // ══════════════════════════════════════════════════════════
    // TEST 1: create_escrow happy path
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_create_escrow() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);

        // Mint tokens for escrow
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };

        // Verify escrow was created as shared object
        ts::next_tx(&mut scenario, CREATOR);
        {
            let escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            assert!(economic_layer::escrow_room_id(&escrow) == room_id());
            assert!(economic_layer::escrow_creator(&escrow) == CREATOR);
            assert!(economic_layer::escrow_balance(&escrow) == ESCROW_AMOUNT);
            assert!(economic_layer::escrow_proof_count(&escrow) == 0);
            assert!(!economic_layer::escrow_is_distributed(&escrow));
            ts::return_shared(escrow);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 2: create_escrow by non-creator aborts 651
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 651)]
    fun test_create_escrow_not_creator_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);

        // Mint tokens for OTHER
        h::mint_to(&mut scenario, ESCROW_AMOUNT, OTHER);

        ts::next_tx(&mut scenario, OTHER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);

            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 3: create_escrow with zero payment aborts 660
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 660)]
    fun test_create_escrow_zero_payment_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = coin::zero<SUI>(ts::ctx(&mut scenario));

            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 4: submit_session_proof happy path
    // NOTE: ed25519 verification cannot be bypassed in unit tests.
    // This test verifies that the proof submission flow reaches the
    // signature check. A real ed25519 signature would be needed to
    // pass. Integration tests provide definitive coverage.
    // We use add_proof_for_testing to verify storage works.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_submit_proof_happy_path() {
        let mut scenario = h::setup_phase3();

        // Create escrow via test helper and add a proof
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            // Add proof via testing helper (bypasses ed25519 verification)
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000,       // packets_forwarded
                500_000,    // bytes_transferred
                0,          // unique_peers
                300,        // duration_seconds
                50,         // avg_latency_ms
                100,        // packet_loss_bps (1% loss)
                10,         // jitter_ms
                0,          // submitted_at
                0,          // relay_role = primary (RO-017)
            );

            assert!(economic_layer::escrow_proof_count(&escrow) == 1);
            economic_layer::destroy_escrow_for_testing(escrow);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 5: submit_session_proof with invalid signature aborts 654
    // Proves the ed25519 check exists by providing garbage signatures.
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 654)]
    fun test_submit_proof_invalid_sig_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Assign val_id_1 to the room so assignment check passes
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_validators_for_testing(
                &mut manager, room_id(), vector[val_id_1()],
            );
            ts::return_shared(manager);
        };

        // Create and share escrow
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Assign a session wallet to val_1
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), @0x51);
            ts::return_shared(val_reg);
        };

        // Submit proof from session wallet with garbage keys/sigs -- should abort 654
        ts::next_tx(&mut scenario, @0x51);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            // Garbage 32-byte pubkeys and 64-byte signatures
            let fake_pubkey = x"0000000000000000000000000000000000000000000000000000000000000000";
            let fake_sig = x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

            economic_layer::submit_session_proof(
                &net_reg,
                &mut escrow,
                &room_mgr,
                &mut val_reg,
                &mut relay_reg,
                room_id(),
                relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10,
                fake_pubkey,
                fake_pubkey,
                fake_sig,
                fake_sig,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 6: submit_session_proof without session wallet aborts 655
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 655)]
    fun test_submit_proof_no_session_wallet_aborts() {
        let mut scenario = h::setup_phase3();
        setup_relay_and_validators(&mut scenario);

        // Create and share escrow
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Submit proof from address with no session wallet -- abort 655
        ts::next_tx(&mut scenario, @0xF9);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            let fake_pubkey = x"0000000000000000000000000000000000000000000000000000000000000000";
            let fake_sig = x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

            economic_layer::submit_session_proof(
                &net_reg,
                &mut escrow,
                &room_mgr,
                &mut val_reg,
                &mut relay_reg,
                room_id(),
                relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10,
                fake_pubkey,
                fake_pubkey,
                fake_sig,
                fake_sig,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 7: submit_session_proof duplicate aborts 656
    // Uses add_proof_for_testing to simulate first submission,
    // then verifies that a second attempt from the same validator
    // triggers the duplicate check (which runs before sig verification).
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 656)]
    fun test_submit_proof_duplicate_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Assign val_id_1 to the room so assignment check passes
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_validators_for_testing(
                &mut manager, room_id(), vector[val_id_1()],
            );
            ts::return_shared(manager);
        };

        // Create escrow with one proof already injected for val_1
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            // Inject first proof for val_1
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Assign session wallet for val_1
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), @0x51);
            ts::return_shared(val_reg);
        };

        // Attempt duplicate submission -- should abort 656 (after assignment check passes)
        ts::next_tx(&mut scenario, @0x51);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            let fake_pubkey = x"0000000000000000000000000000000000000000000000000000000000000000";
            let fake_sig = x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

            economic_layer::submit_session_proof(
                &net_reg,
                &mut escrow,
                &room_mgr,
                &mut val_reg,
                &mut relay_reg,
                room_id(),
                relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10,
                fake_pubkey,
                fake_pubkey,
                fake_sig,
                fake_sig,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 8: distribute_rewards happy path (70/15/15 split)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_distribute_rewards_happy_path() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Excellent quality: 100 bps loss (< 200 threshold)
        setup_escrow_with_proofs(&mut scenario, 500_000, 500_000, 100, 100);

        // Distribute rewards
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
                &net_reg,
                &mut escrow,
                &room_mgr,
                &mut relay_reg,
                &mut val_reg,
                &cp_reg,
                &sig_reg,
                ts::ctx(&mut scenario),
            );

            // Verify distributed flag
            assert!(economic_layer::escrow_is_distributed(&escrow));

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
    // TEST 9: distribute_rewards room not closed aborts 657
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 657)]
    fun test_distribute_rewards_room_not_closed_aborts() {
        let mut scenario = h::setup_phase3();
        setup_relay_and_validators(&mut scenario);

        // Room in PENDING status (not closed)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), CREATOR,
                constants::room_status_pending(),
                constants::relay_mode_sfu(),
                6, ts::ctx(&mut scenario),
            );
            ts::return_shared(manager);
        };

        setup_escrow_with_proofs(&mut scenario, 500_000, 500_000, 100, 100);

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
    // TEST 10: distribute_rewards insufficient proofs aborts 658
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 658)]
    fun test_distribute_rewards_insufficient_proofs_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Create escrow with only 1 proof (need MIN_PROOFS_FOR_DISTRIBUTION = 2)
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 0,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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
    // TEST 11: distribute_rewards already distributed aborts 659
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 659)]
    fun test_distribute_rewards_already_distributed_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);
        setup_escrow_with_proofs(&mut scenario, 500_000, 500_000, 100, 100);

        // First distribution
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

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        // Second distribution -- should abort 659
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
    // TEST 12: quality_multiplier excellent (loss <= 200bp -> 10000)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_quality_multiplier_excellent() {
        assert!(economic_layer::compute_quality_multiplier(0) == 10_000);
        assert!(economic_layer::compute_quality_multiplier(100) == 10_000);
        assert!(economic_layer::compute_quality_multiplier(200) == 10_000);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 13: quality_multiplier good (loss <= 500bp -> 8000)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_quality_multiplier_good() {
        assert!(economic_layer::compute_quality_multiplier(201) == 8_000);
        assert!(economic_layer::compute_quality_multiplier(300) == 8_000);
        assert!(economic_layer::compute_quality_multiplier(500) == 8_000);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 14: quality_multiplier acceptable (loss <= 1000bp -> 5000)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_quality_multiplier_acceptable() {
        assert!(economic_layer::compute_quality_multiplier(501) == 5_000);
        assert!(economic_layer::compute_quality_multiplier(750) == 5_000);
        assert!(economic_layer::compute_quality_multiplier(1000) == 5_000);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 15: quality_multiplier slash (loss > 1000bp -> 0)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_quality_multiplier_slash() {
        assert!(economic_layer::compute_quality_multiplier(1001) == 0);
        assert!(economic_layer::compute_quality_multiplier(5000) == 0);
        assert!(economic_layer::compute_quality_multiplier(10000) == 0);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 16: median computation (odd and even counts)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_median_computation() {
        // Empty
        let empty = vector::empty<u64>();
        assert!(economic_layer::compute_median(&empty) == 0);

        // Single
        let single = vector[42];
        assert!(economic_layer::compute_median(&single) == 42);

        // Odd count (3 elements): [100, 200, 300] -> median = 200
        let odd = vector[300, 100, 200];
        assert!(economic_layer::compute_median(&odd) == 200);

        // Even count (2 elements): [100, 200] -> median = (100+200)/2 = 150
        let even2 = vector[200, 100];
        assert!(economic_layer::compute_median(&even2) == 150);

        // Even count (4 elements): [10, 20, 30, 40] -> median = (20+30)/2 = 25
        let even4 = vector[40, 10, 30, 20];
        assert!(economic_layer::compute_median(&even4) == 25);

        // Duplicate values
        let dups = vector[500, 500, 500];
        assert!(economic_layer::compute_median(&dups) == 500);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 17: validator accuracy scoring
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_validator_accuracy_scoring() {
        // Exact match -> 10000 (perfect score)
        assert!(economic_layer::compute_accuracy_score(1000, 1000) == 10_000);

        // 10% deviation -> 9000
        assert!(economic_layer::compute_accuracy_score(1100, 1000) == 9_000);
        assert!(economic_layer::compute_accuracy_score(900, 1000) == 9_000);

        // 50% deviation -> 5000
        assert!(economic_layer::compute_accuracy_score(1500, 1000) == 5_000);
        assert!(economic_layer::compute_accuracy_score(500, 1000) == 5_000);

        // 100%+ deviation -> 0
        assert!(economic_layer::compute_accuracy_score(2000, 1000) == 0);
        assert!(economic_layer::compute_accuracy_score(0, 1000) == 0);

        // Median is 0 -> always 10000 (basis_points)
        assert!(economic_layer::compute_accuracy_score(500, 0) == 10_000);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 18: escrow remainder returns to creator
    // When total_reward < escrow balance, remainder goes to creator.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_escrow_remainder_returns_to_creator() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);
        assign_single_relay(&mut scenario);

        // Large escrow, small bytes_transferred -> total_reward < escrow_balance
        // base_rate=100, median_bytes=1000, qm=10000 -> total = 100*1000*10000/10000 = 100000
        // escrow = 100_000_000 >> 100_000 so most goes back as remainder
        let large_escrow = 100_000_000u64;
        h::mint_to(&mut scenario, large_escrow, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            // Both validators report same small bytes (excellent quality, tiny reward)
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                100, 1000, 0, 60, 20, 50, 5, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id(),
                100, 1000, 0, 60, 20, 50, 5, 0, 0,
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

            // Before distribution: escrow has full balance
            assert!(economic_layer::escrow_balance(&escrow) == large_escrow);

            economic_layer::distribute_rewards(
                &net_reg, &mut escrow, &room_mgr,
                &mut relay_reg, &mut val_reg,
                &cp_reg, &sig_reg,
                ts::ctx(&mut scenario),
            );

            // After distribution: escrow balance is 0 (all distributed/returned)
            assert!(economic_layer::escrow_balance(&escrow) == 0);
            assert!(economic_layer::escrow_is_distributed(&escrow));

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
    // TEST 19: slash path emits RelaySlashed with slash_amount 0
    // When quality_multiplier == 0 (loss > 10%), the RelaySlashed event
    // is emitted with slash_amount: 0 and escrow is returned to creator.
    // (Direct stake slashing removed — relay_stake no longer passed.)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_slash_returns_escrow_to_creator() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);
        assign_single_relay(&mut scenario);

        let escrow_amount = 1_000_000u64;
        h::mint_to(&mut scenario, escrow_amount, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            // Both validators report packet_loss > 1000bp (> 10%) -> triggers slash path
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 50000, 0, 300, 50, 2000, 20, 0, 0, // 2000 bps = 20% loss
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id(),
                1000, 50000, 0, 300, 50, 1500, 20, 0, 0, // 1500 bps = 15% loss
            );

            economic_layer::share_escrow_for_testing(escrow);
        };

        // Distribute (should trigger slash path — no relay_stake needed)
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

            // Escrow fully returned to creator (no rewards when quality_multiplier == 0)
            assert!(economic_layer::escrow_balance(&escrow) == 0);
            assert!(economic_layer::escrow_is_distributed(&escrow));

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
    // GAP CLOSURE TESTS (Verification Agent gaps 650, 652, 653, 661)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = economic_layer::E_PAUSED)]
    fun test_create_escrow_when_paused_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            dvconf::network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };
        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = economic_layer::E_ROOM_NOT_FOUND)]
    fun test_create_escrow_room_not_found_aborts() {
        let mut scenario = h::setup_phase3();
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        // No room setup — room_id does not exist
        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };
        ts::end(scenario);
    }

    #[test]
    #[expected_failure(abort_code = economic_layer::E_ROOM_NOT_PENDING)]
    fun test_create_escrow_room_not_pending_aborts() {
        let mut scenario = h::setup_phase3();
        // Room in CLOSED status (not PENDING)
        setup_room_closed(&mut scenario);
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };
        ts::end(scenario);
    }

    // ── TD-P13-03: submit_session_proof paused aborts 650 ──
    #[test]
    #[expected_failure(abort_code = economic_layer::E_PAUSED)]
    fun test_submit_proof_when_paused_aborts() {
        let mut scenario = h::setup_phase3();
        setup_relay_and_validators(&mut scenario);

        // Create escrow via test helper
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Assign session wallet for val_1
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), @0x51);
            ts::return_shared(val_reg);
        };

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            dvconf::network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Submit proof — should abort 650
        ts::next_tx(&mut scenario, @0x51);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            let fake_pubkey = x"0000000000000000000000000000000000000000000000000000000000000000";
            let fake_sig = x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

            economic_layer::submit_session_proof(
                &net_reg, &mut escrow, &room_mgr, &mut val_reg, &mut relay_reg,
                room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10,
                fake_pubkey, fake_pubkey, fake_sig, fake_sig,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };
        ts::end(scenario);
    }

    // ── TD-P13-03: distribute_rewards paused aborts 650 ──
    #[test]
    #[expected_failure(abort_code = economic_layer::E_PAUSED)]
    fun test_distribute_rewards_when_paused_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);
        setup_escrow_with_proofs(&mut scenario, 500_000, 500_000, 100, 100);

        // Pause the network
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            dvconf::network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };

        // Distribute rewards — should abort 650
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
    // SEC-001: destroy locked position aborts 201
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 201)] // E_STAKE_LOCKED in staking
    fun test_destroy_locked_position_aborts() {
        let mut scenario = h::setup_phase3();

        h::mint_to(&mut scenario, h::relay_stake(), RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut position = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );

            // Lock the position (simulates active session)
            staking::lock(&mut position);

            // Attempt to destroy -- should abort with E_STAKE_LOCKED (201)
            let (owner, _miner_id, _role, coin_out) = staking::destroy(position, ts::ctx(&mut scenario));
            transfer::public_transfer(coin_out, owner);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // SEC-003: large bytes_transferred no overflow
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_large_bytes_no_overflow() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);
        assign_single_relay(&mut scenario);

        // Use 1TB = 1_000_000_000_000 bytes_transferred
        let large_bytes: u64 = 1_000_000_000_000;
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            // Both validators report 1TB bytes, excellent quality
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, large_bytes, 0, 3600, 20, 50, 5, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id(),
                1000, large_bytes, 0, 3600, 20, 50, 5, 0, 0,
            );

            economic_layer::share_escrow_for_testing(escrow);
        };

        // Distribute — should succeed without overflow
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
            // With corrected formula: step1 = 100 * 10_000 / 10_000 = 100
            // total_reward = 100 * 1_000_000_000_000 = 100_000_000_000_000
            // Capped by escrow (50_000_000), so entire escrow is consumed.
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
    // TEST: Slash path records real slash_amount (Phase 18)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_slash_records_amount() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // RO-023b: the per-relay slash trigger iterates room_assigned_relays —
        // assign the relay so its (high-loss) bucket is evaluated and slashed.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id()],
            );
            ts::return_shared(manager);
        };

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
                1000, 50000, 0, 300, 50, 2000, 20, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id(),
                1000, 50000, 0, 300, 50, 1500, 20, 0, 0,
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
            // add_relay_for_testing hardcodes stake_amount = 1_000_000_000 (1 SUI)
            // SLASH_PERCENTAGE_BPS = 1000 (10%)
            let relay_test_stake = 1_000_000_000u64;
            let expected_slash = relay_test_stake * constants::slash_percentage_bps() / constants::basis_points();
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

    #[test]
    #[expected_failure(abort_code = economic_layer::E_RELAY_NOT_REGISTERED)]
    fun test_submit_proof_relay_not_registered_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);

        // Create escrow
        ts::next_tx(&mut scenario, CREATOR);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            economic_layer::create_escrow(
                &net_reg, &room_mgr, room_id(), coin, ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(room_mgr);
        };

        // NO relay registered — submit proof should abort 661 at relay check
        ts::next_tx(&mut scenario, VAL_OP_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            economic_layer::submit_session_proof(
                &net_reg, &mut escrow, &room_mgr, &mut val_reg, &mut relay_reg,
                room_id(), relay_id(),
                100, 50000, 0, 300, 50, 100, 5,
                x"0000000000000000000000000000000000000000000000000000000000000000",
                x"0000000000000000000000000000000000000000000000000000000000000000",
                x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
                x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
                ts::ctx(&mut scenario),
            );
            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST: Unassigned validator proof rejected (Phase 18)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 662)]
    fun test_submit_proof_unassigned_validator_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Assign ONLY val_id_1 to the room (val_id_2 is NOT assigned)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_validators_for_testing(
                &mut manager, room_id(), vector[val_id_1()],
            );
            ts::return_shared(manager);
        };

        // Create escrow
        h::mint_to(&mut scenario, 50_000_000, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // val_id_2 is NOT assigned — check should abort 662
        ts::next_tx(&mut scenario, VAL_OP_2);
        {
            let escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);

            economic_layer::check_validator_assigned_for_testing(
                &escrow, &room_mgr, val_id_2(),
            );

            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST: pay_slash quality=0 single relay (100% to creator)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_pay_slash_quality_zero_single_relay() {
        let mut scenario = h::setup_phase3();

        // Register relay in registry
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        // Create escrow (empty balance — slash comes from stake, not escrow)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = coin::zero<SUI>(ts::ctx(&mut scenario));
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            // Set slash: 25M, quality=0, no other relays
            economic_layer::set_slash_for_testing(
                &mut escrow, 25_000_000, relay_id(), 0, vector::empty(),
            );

            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create and share StakePosition with 250M balance
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let position = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(position);
        };

        // Call pay_slash
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut relay_stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut relay_stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            // Slash cleared
            assert!(economic_layer::escrow_slash_amount(&escrow) == 0);
            // Stake reduced by 25M
            assert!(staking::amount(&relay_stake) == 225_000_000);

            ts::return_shared(escrow);
            ts::return_shared(relay_stake);
            ts::return_shared(relay_reg);
        };

        // Verify creator received 25M (quality=0 means 100% to creator)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 25_000_000);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST: pay_slash quality=5000 multi relay (50/50 split)
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_pay_slash_quality_5000_multi_relay() {
        let mut scenario = h::setup_phase3();

        // Register two relays
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        // Create escrow with slash: quality=5000, one other relay
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = coin::zero<SUI>(ts::ctx(&mut scenario));
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            economic_layer::set_slash_for_testing(
                &mut escrow, 25_000_000, relay_id(), 5000, vector[relay_id_2()],
            );

            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create and share StakePosition
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let position = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(position);
        };

        // Call pay_slash
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut relay_stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut relay_stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            assert!(economic_layer::escrow_slash_amount(&escrow) == 0);
            assert!(staking::amount(&relay_stake) == 225_000_000);

            ts::return_shared(escrow);
            ts::return_shared(relay_stake);
            ts::return_shared(relay_reg);
        };

        // RELAY_OP_2 receives 12_500_000 (50% of 25M)
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 12_500_000);
            ts::return_to_sender(&scenario, coin);
        };

        // CREATOR receives 12_500_000 (remaining 50%)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 12_500_000);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST: pay_slash wrong stake aborts 664
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 664)]
    fun test_pay_slash_wrong_stake_aborts() {
        let mut scenario = h::setup_phase3();

        // Register relay
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        // Create escrow with slash targeting relay_id()
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = coin::zero<SUI>(ts::ctx(&mut scenario));
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::set_slash_for_testing(
                &mut escrow, 25_000_000, relay_id(), 0, vector::empty(),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create StakePosition for relay_id_2() (WRONG miner)
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let position = staking::create_for_testing(
                RELAY_OP, relay_id_2(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(position);
        };

        // Call pay_slash — should abort 664 (wrong stake)
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut relay_stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut relay_stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            ts::return_shared(escrow);
            ts::return_shared(relay_stake);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST: pay_slash no pending aborts 663
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 663)]
    fun test_pay_slash_no_pending_aborts() {
        let mut scenario = h::setup_phase3();

        // Register relay
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        // Create escrow WITHOUT setting slash (slash_amount = 0)
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = coin::zero<SUI>(ts::ctx(&mut scenario));
            let escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Create StakePosition
        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let position = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(position);
        };

        // Call pay_slash — should abort 663 (no slash pending)
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut relay_stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut relay_stake, &mut relay_reg, ts::ctx(&mut scenario),
            );

            ts::return_shared(escrow);
            ts::return_shared(relay_stake);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-017): relay_role is stored per-proof and readable.
    // The chain derives relay_role = (relay_miner_id == assigned_relays[0]) ? 0 : 1
    // inside submit_session_proof (covered by integration ed25519 tests). Here we
    // verify the field round-trips through the stored SessionProof via the
    // test-only accessor: a primary-relay proof reads back 0, a standby reads 1.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_relay_role_chain_derived() {
        let mut scenario = h::setup_phase3();

        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );

            // Proof 0 attests the PRIMARY relay (assigned_relays[0]) -> relay_role 0
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0,
                0, // relay_role = primary
            );
            // Proof 1 attests the STANDBY relay (assigned_relays[1]) -> relay_role 1
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_2(), room_id(), relay_id_2(),
                1000, 0, 0, 300, 50, 100, 10, 0,
                1, // relay_role = standby
            );

            assert!(economic_layer::escrow_proof_relay_role(&escrow, 0) == 0);
            assert!(economic_layer::escrow_proof_relay_role(&escrow, 1) == 1);

            economic_layer::destroy_escrow_for_testing(escrow);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-023a): compound dedup key (validator_id, relay_miner_id).
    // The dedup loop in submit_session_proof runs BEFORE ed25519 verification.
    // POSITIVE: one validator attests BOTH relays. With one proof already stored
    // for (val_1, relay), a real submit_session_proof for (val_1, relay2) must
    // now PASS the dedup guard and proceed to signature verification — where it
    // aborts 654 on garbage sigs. Today (validator-only dedup) it would abort 656
    // at the dedup loop instead, so asserting 654 is the RED→GREEN signal:
    // reaching the signature check proves the second relay was NOT rejected as a
    // duplicate (i.e. escrow now accepts a 2nd proof from the same validator for a
    // DIFFERENT relay — the unblock RO-019 dual-probe needs).
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 654)]
    fun test_submit_proof_same_validator_two_relays() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Register the standby relay (relay_id_2) too
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        // Assign val_1 to the room + both relays (primary, standby)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_validators_for_testing(
                &mut manager, room_id(), vector[val_id_1()],
            );
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // Create escrow with the val_1→relay (primary) proof already stored
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0,
                0, // relay_role = primary
            );
            assert!(economic_layer::escrow_proof_count(&escrow) == 1);
            economic_layer::share_escrow_for_testing(escrow);
        };

        // Assign session wallet for val_1
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), @0x51);
            ts::return_shared(val_reg);
        };

        // Real submit for the SECOND relay (val_1, relay2) — must pass the compound
        // dedup guard and reach the ed25519 check, aborting 654 on garbage sigs.
        ts::next_tx(&mut scenario, @0x51);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            let fake_pubkey = x"0000000000000000000000000000000000000000000000000000000000000000";
            let fake_sig = x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

            economic_layer::submit_session_proof(
                &net_reg, &mut escrow, &room_mgr, &mut val_reg, &mut relay_reg,
                room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10,
                fake_pubkey, fake_pubkey, fake_sig, fake_sig,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-023a, negative): a 2nd submit for the SAME (validator, relay)
    // pair still aborts 656. The compound dedup must NOT weaken the same-relay
    // duplicate guard — only same validator + DIFFERENT relay is now allowed.
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 656)]
    fun test_submit_proof_same_validator_same_relay_aborts() {
        let mut scenario = h::setup_phase3();
        setup_room_pending(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Assign val_1 + the primary relay
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_validators_for_testing(
                &mut manager, room_id(), vector[val_id_1()],
            );
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // Escrow with the val_1→relay proof already stored
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow,
                val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10, 0,
                0, // relay_role = primary
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), @0x51);
            ts::return_shared(val_reg);
        };

        // Real submit for the SAME relay (val_1, relay) — duplicate, aborts 656.
        ts::next_tx(&mut scenario, @0x51);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let room_mgr = ts::take_shared<RoomManager>(&scenario);
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            let fake_pubkey = x"0000000000000000000000000000000000000000000000000000000000000000";
            let fake_sig = x"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000";

            economic_layer::submit_session_proof(
                &net_reg, &mut escrow, &room_mgr, &mut val_reg, &mut relay_reg,
                room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 100, 10,
                fake_pubkey, fake_pubkey, fake_sig, fake_sig,
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(val_reg);
            ts::return_shared(relay_reg);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-023b): per-relay partition + per-relay median.
    // Room has BOTH relays assigned. relay (primary) gets 2 high-loss proofs
    // (2000 bps -> per-relay quality 0 -> SLASH). relay2 (standby) gets 2
    // low-loss proofs (100 bps -> per-relay quality excellent -> PAID).
    //
    // Today (ONE blended room-wide median of [2000,2000,100,100] = 1050 ->
    // quality 0) the whole room slashes proofs[0].relay (relay) and relay2's
    // operator (RELAY_OP_2) receives NOTHING. After per-relay partition,
    // relay2's bucket distributes independently and RELAY_OP_2 is PAID while
    // relay is slashed. The RED->GREEN signal: RELAY_OP_2 holds a Coin.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_per_relay_median_distinct_outcomes() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        // Register the standby relay (relay_id_2)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        // Assign BOTH relays to the room (primary, standby)
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // Escrow: 2 high-loss proofs for relay (primary) + 2 low-loss for relay2.
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            // relay (primary): high loss -> quality 0 (slash)
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 2000, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 2000, 10, 0, 0,
            );
            // relay2 (standby): low loss -> quality excellent (paid)
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
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

        // RO-023b: relay2's operator (RELAY_OP_2) must be PAID a relay coin.
        // Today (one blended median -> whole-room slash) RELAY_OP_2 holds nothing.
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) > 0);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-023c, FK-2): one validator submitting BOTH relays does NOT alone
    // satisfy distribution. Each relay bucket needs >= MIN_PROOFS_FOR_DISTRIBUTION
    // DISTINCT validator_ids. With val_1 covering relay (1 proof) AND relay2 (1
    // proof), each bucket has only ONE distinct validator -> NEITHER qualifies ->
    // ZERO relays qualify -> whole-room abort E_NO_RELAY_COVERAGE (665).
    // (OQ-M2-6: distinct-validator independence, not raw proof count.)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 665)]
    fun test_one_validator_both_relays_insufficient() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // ONE validator (val_1) covers BOTH relays — 1 distinct validator each.
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
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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
    // TEST (RO-023c, FK-2): pay-covered / skip-uncovered. relay has 2 distinct
    // validators (qualifies + paid); relay2 has only 1 distinct validator
    // (under-covered -> SKIPPED, earns 0). At least one relay qualifies so NO
    // whole-room abort. RELAY_OP paid; RELAY_OP_2 receives nothing.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_per_relay_skip_undercovered() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // relay: 2 distinct validators (qualifies). relay2: 1 validator (skipped).
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
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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

        // RELAY_OP (covered) is PAID.
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) > 0);
            ts::return_to_sender(&scenario, coin);
        };
        // RELAY_OP_2 (under-covered) received NOTHING — no Coin in inventory.
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            assert!(!ts::has_most_recent_for_sender<coin::Coin<SUI>>(&scenario));
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-016): Hybrid equal split. Two covered, healthy, LIVE relays
    // (primary relay_role=0; standby relay_role=1 with duration_seconds>0 =
    // probe-answered liveness). The relay pool splits EQUALLY — RELAY_OP and
    // RELAY_OP_2 each receive the SAME nonzero per-relay share.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_per_relay_reward_split() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // Both relays: 2 distinct validators, identical low-loss, both LIVE
        // (duration_seconds = 300 > 0). Standby (relay2) is relay_role = 1.
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
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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

        // EQUAL split: capture both operators' coin values, assert equal + >0.
        let primary_paid;
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            primary_paid = coin::value(&coin);
            assert!(primary_paid > 0);
            ts::return_to_sender(&scenario, coin);
        };
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == primary_paid); // equal hybrid split
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-016): standby LIVENESS gate. The standby (relay_role=1) is COVERED
    // (2 distinct validators) and would otherwise be HEALTHY (low loss), but its
    // liveness signal is FALSE — median duration_seconds == 0 (the RO-020 probe
    // was NOT answered). So the standby earns 0 and the primary absorbs the full
    // relay pool. Closes DA C4 standby-grinding. Today (no liveness gate) the
    // standby would split the pool equally -> RELAY_OP_2 wrongly paid (RED).
    //
    // FROZEN LIVENESS CONTRACT (for RO-020 / Phase 2.3): a standby (relay_role==1)
    // earns its share iff covered AND its per-relay median `duration_seconds > 0`.
    // duration_seconds is in the signed IC-2 message (un-spoofable, validator-
    // attested) and survives bytes_transferred≈0 for a warm-idle standby.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_standby_liveness_gate_zero() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // primary: live (duration 300). standby: low-loss + covered BUT
        // duration_seconds == 0 (liveness FALSE — probe unanswered).
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
            // standby proofs: duration_seconds = 0 (liveness signal false)
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 0, 0, 0, 50, 100, 10, 0, 1,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id_2(),
                1000, 0, 0, 0, 50, 100, 10, 0, 1,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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

        // Primary is PAID (the full relay pool, since standby gate = 0).
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) > 0);
            ts::return_to_sender(&scenario, coin);
        };
        // Standby (liveness FALSE) received NOTHING.
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            assert!(!ts::has_most_recent_for_sender<coin::Coin<SUI>>(&scenario));
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-018): per-relay ISOLATED slash trigger. In ONE distribute_rewards,
    // relay (high loss -> per-relay quality 0) is SLASHED while relay2 (healthy,
    // low loss) is PAID — the binary if/else is now a per-relay pay-branch +
    // slash-branch. Asserts: escrow.slash_amount records relay's slash + relay's
    // reputation 0; RELAY_OP_2 holds a positive Coin (paid). The payout isolation
    // (pay_slash + slash_other_relays) is REUSED unchanged.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_per_relay_one_paid_one_slashed() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // relay (primary): high loss -> quality 0 -> SLASH.
        // relay2 (standby): low loss + live (duration 300) -> PAID.
        h::mint_to(&mut scenario, ESCROW_AMOUNT, CREATOR);
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 2000, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id(),
                1000, 500_000, 0, 300, 50, 2000, 10, 0, 0,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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

            // relay was SLASHED: escrow records its slash + quality 0.
            let relay_test_stake = 1_000_000_000u64;
            let expected_slash = relay_test_stake * constants::slash_percentage_bps() / constants::basis_points();
            assert!(economic_layer::escrow_slash_amount(&escrow) == expected_slash);
            assert!(economic_layer::escrow_slash_relay_id(&escrow) == relay_id());
            assert!(economic_layer::escrow_slash_quality(&escrow) == 0);
            // slash_other_relays contains relay2 (payout isolation target).
            let others = economic_layer::escrow_slash_other_relays(&escrow);
            assert!(vector::contains(&others, &relay_id_2()));
            assert!(economic_layer::escrow_is_distributed(&escrow));

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        // relay2 (healthy) is PAID — a slashed sibling did NOT block its payout.
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) > 0);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-024): per-relay event vectors match payout (BEHAVIORAL contract).
    // Move cannot introspect emitted event payloads, so we assert the behavioral
    // contract the RewardsDistributed{relay_ids, relay_rewards} vectors carry:
    // BOTH covered+healthy+live relays earn the SAME equal per-relay share, and
    // each operator's actual Coin == that share (so relay_rewards = [s, s] and
    // relay_ids = [relay, relay2] is behaviorally verified per-operator).
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_per_relay_event_vectors_match_payout() {
        let mut scenario = h::setup_phase3();
        setup_room_closed(&mut scenario);
        setup_relay_and_validators(&mut scenario);

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[relay_id(), relay_id_2()],
            );
            ts::return_shared(manager);
        };

        // Both relays covered, healthy, live, identical metrics.
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
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_1(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::add_proof_for_testing(
                &mut escrow, val_id_2(), room_id(), relay_id_2(),
                1000, 500_000, 0, 300, 50, 100, 10, 0, 1,
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

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

            ts::return_shared(net_reg);
            ts::return_shared(escrow);
            ts::return_shared(room_mgr);
            ts::return_shared(relay_reg);
            ts::return_shared(val_reg);
            ts::return_shared(cp_reg);
            ts::return_shared(sig_reg);
        };

        // Both operators received EXACTLY the same per-relay share (relay_rewards
        // vector = [s, s]; relay_ids = [relay, relay2]). Behavioral contract.
        let s1;
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            s1 = coin::value(&coin);
            assert!(s1 > 0);
            ts::return_to_sender(&scenario, coin);
        };
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == s1);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST (RO-024): RelaySlashRedistributed behavioral contract. pay_slash now
    // emits the slash-redistribution breakdown. Move can't read the event, so we
    // assert the per-beneficiary Coin values that the event's `beneficiaries` /
    // `amounts` vectors + `creator_amount` report: with slash 25M, quality 5000,
    // one sibling relay -> beneficiary relay2 gets 12.5M (amounts[0]), creator
    // gets 12.5M (creator_amount). Mirrors test_pay_slash_quality_5000_multi_relay.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_slash_redistribution_event_vectors_match() {
        let mut scenario = h::setup_phase3();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id(), RELAY_OP, ts::ctx(&mut scenario),
            );
            relay_registry::add_relay_for_testing(
                &mut relay_reg, relay_id_2(), RELAY_OP_2, ts::ctx(&mut scenario),
            );
            ts::return_shared(relay_reg);
        };

        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = coin::zero<SUI>(ts::ctx(&mut scenario));
            let mut escrow = economic_layer::create_escrow_for_testing(
                room_id(), CREATOR, coin, ts::ctx(&mut scenario),
            );
            economic_layer::set_slash_for_testing(
                &mut escrow, 25_000_000, relay_id(), 5000, vector[relay_id_2()],
            );
            economic_layer::share_escrow_for_testing(escrow);
        };

        h::mint_to(&mut scenario, 250_000_000, RELAY_OP);
        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            let position = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), coin, ts::ctx(&mut scenario),
            );
            staking::share_for_testing(position);
        };

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let mut escrow = ts::take_shared<economic_layer::RoomEscrow>(&scenario);
            let mut relay_stake = ts::take_shared<staking::StakePosition>(&scenario);
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);

            economic_layer::pay_slash(
                &mut escrow, &mut relay_stake, &mut relay_reg, ts::ctx(&mut scenario),
            );
            assert!(economic_layer::escrow_slash_amount(&escrow) == 0);

            ts::return_shared(escrow);
            ts::return_shared(relay_stake);
            ts::return_shared(relay_reg);
        };

        // beneficiary relay2 (amounts[0]) == 12.5M (50% of 25M at quality 5000).
        ts::next_tx(&mut scenario, RELAY_OP_2);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 12_500_000);
            ts::return_to_sender(&scenario, coin);
        };
        // creator_amount == 12.5M (remaining 50%).
        ts::next_tx(&mut scenario, CREATOR);
        {
            let coin = ts::take_from_sender<coin::Coin<SUI>>(&scenario);
            assert!(coin::value(&coin) == 12_500_000);
            ts::return_to_sender(&scenario, coin);
        };

        ts::end(scenario);
    }
}
