/// Pure scoring module for PVR (Propose-Verify-Reward) consensus.
///
/// All functions are pure math — no shared objects, no state mutations.
/// Only imports dvconf::constants. Returns scores in basis points (0-10000).
module dvconf::pairing_score {
    use dvconf::constants;

    // ── Errors (700+) ──
    const E_NODE_NOT_ACTIVE: u64 = 700;

    /// Compute score for a single node.
    /// All inputs are raw on-chain values. Returns 0-10000 (basis points).
    ///
    /// Formula:
    ///   rtt_score      = (MAX_RTT - min(rtt, MAX_RTT)) * BASIS / MAX_RTT
    ///   load_score     = (MAX_LOAD - min(load, MAX_LOAD)) * BASIS / MAX_LOAD
    ///   stake_score    = min(stake, STAKE_CAP) * BASIS / STAKE_CAP
    ///   liveness_score = heartbeat_age < FRESH: 10000, < STALE: 5000, else: 0
    ///   region_score   = match: 10000, else: 0
    ///   history_score  = raw value (0-10000)
    ///
    ///   score = (rtt * W_RTT + load * W_LOAD + stake * W_STAKE
    ///          + liveness * W_LIVENESS + region * W_REGION + history * W_HISTORY) / BASIS
    public fun compute_node_score(
        rtt: u64,
        load: u64,
        stake: u64,
        heartbeat_age: u64,
        region_match: bool,
        history_score: u64,
    ): u64 {
        let basis = constants::basis_points(); // 10_000
        let max_rtt = constants::pvr_max_rtt();
        let max_load = constants::pvr_max_load();
        let stake_cap = constants::pvr_stake_cap();

        // RTT score: lower is better
        let clamped_rtt = if (rtt < max_rtt) { rtt } else { max_rtt };
        let rtt_score = (max_rtt - clamped_rtt) * basis / max_rtt;

        // Load score: lower is better
        let clamped_load = if (load < max_load) { load } else { max_load };
        let load_score = (max_load - clamped_load) * basis / max_load;

        // Stake score: higher is better, capped
        let clamped_stake = if (stake < stake_cap) { stake } else { stake_cap };
        let stake_score = clamped_stake * basis / stake_cap;

        // Liveness score: based on heartbeat age in epochs
        let liveness_score = if (heartbeat_age < constants::pvr_heartbeat_fresh()) {
            basis // 10_000 = full score
        } else if (heartbeat_age < constants::pvr_heartbeat_stale()) {
            5_000 // half score
        } else {
            0
        };

        // Region score: binary match
        let region_score = if (region_match) { basis } else { 0 };

        // Weighted sum divided by basis points
        let weighted_sum =
            rtt_score * constants::pvr_w_rtt()
            + load_score * constants::pvr_w_load()
            + stake_score * constants::pvr_w_stake()
            + liveness_score * constants::pvr_w_liveness()
            + region_score * constants::pvr_w_region()
            + history_score * constants::pvr_w_history();

        weighted_sum / basis
    }

    /// Compute aggregate pairing score = average of all node scores.
    /// Returns 0 if the vector is empty (defensive).
    public fun compute_pairing_score(node_scores: &vector<u64>): u64 {
        let len = vector::length(node_scores);
        if (len == 0) {
            return 0
        };

        let mut total: u64 = 0;
        let mut i = 0;
        while (i < len) {
            total = total + *vector::borrow(node_scores, i);
            i = i + 1;
        };

        total / len
    }

    /// Compute required validator count from expected_participants.
    /// Formula: max(MIN_VALIDATORS_PER_ROOM, expected / RATIO), capped at MAX.
    public fun required_validators(expected_participants: u64): u64 {
        let min_val = constants::default_min_validators_per_room(); // 4 (ADR-0006)
        let ratio = constants::pvr_validator_ratio();               // 3
        let max_val = constants::pvr_max_validators_per_room();     // 5

        let scaled = expected_participants / ratio;
        let result = if (scaled > min_val) { scaled } else { min_val };
        if (result > max_val) { max_val } else { result }
    }

    /// Error code accessor for liveness check failures.
    public fun e_node_not_active(): u64 { E_NODE_NOT_ACTIVE }
}
