/// Shared test utilities — setup, mint, and register helpers reused across all test modules.
#[test_only]
module dvconf::test_helpers {
    use sui::test_scenario::{Self as ts, Scenario};
    use sui::coin;
    use sui::sui::SUI;
    use dvconf::network_registry::NetworkRegistry;
    use dvconf::miner_store::MinerStore;
    use dvconf::registration;

    // ── Test addresses ──────────────────────────────────────────────────
    const ADMIN:   address = @0xAD;
    const RELAY_1: address = @0xB1;
    const CP_1:    address = @0xC1;
    const VAL_1:   address = @0xD1;
    const USER_1:  address = @0xE1;

    // ── Stake amounts (MIST; 1 SUI = 1_000_000_000) ──────────────────────
    const CP_STAKE:        u64 = 500_000_000; // 0.5 SUI
    const RELAY_STAKE:     u64 = 250_000_000; // 0.25 SUI
    const VALIDATOR_STAKE: u64 = 100_000_000; // 0.1 SUI
    const USER_STAKE:      u64 =  10_000_000; // 0.01 SUI (below signaling threshold)

    // ── Address accessors ───────────────────────────────────────────────
    public fun admin():   address { ADMIN   }
    public fun relay_1(): address { RELAY_1 }
    public fun cp_1():    address { CP_1    }
    public fun val_1():   address { VAL_1   }
    public fun user_1():  address { USER_1  }

    // ── Stake accessors ─────────────────────────────────────────────────
    public fun cp_stake():        u64 { CP_STAKE        }
    public fun relay_stake():     u64 { RELAY_STAKE     }
    public fun validator_stake(): u64 { VALIDATOR_STAKE }
    public fun user_stake():      u64 { USER_STAKE      }

    // ── Additional addresses for Phase 2 ──────────────────────────────
    const RELAY_2: address = @0xB2;
    const VAL_2:   address = @0xD2;
    const USER_2:  address = @0xE2;

    public fun relay_2(): address { RELAY_2 }
    public fun val_2():   address { VAL_2   }
    public fun user_2():  address { USER_2  }

    // ── Signaling addresses and stake (Phase 11) ─────────────────────
    const SIG_1: address = @0xF1;
    const SIGNALING_STAKE: u64 = 50_000_000; // 0.05 SUI — signaling threshold

    public fun sig_1(): address        { SIG_1 }
    public fun signaling_stake(): u64  { SIGNALING_STAKE }

    // ── do_register defaults (used in assertions) ────────────────────
    public fun default_bandwidth_mbps():  u64 { 1000 }
    public fun default_max_concurrent():  u64 { 100  }

    // ── Protocol bootstrap ──────────────────────────────────────────────

    /// Initialise registry and miner_store. Returns scenario after ADMIN tx.
    public fun setup(): Scenario {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            dvconf::network_registry::init_for_testing(ctx);
            dvconf::miner_store::init_for_testing(ctx);
        };
        scenario
    }

    /// Phase 2 bootstrap — includes all Phase 1 + all 5 registries.
    public fun setup_phase2(): Scenario {
        let mut scenario = ts::begin(ADMIN);
        {
            let ctx = ts::ctx(&mut scenario);
            dvconf::network_registry::init_for_testing(ctx);
            dvconf::miner_store::init_for_testing(ctx);
            dvconf::user_registry::init_for_testing(ctx);
            dvconf::validator_registry::init_for_testing(ctx);
            dvconf::relay_registry::init_for_testing(ctx);
            dvconf::control_plane_registry::init_for_testing(ctx);
            dvconf::signaling_registry::init_for_testing(ctx);
            dvconf::room_manager::init_for_testing(ctx);
        };
        scenario
    }

    /// Phase 3 bootstrap — includes all Phase 2 objects.
    /// No additional shared objects needed since RoomEscrow is created per-room.
    public fun setup_phase3(): Scenario {
        setup_phase2()
    }

    /// Mint `amount` SUI to `recipient` for testing.
    public fun mint_to(scenario: &mut Scenario, amount: u64, recipient: address) {
        ts::next_tx(scenario, ADMIN);
        {
            let c = coin::mint_for_testing<SUI>(amount, ts::ctx(scenario));
            transfer::public_transfer(c, recipient);
        };
    }

    /// Register `who` with `stake` using default endpoint and strength values.
    /// Uses register_with_role (test-only) to assign role based on stake bracket,
    /// since determine_role now only auto-assigns CP; all others get role=0.
    public fun do_register(scenario: &mut Scenario, who: address, stake: u64) {
        let role = stake_to_role(stake);
        do_register_with_role(scenario, who, stake, role);
    }

    /// Register `who` with an explicit role.
    public fun do_register_with_role(scenario: &mut Scenario, who: address, stake: u64, role: u8) {
        mint_to(scenario, stake, who);
        ts::next_tx(scenario, who);
        {
            let registry = ts::take_shared<NetworkRegistry>(scenario);
            let mut store = ts::take_shared<MinerStore>(scenario);
            let coin = ts::take_from_sender<coin::Coin<SUI>>(scenario);

            registration::register_with_role(
                &registry,
                &mut store,
                coin,
                role,
                b"192.168.1.1",    // ip
                8080,              // port
                b"stun://s.test",  // stun_url
                b"turn://t.test",  // turn_url
                b"asia-southeast1",// region
                1000,              // bandwidth_mbps
                100,               // max_concurrent
                8,                 // cpu_cores
                b"",               // turn_credential_hash (empty for tests)
                ts::ctx(scenario),
            );

            ts::return_shared(registry);
            ts::return_shared(store);
        };
    }

    /// Map stake amount to expected role (legacy bracket logic for test compatibility).
    public fun stake_to_role(stake: u64): u8 {
        if (stake >= CP_STAKE) {
            dvconf::constants::role_cp()
        } else if (stake >= RELAY_STAKE) {
            dvconf::constants::role_relay()
        } else if (stake >= VALIDATOR_STAKE) {
            dvconf::constants::role_validator()
        } else if (stake >= SIGNALING_STAKE) {
            dvconf::constants::role_signaling()
        } else {
            dvconf::constants::role_user()
        }
    }
}
