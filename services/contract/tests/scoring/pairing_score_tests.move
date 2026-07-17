/// Unit tests for pairing_score module — pure scoring formula tests.
#[test_only]
module dvconf::pairing_score_tests {
    use dvconf::pairing_score;
    use dvconf::constants;

    // ── Test 1: Known inputs produce expected score ──
    #[test]
    fun test_compute_node_score_known_inputs() {
        // rtt=100ms, load=20, stake=1B, heartbeat_age=1 (fresh), region_match=true, history=5000
        // rtt_score = (500-100)*10000/500 = 8000
        // load_score = (100-20)*10000/100 = 8000
        // stake_score = 1_000_000_000 * 10000 / 5_000_000_000 = 2000
        // liveness_score = 10000 (fresh)
        // region_score = 10000
        // history_score = 5000
        // weighted = 8000*3000 + 8000*2500 + 2000*1500 + 10000*1000 + 10000*1000 + 5000*1000
        //          = 24_000_000 + 20_000_000 + 3_000_000 + 10_000_000 + 10_000_000 + 5_000_000
        //          = 72_000_000
        // score = 72_000_000 / 10_000 = 7200
        let score = pairing_score::compute_node_score(100, 20, 1_000_000_000, 1, true, 5000);
        assert!(score == 7200, 0);
    }

    // ── Test 2: Max RTT → rtt_score = 0 ──
    #[test]
    fun test_max_rtt_gives_zero_rtt_score() {
        // rtt=500 (max), everything else perfect
        // rtt_score = (500-500)*10000/500 = 0
        // load_score = (100-0)*10000/100 = 10000
        // stake_score = 5B*10000/5B = 10000
        // liveness = 10000, region = 10000, history = 10000
        // weighted = 0*3000 + 10000*2500 + 10000*1500 + 10000*1000 + 10000*1000 + 10000*1000
        //          = 0 + 25_000_000 + 15_000_000 + 10_000_000 + 10_000_000 + 10_000_000
        //          = 70_000_000
        // score = 7000
        let score = pairing_score::compute_node_score(500, 0, 5_000_000_000, 0, true, 10000);
        assert!(score == 7000, 0);
    }

    // ── Test 3: Zero stake → stake_score = 0 ──
    #[test]
    fun test_zero_stake_gives_zero_stake_score() {
        // Everything perfect except stake=0
        // rtt_score = 10000, load_score = 10000, stake_score = 0
        // liveness = 10000, region = 10000, history = 10000
        // weighted = 10000*3000 + 10000*2500 + 0*1500 + 10000*1000 + 10000*1000 + 10000*1000
        //          = 30_000_000 + 25_000_000 + 0 + 10_000_000 + 10_000_000 + 10_000_000
        //          = 85_000_000
        // score = 8500
        let score = pairing_score::compute_node_score(0, 0, 0, 0, true, 10000);
        assert!(score == 8500, 0);
    }

    // ── Test 4: Stale heartbeat → liveness = 5000 ──
    #[test]
    fun test_stale_heartbeat_half_liveness() {
        // heartbeat_age=5 (>= FRESH=3, < STALE=7) → liveness = 5000
        // All else perfect: rtt=0, load=0, stake=5B, region=true, history=10000
        // weighted = 10000*3000 + 10000*2500 + 10000*1500 + 5000*1000 + 10000*1000 + 10000*1000
        //          = 30M + 25M + 15M + 5M + 10M + 10M = 95M
        // score = 9500
        let score = pairing_score::compute_node_score(0, 0, 5_000_000_000, 5, true, 10000);
        assert!(score == 9500, 0);
    }

    // ── Test 5: Dead heartbeat → liveness = 0 ──
    #[test]
    fun test_dead_heartbeat_zero_liveness() {
        // heartbeat_age=10 (>= STALE=7) → liveness = 0
        // All else perfect
        // weighted = 10000*3000 + 10000*2500 + 10000*1500 + 0*1000 + 10000*1000 + 10000*1000
        //          = 30M + 25M + 15M + 0 + 10M + 10M = 90M
        // score = 9000
        let score = pairing_score::compute_node_score(0, 0, 5_000_000_000, 10, true, 10000);
        assert!(score == 9000, 0);
    }

