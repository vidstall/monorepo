/// Relay registry — tracks registered relay nodes, their loads, and RTT scores.
///
/// Relay nodes register using MinerCap (role=RELAY). RTT scores are
/// package-gated (validator-probed only — never self-reported).
module dvconf::relay_registry {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use sui::event;
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap};
    use dvconf::staking::{Self, StakePosition};

    // ── Errors (520-529) ──
    const E_NOT_RELAY: u64          = 520;
    const E_ALREADY_REGISTERED: u64 = 521;
    const E_NOT_REGISTERED: u64     = 522;
    const E_PAUSED: u64             = 523;
    const E_NOT_OPERATOR: u64       = 524;
    const E_NOT_REGISTERED_RELAY: u64 = 525;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    public struct RelayNodeInfo has store, copy, drop {
        operator:       address,
        miner_id:       ID,
        stake_amount:   u64,
        reputation:     u64,
        registered_at:  u64,
        last_heartbeat: u64,
        region:         vector<u8>,
        endpoint_url:   vector<u8>,
    }

    public struct RelayRegistry has key {
        id: UID,
        nodes:        Table<ID, RelayNodeInfo>,
        rtt_scores:   Table<ID, u64>,
        loads:        Table<ID, u64>,
        active_count: u64,
        active_set:   VecSet<ID>,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct RelayRegistered has copy, drop {
        miner_id:     ID,
        operator:     address,
        region:       vector<u8>,
        stake_amount: u64,
        endpoint_url: vector<u8>,
    }

    public struct RelayLoadUpdated has copy, drop {
        miner_id: ID,
        new_load: u64,
    }

    public struct RelayRTTUpdated has copy, drop {
        miner_id: ID,
        rtt:      u64,
    }

    public struct RelayPerformanceDegraded has copy, drop {
        room_id:        ID,
        relay_miner_id: ID,
        rtt:            u64,
        load:           u64,
        epoch:          u64,
    }

    /// ADR-0004 failover heartbeat. Emitted on a fixed cadence by each registered
    /// relay; CP daemons track `last_seen_epoch` per relay and declare the relay
    /// crashed after `HEARTBEAT_MISS_THRESHOLD` consecutive missed cycles.
    public struct RelayHeartbeat has copy, drop {
        miner_id: ID,
        epoch:    u64,
        region:   vector<u8>,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    public fun create(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(RelayRegistry {
            id: object::new(ctx),
            nodes: table::new(ctx),
            rtt_scores: table::new(ctx),
            loads: table::new(ctx),
            active_count: 0,
            active_set: vec_set::empty(),
        });
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Register a relay node. Requires MinerCap with role=RELAY.
    public fun register_relay(
        net_reg: &NetworkRegistry,
        registry: &mut RelayRegistry,
        cap: &MinerCap,
        stake: &StakePosition,
        region: vector<u8>,
        endpoint_url: vector<u8>,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(caps::miner_cap_role(cap) == constants::role_relay(), E_NOT_RELAY);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(!table::contains(&registry.nodes, miner_id), E_ALREADY_REGISTERED);

        let info = RelayNodeInfo {
            operator: ctx.sender(),
            miner_id,
            stake_amount: staking::amount(stake),
            reputation: constants::default_initial_reputation(),
            registered_at: ctx.epoch(),
            last_heartbeat: ctx.epoch(),
            region,
            endpoint_url,
        };

        table::add(&mut registry.nodes, miner_id, info);
        table::add(&mut registry.loads, miner_id, 0);
        registry.active_count = registry.active_count + 1;
        vec_set::insert(&mut registry.active_set, miner_id);

        event::emit(RelayRegistered {
            miner_id,
            operator: ctx.sender(),
            region: info.region,
            stake_amount: info.stake_amount,
            endpoint_url: info.endpoint_url,
        });
    }

    /// Update the current load (operator-only, self-reported load is allowed).
    public fun update_load(
        net_reg: &NetworkRegistry,
        registry: &mut RelayRegistry,
        cap: &MinerCap,
        new_load: u64,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        // Verify operator owns this cap (role check ensures it's a relay)
        assert!(caps::miner_cap_role(cap) == constants::role_relay(), E_NOT_RELAY);

        // BUG-RR-01: Verify sender is the registered operator
        let info = table::borrow(&registry.nodes, miner_id);
        assert!(info.operator == ctx.sender(), E_NOT_OPERATOR);

        *table::borrow_mut(&mut registry.loads, miner_id) = new_load;

        event::emit(RelayLoadUpdated { miner_id, new_load });
    }

    /// ADR-0004 relay heartbeat — writes `last_heartbeat` and emits `RelayHeartbeat`
    /// for off-chain crash detection + on-chain pairing scoring (F40). Operator-only
    /// (signed by the relay's MinerCap). Pure liveness signal — load is NOT persisted
    /// or echoed here; daemons subscribe to `RelayLoadUpdated` separately for load.
    public fun relay_heartbeat(
        net_reg: &NetworkRegistry,
        registry: &mut RelayRegistry,
        cap: &MinerCap,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(caps::miner_cap_role(cap) == constants::role_relay(), E_NOT_RELAY);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        assert!(info.operator == ctx.sender(), E_NOT_OPERATOR);
        info.last_heartbeat = ctx.epoch();

        event::emit(RelayHeartbeat {
            miner_id,
            epoch: ctx.epoch(),
            region: info.region,
        });
    }

    /// Report relay performance degradation mid-session (informational only).
    /// Emits RelayPerformanceDegraded event. No mid-session migration.
    public fun report_degradation(
        registry: &RelayRegistry,
        room_id: ID,
        relay_miner_id: ID,
        rtt: u64,
        load: u64,
        ctx: &TxContext,
    ) {
        assert!(table::contains(&registry.nodes, relay_miner_id), E_NOT_REGISTERED_RELAY);

        event::emit(RelayPerformanceDegraded {
            room_id,
            relay_miner_id,
            rtt,
            load,
            epoch: ctx.epoch(),
        });
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE-ONLY MUTATIONS
    // ══════════════════════════════════════════════════════════

    /// Update RTT score — validator-probed only (never self-reported).
    public(package) fun update_rtt(
        registry: &mut RelayRegistry,
        miner_id: ID,
        rtt: u64,
    ) {
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);

        if (table::contains(&registry.rtt_scores, miner_id)) {
            *table::borrow_mut(&mut registry.rtt_scores, miner_id) = rtt;
        } else {
            table::add(&mut registry.rtt_scores, miner_id, rtt);
        };

        event::emit(RelayRTTUpdated { miner_id, rtt });
    }

    /// Set reputation score for a relay node.
    public(package) fun set_reputation(
        registry: &mut RelayRegistry,
        miner_id: ID,
        reputation: u64,
    ) {
        assert!(table::contains(&registry.nodes, miner_id), E_NOT_REGISTERED);
        let info = table::borrow_mut(&mut registry.nodes, miner_id);
        info.reputation = reputation;
    }

    /// Silently remove a relay node entry if it exists.
    /// Called by registration::unregister() for cross-registry cleanup (P1-7).
    /// Does NOT abort if miner_id is not registered.
    public(package) fun remove_if_registered(
        registry: &mut RelayRegistry,
        miner_id: ID,
    ) {
        if (!table::contains(&registry.nodes, miner_id)) {
            return
        };

        table::remove(&mut registry.nodes, miner_id);

        if (table::contains(&registry.loads, miner_id)) {
            table::remove(&mut registry.loads, miner_id);
        };

        if (table::contains(&registry.rtt_scores, miner_id)) {
            table::remove(&mut registry.rtt_scores, miner_id);
        };

        if (vec_set::contains(&registry.active_set, &miner_id)) {
            vec_set::remove(&mut registry.active_set, &miner_id);
            registry.active_count = registry.active_count - 1;
        };
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun active_count(r: &RelayRegistry): u64 { r.active_count }

    public fun is_registered(r: &RelayRegistry, miner_id: ID): bool {
        table::contains(&r.nodes, miner_id)
    }

    public fun borrow_info(r: &RelayRegistry, miner_id: ID): &RelayNodeInfo {
        assert!(table::contains(&r.nodes, miner_id), E_NOT_REGISTERED);
        table::borrow(&r.nodes, miner_id)
    }

    public fun get_load(r: &RelayRegistry, miner_id: ID): u64 {
        assert!(table::contains(&r.loads, miner_id), E_NOT_REGISTERED);
        *table::borrow(&r.loads, miner_id)
    }

    public fun get_rtt(r: &RelayRegistry, miner_id: ID): u64 {
        assert!(table::contains(&r.rtt_scores, miner_id), E_NOT_REGISTERED);
        *table::borrow(&r.rtt_scores, miner_id)
    }

    public fun has_rtt(r: &RelayRegistry, miner_id: ID): bool {
        table::contains(&r.rtt_scores, miner_id)
    }

    public fun info_operator(i: &RelayNodeInfo): address       { i.operator }
    public fun info_miner_id(i: &RelayNodeInfo): ID            { i.miner_id }
    public fun info_stake_amount(i: &RelayNodeInfo): u64       { i.stake_amount }
    public fun info_reputation(i: &RelayNodeInfo): u64         { i.reputation }
    public fun info_registered_at(i: &RelayNodeInfo): u64      { i.registered_at }
    public fun info_last_heartbeat(i: &RelayNodeInfo): u64     { i.last_heartbeat }
    public fun info_region(i: &RelayNodeInfo): vector<u8>      { i.region }
    public fun info_endpoint_url(i: &RelayNodeInfo): vector<u8> { i.endpoint_url }

    /// Returns a vector of all active RelayNodeInfo entries.
    /// Used by client devInspect for node discovery.
    /// Cost: O(n) where n = size of active_set. Acceptable for < 100 nodes.
    public fun get_active_relays(registry: &RelayRegistry): vector<RelayNodeInfo> {
        let active_ids = vec_set::keys(&registry.active_set);
        let mut result = vector::empty<RelayNodeInfo>();
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

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        transfer::share_object(RelayRegistry {
            id: object::new(ctx),
            nodes: table::new(ctx),
            rtt_scores: table::new(ctx),
            loads: table::new(ctx),
            active_count: 0,
            active_set: vec_set::empty(),
        });
    }

    #[test_only]
    /// Register a relay with a specific miner_id for testing.
    public fun add_relay_for_testing(
        registry: &mut RelayRegistry,
        miner_id: ID,
        operator: address,
        ctx: &mut TxContext,
    ) {
        let info = RelayNodeInfo {
            operator,
            miner_id,
            stake_amount: 1_000_000_000,
            reputation: constants::default_initial_reputation(),
            registered_at: ctx.epoch(),
            last_heartbeat: ctx.epoch(),
            region: b"asia-southeast1",
            endpoint_url: b"relay://test:8080",
        };
        table::add(&mut registry.nodes, miner_id, info);
        table::add(&mut registry.loads, miner_id, 0);
        registry.active_count = registry.active_count + 1;
        vec_set::insert(&mut registry.active_set, miner_id);
    }
}
