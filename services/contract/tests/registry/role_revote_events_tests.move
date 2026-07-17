/// F47 Phase 1.6 — REQ-RV-007 verification: the two role-revote events
/// (`RoleTransitioned` in `dvconf::registration`, `RevoteEligibleMarked` in
/// `dvconf::role_voting`) are validated here as a unit. Both are already WIRED
/// and emitting (RevoteEligibleMarked since Phase 1.2's 3 mark entries;
/// RoleTransitioned since Phase 1.5's apply_voted_role) — this phase locks their
/// schema + wire layout against future drift for W2/W3/F62 consumers (ADR-0008).
///
/// FRAMEWORK CONSTRAINT (why these tests look the way they do):
///   The Sui Move VM test framework (`sui::test_scenario`) can only COUNT user
///   events (`num_user_events`); it cannot DECODE an emitted event's payload in
///   the VM (`take_events<T>` lives in the Rust/TS SDK, not in Move tests). So
///   ROADMAP Phase 1.6's done-criteria are met by the only mechanisms the VM
///   actually supports:
///     (2) "assert each schema field"  -> a compile-time field-naming PIN: the
///         `new_*_for_testing` constructors below name every field by hand, so a
///         field RENAME or REMOVAL fails THIS build before it can ship — exactly
///         the ADR-0008 lock ("no field rename post-Phase 5"). A pure field
///         REORDER keeps the names so it still compiles; that drift is instead
///         caught at runtime by criterion (3)'s BCS peel below (the two layers
///         are complementary, not redundant).
///     (3) "BCS round-trip"            -> construct + `bcs::to_bytes` + peel back,
///         asserting the exact byte layout an off-chain indexer decodes.
///     (1) "emission count"            -> `num_user_events` delta.
///
/// Coverage (3 tests) + RTM mapping to ROADMAP done-criteria:
///   RV-EVT-01: RoleTransitioned     -> criteria (2)+(3): schema-lock construct +
///              BCS 34-byte layout {ID:32, old_role:u8, new_role:u8}, field order
///              verified by sequential peel.
///   RV-EVT-02: RevoteEligibleMarked -> criteria (2)+(3): schema-lock construct +
///              BCS 42-byte layout {ID:32, reason:u8, current_role:u8, marked_at:u64}.
///   RV-EVT-03: RevoteEligibleMarked -> criterion (1): a mark_revote_eligible_*
///              entry fires exactly 1 user event.
///
/// NOT-DUPLICATED (no silent cap): RoleTransitioned's emission COUNT is already
/// asserted by `registration_apply_voted_role_tests`:
///   - APPLY-01 (role change)    -> 2 user events (RoleApplied + RoleTransitioned)
///   - APPLY-02 (same-role apply)-> 1 user event  (RoleApplied only; RoleTransitioned absent)
/// Re-deriving it here would mean duplicating the 9-arg apply scaffolding for zero
/// new signal, so this file cross-references it instead.
///
/// NOT-VM-ASSERTABLE (code-review verified): the per-entry `reason` value mapping
/// (1=IDLE / 2=COMPOSITION_SHIFT / 3=MINER_REQUEST) is a literal in each emit call
/// (role_voting.move) and cannot be read off the live event in-VM; the `reason`
/// field itself is schema-locked by RV-EVT-02, and each entry's success path is
/// covered by `role_voting_mark_tests` RV-MARK-01/02/03.
#[test_only]
module dvconf::role_revote_events_tests {
    use sui::test_scenario::{Self as ts};
    use sui::bcs;
    use dvconf::registration;
    use dvconf::role_voting::{Self, RoleVoteBox};
    use dvconf::test_helpers::{Self as h};
    use dvconf::constants;
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::miner_store::MinerStore;
    use dvconf::caps::MinerCap;

    // ── Test fixtures ────────────────────────────────────────────────────
    const MINER: address = @0xA1;

    // Sample IDs/values for the pure schema + BCS tests (no chain needed).
    fun sample_miner_id(): ID { object::id_from_address(@0xBEEF) }

