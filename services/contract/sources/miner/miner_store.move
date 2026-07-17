module dvconf::miner_store {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use dvconf::constants;

    // ── Errors ──
    const E_NOT_REGISTERED: u64 = 300;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    /// Network endpoint — how other nodes connect to this miner
    public struct Endpoint has store, copy, drop {
        ip:                   vector<u8>,
        port:                 u16,
        stun_url:             vector<u8>,
        turn_url:             vector<u8>,
        turn_credential_hash: vector<u8>,
    }

    /// Capacity and location — used by CP for relay scoring
    public struct NodeStrength has store, copy, drop {
        region:         vector<u8>,
        bandwidth_mbps: u64,
        max_concurrent: u64,
        current_load:   u64,
        cpu_cores:      u64,
    }

    /// Full miner profile — stored inside MinerStore
    public struct MinerProfile has store, drop {
        owner:         address,
        role:          u8,
        endpoint:      Endpoint,
        strength:      NodeStrength,
        reputation:    u64,
        registered_at: u64,
        last_active:   u64,
        active:        bool,
    }

    // ══════════════════════════════════════════════════════════
    // SHARED STORE
    // ══════════════════════════════════════════════════════════

    public struct MinerStore has key {
        id: UID,
        profiles:          Table<ID, MinerProfile>,
        cp_miners:         VecSet<ID>,
        relay_miners:      VecSet<ID>,
        validator_miners:  VecSet<ID>,
        signaling_miners:  VecSet<ID>,  // Phase 11 — signaling node tracking (ADD IMP-2)
        user_miners:       VecSet<ID>,
        total_registered:  u64,
    }

    fun init(ctx: &mut TxContext) {
        transfer::share_object(MinerStore {
            id: object::new(ctx),
            profiles: table::new(ctx),
            cp_miners: vec_set::empty(),
            relay_miners: vec_set::empty(),
            validator_miners: vec_set::empty(),
            signaling_miners: vec_set::empty(),
            user_miners: vec_set::empty(),
            total_registered: 0,
        });
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTORS (package-only)
    // ══════════════════════════════════════════════════════════

    public(package) fun new_endpoint(
        ip: vector<u8>, port: u16,
        stun_url: vector<u8>, turn_url: vector<u8>,
        turn_credential_hash: vector<u8>,
    ): Endpoint {
        Endpoint { ip, port, stun_url, turn_url, turn_credential_hash }
    }

    public(package) fun new_strength(
        region: vector<u8>, bandwidth_mbps: u64,
        max_concurrent: u64, cpu_cores: u64,
    ): NodeStrength {
        NodeStrength {
            region, bandwidth_mbps, max_concurrent,
            current_load: 0, cpu_cores,
        }
    }

    public(package) fun new_profile(
        owner: address, role: u8,
        endpoint: Endpoint, strength: NodeStrength,
        epoch: u64,
    ): MinerProfile {
        MinerProfile {
            owner, role, endpoint, strength,
            reputation: constants::default_initial_reputation(),
            registered_at: epoch,
            last_active: epoch,
            active: true,
        }
    }

    // ══════════════════════════════════════════════════════════
    // STORE MUTATIONS (package-only)
    // ══════════════════════════════════════════════════════════

    public(package) fun add_profile(
        store: &mut MinerStore, miner_id: ID, profile: MinerProfile,
    ) {
        let role = profile.role;
        table::add(&mut store.profiles, miner_id, profile);
        add_to_role_set(store, role, miner_id);
        store.total_registered = store.total_registered + 1;
    }

    public(package) fun remove_profile(
        store: &mut MinerStore, miner_id: ID, role: u8,
    ) {
        table::remove(&mut store.profiles, miner_id);
        remove_from_role_set(store, role, miner_id);
        store.total_registered = store.total_registered - 1;
    }

    public(package) fun borrow_profile_mut(
        store: &mut MinerStore, miner_id: ID,
    ): &mut MinerProfile {
        assert!(table::contains(&store.profiles, miner_id), E_NOT_REGISTERED);
        table::borrow_mut(&mut store.profiles, miner_id)
    }

    public(package) fun change_role(
        store: &mut MinerStore, miner_id: ID,
        old_role: u8, new_role: u8,
    ) {
        assert!(table::contains(&store.profiles, miner_id), E_NOT_REGISTERED);
        remove_from_role_set(store, old_role, miner_id);
        add_to_role_set(store, new_role, miner_id);
        let profile = table::borrow_mut(&mut store.profiles, miner_id);
        profile.role = new_role;
    }

    // ══════════════════════════════════════════════════════════
    // PROFILE FIELD SETTERS (package-only)
    // ══════════════════════════════════════════════════════════

    public(package) fun set_endpoint(p: &mut MinerProfile, e: Endpoint) {
        p.endpoint = e;
    }

    public(package) fun set_strength_preserving_load(
        p: &mut MinerProfile,
        region: vector<u8>, bandwidth_mbps: u64,
        max_concurrent: u64, cpu_cores: u64,
    ) {
        let old_load = p.strength.current_load;
        p.strength = NodeStrength {
            region, bandwidth_mbps, max_concurrent,
            current_load: old_load, cpu_cores,
        };
    }

    public(package) fun set_load(p: &mut MinerProfile, load: u64, epoch: u64) {
        p.strength.current_load = load;
        p.last_active = epoch;
    }

    public(package) fun set_active_flag(p: &mut MinerProfile, active: bool) {
        p.active = active;
    }

    public(package) fun set_reputation(p: &mut MinerProfile, rep: u64) {
        p.reputation = rep;
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS (public)
    // ══════════════════════════════════════════════════════════

    public fun total_registered(store: &MinerStore): u64 { store.total_registered }

    public fun has_profile(store: &MinerStore, id: ID): bool {
        table::contains(&store.profiles, id)
    }

    public fun borrow_profile(store: &MinerStore, id: ID): &MinerProfile {
        assert!(table::contains(&store.profiles, id), E_NOT_REGISTERED);
        table::borrow(&store.profiles, id)
    }

    // Profile reads
    public fun profile_owner(p: &MinerProfile): address         { p.owner }
    public fun profile_role(p: &MinerProfile): u8               { p.role }
    public fun profile_endpoint(p: &MinerProfile): Endpoint     { p.endpoint }
    public fun profile_strength(p: &MinerProfile): NodeStrength { p.strength }
    public fun profile_reputation(p: &MinerProfile): u64        { p.reputation }
    public fun profile_active(p: &MinerProfile): bool           { p.active }

    // Endpoint reads
    public fun endpoint_ip(e: &Endpoint): vector<u8> { e.ip }
    public fun endpoint_port(e: &Endpoint): u16      { e.port }
    public fun endpoint_stun_url(e: &Endpoint): vector<u8>             { e.stun_url }
    public fun endpoint_turn_url(e: &Endpoint): vector<u8>             { e.turn_url }
    public fun endpoint_turn_credential_hash(e: &Endpoint): vector<u8> { e.turn_credential_hash }

    // Strength reads
    public fun strength_region(s: &NodeStrength): vector<u8> { s.region }
    public fun strength_bandwidth(s: &NodeStrength): u64     { s.bandwidth_mbps }
    public fun strength_load(s: &NodeStrength): u64          { s.current_load }
    public fun strength_max(s: &NodeStrength): u64           { s.max_concurrent }
    public fun strength_cpu(s: &NodeStrength): u64           { s.cpu_cores }

    /// Convenience: get bandwidth_mbps for a miner by ID (used by CP role voting via devInspect).
    public fun get_miner_bandwidth(store: &MinerStore, miner_id: ID): u64 {
        let profile = borrow_profile(store, miner_id);
        profile.strength.bandwidth_mbps
    }

    /// Convenience: get cpu_cores for a miner by ID (used by CP role voting via devInspect).
    public fun get_miner_cpu_cores(store: &MinerStore, miner_id: ID): u64 {
        let profile = borrow_profile(store, miner_id);
        profile.strength.cpu_cores
    }

    // Role set reads
    public fun relay_set(store: &MinerStore): &VecSet<ID>             { &store.relay_miners }
    public(package) fun validator_set(store: &MinerStore): &VecSet<ID> { &store.validator_miners }
    public fun cp_count(store: &MinerStore): u64              { vec_set::length(&store.cp_miners) }
    public fun relay_count(store: &MinerStore): u64           { vec_set::length(&store.relay_miners) }
    public fun validator_count(store: &MinerStore): u64       { vec_set::length(&store.validator_miners) }
    public fun signaling_count(store: &MinerStore): u64       { vec_set::length(&store.signaling_miners) }
    public fun user_count(store: &MinerStore): u64            { vec_set::length(&store.user_miners) }

    // Role constants
    public fun role_user(): u8      { constants::role_user() }
    public fun role_validator(): u8 { constants::role_validator() }
    public fun role_relay(): u8     { constants::role_relay() }
    public fun role_cp(): u8        { constants::role_cp() }
    public fun role_signaling(): u8 { constants::role_signaling() }

    // ══════════════════════════════════════════════════════════
    // INTERNAL HELPERS
    // ══════════════════════════════════════════════════════════

    fun add_to_role_set(store: &mut MinerStore, role: u8, id: ID) {
        if (role == constants::role_cp())             { vec_set::insert(&mut store.cp_miners, id) }
        else if (role == constants::role_relay())     { vec_set::insert(&mut store.relay_miners, id) }
        else if (role == constants::role_validator()) { vec_set::insert(&mut store.validator_miners, id) }
        else if (role == constants::role_signaling()) { vec_set::insert(&mut store.signaling_miners, id) }
        else                                          { vec_set::insert(&mut store.user_miners, id) }
    }

    fun remove_from_role_set(store: &mut MinerStore, role: u8, id: ID) {
        if (role == constants::role_cp())             { vec_set::remove(&mut store.cp_miners, &id) }
        else if (role == constants::role_relay())     { vec_set::remove(&mut store.relay_miners, &id) }
        else if (role == constants::role_validator()) { vec_set::remove(&mut store.validator_miners, &id) }
        else if (role == constants::role_signaling()) { vec_set::remove(&mut store.signaling_miners, &id) }
        else                                          { vec_set::remove(&mut store.user_miners, &id) }
    }

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        init(ctx);
    }
}
