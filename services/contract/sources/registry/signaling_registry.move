/// Signaling Node registry -- tracks registered signaling nodes, heartbeats,
/// load reporting, and provides a vector-returning accessor for client
/// discovery via devInspect.
///
/// Signaling nodes register using their MinerCap (role=SIGNALING).
/// Heartbeats keep nodes marked as active. Load is reported as raw
/// WebSocket connection count.
module dvconf::signaling_registry {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use sui::event;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::constants;

    // ── Errors (600-604) ──
    const E_NOT_SIGNALING: u64     = 600;
    const E_ALREADY_REGISTERED: u64 = 601;
    const E_NOT_REGISTERED: u64    = 602;
    const E_PAUSED: u64            = 603;
    const E_NOT_OPERATOR: u64      = 604;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    public struct SignalingNodeInfo has store, copy, drop {
        operator:       address,
        miner_id:       ID,
        stake_amount:   u64,
        last_heartbeat: u64,
        is_active:      bool,
        endpoint_url:   vector<u8>,
        region:         vector<u8>,
        load:           u64,
        registered_at:  u64,
    }

    public struct SignalingRegistry has key {
        id: UID,
        nodes:      Table<ID, SignalingNodeInfo>,
        active_set: VecSet<ID>,
        node_count: u64,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct SignalingRegistered has copy, drop {
        miner_id:     ID,
        operator:     address,
        endpoint_url: vector<u8>,
        region:       vector<u8>,
        stake_amount: u64,
    }

    public struct SignalingHeartbeat has copy, drop {
        miner_id: ID,
        epoch:    u64,
    }

    public struct SignalingLoadUpdated has copy, drop {
        miner_id: ID,
        new_load: u64,
    }

