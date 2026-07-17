/// TURN credential issuance tests — verifies issue_turn_credential +
/// provision_turn_secret entries.
///
/// Module under test: dvconf::turn_credential (ADR-0005).
///
/// Coverage:
///   TURN-01: TTL bound constants exposed correctly
///   TURN-02: issue_turn_credential happy path (no abort)
///   TURN-03: provision_turn_secret happy path (no abort)
///   TURN-04: TTL boundaries — exact min + exact max accepted
///   TURN-05: Paused guard — issue rejected
///   TURN-06: Paused guard — provision rejected
///   TURN-07: TTL out-of-bounds — below min rejected
///   TURN-08: TTL out-of-bounds — above max rejected
///   TURN-09: Empty credential hash rejected
#[test_only]
module dvconf::turn_credential_tests {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::turn_credential;

    // ── Test addresses ──
    const CP_OP: address  = @0xC1;
    const CP_ID: address  = @0xA6;
    const MINER:  address = @0xAA;

    // ── ADR-0005 constants (mirror module) ──
    const TTL_MIN_SEC: u64     =   900;  // 15 min
    const TTL_DEFAULT_SEC: u64 =  1_200; // 20 min (ADR-0005 default)
    const TTL_MAX_SEC: u64     =  1_800; // 30 min
    const SECRET_ID:   u64     =     42;

    fun id_from_addr(addr: address): ID {
        object::id_from_address(addr)
    }

    /// Setup: network_registry + miner_store initialised, CP_OP holds a
    /// ControlPlaneCap bound to CP_ID.
    fun setup_with_cap(): ts::Scenario {
        let mut scenario = h::setup();

        ts::next_tx(&mut scenario, CP_OP);
        {
            let cap = caps::new_cp_cap(id_from_addr(CP_ID), ts::ctx(&mut scenario));
            transfer::public_transfer(cap, CP_OP);
        };

        scenario
    }

    /// Pause the network using AdminCap held by ADMIN.
    fun pause_network(scenario: &mut ts::Scenario) {
        ts::next_tx(scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(scenario);
            let mut net_reg = ts::take_shared<NetworkRegistry>(scenario);
            network_registry::set_paused(&admin_cap, &mut net_reg, true);
            ts::return_to_sender(scenario, admin_cap);
            ts::return_shared(net_reg);
        };
    }

