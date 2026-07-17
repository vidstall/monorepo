module dvconf::caps {

    /// Control Plane operators get this — gates CP query functions
    public struct ControlPlaneCap has key, store {
        id: UID,
        miner_id: ID,
    }

    /// Non-CP miners (relay, validator, user) get this
    public struct MinerCap has key, store {
        id: UID,
        miner_id: ID,
        role: u8,
    }

    // ── Constructors (package-only) ──

    public(package) fun new_cp_cap(miner_id: ID, ctx: &mut TxContext): ControlPlaneCap {
        ControlPlaneCap { id: object::new(ctx), miner_id }
    }

    public(package) fun new_miner_cap(miner_id: ID, role: u8, ctx: &mut TxContext): MinerCap {
        MinerCap { id: object::new(ctx), miner_id, role }
    }

    // ── Read accessors ──

    public fun cp_cap_miner_id(c: &ControlPlaneCap): ID { c.miner_id }
    public fun miner_cap_miner_id(c: &MinerCap): ID     { c.miner_id }
    public fun miner_cap_role(c: &MinerCap): u8          { c.role }

    // ── Mutators (package-only) ──

    /// Update MinerCap role. Package-only — called by registration::apply_voted_role.
    public(package) fun set_miner_cap_role(cap: &mut MinerCap, role: u8) {
        cap.role = role;
    }
}
