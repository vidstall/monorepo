module dvconf::staking {
    use sui::balance::{Self, Balance};
    use sui::coin::{Self, Coin};
    use sui::sui::SUI;
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::miner_store;
    use dvconf::constants;

    // ── Errors ──
    const E_INSUFFICIENT_STAKE: u64 = 200;
    #[allow(unused_const)]
    const E_STAKE_LOCKED: u64 = 201; // reserved for Phase 3 session lock enforcement
    #[allow(unused_const)]
    const E_NOT_OWNER: u64 = 202;    // reserved for Phase 3 ownership checks within staking

    // ══════════════════════════════════════════════════════════
    // STAKE POSITION (owned by miner wallet)
    // ══════════════════════════════════════════════════════════

    public struct StakePosition has key {
        id: UID,
        owner:    address,
        miner_id: ID,
        role:     u8,
        amount:   Balance<SUI>,
        locked:   bool,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR (package-only)
    // ══════════════════════════════════════════════════════════

    public(package) fun create(
        owner: address,
        miner_id: ID,
        role: u8,
        coin: Coin<SUI>,
        ctx: &mut TxContext,
    ): StakePosition {
        StakePosition {
            id: object::new(ctx),
            owner, miner_id, role,
            amount: coin::into_balance(coin),
            locked: false,
        }
    }

    // ══════════════════════════════════════════════════════════
    // ROLE DETERMINATION
    // ══════════════════════════════════════════════════════════

    /// Determine role from stake amount.
    /// Only CP is auto-assigned (dynamic threshold increases with cp_count).
    /// All other miners get role=0 (user) and enter the CP voting queue.
    public fun determine_role(stake_amount: u64, registry: &NetworkRegistry, cp_count: u64): u8 {
        let t = network_registry::role_thresholds(registry);
        let dynamic_cp_threshold = network_registry::cp_threshold(&t)
            + cp_count * constants::cp_threshold_step();
        if (stake_amount >= dynamic_cp_threshold) {
            miner_store::role_cp()
        } else {
            miner_store::role_user()
        }
    }

    /// Get minimum stake for a given role
    public fun minimum_for_role(role: u8, registry: &NetworkRegistry): u64 {
        let t = network_registry::role_thresholds(registry);
        if (role == miner_store::role_cp()) {
            network_registry::cp_threshold(&t)
        } else if (role == miner_store::role_relay()) {
            network_registry::relay_threshold(&t)
        } else if (role == miner_store::role_validator()) {
            network_registry::validator_threshold(&t)
        } else if (role == miner_store::role_signaling()) {
            network_registry::signaling_threshold(&t)
        } else {
            0
        }
    }

    // ══════════════════════════════════════════════════════════
    // MUTATIONS
    // ══════════════════════════════════════════════════════════

    public fun top_up(position: &mut StakePosition, coin: Coin<SUI>) {
        balance::join(&mut position.amount, coin::into_balance(coin));
    }

    /// Destroy position, return all inner values. Caller handles cleanup.
    /// SEC-001: Aborts if position is locked (active session).
    public(package) fun destroy(
        position: StakePosition, ctx: &mut TxContext,
    ): (address, ID, u8, Coin<SUI>) {
        assert!(!position.locked, E_STAKE_LOCKED);
        let StakePosition { id, owner, miner_id, role, amount, locked: _ } = position;
        object::delete(id);
        (owner, miner_id, role, coin::from_balance(amount, ctx))
    }

    public(package) fun set_role(position: &mut StakePosition, role: u8) {
        position.role = role;
    }

    public(package) fun lock(position: &mut StakePosition) {
        position.locked = true;
    }

    public(package) fun unlock(position: &mut StakePosition) {
        position.locked = false;
    }

    /// Transfer position to recipient. Must be called from this module because
    /// StakePosition has no `store` ability (prevents external transfer).
    public(package) fun transfer_to(position: StakePosition, recipient: address) {
        transfer::transfer(position, recipient);
    }

    public(package) fun slash(
        position: &mut StakePosition, amount: u64, ctx: &mut TxContext,
    ): Coin<SUI> {
        assert!(balance::value(&position.amount) >= amount, E_INSUFFICIENT_STAKE);
        coin::from_balance(balance::split(&mut position.amount, amount), ctx)
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun amount(p: &StakePosition): u64     { balance::value(&p.amount) }
    public fun role(p: &StakePosition): u8        { p.role }
    public fun owner(p: &StakePosition): address  { p.owner }
    public fun miner_id(p: &StakePosition): ID    { p.miner_id }
    public fun is_locked(p: &StakePosition): bool { p.locked }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    /// Create a StakePosition for testing with a specific miner_id.
    public fun create_for_testing(
        owner: address,
        miner_id: ID,
        role: u8,
        coin: Coin<SUI>,
        ctx: &mut TxContext,
    ): StakePosition {
        StakePosition {
            id: object::new(ctx),
            owner, miner_id, role,
            amount: coin::into_balance(coin),
            locked: false,
        }
    }

    #[test_only]
    /// Share a StakePosition for testing (makes it a shared object for pay_slash tests).
    public fun share_for_testing(position: StakePosition) {
        transfer::share_object(position);
    }

    #[test_only]
    /// Destroy a StakePosition for testing cleanup.
    public fun destroy_for_testing(position: StakePosition) {
        let StakePosition { id, owner: _, miner_id: _, role: _, amount, locked: _ } = position;
        object::delete(id);
        balance::destroy_for_testing(amount);
    }
}
