/// Node Health — M2a Phase 1 Move tests (REQ-DOH-013).
///
/// TDD:  RED written FIRST — references `node_health::report_node_degradation`
///       before `sources/registry/node_health.move` exists (unbound-module
///       compile error). GREEN after the P1 skeleton lands: module decl + the
///       four error consts (670-673) + the frozen `NodeDegraded` struct +
///       the `report_node_degradation` skeleton entry.
///
/// DOH-013 (level-0/1/2 self-degradation model): P1 freezes the wire-contract
///         symbol + the `NodeDegraded` event shape. Asserts + emit land in
///         P2 (generic entry) / P3 (CP variant).
#[test_only]
module dvconf::node_health_tests {
    use sui::test_scenario::{Self as ts};
    use sui::bcs;
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap, ControlPlaneCap};
    use dvconf::node_health;

    const ADMIN:       address = @0xAD;
    const RELAY_1:     address = @0xB1;
    const VALIDATOR_1: address = @0xB2;
    const CP_1:        address = @0xB3;
    const SIGNALING_1: address = @0xB4;
    const OUTSIDER:    address = @0xBEEF;

    /// DOH-013 (P1 skeleton): `report_node_degradation` exists with the FROZEN
    /// signature `(&NetworkRegistry, &MinerCap, operator, level, &TxContext)`.
    /// The call compiling IS the assertion (symbol-exists). The P1 body is a
    /// no-op; this happy path is forward-compatible with P2's asserts — relay
    /// cap role=2 (in {1,2,4}), operator == sender, level=1 (<= 2), not paused.
    #[test]
    fun test_doh_013_report_node_degradation_symbol_exists() {
        let mut scenario = ts::begin(ADMIN);
        {
            network_registry::init_for_testing(ts::ctx(&mut scenario));
        };
        ts::next_tx(&mut scenario, RELAY_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap: MinerCap = caps::new_miner_cap(
                object::id_from_address(RELAY_1),
                constants::role_relay(),
                ts::ctx(&mut scenario),
            );

            node_health::report_node_degradation(
                &net_reg,
                &cap,
                RELAY_1, // operator == ctx.sender()
                1,       // level: degraded
                ts::ctx(&mut scenario),
            );

            transfer::public_transfer(cap, RELAY_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // P2 (REQ-DOH-013/014/015) — report_node_degradation BODY
    //
    // node_type is NEVER an argument: it is always caps::miner_cap_role(cap), so
    // a node cannot forge a foreign node_type. These tests prove (a) the role
    // gate {1=validator, 2=relay, 4=signaling} accepts each daemon role and emits
    // exactly one NodeDegraded, and (b) the 4 per-assert aborts in the canonical
    // order PAUSED(672) -> NOT_OPERATOR(673) -> INVALID_NODE_TYPE(671) ->
    // INVALID_LEVEL(670). Each abort test violates EXACTLY ONE condition.
    // ══════════════════════════════════════════════════════════

    /// Fresh network registry (un-paused), scenario left at ADMIN tx-0.
    fun new_registry_scenario(): ts::Scenario {
        let mut scenario = ts::begin(ADMIN);
        {
            network_registry::init_for_testing(ts::ctx(&mut scenario));
        };
        scenario
    }

    /// Drive one VALID report (operator == sender, level 1, not paused) for a
    /// given cap `role`; assert exactly one NodeDegraded fired. node_type is
    /// derived from the cap role, so this proves DOH-014 for that daemon type.
    fun assert_report_emits_one(role: u8, sender: address) {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, sender);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_miner_cap(
                object::id_from_address(sender), role, ts::ctx(&mut scenario),
            );
            node_health::report_node_degradation(
                &net_reg, &cap, sender, 1, ts::ctx(&mut scenario),
            );
            transfer::public_transfer(cap, sender);
            ts::return_shared(net_reg);
        };
        let effects = ts::next_tx(&mut scenario, sender);
        assert!(ts::num_user_events(&effects) == 1, 0);
        ts::end(scenario);
    }

    #[test] fun test_doh_014_emits_for_relay()     { assert_report_emits_one(constants::role_relay(),     RELAY_1); }
    #[test] fun test_doh_014_emits_for_validator() { assert_report_emits_one(constants::role_validator(), VALIDATOR_1); }
    #[test] fun test_doh_014_emits_for_signaling() { assert_report_emits_one(constants::role_signaling(), SIGNALING_1); }

    /// PAUSED [672]: network paused, everything else valid.
    #[test]
    #[expected_failure(abort_code = node_health::E_PAUSED)]
    fun test_doh_015_abort_when_paused() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, ADMIN);
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };
        ts::next_tx(&mut scenario, RELAY_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_miner_cap(
                object::id_from_address(RELAY_1), constants::role_relay(), ts::ctx(&mut scenario),
            );
            node_health::report_node_degradation(&net_reg, &cap, RELAY_1, 1, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, RELAY_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    /// NOT_OPERATOR [673]: operator (OUTSIDER) != ctx.sender() (RELAY_1).
    #[test]
    #[expected_failure(abort_code = node_health::E_NOT_OPERATOR)]
    fun test_doh_015_abort_operator_mismatch() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, RELAY_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_miner_cap(
                object::id_from_address(RELAY_1), constants::role_relay(), ts::ctx(&mut scenario),
            );
            node_health::report_node_degradation(&net_reg, &cap, OUTSIDER, 1, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, RELAY_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    /// INVALID_NODE_TYPE [671]: role_cp()=3 is NOT in {1,2,4} — a CP must use
    /// report_cp_degradation (P3), not the generic entry.
    #[test]
    #[expected_failure(abort_code = node_health::E_INVALID_NODE_TYPE)]
    fun test_doh_014_abort_cp_role_rejected() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, RELAY_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_miner_cap(
                object::id_from_address(RELAY_1), constants::role_cp(), ts::ctx(&mut scenario),
            );
            node_health::report_node_degradation(&net_reg, &cap, RELAY_1, 1, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, RELAY_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    /// INVALID_LEVEL [670]: level 3 > 2.
    #[test]
    #[expected_failure(abort_code = node_health::E_INVALID_LEVEL)]
    fun test_doh_013_abort_level_out_of_range() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, RELAY_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_miner_cap(
                object::id_from_address(RELAY_1), constants::role_relay(), ts::ctx(&mut scenario),
            );
            node_health::report_node_degradation(&net_reg, &cap, RELAY_1, 3, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, RELAY_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // P3 (REQ-DOH-013/014/015) — report_cp_degradation CP variant
    //
    // The ControlPlaneCap carries NO role byte, so node_type is HARDCODED to
    // role_cp()=3 (the cap TYPE itself is the CP authority proof). There is NO
    // role gate, so NO E_INVALID_NODE_TYPE(671) path — only the three asserts
    // PAUSED(672) -> NOT_OPERATOR(673) -> INVALID_LEVEL(670). The emitted
    // NodeDegraded shape is IDENTICAL to the generic entry's.
    // ══════════════════════════════════════════════════════════

    /// DOH-014 (P3 happy): a ControlPlaneCap reports node_type=3 (hardcoded
    /// role_cp(), never an arg) at level 2 and emits exactly one NodeDegraded.
    #[test]
    fun test_doh_014_emits_for_cp() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, CP_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_cp_cap(
                object::id_from_address(CP_1), ts::ctx(&mut scenario),
            );
            node_health::report_cp_degradation(
                &net_reg, &cap, CP_1, 2, ts::ctx(&mut scenario),
            );
            transfer::public_transfer(cap, CP_1);
            ts::return_shared(net_reg);
        };
        let effects = ts::next_tx(&mut scenario, CP_1);
        assert!(ts::num_user_events(&effects) == 1, 0);
        ts::end(scenario);
    }

    /// CP PAUSED [672]: network paused, everything else valid.
    #[test]
    #[expected_failure(abort_code = node_health::E_PAUSED)]
    fun test_doh_015_cp_abort_when_paused() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, ADMIN);
        {
            let admin_cap = ts::take_from_sender<AdminCap>(&scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(&scenario, admin_cap);
            ts::return_shared(net_reg);
        };
        ts::next_tx(&mut scenario, CP_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_cp_cap(object::id_from_address(CP_1), ts::ctx(&mut scenario));
            node_health::report_cp_degradation(&net_reg, &cap, CP_1, 1, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    /// CP NOT_OPERATOR [673]: operator (OUTSIDER) != ctx.sender() (CP_1).
    #[test]
    #[expected_failure(abort_code = node_health::E_NOT_OPERATOR)]
    fun test_doh_015_cp_abort_operator_mismatch() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, CP_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_cp_cap(object::id_from_address(CP_1), ts::ctx(&mut scenario));
            node_health::report_cp_degradation(&net_reg, &cap, OUTSIDER, 1, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    /// CP INVALID_LEVEL [670]: level 3 > 2. (No 671 path — CP has no role gate.)
    #[test]
    #[expected_failure(abort_code = node_health::E_INVALID_LEVEL)]
    fun test_doh_013_cp_abort_level_out_of_range() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, CP_1);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = caps::new_cp_cap(object::id_from_address(CP_1), ts::ctx(&mut scenario));
            node_health::report_cp_degradation(&net_reg, &cap, CP_1, 3, ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_1);
            ts::return_shared(net_reg);
        };
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // P4 (REQ-DOH-014) — closes DESIGN-CRITIQUE #8 (the authority residual).
    //
    // The cap's role IS the node_type proof and the cap's id IS the miner_id —
    // BOTH are DERIVED in the production emit (node_health.move:93-99 generic /
    // :121-127 cp), NEITHER is a function argument. So a validly-minted but
    // unregistered cap CAN emit a NodeDegraded, but it can ONLY ever carry that
    // cap's OWN miner_id. Every off-chain reactor (F60 SelfShutdownWatcher + the
    // two viz panels) self-filters by its OWN miner_id — exactly as they already
    // self-filter economic_layer::RelaySlashed by relay_miner_id — so a foreign
    // emit is DROPPED: the residual is bounded to self-noise and can never drive
    // a foreign slash/failover.
    //
    // VM constraint (see role_revote_events_tests header): the Move test VM cannot
    // DECODE a live-emitted event payload (`take_events<T>` is SDK-only). (a) below
    // therefore materializes the NodeDegraded via the #[test_only] named-field
    // constructor + peels the BCS wire bytes — the same mechanism
    // role_revote_events_tests uses to lock RoleTransitioned/RevoteEligibleMarked —
    // to read the miner_id key the off-chain self-filter reads, AND to lock the
    // frozen 74-byte wire layout the P5 single-owner TS mirror byte-mirrors.
    // (b) witnesses the emit-only property at runtime.
    // ══════════════════════════════════════════════════════════

    /// Models the off-chain consumer self-filter (F60 + viz): a node ACTS on a
    /// NodeDegraded only when the event's miner_id == its own; a foreign id is
    /// DROPPED. (Same self-filter shape the reactors use for RelaySlashed's
    /// relay_miner_id.)
    fun self_filter_drops(event_miner_id: address, my_miner_id: address): bool {
        event_miner_id != my_miner_id
    }

    /// DOH-014 (P4 / critique #8a): a foreign-miner_id NodeDegraded is IGNORED.
    /// Materializes the event an OUTSIDER's cap would produce (carrying its OWN id,
    /// because production derives miner_id from the cap — never an arg), peels the
    /// full FROZEN wire layout, and proves a victim (RELAY_1) self-filters it out.
    /// Doubles as the Move-side wire-layout lock the P5 TS mirror byte-mirrors.
    #[test]
    fun test_doh_014_foreign_miner_id_node_degraded_ignored() {
        // The event an outsider would emit carries the OUTSIDER's OWN cap id.
        let ev = node_health::new_node_degraded_for_testing(
            object::id_from_address(OUTSIDER), // miner_id = the reporter's OWN id
            constants::role_relay(),           // node_type 2 (in prod: derived from cap role)
            2,                                  // level
            OUTSIDER,                           // operator
            7,                                  // epoch
        );

        // FROZEN wire layout (P5 TS mirror byte-mirrors this):
        // {miner_id:ID(32), node_type:u8(1), level:u8(1), operator:address(32), epoch:u64(8)} = 74.
        let bytes = bcs::to_bytes(&ev);
        assert!(vector::length(&bytes) == 74, 0);
        let mut reader = bcs::new(bytes);
        let id_back    = bcs::peel_address(&mut reader); // miner_id — the self-filter key (field #1)
        let nt_back    = bcs::peel_u8(&mut reader);
        let lvl_back   = bcs::peel_u8(&mut reader);
        let op_back    = bcs::peel_address(&mut reader);
        let epoch_back = bcs::peel_u64(&mut reader);
        assert!(id_back    == OUTSIDER, 1);
        assert!(nt_back    == constants::role_relay(), 2);
        assert!(lvl_back   == 2, 3);
        assert!(op_back    == OUTSIDER, 4);
        assert!(epoch_back == 7, 5);

        // The victim (RELAY_1) self-filters on its OWN id → the foreign report is DROPPED.
        assert!(self_filter_drops(id_back, RELAY_1), 6);
        // The outsider would only ever act on its OWN self-noise.
        assert!(!self_filter_drops(id_back, OUTSIDER), 7);
    }

    /// DOH-014 (P4 / critique #8b): report_node_degradation is EMIT-ONLY.
    /// Both degraded entries take ONLY immutable refs (&NetworkRegistry, &MinerCap
    /// / &ControlPlaneCap) + value args and return () — the type system forbids
    /// mutating any shared/owned object (no &mut anywhere; a future &mut would fail
    /// to compile against every happy-path test in this file). Runtime witness: the
    /// report tx creates NO object, deletes NO object, and its SOLE effect is one
    /// event. (Cap minted in a PRIOR tx so its creation does not pollute these effects.)
    #[test]
    fun test_doh_014_report_node_degradation_is_emit_only() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, RELAY_1); // mint + park the cap (isolates its creation)
        {
            let cap = caps::new_miner_cap(
                object::id_from_address(RELAY_1), constants::role_relay(), ts::ctx(&mut scenario),
            );
            transfer::public_transfer(cap, RELAY_1);
        };
        ts::next_tx(&mut scenario, RELAY_1); // the report tx — only &-borrows
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);
            node_health::report_node_degradation(&net_reg, &cap, RELAY_1, 1, ts::ctx(&mut scenario));
            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
        };
        let effects = ts::next_tx(&mut scenario, RELAY_1);
        assert!(ts::num_user_events(&effects) == 1, 0);          // sole effect = the event
        assert!(vector::length(&ts::created(&effects)) == 0, 1); // no object minted
        assert!(vector::length(&ts::deleted(&effects)) == 0, 2); // no object burned
        ts::end(scenario);
    }

    /// DOH-014 (P4 / critique #8b): report_cp_degradation is likewise EMIT-ONLY.
    #[test]
    fun test_doh_014_report_cp_degradation_is_emit_only() {
        let mut scenario = new_registry_scenario();
        ts::next_tx(&mut scenario, CP_1); // mint + park the cap (isolates its creation)
        {
            let cap = caps::new_cp_cap(object::id_from_address(CP_1), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_1);
        };
        ts::next_tx(&mut scenario, CP_1); // the report tx — only &-borrows
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(&scenario);
            node_health::report_cp_degradation(&net_reg, &cap, CP_1, 2, ts::ctx(&mut scenario));
            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
        };
        let effects = ts::next_tx(&mut scenario, CP_1);
        assert!(ts::num_user_events(&effects) == 1, 0);
        assert!(vector::length(&ts::created(&effects)) == 0, 1);
        assert!(vector::length(&ts::deleted(&effects)) == 0, 2);
        ts::end(scenario);
    }
}
