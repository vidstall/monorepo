module dvconf::registration {
    use sui::coin::{Self, Coin};
    use sui::event;
    use sui::sui::SUI;
    use dvconf::network_registry::{Self, NetworkRegistry};
    use dvconf::miner_store::{Self, MinerStore};
    use dvconf::staking::{Self, StakePosition};
    use dvconf::caps;
    use dvconf::role_voting::{Self, RoleVoteBox};
    use dvconf::signaling_registry::{Self, SignalingRegistry};
    use dvconf::relay_registry::{Self, RelayRegistry};
    use dvconf::validator_registry::{Self, ValidatorRegistry};
    use dvconf::control_plane_registry::{Self, ControlPlaneRegistry};

    // ── Errors ──
    const E_INSUFFICIENT_STAKE: u64 = 400;
    const E_STAKE_LOCKED: u64 = 401;
    const E_NOT_OWNER: u64 = 402;
    const E_PROTOCOL_PAUSED: u64 = 403;
    const E_ALREADY_REGISTERED: u64 = 404;
    const E_NOT_REGISTERED: u64 = 405;
    // Borrowed from role_voting's namespace (700-718). The apply-side defensively
    // mirrors the cast-side Q5 guard (role_voting.move) so direct apply_voted_role
    // callers also cannot fast-path a CP<->non-CP transition. Same numeric code =>
    // consumers see one consistent abort regardless of which entry point rejected.
    // Keep in sync with role_voting::E_CP_REVOTE_REQUIRES_MIGRATION.
    const E_CP_REVOTE_REQUIRES_MIGRATION: u64 = 714;
    // Stake guards relocated here from role_voting (D-S70-4 / OQ-PH13). cast_role_vote is CP-signed
    // and CANNOT reference a miner's owned StakePosition, so the binding + threshold checks were
    // moved to this MINER-signed apply path. Same numeric codes as role_voting's old namespace
    // (713/717) so consumers see one consistent abort. Mirror of role_voting's 700-718 namespace.
    const E_INSUFFICIENT_STAKE_FOR_ROLE: u64 = 713;
    const E_STAKE_NOT_OWNED_BY_MINER: u64 = 717;

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct MinerRegistered has copy, drop {
        miner_id: ID,
        owner: address,
        role: u8,
        stake_amount: u64,
    }

    public struct MinerUnregistered has copy, drop {
        miner_id: ID,
        owner: address,
    }

    public struct RoleChanged has copy, drop {
        miner_id: ID,
        old_role: u8,
        new_role: u8,
        new_stake: u64,
    }

    public struct RoleApplied has copy, drop {
        miner_id: ID,
        role: u8,
        owner: address,
    }

    /// F47 Phase 1.5 (REQ-RV-005/RV-007) — emitted in apply_voted_role ONLY on a real
    /// role change (old_role != new_role). This is the stable loose-coupling interface
    /// for W2/W3/F62 consumers per ADR-0008; schema is locked {miner_id, old_role,
    /// new_role} (additive-only evolution allowed, no rename post-Phase 5 ship).
    public struct RoleTransitioned has copy, drop {
        miner_id: ID,
        old_role: u8,
        new_role: u8,
    }

    // ══════════════════════════════════════════════════════════
    // REGISTER
    // ══════════════════════════════════════════════════════════

    public fun register(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        coin: Coin<SUI>,
        ip: vector<u8>,
        port: u16,
        stun_url: vector<u8>,
        turn_url: vector<u8>,
        region: vector<u8>,
        bandwidth_mbps: u64,
        max_concurrent: u64,
        cpu_cores: u64,
        turn_credential_hash: vector<u8>,
        ctx: &mut TxContext
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);

        let sender = ctx.sender();
        let stake_amount = coin::value(&coin);

        let cp_count = miner_store::cp_count(store);
        let role = staking::determine_role(stake_amount, registry, cp_count);
        let min = staking::minimum_for_role(role, registry);
        assert!(stake_amount >= min, E_INSUFFICIENT_STAKE);

        let miner_id = object::id_from_address(sender);
        assert!(!miner_store::has_profile(store, miner_id), E_ALREADY_REGISTERED);

        let endpoint = miner_store::new_endpoint(ip, port, stun_url, turn_url, turn_credential_hash);
        let strength = miner_store::new_strength(
            region, bandwidth_mbps, max_concurrent, cpu_cores,
        );
        let profile = miner_store::new_profile(
            sender, role, endpoint, strength, ctx.epoch(),
        );

        miner_store::add_profile(store, miner_id, profile);

        let stake_pos = staking::create(sender, miner_id, role, coin, ctx);
        staking::transfer_to(stake_pos, sender);

        if (role == miner_store::role_cp()) {
            transfer::public_transfer(caps::new_cp_cap(miner_id, ctx), sender);
        } else {
            transfer::public_transfer(caps::new_miner_cap(miner_id, role, ctx), sender);
        };

        event::emit(MinerRegistered { miner_id, owner: sender, role, stake_amount });
    }

    // ══════════════════════════════════════════════════════════
    // APPLY VOTED ROLE
    // ══════════════════════════════════════════════════════════

    /// Apply a role assigned by CP voting. Called by the miner's own daemon.
    /// Consumes the vote assignment, updates MinerCap + MinerProfile + StakePosition,
    /// and (on a genuine transition) removes the stale entry the miner held under its
    /// OLD role registry so a re-vote cannot leave a node enrolled in two registries.
    ///
    /// F47 Phase 1.5 (REQ-RV-005 / RV-006): the signature gains the 4 role registries
    /// for cross-registry cleanup plus an apply-side Q5 guard that defensively mirrors
    /// the cast-side guard in role_voting.move (CP<->non-CP re-vote transitions must
    /// take the canonical unregister+register migration path, never this fast-path).
    public fun apply_voted_role(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        vote_box: &mut RoleVoteBox,
        signaling_reg: &mut SignalingRegistry,
        relay_reg: &mut RelayRegistry,
        validator_reg: &mut ValidatorRegistry,
        cp_reg: &mut ControlPlaneRegistry,
        cap: &mut caps::MinerCap,
        stake: &mut StakePosition,
        ctx: &TxContext,
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);

        let miner_id = caps::miner_cap_miner_id(cap);
        let sender = ctx.sender();
        assert!(miner_store::has_profile(store, miner_id), E_NOT_REGISTERED);

        // Consume the voting assignment (removes from assigned_roles table).
        let new_role = role_voting::consume_assignment(vote_box, miner_id);

        // Old role, read before any mutation.
        let old_role = caps::miner_cap_role(cap);

        // ── Q5 (ADR-0008) apply-side guard — defensive mirror of role_voting.move ──
        // A re-vote (old_role != USER) into or out of CP must migrate via
        // unregister+register, never this apply fast-path. An INITIAL application
        // (old_role == USER) into CP is unaffected, exactly like the cast-side guard.
        assert!(
            old_role == miner_store::role_user()
                || (old_role != miner_store::role_cp() && new_role != miner_store::role_cp()),
            E_CP_REVOTE_REQUIRES_MIGRATION,
        );

        // ── Stake guards (relocated from cast_role_vote per D-S70-4 / OQ-PH13) ──
        // These ran on the cast side in Phase 1.3, but cast_role_vote is CP-signed and a CP-signed
        // TX cannot reference a miner's OWNED StakePosition on Sui. apply_voted_role is MINER-signed
        // and already holds &mut StakePosition, so the binding + surplus checks belong here.
        //
        // Binding: the supplied stake must belong to the miner whose cap drives this apply — a node
        // cannot apply a voted role using some other miner's StakePosition.
        assert!(staking::miner_id(stake) == miner_id, E_STAKE_NOT_OWNED_BY_MINER);
        // Threshold: the miner's stake must meet the minimum for the role it was voted into.
        // Stuck-assignment edge: a CP may vote a miner into a role the miner cannot yet afford → this
        // apply aborts (E_INSUFFICIENT_STAKE_FOR_ROLE) → the assignment stays pending until the miner
        // tops up its stake, after which the same apply succeeds. (consume_assignment already removed
        // the assignment from assigned_roles, but this abort rolls the whole TX back, so it persists.)
        // A decline/expire path for an assignment the miner never tops up is a follow-up (OQ).
        assert!(staking::amount(stake) >= staking::minimum_for_role(new_role, registry), E_INSUFFICIENT_STAKE_FOR_ROLE);

        // ── Cross-registry cleanup ──
        // On a genuine role change, drop the stale entry the miner held under its OLD
        // role registry (mirrors unregister's cleanup). Same-role re-votes and
        // first-time (USER) applications have nothing to remove.
        if (old_role != new_role) {
            cleanup_old_registry(
                old_role, miner_id, signaling_reg, relay_reg, validator_reg, cp_reg,
            );
        };

        // Update all three owned objects atomically.
        caps::set_miner_cap_role(cap, new_role);
        miner_store::change_role(store, miner_id, old_role, new_role);
        staking::set_role(stake, new_role);

        // RoleApplied fires on every application (backward-compatible signal already
        // consumed by the E2E suite). RoleTransitioned is the F47 loose-coupling
        // interface for W2/W3/F62 consumers (ADR-0008) and fires ONLY on a real role
        // change, so a same-role re-application triggers no spurious downstream work.
        event::emit(RoleApplied { miner_id, role: new_role, owner: sender });
        if (old_role != new_role) {
            event::emit(RoleTransitioned { miner_id, old_role, new_role });
        };
    }

    /// Remove the miner's entry from the registry matching its OLD role. Idempotent:
    /// `remove_if_registered` is a no-op if the entry is absent. USER holds no registry
    /// entry, and CP transitions are blocked upstream by the Q5 guard, so `_cp_reg` is
    /// accepted for signature symmetry with unregister but is never touched here.
    fun cleanup_old_registry(
        old_role: u8,
        miner_id: ID,
        signaling_reg: &mut SignalingRegistry,
        relay_reg: &mut RelayRegistry,
        validator_reg: &mut ValidatorRegistry,
        _cp_reg: &mut ControlPlaneRegistry,
    ) {
        if (old_role == miner_store::role_relay()) {
            relay_registry::remove_if_registered(relay_reg, miner_id);
        } else if (old_role == miner_store::role_validator()) {
            validator_registry::remove_if_registered(validator_reg, miner_id);
        } else if (old_role == miner_store::role_signaling()) {
            signaling_registry::remove_if_registered(signaling_reg, miner_id);
        };
    }

    // ══════════════════════════════════════════════════════════
    // UNREGISTER
    // ══════════════════════════════════════════════════════════

    public fun unregister(
        store: &mut MinerStore,
        signaling_reg: &mut SignalingRegistry,
        relay_reg: &mut RelayRegistry,
        validator_reg: &mut ValidatorRegistry,
        cp_reg: &mut ControlPlaneRegistry,
        position: StakePosition,
        ctx: &mut TxContext
    ) {
        assert!(!staking::is_locked(&position), E_STAKE_LOCKED);
        assert!(staking::owner(&position) == ctx.sender(), E_NOT_OWNER);

        let (owner, miner_id, role, coin) = staking::destroy(position, ctx);

        // Cross-registry cleanup: remove entries if they exist (P1-7)
        signaling_registry::remove_if_registered(signaling_reg, miner_id);
        relay_registry::remove_if_registered(relay_reg, miner_id);
        validator_registry::remove_if_registered(validator_reg, miner_id);
        control_plane_registry::remove_if_registered(cp_reg, miner_id);

        miner_store::remove_profile(store, miner_id, role);
        transfer::public_transfer(coin, owner);

        event::emit(MinerUnregistered { miner_id, owner });
    }

    // ══════════════════════════════════════════════════════════
    // TOP UP STAKE (may upgrade role)
    // ══════════════════════════════════════════════════════════

    public fun top_up_stake(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        position: &mut StakePosition,
        coin: Coin<SUI>,
        ctx: &mut TxContext
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);
        assert!(staking::owner(position) == ctx.sender(), E_NOT_OWNER);

        staking::top_up(position, coin);

        // Only promote to CP if stake crosses dynamic CP threshold.
        // Never downgrade a voted role back to user.
        let cp_count = miner_store::cp_count(store);
        let new_role = staking::determine_role(staking::amount(position), registry, cp_count);
        let old_role = staking::role(position);

        if (new_role == miner_store::role_cp() && old_role != miner_store::role_cp()) {
            let miner_id = staking::miner_id(position);
            miner_store::change_role(store, miner_id, old_role, new_role);
            staking::set_role(position, new_role);

            event::emit(RoleChanged {
                miner_id, old_role, new_role,
                new_stake: staking::amount(position),
            });
        }
    }

    // ══════════════════════════════════════════════════════════
    // SELF-UPDATE
    // ══════════════════════════════════════════════════════════

    public fun update_endpoint(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        position: &StakePosition,
        ip: vector<u8>, port: u16,
        stun_url: vector<u8>, turn_url: vector<u8>,
        turn_credential_hash: vector<u8>,
        ctx: &mut TxContext
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);
        assert!(staking::owner(position) == ctx.sender(), E_NOT_OWNER);
        let profile = miner_store::borrow_profile_mut(
            store, staking::miner_id(position),
        );
        miner_store::set_endpoint(
            profile, miner_store::new_endpoint(ip, port, stun_url, turn_url, turn_credential_hash),
        );
    }

    public fun update_strength(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        position: &StakePosition,
        region: vector<u8>, bandwidth_mbps: u64,
        max_concurrent: u64, cpu_cores: u64,
        ctx: &mut TxContext
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);
        assert!(staking::owner(position) == ctx.sender(), E_NOT_OWNER);
        let profile = miner_store::borrow_profile_mut(
            store, staking::miner_id(position),
        );
        miner_store::set_strength_preserving_load(
            profile, region, bandwidth_mbps, max_concurrent, cpu_cores,
        );
    }

    public fun update_load(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        position: &StakePosition,
        current_load: u64,
        ctx: &mut TxContext
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);
        assert!(staking::owner(position) == ctx.sender(), E_NOT_OWNER);
        let profile = miner_store::borrow_profile_mut(
            store, staking::miner_id(position),
        );
        miner_store::set_load(profile, current_load, ctx.epoch());
    }

    public fun set_active(
        store: &mut MinerStore,
        position: &StakePosition,
        active: bool,
        ctx: &mut TxContext
    ) {
        assert!(staking::owner(position) == ctx.sender(), E_NOT_OWNER);
        let profile = miner_store::borrow_profile_mut(
            store, staking::miner_id(position),
        );
        miner_store::set_active_flag(profile, active);
    }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    /// Register with an explicit role (bypasses determine_role). For tests only.
    public fun register_with_role(
        registry: &NetworkRegistry,
        store: &mut MinerStore,
        coin: Coin<SUI>,
        role: u8,
        ip: vector<u8>,
        port: u16,
        stun_url: vector<u8>,
        turn_url: vector<u8>,
        region: vector<u8>,
        bandwidth_mbps: u64,
        max_concurrent: u64,
        cpu_cores: u64,
        turn_credential_hash: vector<u8>,
        ctx: &mut TxContext
    ) {
        assert!(!network_registry::is_paused(registry), E_PROTOCOL_PAUSED);

        let sender = ctx.sender();
        let stake_amount = coin::value(&coin);

        let miner_id = object::id_from_address(sender);
        assert!(!miner_store::has_profile(store, miner_id), E_ALREADY_REGISTERED);

        let endpoint = miner_store::new_endpoint(ip, port, stun_url, turn_url, turn_credential_hash);
        let strength = miner_store::new_strength(
            region, bandwidth_mbps, max_concurrent, cpu_cores,
        );
        let profile = miner_store::new_profile(
            sender, role, endpoint, strength, ctx.epoch(),
        );

        miner_store::add_profile(store, miner_id, profile);

        let stake_pos = staking::create(sender, miner_id, role, coin, ctx);
        staking::transfer_to(stake_pos, sender);

        if (role == miner_store::role_cp()) {
            transfer::public_transfer(caps::new_cp_cap(miner_id, ctx), sender);
        } else {
            transfer::public_transfer(caps::new_miner_cap(miner_id, role, ctx), sender);
        };

        event::emit(MinerRegistered { miner_id, owner: sender, role, stake_amount });
    }

    // ── F47 Phase 1.6 (REQ-RV-007) — RoleTransitioned schema-lock anchor ──
    //
    // Test-only constructor. Its sole purpose is to let the events test module
    // (`dvconf::role_revote_events_tests`) name every field of RoleTransitioned:
    // RENAMING or REMOVING a field breaks THIS line and the test build before it
    // can ship — enforcing the ADR-0008 schema lock ("no field rename post-Phase
    // 5"). (A pure field REORDER still compiles here since field shorthand binds
    // by name; that drift is caught by the BCS peel in that test instead.) It
    // also lets that test BCS-serialize the exact wire layout W2/W3/F62 indexers
    // decode. Not used by any production path.
    #[test_only]
    public fun new_role_transitioned_for_testing(
        miner_id: ID,
        old_role: u8,
        new_role: u8,
    ): RoleTransitioned {
        RoleTransitioned { miner_id, old_role, new_role }
    }
}
