/// Control Plane registry — tracks registered CP nodes, heartbeats, and room assignments.
///
/// CP nodes register using their ControlPlaneCap. Heartbeats keep nodes
/// marked as active. Room assignments are package-gated for Phase 3.
module dvconf::control_plane_registry {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use sui::event;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, ControlPlaneCap};
    use dvconf::staking::{Self, StakePosition};

    // ── Errors (510-519) ──
    const E_NOT_CP: u64              = 510;
    const E_ALREADY_REGISTERED: u64  = 511;
    const E_NOT_REGISTERED: u64      = 512;
    const E_PAUSED: u64              = 513;
    #[allow(unused_const)]
    const E_NOT_ACTIVE: u64          = 514;
    #[allow(unused_const)]
    const E_ALREADY_ASSIGNED: u64    = 515;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    public struct CPNodeInfo has store, copy, drop {
        operator:       address,
        miner_id:       ID,
        stake_amount:   u64,
        last_heartbeat: u64,
        is_active:      bool,
        registered_at:  u64,
        reputation:     u64,
    }

    public struct ControlPlaneRegistry has key {
        id: UID,
        nodes:            Table<ID, CPNodeInfo>,
        active_cps:       VecSet<ID>,
        room_assignments: Table<ID, vector<ID>>, // room_id -> vec of cp miner_ids
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct CPRegistered has copy, drop {
        miner_id:     ID,
        operator:     address,
        stake_amount: u64,
    }

    public struct CPHeartbeat has copy, drop {
        miner_id: ID,
        epoch:    u64,
    }

    public struct CPAssignedToRoom has copy, drop {
        miner_id: ID,
        room_id:  ID,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    public fun create(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(ControlPlaneRegistry {
            id: object::new(ctx),
            nodes: table::new(ctx),
            active_cps: vec_set::empty(),
            room_assignments: table::new(ctx),
        });
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Register a CP node. Requires ControlPlaneCap.
    public fun register_cp(
        net_reg: &NetworkRegistry,
        registry: &mut ControlPlaneRegistry,
        cap: &ControlPlaneCap,
        stake: &StakePosition,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let miner_id = caps::cp_cap_miner_id(cap);
        assert!(!table::contains(&registry.nodes, miner_id), E_ALREADY_REGISTERED);

        let info = CPNodeInfo {
            operator: ctx.sender(),
            miner_id,
            stake_amount: staking::amount(stake),
            last_heartbeat: ctx.epoch(),
            is_active: true,
            registered_at: ctx.epoch(),
            reputation: 0,
        };

        table::add(&mut registry.nodes, miner_id, info);
        vec_set::insert(&mut registry.active_cps, miner_id);

        event::emit(CPRegistered {
            miner_id,
            operator: ctx.sender(),
            stake_amount: staking::amount(stake),
        });
    }

    /// Send a heartbeat to keep the CP node active.
    public fun heartbeat(
        net_reg: &NetworkRegistry,
        registry: &mut ControlPlaneRegistry,
        cap: &ControlPlaneCap,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let miner_id = caps::cp_cap_miner_id(cap);
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        info.last_heartbeat = ctx.epoch();
        info.is_active = true;

        if (!vec_set::contains(&registry.active_cps, &miner_id)) {
            vec_set::insert(&mut registry.active_cps, miner_id);
        };

        event::emit(CPHeartbeat { miner_id, epoch: ctx.epoch() });
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE-ONLY MUTATIONS
    // ══════════════════════════════════════════════════════════

    /// Assign a CP node to a room (Phase 3 calls this).
    public(package) fun assign_to_room(
        registry: &mut ControlPlaneRegistry,
        miner_id: ID,
        room_id: ID,
    ) {
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        if (table::contains(&registry.room_assignments, room_id)) {
            let assignments = table::borrow_mut(&mut registry.room_assignments, room_id);
            assignments.push_back(miner_id);
        } else {
            let mut assignments = vector::empty<ID>();
            assignments.push_back(miner_id);
            table::add(&mut registry.room_assignments, room_id, assignments);
        };

        event::emit(CPAssignedToRoom { miner_id, room_id });
    }

    /// Unassign all CPs from a room (room close).
    public(package) fun unassign_from_room(
        registry: &mut ControlPlaneRegistry,
        room_id: ID,
    ) {
        if (table::contains(&registry.room_assignments, room_id)) {
            table::remove(&mut registry.room_assignments, room_id);
        };
    }

    /// Increment reputation for a CP node (called by room_manager on proposal win).
    public(package) fun increment_reputation(
        registry: &mut ControlPlaneRegistry,
        miner_id: ID,
    ) {
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);
        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        info.reputation = info.reputation + 1;
    }

    /// Silently remove a CP node entry if it exists.
    /// Called by registration::unregister() for cross-registry cleanup (P1-7).
    /// Does NOT abort if miner_id is not registered.
    public(package) fun remove_if_registered(
        registry: &mut ControlPlaneRegistry,
        miner_id: ID,
    ) {
        if (!table::contains(&registry.nodes, miner_id)) {
            return
        };

        table::remove(&mut registry.nodes, miner_id);

        if (vec_set::contains(&registry.active_cps, &miner_id)) {
            vec_set::remove(&mut registry.active_cps, &miner_id);
        };
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun active_cp_count(r: &ControlPlaneRegistry): u64 {
        vec_set::length(&r.active_cps)
    }

    public fun is_registered(r: &ControlPlaneRegistry, miner_id: ID): bool {
        table::contains(&r.nodes, miner_id)
    }

    public fun borrow_info(r: &ControlPlaneRegistry, miner_id: ID): &CPNodeInfo {
        assert!(table::contains(&r.nodes, miner_id), E_NOT_REGISTERED);
        table::borrow(&r.nodes, miner_id)
    }

    public fun get_room_assignments(r: &ControlPlaneRegistry, room_id: ID): vector<ID> {
        if (table::contains(&r.room_assignments, room_id)) {
            *table::borrow(&r.room_assignments, room_id)
        } else {
            vector::empty()
        }
    }

    /// Returns a vector of all active CPNodeInfo entries.
    /// Used by client devInspect for node discovery.
    /// Cost: O(n) where n = size of active_cps. Acceptable for < 100 nodes.
    public fun get_active_cps(registry: &ControlPlaneRegistry): vector<CPNodeInfo> {
        let active_ids = vec_set::keys(&registry.active_cps);
        let mut result = vector::empty<CPNodeInfo>();
        let mut i = 0;
        let len = active_ids.length();
        while (i < len) {
            let id = *active_ids.borrow(i);
            if (table::contains(&registry.nodes, id)) {
                result.push_back(*table::borrow(&registry.nodes, id));
            };
            i = i + 1;
        };
        result
    }

    public fun info_operator(i: &CPNodeInfo): address       { i.operator }
    public fun info_miner_id(i: &CPNodeInfo): ID            { i.miner_id }
    public fun info_stake_amount(i: &CPNodeInfo): u64       { i.stake_amount }
    public fun info_last_heartbeat(i: &CPNodeInfo): u64     { i.last_heartbeat }
    public fun info_is_active(i: &CPNodeInfo): bool         { i.is_active }
    public fun info_registered_at(i: &CPNodeInfo): u64      { i.registered_at }
    public fun info_reputation(i: &CPNodeInfo): u64        { i.reputation }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        transfer::share_object(ControlPlaneRegistry {
            id: object::new(ctx),
            nodes: table::new(ctx),
            active_cps: vec_set::empty(),
            room_assignments: table::new(ctx),
        });
    }

    #[test_only]
    public fun add_cp_for_testing(
        registry: &mut ControlPlaneRegistry,
        miner_id: ID,
        operator: address,
        stake_amount: u64,
        ctx: &mut TxContext,
    ) {
        let info = CPNodeInfo {
            operator,
            miner_id,
            stake_amount,
            last_heartbeat: ctx.epoch(),
            is_active: true,
            registered_at: ctx.epoch(),
            reputation: 0,
        };
        table::add(&mut registry.nodes, miner_id, info);
        vec_set::insert(&mut registry.active_cps, miner_id);
    }

    #[test_only]
    public fun set_reputation_for_testing(
        registry: &mut ControlPlaneRegistry,
        miner_id: ID,
        reputation: u64,
    ) {
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);
        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        info.reputation = reputation;
    }
}
