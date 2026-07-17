/// REQ-CFA-006 / INV-C / D-CFA-8,9 — canary_audit slashing tests.
///
/// Covers `slash_for_canary_divergence`: a >=2-DISTINCT-validator Wallet-B
/// attestation quorum over the FROZEN 145-byte canonical proof message
/// (apps/validator-daemon/src/canary/proof.ts), per-attestation session-wallet
/// resolution via `validator_registry::lookup_session_wallet` (NOT ctx.sender),
/// the paused-flag invariant, R_k room-assignment, divergence (expected != observed),
/// and the cross-repo GOLDEN VECTOR byte-mirror (a REAL proof.ts signature verifies
/// under the Move-rebuilt message).
///
/// INV-C: NO Wallet-A material on-chain. Distinct-validator quorum is resolved from
/// the session pubkeys alone (a single validator rotating Wallet-B twice => 2 distinct
/// pubkeys but the SAME miner_id => VecSet size 1 => ABORT).
#[test_only]
module dvconf::canary_audit_tests {
    use sui::test_scenario::{Self as ts};
    use sui::coin;
    use sui::sui::SUI;
    use sui::ed25519;
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::room_manager::{Self, RoomManager};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::constants;
    use dvconf::canary_audit;

    // ── Deterministic IDs (mirror economic_layer_tests / the golden-vector inputs) ──
    fun room_id(): ID    { object::id_from_address(@0x1001) }
    fun relay_id(): ID   { object::id_from_address(@0x2001) }
    fun val_id_1(): ID   { object::id_from_address(@0x3001) }
    fun val_id_2(): ID   { object::id_from_address(@0x3002) }

    const VAL_OP_1: address = @0xD1;
    const VAL_OP_2: address = @0xD2;
    const RELAY_OP: address = @0xB1;
    const CREATOR:  address = @0xE1;

    // ── Golden-vector Wallet-B session-wallet addresses (blake2b256(0x00||pubkey)) ──
    // From the FIXED-seed proof.ts run (Phase 3.1 capture). ADDR_A -> val_1, ADDR_B -> val_2.
    const SESS_ADDR_A: address = @0x7573c697fa68450f04fa0dee2d39dcdc8a5ccf5db547f3e47638a6f8eeeec110;
    const SESS_ADDR_B: address = @0x13a7b144121d74c36412d571cdc52b47c383f2cb78f65d2a660d34e7ba8f13af;

    const BOND_AMOUNT: u64 = 100_000_000; // 0.1 SUI bond

    // ══════════════════════════════════════════════════════════
    // GOLDEN VECTORS (captured from a FIXED-seed proof.ts run; see test file header)
    // ══════════════════════════════════════════════════════════

    // Wallet-B session pubkeys (raw 32 bytes).
    fun pubkey_a(): vector<u8> {
        x"79b5562e8fe654f94078b112e8a98ba7901f853ae695bed7e0e3910bad049664"
    }
    fun pubkey_b(): vector<u8> {
        x"274ed6b26805d2fe8d060529ee9a2f28763b6976d9c5fd1dee38ff36b3b76939"
    }

    // Real ed25519 signatures over the PRESENT (divergence) canonical message.
    fun sig_a_present(): vector<u8> {
        x"6b7283ffc0a5e7cc0a605bb2f10be49c9e0032437b76ae7bc0d97e51d943efae95c9a4d5f095034a07abea0a04ce5a572e083aefd9879b9ce8ffaedd8a01470f"
    }
    fun sig_b_present(): vector<u8> {
        x"3aa0795563bacf4009a95f275db3042f1752ad2deaa0a2e855d4bb81c5c212af0845e8da0e5270243b7e77ca8c16e6b22c6a029c5647772a01eb9c284d022a04"
    }

    // The FROZEN 145-byte canonical PRESENT message proof.ts emitted (for byte-identity).
    fun golden_msg_present(): vector<u8> {
        x"0000000000000000000000000000000000000000000000000000000000001001000000000000000000000000000000000000000000000000000000000000200107000000000000002a00000000000000abababababababababababababababababababababababababababababababab01cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"
    }

    // Golden-vector divergence fields (canary_id=7, frame_seq=42, expected != observed).
    const G_CANARY_ID: u64 = 7;
    const G_FRAME_SEQ: u64 = 42;
    fun expected_hash(): vector<u8> { x"abababababababababababababababababababababababababababababababab" }
    fun observed_hash(): vector<u8> { x"cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd" }
    fun zero_hash():     vector<u8> { x"0000000000000000000000000000000000000000000000000000000000000000" }

    // ══════════════════════════════════════════════════════════
    // BOOTSTRAP
    // ══════════════════════════════════════════════════════════