    /// Convenience: call issue_turn_credential as CP_OP with given ttl_sec
    /// and credential_hash. Caller controls Scenario state.
    fun do_issue(scenario: &mut ts::Scenario, ttl_sec: u64, credential_hash: vector<u8>) {
        ts::next_tx(scenario, CP_OP);
        {
            let net = ts::take_shared<NetworkRegistry>(scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(scenario);
            turn_credential::issue_turn_credential(
                &net,
                &cap,
                id_from_addr(MINER),
                ttl_sec,
                credential_hash,
                SECRET_ID,
                ts::ctx(scenario),
            );
            ts::return_to_sender(scenario, cap);
            ts::return_shared(net);
        };
    }

    /// Convenience: call provision_turn_secret as CP_OP.
    fun do_provision(scenario: &mut ts::Scenario, secret_id: u64) {
        ts::next_tx(scenario, CP_OP);
        {
            let net = ts::take_shared<NetworkRegistry>(scenario);
            let cap = ts::take_from_sender<ControlPlaneCap>(scenario);
            turn_credential::provision_turn_secret(
                &net,
                &cap,
                secret_id,
                ts::ctx(scenario),
            );
            ts::return_to_sender(scenario, cap);
            ts::return_shared(net);
        };
    }

    /// Convenience: call emergency_rotate_relay_secret as ADMIN (AdminCap-gated, F8).
    fun do_emergency_rotate(
        scenario:      &mut ts::Scenario,
        old_secret_id: u64,
        new_secret_id: u64,
        reason:        u8,
    ) {
        ts::next_tx(scenario, h::admin());
        {
            let admin_cap = ts::take_from_sender<AdminCap>(scenario);
            let net = ts::take_shared<NetworkRegistry>(scenario);
            turn_credential::emergency_rotate_relay_secret(
                &admin_cap,
                &net,
                id_from_addr(CP_ID),
                old_secret_id,
                new_secret_id,
                reason,
                ts::ctx(scenario),
            );
            ts::return_to_sender(scenario, admin_cap);
            ts::return_shared(net);
        };
    }

    // ══════════════════════════════════════════════════════════
    // TURN-01: TTL constants exposed
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_ttl_constants() {
        assert!(turn_credential::ttl_min_sec()     == TTL_MIN_SEC,     0);
        assert!(turn_credential::ttl_default_sec() == TTL_DEFAULT_SEC, 1);
        assert!(turn_credential::ttl_max_sec()     == TTL_MAX_SEC,     2);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-02: issue_turn_credential happy path
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_issue_happy_path() {
        let mut scenario = setup_with_cap();
        do_issue(&mut scenario, TTL_DEFAULT_SEC, b"hmac-credential-hash");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-03: provision_turn_secret happy path
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_provision_happy_path() {
        let mut scenario = setup_with_cap();
        do_provision(&mut scenario, SECRET_ID);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-04a: TTL exact min boundary accepted
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_issue_at_ttl_min_boundary_ok() {
        let mut scenario = setup_with_cap();
        do_issue(&mut scenario, TTL_MIN_SEC, b"h");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-04b: TTL exact max boundary accepted
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_issue_at_ttl_max_boundary_ok() {
        let mut scenario = setup_with_cap();
        do_issue(&mut scenario, TTL_MAX_SEC, b"h");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-05: Paused guard rejects issue (E_PAUSED = 800)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 800)]
    fun test_issue_aborts_when_paused() {
        let mut scenario = setup_with_cap();
        pause_network(&mut scenario);
        do_issue(&mut scenario, TTL_DEFAULT_SEC, b"h");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-06: Paused guard rejects provision (E_PAUSED = 800)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 800)]
    fun test_provision_aborts_when_paused() {
        let mut scenario = setup_with_cap();
        pause_network(&mut scenario);
        do_provision(&mut scenario, SECRET_ID);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-07: TTL below min rejected (E_TTL_OUT_OF_BOUNDS = 801)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 801)]
    fun test_issue_aborts_below_ttl_min() {
        let mut scenario = setup_with_cap();
        do_issue(&mut scenario, TTL_MIN_SEC - 1, b"h");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-08: TTL above max rejected (E_TTL_OUT_OF_BOUNDS = 801)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 801)]
    fun test_issue_aborts_above_ttl_max() {
        let mut scenario = setup_with_cap();
        do_issue(&mut scenario, TTL_MAX_SEC + 1, b"h");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-09: Empty credential_hash rejected (E_EMPTY_CREDENTIAL_HASH = 802)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 802)]
    fun test_issue_aborts_empty_hash() {
        let mut scenario = setup_with_cap();
        do_issue(&mut scenario, TTL_DEFAULT_SEC, b"");
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-10: emergency_rotate_relay_secret happy path (F8, REQ-CRR-004)
    //          AdminCap-gated emergency rotation emits SecretRotated.
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_emergency_rotate_happy_path() {
        let mut scenario = setup_with_cap();
        do_emergency_rotate(&mut scenario, 1, 2, 0);  // old=1 new=2 reason=0 (leakage)
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-11: Paused guard rejects emergency rotate (E_PAUSED = 800)
    //          SoT invariant — paused-ABORT kept (CONTEXT D6).
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 800)]
    fun test_emergency_rotate_aborts_when_paused() {
        let mut scenario = setup_with_cap();
        pause_network(&mut scenario);
        do_emergency_rotate(&mut scenario, 1, 2, 0);
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-12: same old/new secret_id rejected (E_SAME_SECRET_ID = 804)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 804)]
    fun test_emergency_rotate_rejects_same_secret_id() {
        let mut scenario = setup_with_cap();
        do_emergency_rotate(&mut scenario, 7, 7, 0);  // old == new
        ts::end(scenario);
    }

    // ══════════════════════════════════════════════════════════
    // TURN-13: reason out of enum (>2) rejected (E_INVALID_ROTATION_REASON = 803)
    // ══════════════════════════════════════════════════════════

    #[test]
    #[expected_failure(abort_code = 803)]
    fun test_emergency_rotate_rejects_bad_reason() {
        let mut scenario = setup_with_cap();
        do_emergency_rotate(&mut scenario, 1, 2, 3);  // reason 3 invalid (enum 0..2)
        ts::end(scenario);
    }
}
