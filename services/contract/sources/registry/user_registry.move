/// User registry — tracks registered conference users.
///
/// Any address can self-register (no cap required). The registry is consumed
/// by RoomManager to verify that room creators are registered users.
module dvconf::user_registry {
    use sui::table::{Self, Table};
    use sui::event;
    use dvconf::network_registry::{Self, NetworkRegistry, AdminCap};

    // ── Errors (540-549) ──
    const E_ALREADY_REGISTERED: u64 = 540;
    const E_NOT_REGISTERED: u64     = 541;
    const E_PAUSED: u64             = 542;

    // ══════════════════════════════════════════════════════════
    // DATA TYPES
    // ══════════════════════════════════════════════════════════

    public struct UserProfile has store, copy, drop {
        display_name:  vector<u8>,
        registered_at: u64,
        room_count:    u64,
    }

    public struct UserRegistry has key {
        id: UID,
        users:       Table<address, UserProfile>,
        total_users: u64,
    }

    // ══════════════════════════════════════════════════════════
    // EVENTS
    // ══════════════════════════════════════════════════════════

    public struct UserRegistered has copy, drop {
        user:         address,
        display_name: vector<u8>,
    }

    public struct UserProfileUpdated has copy, drop {
        user:         address,
        display_name: vector<u8>,
    }

    // ══════════════════════════════════════════════════════════
    // CONSTRUCTOR
    // ══════════════════════════════════════════════════════════

    /// Post-upgrade deployment — AdminCap gates creation.
    public fun create(_: &AdminCap, ctx: &mut TxContext) {
        transfer::share_object(UserRegistry {
            id: object::new(ctx),
            users: table::new(ctx),
            total_users: 0,
        });
    }

    // ══════════════════════════════════════════════════════════
    // ENTRY FUNCTIONS
    // ══════════════════════════════════════════════════════════

    /// Register a new user. Any address can self-register.
    public fun register_user(
        net_reg: &NetworkRegistry,
        registry: &mut UserRegistry,
        display_name: vector<u8>,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        let sender = ctx.sender();
        assert!(!table::contains(&registry.users, sender), E_ALREADY_REGISTERED);

        let profile = UserProfile {
            display_name,
            registered_at: ctx.epoch(),
            room_count: 0,
        };
        table::add(&mut registry.users, sender, profile);
        registry.total_users = registry.total_users + 1;

        event::emit(UserRegistered { user: sender, display_name });
    }

    /// Update display name.
    public fun update_profile(
        net_reg: &NetworkRegistry,
        registry: &mut UserRegistry,
        display_name: vector<u8>,
        ctx: &mut TxContext,
    ) {
        assert!(!network_registry::is_paused(net_reg), E_PAUSED);
        let sender = ctx.sender();
        assert!(table::contains(&registry.users, sender), E_NOT_REGISTERED);
        let profile = table::borrow_mut(&mut registry.users, sender);
        profile.display_name = display_name;

        event::emit(UserProfileUpdated { user: sender, display_name });
    }

    // ══════════════════════════════════════════════════════════
    // PACKAGE-ONLY MUTATIONS
    // ══════════════════════════════════════════════════════════

    /// Increment room count — called by RoomManager when user creates a room.
    public(package) fun increment_room_count(
        registry: &mut UserRegistry, user: address,
    ) {
        assert!(table::contains(&registry.users, user), E_NOT_REGISTERED);
        let profile = table::borrow_mut(&mut registry.users, user);
        profile.room_count = profile.room_count + 1;
    }

    // ══════════════════════════════════════════════════════════
    // READ ACCESSORS
    // ══════════════════════════════════════════════════════════

    public fun total_users(r: &UserRegistry): u64 { r.total_users }

    public fun is_registered(r: &UserRegistry, user: address): bool {
        table::contains(&r.users, user)
    }

    public fun borrow_profile(r: &UserRegistry, user: address): &UserProfile {
        assert!(table::contains(&r.users, user), E_NOT_REGISTERED);
        table::borrow(&r.users, user)
    }

    public fun display_name(p: &UserProfile): vector<u8> { p.display_name }
    public fun registered_at(p: &UserProfile): u64        { p.registered_at }
    public fun room_count(p: &UserProfile): u64           { p.room_count }

    // ══════════════════════════════════════════════════════════
    // TEST ONLY
    // ══════════════════════════════════════════════════════════

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        transfer::share_object(UserRegistry {
            id: object::new(ctx),
            users: table::new(ctx),
            total_users: 0,
        });
    }
}
