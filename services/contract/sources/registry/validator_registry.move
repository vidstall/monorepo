/// Validator registry — tracks registered validators and their session wallets.
///
/// Validators register using their MinerCap (role=VALIDATOR). Session wallet
/// mappings are package-only to enforce identity hiding during sessions.
module dvconf::validator_registry {
    use sui::table::{Self, Table};
    use sui::vec_set::{Self, VecSet};
    use sui::event;
    use dvconf::constants;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};
    use dvconf::caps::{Self, MinerCap, ControlPlaneCap};
    use dvconf::staking::{Self, StakePosition};

    // ── Errors (530-539) ──
    const E_NOT_VALIDATOR: u64      = 530;
    const E_ALREADY_REGISTERED: u64 = 531;
    const E_NOT_REGISTERED: u64     = 532;
    const E_PAUSED: u64             = 533;
    const E_SESSION_EXISTS: u64     = 534;
    const E_NO_SESSION: u64         = 535;
    const E_NOT_OPERATOR: u64       = 536;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    public struct ValidatorInfo has store, copy, drop {
        operator:       address,
        miner_id:       ID,
        stake_amount:   u64,
        reputation:     u64,
        registered_at:  u64,
        last_heartbeat: u64,
        session_count:  u64,
    }

    public struct ValidatorRegistry has key {
        id: UID,
        validators:      Table<ID, ValidatorInfo>,
        active_count:    u64,
        active_set:      VecSet<ID>,
        session_wallets: Table<address, ID>, // session_wallet_addr -> miner_id
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct ValidatorRegistered has copy, drop {
        miner_id:     ID,
        operator:     address,
        stake_amount: u64,
    }

    public struct SessionWalletAssigned has copy, drop {
        session_wallet: address,
    }

    public struct SessionWalletRevealed has copy, drop {
        miner_id:       ID,
        session_wallet: address,
    }

    /// F40: emitted on every validator heartbeat. CP daemons use the cadence
    /// to detect crashed validators; the on-chain `last_heartbeat` field is
    /// the canonical liveness source for pairing scoring.
    public struct ValidatorHeartbeat has copy, drop {
        miner_id: ID,
        epoch:    u64,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    public fun create(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(ValidatorRegistry {
            id: object::new(ctx),
            validators: table::new(ctx),
            active_count: 0,
            active_set: vec_set::empty(),
            session_wallets: table::new(ctx),
        });
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Register a validator. Requires MinerCap with role=VALIDATOR.
    public fun register_validator(
        net_reg: &NetworkRegistry,
        registry: &mut ValidatorRegistry,
        cap: &MinerCap,
        stake: &StakePosition,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(caps::miner_cap_role(cap) == constants::role_validator(), E_NOT_VALIDATOR);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(!table::contains(&registry.validators, miner_id), E_ALREADY_REGISTERED);

        let info = ValidatorInfo {
            operator: ctx.sender(),
            miner_id,
            stake_amount: staking::amount(stake),
            reputation: constants::default_initial_reputation(),
            registered_at: ctx.epoch(),
            last_heartbeat: ctx.epoch(),
            session_count: 0,
        };

        table::add(&mut registry.validators, miner_id, info);
        registry.active_count = registry.active_count + 1;
        vec_set::insert(&mut registry.active_set, miner_id);

        event::emit(ValidatorRegistered {
            miner_id,
            operator: ctx.sender(),
            stake_amount: staking::amount(stake),
        });
    }

    /// CP-gated session wallet assignment. The CP daemon calls this after
    /// selecting validators for a room, passing each validator's pre-registered
    /// session wallet address. This bridges the gap between the package-only
    /// `assign_session_wallet` and external daemon callers.
    public fun assign_validator_session(
        net_reg: &NetworkRegistry,
        registry: &mut ValidatorRegistry,
        _cap: &ControlPlaneCap,
        miner_id: ID,
        session_wallet: address,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assign_session_wallet(registry, miner_id, session_wallet);
    }

    /// Self-register a session wallet. The validator operator can register
    /// their own session wallet using their MinerCap as authentication.
    /// This allows validators to participate without CP coordination.
    public fun self_assign_session_wallet(
        net_reg: &NetworkRegistry,
        registry: &mut ValidatorRegistry,
        cap: &MinerCap,
        session_wallet: address,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(caps::miner_cap_role(cap) == constants::role_validator(), E_NOT_VALIDATOR);
        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.validators, miner_id), E_NOT_REGISTERED);
        assign_session_wallet(registry, miner_id, session_wallet);
    }

    /// F40: validator heartbeat — writes `last_heartbeat` on-chain and emits
    /// `ValidatorHeartbeat`. Mirrors `signaling_registry::heartbeat` (canonical
    /// pattern). Operator-only (signed by the validator's MinerCap). Consumed
    /// by CP daemons (off-chain) and by `room_manager::finalize_room` pairing
    /// scoring (on-chain), which now reads from `info_last_heartbeat`.
    public fun heartbeat(
        net_reg: &NetworkRegistry,
        registry: &mut ValidatorRegistry,
        cap: &MinerCap,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        assert!(caps::miner_cap_role(cap) == constants::role_validator(), E_NOT_VALIDATOR);

        let miner_id = caps::miner_cap_miner_id(cap);
        assert!(table::contains(&registry.validators, miner_id), E_NOT_REGISTERED);

        let info = table::borrow_mut(&mut registry.validators, miner_id);
        assert!(info.operator == ctx.sender(), E_NOT_OPERATOR);
        info.last_heartbeat = ctx.epoch();

        event::emit(ValidatorHeartbeat { miner_id, epoch: ctx.epoch() });
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE-ONLY MUTATIONS
    // ══════════════════════════════════════════════════════════

    /// Assign a session wallet to a validator (identity hidden during session).
    public(package) fun assign_session_wallet(
        registry: &mut ValidatorRegistry,
        miner_id: ID,
        session_wallet: address,
    ) {
        assert!(table::contains(&registry.validators, miner_id), E_NOT_REGISTERED);
        assert!(!table::contains(&registry.session_wallets, session_wallet), E_SESSION_EXISTS);

        table::add(&mut registry.session_wallets, session_wallet, miner_id);

        event::emit(SessionWalletAssigned { session_wallet });
    }

    /// Reveal a session wallet (post-session proof).
    public(package) fun reveal_session_wallet(
        registry: &mut ValidatorRegistry,
        session_wallet: address,
    ) {
        assert!(table::contains(&registry.session_wallets, session_wallet), E_NO_SESSION);
        let miner_id = table::remove(&mut registry.session_wallets, session_wallet);

        event::emit(SessionWalletRevealed { miner_id, session_wallet });
    }

    /// Set reputation score for a validator.
    public(package) fun set_reputation(
        registry: &mut ValidatorRegistry,
        miner_id: ID,
        reputation: u64,
    ) {
        assert!(table::contains(&registry.validators, miner_id), E_NOT_REGISTERED);
        let info = table::borrow_mut(&mut registry.validators, miner_id);
        info.reputation = reputation;
    }

    /// Increment session count after a completed session.
    public(package) fun increment_session_count(
        registry: &mut ValidatorRegistry,
        miner_id: ID,
    ) {
        assert!(table::contains(&registry.validators, miner_id), E_NOT_REGISTERED);
        let info = table::borrow_mut(&mut registry.validators, miner_id);
        info.session_count = info.session_count + 1;
    }

    /// Silently remove a validator entry if it exists.
    /// Called by registration::unregister() for cross-registry cleanup (P1-7).
    /// Does NOT abort if miner_id is not registered.
    public(package) fun remove_if_registered(
        registry: &mut ValidatorRegistry,
        miner_id: ID,
    ) {
        if (!table::contains(&registry.validators, miner_id)) {
            return
        };

        table::remove(&mut registry.validators, miner_id);

        if (vec_set::contains(&registry.active_set, &miner_id)) {
            vec_set::remove(&mut registry.active_set, &miner_id);
            registry.active_count = registry.active_count - 1;
        };
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun active_count(r: &ValidatorRegistry): u64 { r.active_count }

    public fun is_registered(r: &ValidatorRegistry, miner_id: ID): bool {
        table::contains(&r.validators, miner_id)
    }

    public fun borrow_info(r: &ValidatorRegistry, miner_id: ID): &ValidatorInfo {
        assert!(table::contains(&r.validators, miner_id), E_NOT_REGISTERED);
        table::borrow(&r.validators, miner_id)
    }

    public(package) fun has_session_wallet(r: &ValidatorRegistry, wallet: address): bool {
        table::contains(&r.session_wallets, wallet)
    }

    /// Look up which validator owns a session wallet (without removing it).
    /// Used by economic_layer to identify the validator before proof submission.
    public(package) fun lookup_session_wallet(
        r: &ValidatorRegistry, wallet: address,
    ): ID {
        assert!(table::contains(&r.session_wallets, wallet), E_NO_SESSION);
        *table::borrow(&r.session_wallets, wallet)
    }

    /// Returns a vector of all active ValidatorInfo entries.
    /// Used by client devInspect for node discovery.
    /// Cost: O(n) where n = size of active_set. Acceptable for < 100 nodes.
    public fun get_active_validators(registry: &ValidatorRegistry): vector<ValidatorInfo> {
        let active_ids = vec_set::keys(&registry.active_set);
        let mut result = vector::empty<ValidatorInfo>();
        let mut i = 0;
        let len = active_ids.length();
        while (i < len) {
            let id = *active_ids.borrow(i);
            if (table::contains(&registry.validators, id)) {
                result.push_back(*table::borrow(&registry.validators, id));
            };
            i = i + 1;
        };
        result
    }

    public fun info_operator(i: &ValidatorInfo): address   { i.operator }
    public fun info_miner_id(i: &ValidatorInfo): ID        { i.miner_id }
    public fun info_stake_amount(i: &ValidatorInfo): u64   { i.stake_amount }
    public fun info_reputation(i: &ValidatorInfo): u64     { i.reputation }
    public fun info_registered_at(i: &ValidatorInfo): u64  { i.registered_at }
    public fun info_last_heartbeat(i: &ValidatorInfo): u64 { i.last_heartbeat }
    public fun info_session_count(i: &ValidatorInfo): u64  { i.session_count }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        transfer::share_object(ValidatorRegistry {
            id: object::new(ctx),
            validators: table::new(ctx),
            active_count: 0,
            active_set: vec_set::empty(),
            session_wallets: table::new(ctx),
        });
    }

    #[test_only]
    /// Register a validator with a specific miner_id for testing.
    public fun add_validator_for_testing(
        registry: &mut ValidatorRegistry,
        miner_id: ID,
        operator: address,
        stake_amount: u64,
        ctx: &mut TxContext,
    ) {
        let info = ValidatorInfo {
            operator,
            miner_id,
            stake_amount,
            reputation: constants::default_initial_reputation(),
            registered_at: ctx.epoch(),
            last_heartbeat: ctx.epoch(),
            session_count: 0,
        };
        table::add(&mut registry.validators, miner_id, info);
        registry.active_count = registry.active_count + 1;
        vec_set::insert(&mut registry.active_set, miner_id);
    }
}