    /// Register the relay + 2 distinct validators, assign their golden session wallets,
    /// assign the relay to the room, and SHARE a StakePosition bond for the relay.
    fun bootstrap(scenario: &mut ts::Scenario) {
        // Relay
        ts::next_tx(scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, relay_id(), RELAY_OP, ts::ctx(scenario));
            ts::return_shared(relay_reg);
        };

        // Validators + session-wallet bindings (golden ADDR_A -> val_1, ADDR_B -> val_2)
        ts::next_tx(scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(scenario);
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_1(), VAL_OP_1, h::validator_stake(), ts::ctx(scenario),
            );
            validator_registry::add_validator_for_testing(
                &mut val_reg, val_id_2(), VAL_OP_2, h::validator_stake(), ts::ctx(scenario),
            );
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), SESS_ADDR_A);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_2(), SESS_ADDR_B);
            ts::return_shared(val_reg);
        };

        // Room (closed) + assign relay
        ts::next_tx(scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), CREATOR,
                constants::room_status_closed(), constants::relay_mode_sfu(), 6, ts::ctx(scenario),
            );
            room_manager::set_assigned_relays_for_testing(&mut manager, room_id(), vector[relay_id()]);
            ts::return_shared(manager);
        };

        // Shared relay bond (StakePosition)
        ts::next_tx(scenario, h::admin());
        {
            let c = coin::mint_for_testing<SUI>(BOND_AMOUNT, ts::ctx(scenario));
            let pos = staking::create_for_testing(
                RELAY_OP, relay_id(), constants::role_relay(), c, ts::ctx(scenario),
            );
            staking::share_for_testing(pos);
        };
    }

    fun pause_network(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, h::admin());
        {
            let mut net_reg = ts::take_shared<NetworkRegistry>(scenario);
            let admin_cap = ts::take_from_sender<AdminCap>(scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(scenario, admin_cap);
            ts::return_shared(net_reg);
        };
    }

    // ══════════════════════════════════════════════════════════
    // TEST 1 — HAPPY PATH: 2 distinct validators, divergence => slash + event
    // ══════════════════════════════════════════════════════════
    #[test]
    fun test_happy_slash_on_divergence() {
        let mut scenario = h::setup_phase2();
        bootstrap(&mut scenario);

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let manager = ts::take_shared<RoomManager>(&scenario);
            let mut bond = ts::take_shared<StakePosition>(&scenario);

            let before = staking::amount(&bond);

            canary_audit::slash_for_canary_divergence(
                &net_reg, &val_reg, &manager, &mut bond,
                room_id(), relay_id(),
                G_CANARY_ID, G_FRAME_SEQ,
                expected_hash(), observed_hash(), true, // observed present, diverges
                vector[pubkey_a(), pubkey_b()],
                vector[sig_a_present(), sig_b_present()],
                ts::ctx(&mut scenario),
            );

            let after = staking::amount(&bond);
            assert!(after < before, 0); // bond deducted

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_shared(manager);
            ts::return_shared(bond);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 2 — <2 DISTINCT validators (Wallet-B rotated twice -> SAME miner_id)
    // ══════════════════════════════════════════════════════════
    #[test]
    #[expected_failure(abort_code = canary_audit::E_INSUFFICIENT_DISTINCT_ATTESTERS)]
    fun test_abort_single_distinct_validator() {
        let mut scenario = h::setup_phase2();
        bootstrap(&mut scenario);

        // Re-bind ADDR_B to val_1 too: now BOTH golden pubkeys resolve to val_id_1
        // (a single validator rotating Wallet-B) => VecSet size 1 => abort.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            // remove existing ADDR_B->val_2 binding and re-point to val_1
            validator_registry::reveal_session_wallet(&mut val_reg, SESS_ADDR_B);
            validator_registry::assign_session_wallet(&mut val_reg, val_id_1(), SESS_ADDR_B);
            ts::return_shared(val_reg);
        };

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let manager = ts::take_shared<RoomManager>(&scenario);
            let mut bond = ts::take_shared<StakePosition>(&scenario);

            canary_audit::slash_for_canary_divergence(
                &net_reg, &val_reg, &manager, &mut bond,
                room_id(), relay_id(),
                G_CANARY_ID, G_FRAME_SEQ,
                expected_hash(), observed_hash(), true,
                vector[pubkey_a(), pubkey_b()],
                vector[sig_a_present(), sig_b_present()],
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_shared(manager);
            ts::return_shared(bond);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 3 — paused network => abort
    // ══════════════════════════════════════════════════════════
    #[test]
    #[expected_failure(abort_code = canary_audit::E_PAUSED)]
    fun test_abort_when_paused() {
        let mut scenario = h::setup_phase2();
        bootstrap(&mut scenario);
        pause_network(&mut scenario);

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let manager = ts::take_shared<RoomManager>(&scenario);
            let mut bond = ts::take_shared<StakePosition>(&scenario);

            canary_audit::slash_for_canary_divergence(
                &net_reg, &val_reg, &manager, &mut bond,
                room_id(), relay_id(),
                G_CANARY_ID, G_FRAME_SEQ,
                expected_hash(), observed_hash(), true,
                vector[pubkey_a(), pubkey_b()],
                vector[sig_a_present(), sig_b_present()],
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_shared(manager);
            ts::return_shared(bond);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 4 — relay NOT assigned to the room => abort
    // ══════════════════════════════════════════════════════════
    #[test]
    #[expected_failure(abort_code = canary_audit::E_RELAY_NOT_ASSIGNED)]
    fun test_abort_relay_not_assigned() {
        let mut scenario = h::setup_phase2();
        bootstrap(&mut scenario);

        // Unassign the relay from the room.
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::set_assigned_relays_for_testing(&mut manager, room_id(), vector[]);
            ts::return_shared(manager);
        };

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let manager = ts::take_shared<RoomManager>(&scenario);
            let mut bond = ts::take_shared<StakePosition>(&scenario);

            canary_audit::slash_for_canary_divergence(
                &net_reg, &val_reg, &manager, &mut bond,
                room_id(), relay_id(),
                G_CANARY_ID, G_FRAME_SEQ,
                expected_hash(), observed_hash(), true,
                vector[pubkey_a(), pubkey_b()],
                vector[sig_a_present(), sig_b_present()],
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_shared(manager);
            ts::return_shared(bond);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 5 — NO divergence (expected == observed) => abort
    // ══════════════════════════════════════════════════════════
    #[test]
    #[expected_failure(abort_code = canary_audit::E_NO_DIVERGENCE)]
    fun test_abort_no_divergence() {
        let mut scenario = h::setup_phase2();
        bootstrap(&mut scenario);

        ts::next_tx(&mut scenario, RELAY_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let val_reg = ts::take_shared<ValidatorRegistry>(&scenario);
            let manager = ts::take_shared<RoomManager>(&scenario);
            let mut bond = ts::take_shared<StakePosition>(&scenario);

            // expected == observed (both = expected_hash); presence=true.
            // NOTE: sigs here are over a DIFFERENT message than this build, but the
            // divergence check fires BEFORE sig verification, so this still aborts on
            // E_NO_DIVERGENCE (the intended assertion). See module ordering.
            canary_audit::slash_for_canary_divergence(
                &net_reg, &val_reg, &manager, &mut bond,
                room_id(), relay_id(),
                G_CANARY_ID, G_FRAME_SEQ,
                expected_hash(), expected_hash(), true,
                vector[pubkey_a(), pubkey_b()],
                vector[sig_a_present(), sig_b_present()],
                ts::ctx(&mut scenario),
            );

            ts::return_shared(net_reg);
            ts::return_shared(val_reg);
            ts::return_shared(manager);
            ts::return_shared(bond);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TEST 6 — GOLDEN VECTOR cross-repo byte-mirror
    //   (a) Move rebuilds the EXACT 145 bytes proof.ts signed, AND
    //   (b) a REAL proof.ts ed25519 signature verifies under the Move-built message.
    // ══════════════════════════════════════════════════════════
    #[test]
    fun test_golden_vector_byte_mirror() {
        // (a) byte-identity: Move builder reproduces proof.ts's 145-byte PRESENT message.
        let move_msg = canary_audit::build_canonical_message_for_testing(
            room_id(), relay_id(), G_CANARY_ID, G_FRAME_SEQ,
            expected_hash(), observed_hash(), true,
        );
        assert!(move_msg == golden_msg_present(), 100);
        assert!(vector::length(&move_msg) == 145, 101);

        // (b) a REAL proof.ts signature verifies under the Move-rebuilt message.
        assert!(ed25519::ed25519_verify(&sig_a_present(), &pubkey_a(), &move_msg), 102);
        assert!(ed25519::ed25519_verify(&sig_b_present(), &pubkey_b(), &move_msg), 103);

        // DROP variant: presence=false => all-zero observed region.
        let move_msg_drop = canary_audit::build_canonical_message_for_testing(
            room_id(), relay_id(), G_CANARY_ID, G_FRAME_SEQ,
            expected_hash(), zero_hash(), false,
        );
        let golden_drop: vector<u8> =
            x"0000000000000000000000000000000000000000000000000000000000001001000000000000000000000000000000000000000000000000000000000000200107000000000000002a00000000000000abababababababababababababababababababababababababababababababab000000000000000000000000000000000000000000000000000000000000000000";
        assert!(move_msg_drop == golden_drop, 104);
        assert!(vector::length(&move_msg_drop) == 145, 105);
    }
}
