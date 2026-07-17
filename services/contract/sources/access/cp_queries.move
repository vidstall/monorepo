module dvconf::cp_queries {
    use sui::vec_set::VecSet;
    use dvconf::caps::ControlPlaneCap;
    use dvconf::miner_store::{Self, MinerStore, Endpoint, NodeStrength};

    /// Read a miner's full profile for relay scoring
    public fun get_profile(
        _: &ControlPlaneCap,
        store: &MinerStore,
        miner_id: ID,
    ): (address, u8, Endpoint, NodeStrength, u64, bool) {
        let p = miner_store::borrow_profile(store, miner_id);
        (
            miner_store::profile_owner(p),
            miner_store::profile_role(p),
            miner_store::profile_endpoint(p),
            miner_store::profile_strength(p),
            miner_store::profile_reputation(p),
            miner_store::profile_active(p),
        )
    }

    /// All relay IDs — CP iterates and scores each
    public fun get_relay_set(
        _: &ControlPlaneCap, store: &MinerStore,
    ): &VecSet<ID> {
        miner_store::relay_set(store)
    }

    /// All validator IDs — for secret room assignment
    public fun get_validator_set(
        _: &ControlPlaneCap, store: &MinerStore,
    ): &VecSet<ID> {
        miner_store::validator_set(store)
    }

    /// Count per role
    public fun get_counts(
        _: &ControlPlaneCap, store: &MinerStore,
    ): (u64, u64, u64, u64) {
        (
            miner_store::cp_count(store),
            miner_store::relay_count(store),
            miner_store::validator_count(store),
            miner_store::user_count(store),
        )
    }

    /// Check if a miner is online + has capacity
    public fun check_assignable(
        _: &ControlPlaneCap, store: &MinerStore, miner_id: ID,
    ): (bool, u64, u64, u64) {
        let p = miner_store::borrow_profile(store, miner_id);
        let s = miner_store::profile_strength(p);
        let assignable = miner_store::profile_active(p)
            && (miner_store::strength_load(&s) < miner_store::strength_max(&s));
        (
            assignable,
            miner_store::strength_load(&s),
            miner_store::strength_max(&s),
            miner_store::strength_bandwidth(&s),
        )
    }
}