    // ── Test 6: Region match vs no match ──
    #[test]
    fun test_region_match_vs_no_match() {
        let score_match = pairing_score::compute_node_score(0, 0, 5_000_000_000, 0, true, 10000);
        let score_no_match = pairing_score::compute_node_score(0, 0, 5_000_000_000, 0, false, 10000);
        // Difference should be exactly W_REGION * BASIS / BASIS = W_REGION = 1000
        // region contributes 10000 * 1000 / 10000 = 1000 when matched, 0 when not
        assert!(score_match - score_no_match == 1000, 0);
    }

    // ── Test 7: Average of multiple scores ──
    #[test]
    fun test_compute_pairing_score_averages() {
        let mut scores = vector::empty<u64>();
        scores.push_back(8000);
        scores.push_back(6000);
        scores.push_back(4000);
        // average = 18000 / 3 = 6000
        let avg = pairing_score::compute_pairing_score(&scores);
        assert!(avg == 6000, 0);
    }

    // ── Test 7b: Empty vector returns 0 ──
    #[test]
    fun test_compute_pairing_score_empty() {
        let scores = vector::empty<u64>();
        let avg = pairing_score::compute_pairing_score(&scores);
        assert!(avg == 0, 0);
    }

    // ── Test 8: required_validators scaling + cap (post-ADR-0006 migration) ──
    #[test]
    fun test_required_validators_scaling_and_cap() {
        // min_validators = 4 (DEFAULT_MIN_VALIDATORS_PER_ROOM, ADR-0006: n = 3f+1, f=1)
        // ratio = 3 (PVR_VALIDATOR_RATIO)
        // max = 5 (PVR_MAX_VALIDATORS_PER_ROOM)

        // 0 participants: max(4, 0/3=0) = 4
        assert!(pairing_score::required_validators(0) == 4, 0);

        // 3 participants: max(4, 3/3=1) = 4
        assert!(pairing_score::required_validators(3) == 4, 1);

        // 6 participants: max(4, 6/3=2) = 4
        assert!(pairing_score::required_validators(6) == 4, 2);

        // 9 participants: max(4, 9/3=3) = 4
        assert!(pairing_score::required_validators(9) == 4, 3);

        // 12 participants: max(4, 12/3=4) = 4
        assert!(pairing_score::required_validators(12) == 4, 4);

        // 15 participants: max(4, 15/3=5) = 5 (at cap)
        assert!(pairing_score::required_validators(15) == 5, 5);

        // 30 participants: max(4, 30/3=10) → capped at 5
        assert!(pairing_score::required_validators(30) == 5, 6);
    }

    // ── Test: RTT beyond max is clamped ──
    #[test]
    fun test_rtt_beyond_max_clamped() {
        // rtt=1000 > max=500 → clamped to 500 → rtt_score = 0
        let score_max = pairing_score::compute_node_score(500, 0, 0, 0, true, 5000);
        let score_over = pairing_score::compute_node_score(1000, 0, 0, 0, true, 5000);
        assert!(score_max == score_over, 0);
    }

    // ── Test: Perfect node gets maximum score ──
    #[test]
    fun test_perfect_node_max_score() {
        // All perfect: rtt=0, load=0, stake>=cap, fresh heartbeat, region match, history=10000
        let score = pairing_score::compute_node_score(0, 0, 5_000_000_000, 0, true, 10000);
        // All sub-scores = 10000
        // weighted = 10000*(3000+2500+1500+1000+1000+1000) = 10000*10000 = 100_000_000
        // score = 100_000_000 / 10_000 = 10000
        assert!(score == 10000, 0);
    }
}
