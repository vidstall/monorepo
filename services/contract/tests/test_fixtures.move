#[test_only]
module xaisen_contract::test_fixtures;

use std::vector;
use sui::clock;
use sui::coin;
use sui::tx_context;
use xaisen_contract::registry;
use xaisen_contract::worker_accessors;
use xaisen_contract::workers;

public struct TEST_COIN has drop {}

const OWNER: address = @0xA;
const CLIENT: address = @0xB;
const OTHER: address = @0xC;
const WORKER_B: address = @0xD;
const WORKER_C: address = @0xE;

const PRICE: u64 = 500;
const CAPACITY: u64 = 4;

public fun owner(): address { OWNER }
public fun client(): address { CLIENT }
public fun other(): address { OTHER }
public fun worker_b(): address { WORKER_B }
public fun worker_c(): address { WORKER_C }
public fun price(): u64 { PRICE }
public fun capacity(): u64 { CAPACITY }

public fun ctx(sender: address, hint: u64): tx_context::TxContext {
    tx_context::new_from_hint(sender, hint, 0, 0, 0)
}

public fun stake(ctx: &mut tx_context::TxContext): coin::Coin<TEST_COIN> {
    coin::mint_for_testing<TEST_COIN>(worker_accessors::min_worker_stake_for_testing(), ctx)
}

public fun payment(ctx: &mut tx_context::TxContext): coin::Coin<TEST_COIN> {
    coin::mint_for_testing<TEST_COIN>(PRICE, ctx)
}

public fun uri(): vector<u8> { b"ipfs://xaisen-worker" }
public fun updated_uri(): vector<u8> { b"ipfs://xaisen-worker-updated" }
public fun room(): vector<u8> { b"xaisen-room" }

public fun hash(byte: u8): vector<u8> {
    let mut output = vector[];
    let mut i = 0u64;
    while (i < 32) {
        vector::push_back(&mut output, byte);
        i = i + 1;
    };
    output
}

public fun registered_registry(
    clock: &clock::Clock,
    ctx: &mut tx_context::TxContext,
): registry::Registry<TEST_COIN> {
    let mut reg = registry::new_registry_for_testing<TEST_COIN>(ctx);
    workers::register_worker(&mut reg, uri(), hash(1), PRICE, stake(ctx), clock, ctx);
    reg
}
