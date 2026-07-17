/// F47 Phase 1.1 — REQ-RV-001 verification: RoleVoteBox post-init state
/// asserts the two new fields `revote_eligible` (VecSet<ID>) and
/// `revote_eligible_since` (Table<ID, u64>) are empty after `init`.
///
/// Coverage:
///   RV-INIT-01: Both revote fields are empty post-init
#[test_only]
module dvconf::role_voting_init_test {
    use sui::test_scenario::{Self as ts};
    use dvconf::test_helpers::{Self as h};
    use dvconf::role_voting::{Self, RoleVoteBox};

    // ══════════════════════════════════════════════════════════
    // RV-INIT-01: revote_eligible + revote_eligible_since empty post-init
    // ══════════════════════════════════════════════════════════

    #[test]
    fun test_revote_fields_initialized() {
        let mut scenario = h::setup_phase2();

        // Initialize RoleVoteBox via the production init path
        ts::next_tx(&mut scenario, h::admin());
        {
            role_voting::init_for_testing(ts::ctx(&mut scenario));
        };

        // Inspect post-init state — both new fields must be empty
        ts::next_tx(&mut scenario, h::admin());
        {
            let vote_box = ts::take_shared<RoleVoteBox>(&scenario);
            assert!(role_voting::revote_eligible_is_empty(&vote_box), 0);
            assert!(role_voting::revote_eligible_since_is_empty(&vote_box), 1);
            ts::return_shared(vote_box);
        };

        ts::end(scenario);
    }
}