    // ══════════════════════════════════════════════════════════════════════
    // RV-EVT-01: RoleTransitioned — schema-lock construct + BCS wire layout.
    //   done-criteria (2) field schema + (3) BCS round-trip.
    //   Constructing via the named-field constructor is the compile-time rename
    //   lock; the sequential peel asserts both exact byte length (34) and field
    //   ORDER {miner_id:ID(32), old_role:u8, new_role:u8} an indexer decodes.
    // ══════════════════════════════════════════════════════════════════════
    #[test]
    fun test_role_transitioned_schema_and_bcs_layout() {
        let old_role = constants::role_relay();     // 1
        let new_role = constants::role_validator();  // 2

        // schema-lock: this line names every field — rename/reorder breaks build.
        let ev = registration::new_role_transitioned_for_testing(
            sample_miner_id(), old_role, new_role,
        );

        let bytes = bcs::to_bytes(&ev);
        // {ID:32, old_role:u8, new_role:u8} = 34 bytes, no length prefix.
        assert!(vector::length(&bytes) == 34, 0);

        // BCS round-trip: peel in declaration order, assert values survive.
        let mut reader = bcs::new(bytes);
        let id_back = bcs::peel_address(&mut reader);
        let old_back = bcs::peel_u8(&mut reader);
        let new_back = bcs::peel_u8(&mut reader);

        assert!(id_back == @0xBEEF, 1);
        assert!(old_back == old_role, 2);
        assert!(new_back == new_role, 3);
        assert!(old_back != new_back, 4); // sanity: a real transition
    }

    // ══════════════════════════════════════════════════════════════════════
    // RV-EVT-02: RevoteEligibleMarked — schema-lock construct + BCS wire layout.
    //   done-criteria (2) field schema + (3) BCS round-trip.
    //   {miner_id:ID(32), reason:u8, current_role:u8, marked_at:u64} = 42 bytes.
    // ══════════════════════════════════════════════════════════════════════
    #[test]
    fun test_revote_eligible_marked_schema_and_bcs_layout() {
        let reason = 3u8;                            // 3 = MINER_REQUEST
        let current_role = constants::role_relay();  // 1
        let marked_at = 12_345u64;

        // schema-lock: names every field — rename/reorder breaks build.
        let ev = role_voting::new_revote_eligible_marked_for_testing(
            sample_miner_id(), reason, current_role, marked_at,
        );

        let bytes = bcs::to_bytes(&ev);
        // {ID:32, reason:u8, current_role:u8, marked_at:u64} = 42 bytes.
        assert!(vector::length(&bytes) == 42, 0);

        // BCS round-trip: peel in declaration order.
        let mut reader = bcs::new(bytes);
        let id_back = bcs::peel_address(&mut reader);
        let reason_back = bcs::peel_u8(&mut reader);
        let role_back = bcs::peel_u8(&mut reader);
        let marked_back = bcs::peel_u64(&mut reader);

        assert!(id_back == @0xBEEF, 1);
        assert!(reason_back == reason, 2);
        assert!(role_back == current_role, 3);
        assert!(marked_back == marked_at, 4);
    }

    // ══════════════════════════════════════════════════════════════════════
    // RV-EVT-03: RevoteEligibleMarked emission — a mark entry fires exactly 1
    //   user event. done-criterion (1) emission count. Uses the lightest mark
    //   path (miner_request: no epoch advance, no surplus composition needed).
    //   Pattern mirrors capability_events_tests: do the mark in one tx, then
    //   next_tx closes it and returns its effects to count.
    // ══════════════════════════════════════════════════════════════════════
    #[test]
    fun test_revote_eligible_marked_emits_exactly_one_event() {
        let mut scenario = h::setup_phase2();

        // Register a relay miner (owner = MINER) → receives a MinerCap.
        h::do_register_with_role(&mut scenario, MINER, h::relay_stake(), constants::role_relay());

        // Initialize the RoleVoteBox.
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        // Open a fresh tx and perform the mark in it.
        ts::next_tx(&mut scenario, MINER);
        {
            let net_reg = ts::take_shared<NetworkRegistry>(&scenario);
            let mut vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            let store = ts::take_shared<MinerStore>(&scenario);
            let cap = ts::take_from_sender<MinerCap>(&scenario);

            role_voting::mark_revote_eligible_miner_request(
                &net_reg,
                &mut vote_box,
                &store,
                &cap,
                ts::ctx(&mut scenario),
            );

            ts::return_to_sender(&scenario, cap);
            ts::return_shared(net_reg);
            ts::return_shared(vote_box);
            ts::return_shared(store);
        };

        // Close the mark tx and read its effects: exactly 1 RevoteEligibleMarked.
        let effects = ts::next_tx(&mut scenario, MINER);
        assert!(ts::num_user_events(&effects) == 1, 0);

        ts::end(scenario);
    }
}
