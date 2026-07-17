module dvconf::network_registry {
    use dvconf::constants;

    // ── Errors ──
    const E_INVALID_WEIGHT: u64 = 100;
    const E_INVALID_THRESHOLD: u64 = 101;
    const E_INVALID_RATIO: u64 = 102;

    /// Governance capability — required for all config writes
    public struct AdminCap has key, store {
        id: UID,
    }

    /// Stake thresholds that determine role assignment
    public struct RoleThresholds has store, copy, drop {
        cp_threshold:        u64,   // default: 2_000_000_000 (2 DVCONF)
        relay_threshold:     u64,   // default: 1_000_000_000 (1 DVCONF)
        validator_threshold: u64,   // default:   500_000_000 (0.5 DVCONF)
        signaling_threshold: u64,  // default:   250_000_000 (0.25 DVCONF) — Phase 11
    }

    /// Relay scoring weights — basis points, must sum to 10_000
    public struct ScoringWeights has store, copy, drop {
        reputation:   u64,
        rtt:          u64,
        load:         u64,
        stake:        u64,
        region_match: u64,
    }

    /// Token distribution ratios — basis points, must sum to 10_000
    public struct RewardRatios has store, copy, drop {
        relay:         u64,
        validator:     u64,
        control_plane: u64,
    }

    /// The singleton shared config object
    public struct NetworkRegistry has key {
        id: UID,
        role_thresholds: RoleThresholds,
        scoring_weights: ScoringWeights,
        reward_ratios: RewardRatios,
        base_rate_per_mb: u64,
        min_validators_per_room: u64,
        min_relays_per_room: u64,
        min_cps_per_room: u64,
        cp_consensus_threshold_bps: u64,
        version: u64,
        paused: bool,
    }

    fun init(ctx: &mut TxContext) {
        let registry = NetworkRegistry {
            id: object::new(ctx),
            role_thresholds: RoleThresholds {
                cp_threshold:        constants::default_cp_threshold(),
                relay_threshold:     constants::default_relay_threshold(),
                validator_threshold: constants::default_validator_threshold(),
                signaling_threshold: constants::default_signaling_threshold(),
            },
            scoring_weights: ScoringWeights {
                reputation:   constants::default_w_reputation(),
                rtt:          constants::default_w_rtt(),
                load:         constants::default_w_load(),
                stake:        constants::default_w_stake(),
                region_match: constants::default_w_region_match(),
            },
            reward_ratios: RewardRatios {
                relay:         constants::default_ratio_relay(),
                validator:     constants::default_ratio_validator(),
                control_plane: constants::default_ratio_control_plane(),
            },
            base_rate_per_mb:           constants::default_base_rate_per_mb(),
            min_validators_per_room:    constants::default_min_validators_per_room(),
            min_relays_per_room:        constants::default_min_relays_per_room(),
            min_cps_per_room:           constants::default_min_cps_per_room(),
            cp_consensus_threshold_bps: constants::default_cp_consensus_threshold_bps(),
            version:                    constants::default_version(),
            paused:                   false,
        };

        let admin_cap = AdminCap { id: object::new(ctx) };

        transfer::share_object(registry);
        transfer::transfer(admin_cap, ctx.sender());
    }

    // ── Read accessors ──

    public fun role_thresholds(r: &NetworkRegistry): RoleThresholds   { r.role_thresholds }
    public fun scoring_weights(r: &NetworkRegistry): ScoringWeights   { r.scoring_weights }
    public fun reward_ratios(r: &NetworkRegistry): RewardRatios       { r.reward_ratios }
    public fun base_rate_per_mb(r: &NetworkRegistry): u64             { r.base_rate_per_mb }
    public fun min_cps_per_room(r: &NetworkRegistry): u64             { r.min_cps_per_room }
    public fun min_relays_per_room(r: &NetworkRegistry): u64          { r.min_relays_per_room }
    public fun min_validators_per_room(r: &NetworkRegistry): u64      { r.min_validators_per_room }
    public fun cp_consensus_threshold_bps(r: &NetworkRegistry): u64   { r.cp_consensus_threshold_bps }
    public fun is_paused(r: &NetworkRegistry): bool                   { r.paused }
    public fun version(r: &NetworkRegistry): u64                      { r.version }

    public fun cp_threshold(t: &RoleThresholds): u64        { t.cp_threshold }
    public fun relay_threshold(t: &RoleThresholds): u64     { t.relay_threshold }
    public fun validator_threshold(t: &RoleThresholds): u64 { t.validator_threshold }
    public fun signaling_threshold(t: &RoleThresholds): u64 { t.signaling_threshold }

    public fun w_reputation(w: &ScoringWeights): u64  { w.reputation }
    public fun w_rtt(w: &ScoringWeights): u64         { w.rtt }
    public fun w_load(w: &ScoringWeights): u64        { w.load }
    public fun w_stake(w: &ScoringWeights): u64       { w.stake }
    public fun w_region(w: &ScoringWeights): u64      { w.region_match }

    public fun ratio_relay(r: &RewardRatios): u64     { r.relay }
    public fun ratio_validator(r: &RewardRatios): u64 { r.validator }
    public fun ratio_cp(r: &RewardRatios): u64        { r.control_plane }

    // ── Governance writes (require AdminCap) ──

    /// Update role thresholds. Must maintain ordering: cp >= relay >= validator >= signaling.
    public fun update_role_thresholds(
        _: &AdminCap,
        registry: &mut NetworkRegistry,
        cp: u64, relay: u64, validator: u64, signaling: u64,
    ) {
        assert!(cp >= relay && relay >= validator && validator >= signaling, E_INVALID_THRESHOLD);
        registry.role_thresholds = RoleThresholds {
            cp_threshold: cp,
            relay_threshold: relay,
            validator_threshold: validator,
            signaling_threshold: signaling,
        };
    }

    public fun update_scoring_weights(
        _: &AdminCap,
        registry: &mut NetworkRegistry,
        reputation: u64, rtt: u64, load: u64, stake: u64, region_match: u64,
    ) {
        assert!(reputation + rtt + load + stake + region_match == constants::basis_points(), E_INVALID_WEIGHT);
        registry.scoring_weights = ScoringWeights { reputation, rtt, load, stake, region_match };
    }

    public fun update_base_rate(
        _: &AdminCap, registry: &mut NetworkRegistry, new_rate: u64,
    ) {
        registry.base_rate_per_mb = new_rate;
    }

    public fun set_paused(
        _: &AdminCap, registry: &mut NetworkRegistry, paused: bool,
    ) {
        registry.paused = paused;
    }

    public fun update_reward_ratios(
        _: &AdminCap,
        registry: &mut NetworkRegistry,
        relay: u64, validator: u64, cp: u64,
    ) {
        assert!(relay + validator + cp == constants::basis_points(), E_INVALID_RATIO);
        registry.reward_ratios = RewardRatios { relay, validator, control_plane: cp };
    }

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        init(ctx);
    }
}