    public struct SignalingUnregistered has copy, drop {
        miner_id: ID,
        operator: address,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    public fun create(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(SignalingRegistry {
            id: object::new(ctx),
            nodes: table::new(ctx),
            active_set: vec_set::empty(),
            node_count: 0,
        });
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Register a signaling node. Requires MinerCap with role=SIGNALING.
    public fun register_signaling(
        net_reg: &NetworkRegistry,
        registry: &mut SignalingRegistry,
        cap: &MinerCap,
        stake: &StakePosition,
        endpoint_url: vector<u8>,
        region: vector<u8>,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(caps::miner_cap_role(cap) == constants::role_signaling(), E_NOT_SIGNALING);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(!table::contains(&registry.nodes, miner_id), E_ALREADY_REGISTERED);

        let info = SignalingNodeInfo {
            operator: ctx.sender(),
            miner_id,
            stake_amount: staking::amount(stake),
            last_heartbeat: ctx.epoch(),
            is_active: true,
            endpoint_url,
            region,
            load: 0,
            registered_at: ctx.epoch(),
        };

        table::add(&mut registry.nodes, miner_id, info);
        vec_set::insert(&mut registry.active_set, miner_id);
        registry.node_count = registry.node_count + 1;

        event::emit(SignalingRegistered {
            miner_id,
            operator: ctx.sender(),
            endpoint_url: info.endpoint_url,
            region: info.region,
            stake_amount: staking::amount(stake),
        });
    }

    /// Send a heartbeat to keep the signaling node active.
    public fun heartbeat(
        net_reg: &NetworkRegistry,
        registry: &mut SignalingRegistry,
        cap: &MinerCap,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        info.last_heartbeat = ctx.epoch();
        info.is_active = true;

        if (!vec_set::contains(&registry.active_set, &miner_id)) {
            vec_set::insert(&mut registry.active_set, miner_id);
        };

        event::emit(SignalingHeartbeat { miner_id, epoch: ctx.epoch() });
    }

    /// Update the load (WebSocket connection count) for a signaling node.
    public fun update_load(
        net_reg: &NetworkRegistry,
        registry: &mut SignalingRegistry,
        cap: &MinerCap,
        new_load: u64,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        assert!(ctx.sender() == info.operator, E_NOT_OPERATOR);

        info.load = new_load;

        event::emit(SignalingLoadUpdated { miner_id, new_load });
    }

    /// Unregister a signaling node. NO pause check -- operators can always exit.
    public fun unregister_signaling(
        registry: &mut SignalingRegistry,
        cap: &MinerCap,
        ctx: &mut TxContext,
    ) {
        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        let info = table::remove(&mut registry.nodes, miner_id);
        assert!(ctx.sender() == info.operator, E_NOT_OPERATOR);

        if (vec_set::contains(&registry.active_set, &miner_id)) {
            vec_set::remove(&mut registry.active_set, &miner_id);
        };
        registry.node_count = registry.node_count - 1;

        event::emit(SignalingUnregistered {
            miner_id,
            operator: info.operator,
        });
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE-ONLY HELPERS
    // ══════════════════════════════════════════════════════════

    /// Silently remove a signaling node entry if it exists.
    /// Called by registration::unregister() for cross-registry cleanup (TD-P11-04).
    /// Does NOT abort if miner_id is not registered.
    public(package) fun remove_if_registered(
        registry: &mut SignalingRegistry,
        miner_id: ID,
    ) {
        if (!table::contains(&registry.nodes, miner_id)) {
            return
        };

        let info = table::remove(&mut registry.nodes, miner_id);

        if (vec_set::contains(&registry.active_set, &miner_id)) {
            vec_set::remove(&mut registry.active_set, &miner_id);
        };
        registry.node_count = registry.node_count - 1;

        event::emit(SignalingUnregistered {
            miner_id,
            operator: info.operator,
        });
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun active_signaling_count(r: &SignalingRegistry): u64 {
        vec_set::size(&r.active_set)
    }

    public fun is_registered(r: &SignalingRegistry, miner_id: ID): bool {
        table::contains(&r.nodes, miner_id)
    }

    public fun borrow_info(r: &SignalingRegistry, miner_id: ID): &SignalingNodeInfo {
        assert!(table::contains(&r.nodes, miner_id), E_NOT_REGISTERED);
        table::borrow(&r.nodes, miner_id)
    }

    /// Returns a vector of all active SignalingNodeInfo entries.
    /// Used by client devInspect for node discovery.
    /// Cost: O(n) where n = size of active_set. Acceptable for < 100 nodes.
    public fun get_active_nodes(registry: &SignalingRegistry): vector<SignalingNodeInfo> {
        let active_ids = vec_set::keys(&registry.active_set);
        let mut result = vector::empty<SignalingNodeInfo>();
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

    // ── Field accessors on SignalingNodeInfo ──

    public fun info_operator(i: &SignalingNodeInfo): address       { i.operator }
    public fun info_miner_id(i: &SignalingNodeInfo): ID            { i.miner_id }
    public fun info_stake_amount(i: &SignalingNodeInfo): u64       { i.stake_amount }
    public fun info_last_heartbeat(i: &SignalingNodeInfo): u64     { i.last_heartbeat }
    public fun info_is_active(i: &SignalingNodeInfo): bool         { i.is_active }
    public fun info_endpoint_url(i: &SignalingNodeInfo): vector<u8> { i.endpoint_url }
    public fun info_region(i: &SignalingNodeInfo): vector<u8>      { i.region }
    public fun info_load(i: &SignalingNodeInfo): u64               { i.load }
    public fun info_registered_at(i: &SignalingNodeInfo): u64      { i.registered_at }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        transfer::share_object(SignalingRegistry {
            id: object::new(ctx),
            nodes: table::new(ctx),
            active_set: vec_set::empty(),
            node_count: 0,
        });
    }

    #[test_only]
    public fun add_signaling_for_testing(
        registry: &mut SignalingRegistry,
        miner_id: ID,
        operator: address,
        ctx: &mut TxContext,
    ) {
        let info = SignalingNodeInfo {
            operator,
            miner_id,
            stake_amount: 50_000_000,
            last_heartbeat: ctx.epoch(),
            is_active: true,
            endpoint_url: b"wss://sig.test:443",
            region: b"asia-southeast1",
            load: 0,
            registered_at: ctx.epoch(),
        };
        table::add(&mut registry.nodes, miner_id, info);
        vec_set::insert(&mut registry.active_set, miner_id);
        registry.node_count = registry.node_count + 1;
    }
}
