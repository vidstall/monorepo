/// REQ-RMS-009 — authorize_spill_relay: CP-quorum-gated APPEND to assigned_relays.
///
/// TDD: RED first (before authorize_spill_relay exists). GREEN after the entry +
/// RelaySpillAuthorized + error codes 565/566/567 are added.
///
/// Asserts: (1) the entry push_back-es a NEW relay onto assigned_relays (no swap);
/// (2) a non-registered ControlPlaneCap aborts (565); (3) the new event type exists.
///
/// ONCHAIN-4 fold (M1 team-review carry-forward (b)): one expected_failure test that
/// `update_room_rules(min_relay = 1)` aborts with E_INVALID_MIN (505), the governance
/// floor that hardens the REQ-RMS-004 ballot-size invariant.
#[test_only]
module dvconf::room_spill_authorization_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::constants;
    use dvconf::network_registry::{NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::room_manager::{Self, RoomManager, RelaySpillAuthorized};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};
    use dvconf::test_helpers as h;

    const CP_ID:  address = @0xC1;
    const CP_OP:  address = @0xC2;
    const RELAY_PRIMARY: address = @0xA1;
    const RELAY_SPILL:   address = @0xA2;

    fun id_of(a: address): ID { object::id_from_address(a) }
    fun room_id(): ID { object::id_from_address(@0x6001) }

    /// Registers a CP + its cap, two relays, and a READY room with one assigned relay.
    fun setup_room_with_one_relay(): ts::Scenario {
        let mut scenario = h::setup_phase2();

        ts::next_tx(&mut scenario, h::admin());
        {
            let mut relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_of(RELAY_PRIMARY), @0xB1, ctx);
            relay_registry::add_relay_for_testing(&mut relay_reg, id_of(RELAY_SPILL), @0xB2, ctx);
            ts::return_shared(relay_reg);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let ctx = ts::ctx(&mut scenario);
            control_plane_registry::add_cp_for_testing(&mut cp_reg, id_of(CP_ID), CP_OP, 500_000_000, ctx);
            ts::return_shared(cp_reg);
        };
        ts::next_tx(&mut scenario, CP_OP);
        {
            let cap = caps::new_cp_cap(id_of(CP_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_OP);
        };
        ts::next_tx(&mut scenario, h::admin());
        {
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            room_manager::add_room_for_testing(
                &mut manager, room_id(), h::user_1(),
                constants::room_status_ready(), constants::relay_mode_sfu(),
                1, ts::ctx(&mut scenario),
            );
            room_manager::set_assigned_relays_for_testing(
                &mut manager, room_id(), vector[id_of(RELAY_PRIMARY)],
            );
            ts::return_shared(manager);
        };
        scenario
    }

    #[test]
    fun test_authorize_spill_relay_appends_to_assigned_relays() {
        let mut scenario = setup_room_with_one_relay();
        ts::next_tx(&mut scenario, CP_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);

            room_manager::authorize_spill_relay(
                &net_reg, &mut manager, &cp_reg, &relay_reg, &cap,
                room_id(), id_of(RELAY_SPILL), ts::ctx(&mut scenario),
            );

            // APPEND, not swap: slot[0] unchanged, the spill relay is appended.
            let info = room_manager::borrow_room(&manager, room_id());
            let relays = room_manager::room_assigned_relays(info);
            assert!(vector::length(&relays) == 2, 0);
            assert!(*vector::borrow(&relays, 0) == id_of(RELAY_PRIMARY), 1);
            assert!(*vector::borrow(&relays, 1) == id_of(RELAY_SPILL), 2);

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
        };
        // The authorize tx emitted exactly one user event: RelaySpillAuthorized.
        // Move cannot decode the payload, but the emission COUNT is assertable
        // (codebase convention: node_health_tests.move:100,
        // registration_apply_voted_role_tests.move:129). This proves the additive
        // event actually FIRES (its relay_count/authorized_by/epoch fields are
        // otherwise untested), not merely that the type compiles.
        let effects = ts::next_tx(&mut scenario, CP_OP);
        assert!(ts::num_user_events(&effects) == 1, 3);
        ts::end(scenario);
    }

    /// REQ-RMS-009 — a ControlPlaneCap whose cp_id is NOT registered aborts (565).
    #[test]
    #[expected_failure(abort_code = 565)]
    fun test_authorize_spill_relay_unregistered_cp_aborts() {
        let mut scenario = setup_room_with_one_relay();
        // Mint a cap for an UNREGISTERED cp id and try to authorize.
        ts::next_tx(&mut scenario, CP_OP);
        {
            let cap = caps::new_cp_cap(id_of(@0xDEAD), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_OP);
        };
        ts::next_tx(&mut scenario, CP_OP);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);
            let cp_reg = ts::take_shared<ControlPlaneRegistry>(&scenario);
            let relay_reg = ts::take_shared<RelayRegistry>(&scenario);
            // Take the UNREGISTERED cap (most-recent), assert the abort.
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            room_manager::authorize_spill_relay(
                &net_reg, &mut manager, &cp_reg, &relay_reg, &cap,
                room_id(), id_of(RELAY_SPILL), ts::ctx(&mut scenario),
            );
            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(manager);
            ts::return_shared(cp_reg);
            ts::return_shared(relay_reg);
        };
        ts::end(scenario);
    }

    /// Sanity: the new event type exists (consumed so the import is non-dead).
    #[test]
    fun test_relay_spill_authorized_event_type_exists() {
        let _ = std::type_name::get<RelaySpillAuthorized>();
    }

    /// ONCHAIN-4 fold — update_room_rules with min_relay = 1 aborts on the governance
    /// floor E_INVALID_MIN (505). The const is module-private, so the literal 505 is
    /// used (Move requires a public const or a literal in #[expected_failure]).
    #[test]
    #[expected_failure(abort_code = 505)]
    fun test_update_room_rules_below_floor_aborts() {
        let mut scenario = h::setup_phase2();
        ts::next_tx(&mut scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut manager = ts::take_shared<RoomManager>(&scenario);

            // min_relay = 1 is below the >= 2 floor → aborts E_INVALID_MIN (505).
            room_manager::update_room_rules(&admin_cap, &mut manager, 1, 5, 4);

            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(manager);
        };
        ts::end(scenario);
    }
}
