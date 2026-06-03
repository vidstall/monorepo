#[test_only]
module xaisen_contract::node_registry_tests;

use std::vector;
use sui::clock;
use sui::tx_context;
use xaisen_contract::node_registry;

const OWNER: address = @0xA;
const OTHER: address = @0xB;
const E_EMPTY_METADATA_URI: u64 = 0;
const E_INVALID_METADATA_HASH: u64 = 1;
const E_NODE_NOT_FOUND: u64 = 2;
const E_NOT_NODE_OWNER: u64 = 3;

#[test]
fun registry_initializes_empty() {
    let mut ctx = ctx(OWNER, 1);
    let registry = node_registry::new_registry_for_testing(&mut ctx);

    assert!(node_registry::node_count(&registry) == 0);
    assert!(!node_registry::node_exists(&registry, 1));

    node_registry::destroy_registry_for_testing(registry);
}

#[test]
fun register_worker_stores_record() {
    let mut ctx = ctx(OWNER, 1);
    let mut clock = clock::create_for_testing(&mut ctx);
    clock::set_for_testing(&mut clock, 1000);
    let mut registry = node_registry::new_registry_for_testing(&mut ctx);

    node_registry::register_worker(&mut registry, uri(), hash(1), &clock, &mut ctx);

    assert!(node_registry::node_count(&registry) == 1);
    assert!(node_registry::node_exists(&registry, 1));
    assert!(node_registry::worker_owner(&registry, 1) == OWNER);
    assert!(node_registry::worker_active(&registry, 1));
    assert!(node_registry::worker_metadata_uri(&registry, 1) == uri());
    assert!(node_registry::worker_metadata_hash(&registry, 1) == hash(1));
    assert!(node_registry::worker_created_at_ms(&registry, 1) == 1000);
    assert!(node_registry::worker_updated_at_ms(&registry, 1) == 1000);

    node_registry::unregister_worker(&mut registry, 1, &mut ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_EMPTY_METADATA_URI, location = xaisen_contract::node_registry)]
fun empty_metadata_uri_aborts() {
    node_registry::validate_metadata_for_testing(vector[], hash(1));
}

#[test]
#[expected_failure(abort_code = E_INVALID_METADATA_HASH, location = xaisen_contract::node_registry)]
fun invalid_metadata_hash_aborts() {
    node_registry::validate_metadata_for_testing(uri(), vector[1, 2, 3]);
}

#[test]
fun owner_can_update_metadata() {
    let mut ctx = ctx(OWNER, 1);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut registry = node_registry::new_registry_for_testing(&mut ctx);

    node_registry::register_worker(&mut registry, uri(), hash(1), &clock, &mut ctx);
    clock::set_for_testing(&mut clock, 2000);
    node_registry::update_worker_metadata(&mut registry, 1, updated_uri(), hash(2), &clock, &mut ctx);

    assert!(node_registry::worker_metadata_uri(&registry, 1) == updated_uri());
    assert!(node_registry::worker_metadata_hash(&registry, 1) == hash(2));
    assert!(node_registry::worker_updated_at_ms(&registry, 1) == 2000);

    node_registry::unregister_worker(&mut registry, 1, &mut ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_NODE_OWNER, location = xaisen_contract::node_registry)]
fun non_owner_cannot_update_metadata() {
    node_registry::assert_worker_owner_for_testing(OWNER, OTHER);
}

#[test]
fun owner_can_toggle_active_status() {
    let mut ctx = ctx(OWNER, 1);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut registry = node_registry::new_registry_for_testing(&mut ctx);

    node_registry::register_worker(&mut registry, uri(), hash(1), &clock, &mut ctx);
    clock::set_for_testing(&mut clock, 3000);
    node_registry::set_worker_active(&mut registry, 1, false, &clock, &mut ctx);

    assert!(!node_registry::worker_active(&registry, 1));
    assert!(node_registry::worker_updated_at_ms(&registry, 1) == 3000);

    node_registry::set_worker_active(&mut registry, 1, true, &clock, &mut ctx);
    assert!(node_registry::worker_active(&registry, 1));

    node_registry::unregister_worker(&mut registry, 1, &mut ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun owner_can_unregister_worker() {
    let mut ctx = ctx(OWNER, 1);
    let clock = clock::create_for_testing(&mut ctx);
    let mut registry = node_registry::new_registry_for_testing(&mut ctx);

    node_registry::register_worker(&mut registry, uri(), hash(1), &clock, &mut ctx);
    node_registry::unregister_worker(&mut registry, 1, &mut ctx);

    assert!(node_registry::node_count(&registry) == 0);
    assert!(!node_registry::node_exists(&registry, 1));

    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NODE_NOT_FOUND, location = xaisen_contract::node_registry)]
fun missing_node_operation_aborts() {
    node_registry::assert_node_present_for_testing(false);
}

fun ctx(sender: address, hint: u64): tx_context::TxContext {
    tx_context::new_from_hint(sender, hint, 0, 0, 0)
}

fun uri(): vector<u8> {
    b"ipfs://xaisen-worker"
}

fun updated_uri(): vector<u8> {
    b"ipfs://xaisen-worker-updated"
}

fun hash(byte: u8): vector<u8> {
    let mut output = vector[];
    let mut i = 0u64;
    while (i < 32) {
        vector::push_back(&mut output, byte);
        i = i + 1;
    };
    output
}
