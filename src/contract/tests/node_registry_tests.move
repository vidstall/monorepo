#[test_only]
module xaisen_contract::node_registry_tests;

use std::vector;
use sui::clock;
use sui::coin;
use sui::tx_context;
use xaisen_contract::node_registry;

public struct TEST_COIN has drop {}

const OWNER: address = @0xA;
const CLIENT: address = @0xB;
const OTHER: address = @0xC;
const WORKER_B: address = @0xD;
const WORKER_C: address = @0xE;

const E_EMPTY_METADATA_URI: u64 = 0;
const E_INVALID_METADATA_HASH: u64 = 1;
const E_NODE_NOT_FOUND: u64 = 2;
const E_NOT_NODE_OWNER: u64 = 3;
const E_INVALID_PRICE: u64 = 4;
const E_INSUFFICIENT_STAKE: u64 = 5;
const E_WORKER_UNAVAILABLE: u64 = 6;
const E_INVALID_PAYMENT_AMOUNT: u64 = 7;
const E_EMPTY_ROOM_NAME: u64 = 8;
const E_NOT_RENTAL_CLIENT: u64 = 10;
const E_RENTAL_NOT_PENDING: u64 = 11;
const E_WORKER_HAS_ACTIVE_RENTAL: u64 = 12;
const E_WORKER_ACTIVE: u64 = 13;
const E_INVALID_CAPACITY: u64 = 14;
const E_NOT_ACTIVE_WORKER: u64 = 15;
const E_ALREADY_VOTED: u64 = 16;
const E_PROPOSAL_EXPIRED: u64 = 18;
const E_PROPOSAL_ALREADY_FINALIZED: u64 = 19;
const E_INVALID_ROLE: u64 = 20;

const PRICE: u64 = 500;
const CAPACITY: u64 = 4;

// ── Existing tests (updated for capacity parameter) ─────────────────

#[test]
fun registry_initializes_empty() {
    let mut ctx = ctx(OWNER, 1);
    let registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    assert!(node_registry::node_count(&registry) == 0);
    assert!(node_registry::total_rewards_paid(&registry) == 0);
    assert!(node_registry::active_worker_count_for_testing(&registry) == 0);

    node_registry::destroy_registry_for_testing(registry);
}

#[test]
fun register_worker_stores_record() {
    let mut ctx = ctx(OWNER, 2);
    let clock = clock::create_for_testing(&mut ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    node_registry::register_worker(
        &mut registry,
        uri(),
        hash(1),
        PRICE,
        stake(&mut ctx),
        &clock,
        &mut ctx,
    );

    assert!(node_registry::node_count(&registry) == 1);
    assert!(node_registry::active_worker_count_for_testing(&registry) == 1);
    assert!(node_registry::worker_owner(&registry, 1) == OWNER);
    assert!(node_registry::worker_metadata_uri(&registry, 1) == uri());
    assert!(node_registry::worker_metadata_hash(&registry, 1) == hash(1));
    assert!(node_registry::worker_active(&registry, 1));
    assert!(node_registry::worker_rentable(&registry, 1));
    assert!(node_registry::worker_price_per_rental(&registry, 1) == PRICE);
    assert!(node_registry::worker_stake_value(&registry, 1) == node_registry::min_worker_stake_for_testing());
    assert!(node_registry::worker_active_rental_id(&registry, 1) == node_registry::no_active_rental_for_testing());
    assert!(node_registry::worker_created_at_ms(&registry, 1) == 0);
    assert!(node_registry::worker_updated_at_ms(&registry, 1) == 0);

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
    node_registry::validate_metadata_for_testing(uri(), vector[1]);
}

#[test]
#[expected_failure(abort_code = E_INSUFFICIENT_STAKE, location = xaisen_contract::node_registry)]
fun insufficient_stake_aborts() {
    let mut ctx = ctx(OWNER, 3);
    let clock = clock::create_for_testing(&mut ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    node_registry::register_worker(
        &mut registry,
        uri(),
        hash(1),
        PRICE,
        coin::mint_for_testing<TEST_COIN>(node_registry::min_worker_stake_for_testing() - 1, &mut ctx),
        &clock,
        &mut ctx,
    );

    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_PRICE, location = xaisen_contract::node_registry)]
fun invalid_zero_price_aborts() {
    let mut ctx = ctx(OWNER, 4);
    let clock = clock::create_for_testing(&mut ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut ctx);

    node_registry::register_worker(
        &mut registry,
        uri(),
        hash(1),
        0,
        stake(&mut ctx),
        &clock,
        &mut ctx,
    );

    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun owner_can_update_metadata_and_price() {
    let mut ctx = ctx(OWNER, 5);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut registry = registered_registry(&clock, &mut ctx);

    clock::set_for_testing(&mut clock, 2000);
    node_registry::update_worker_metadata(&mut registry, 1, updated_uri(), hash(2), &clock, &mut ctx);
    node_registry::update_worker_price(&mut registry, 1, PRICE + 100, &mut ctx);

    assert!(node_registry::worker_metadata_uri(&registry, 1) == updated_uri());
    assert!(node_registry::worker_metadata_hash(&registry, 1) == hash(2));
    assert!(node_registry::worker_updated_at_ms(&registry, 1) == 2000);
    assert!(node_registry::worker_price_per_rental(&registry, 1) == PRICE + 100);

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
    let mut ctx = ctx(OWNER, 8);
    let mut clock = clock::create_for_testing(&mut ctx);
    let mut registry = registered_registry(&clock, &mut ctx);

    assert!(node_registry::active_worker_count_for_testing(&registry) == 1);

    clock::set_for_testing(&mut clock, 3000);
    node_registry::set_worker_active(&mut registry, 1, false, &clock, &mut ctx);

    assert!(!node_registry::worker_active(&registry, 1));
    assert!(!node_registry::worker_rentable(&registry, 1));
    assert!(node_registry::worker_updated_at_ms(&registry, 1) == 3000);
    assert!(node_registry::active_worker_count_for_testing(&registry) == 0);

    node_registry::set_worker_active(&mut registry, 1, true, &clock, &mut ctx);
    assert!(node_registry::worker_active(&registry, 1));
    assert!(node_registry::worker_rentable(&registry, 1));
    assert!(node_registry::active_worker_count_for_testing(&registry) == 1);

    node_registry::unregister_worker(&mut registry, 1, &mut ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun hire_worker_creates_rental_and_marks_worker_busy() {
    let mut owner_ctx = ctx(OWNER, 9);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 10);

    node_registry::hire_worker(
        &mut registry,
        1,
        room(),
        CAPACITY,
        payment(&mut client_ctx),
        &clock,
        &mut client_ctx,
    );

    assert!(node_registry::rental_exists(&registry, 1));
    assert!(node_registry::rental_status(&registry, 1) == node_registry::rental_pending_for_testing());
    assert!(node_registry::rental_client(&registry, 1) == CLIENT);
    assert!(node_registry::rental_worker_node_id(&registry, 1) == 1);
    assert!(node_registry::rental_room_name(&registry, 1) == room());
    assert!(node_registry::rental_capacity(&registry, 1) == CAPACITY);
    assert!(node_registry::rental_payment_amount(&registry, 1) == PRICE);
    assert!(node_registry::worker_active_rental_id(&registry, 1) == 1);

    node_registry::cancel_rental(&mut registry, 1, &mut client_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_PAYMENT_AMOUNT, location = xaisen_contract::node_registry)]
fun incorrect_payment_amount_aborts() {
    let mut owner_ctx = ctx(OWNER, 11);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 12);

    node_registry::hire_worker(
        &mut registry,
        1,
        room(),
        CAPACITY,
        coin::mint_for_testing<TEST_COIN>(PRICE - 1, &mut client_ctx),
        &clock,
        &mut client_ctx,
    );

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_EMPTY_ROOM_NAME, location = xaisen_contract::node_registry)]
fun empty_room_name_aborts() {
    let mut owner_ctx = ctx(OWNER, 13);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 14);

    node_registry::hire_worker(
        &mut registry,
        1,
        vector[],
        CAPACITY,
        payment(&mut client_ctx),
        &clock,
        &mut client_ctx,
    );

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_HAS_ACTIVE_RENTAL, location = xaisen_contract::node_registry)]
fun second_rental_for_busy_worker_aborts() {
    let mut owner_ctx = ctx(OWNER, 15);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 16);
    let mut other_ctx = ctx(OTHER, 17);

    node_registry::hire_worker(&mut registry, 1, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);
    node_registry::hire_worker(&mut registry, 1, b"room-two", CAPACITY, payment(&mut other_ctx), &clock, &mut other_ctx);

    node_registry::cancel_rental(&mut registry, 1, &mut client_ctx);
    node_registry::unregister_worker(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_UNAVAILABLE, location = xaisen_contract::node_registry)]
fun inactive_worker_cannot_be_hired() {
    let mut owner_ctx = ctx(OWNER, 18);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 19);

    node_registry::set_worker_active_for_testing(&mut registry, 1, false);
    node_registry::hire_worker(&mut registry, 1, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun client_completes_rental_and_worker_gets_reward() {
    let mut owner_ctx = ctx(OWNER, 20);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 21);

    node_registry::hire_worker(&mut registry, 1, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);
    clock::set_for_testing(&mut clock, 4000);
    node_registry::complete_rental(&mut registry, 1, &clock, &mut client_ctx);

    assert!(!node_registry::rental_exists(&registry, 1));
    assert!(node_registry::worker_active_rental_id(&registry, 1) == node_registry::no_active_rental_for_testing());
    assert!(node_registry::total_rewards_paid(&registry) == PRICE);

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_RENTAL_CLIENT, location = xaisen_contract::node_registry)]
fun non_client_cannot_complete_rental() {
    node_registry::assert_rental_client_for_testing(CLIENT, OTHER);
}

#[test]
fun client_cancels_rental_and_gets_refund() {
    let mut owner_ctx = ctx(OWNER, 25);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 26);

    node_registry::hire_worker(&mut registry, 1, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);
    node_registry::cancel_rental(&mut registry, 1, &mut client_ctx);

    assert!(!node_registry::rental_exists(&registry, 1));
    assert!(node_registry::worker_active_rental_id(&registry, 1) == node_registry::no_active_rental_for_testing());
    assert!(node_registry::total_rewards_paid(&registry) == 0);

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_RENTAL_NOT_PENDING, location = xaisen_contract::node_registry)]
fun completed_rental_cannot_be_canceled() {
    node_registry::assert_rental_pending_for_testing(1);
}

#[test]
#[expected_failure(abort_code = E_WORKER_ACTIVE, location = xaisen_contract::node_registry)]
fun stake_withdrawal_fails_while_worker_active() {
    let mut ctx = ctx(OWNER, 27);
    let clock = clock::create_for_testing(&mut ctx);
    let mut registry = registered_registry(&clock, &mut ctx);

    node_registry::withdraw_worker_stake(&mut registry, 1, &mut ctx);

    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_WORKER_HAS_ACTIVE_RENTAL, location = xaisen_contract::node_registry)]
fun stake_withdrawal_fails_while_worker_rented() {
    node_registry::assert_no_active_rental_for_testing(1);
}

#[test]
fun stake_withdrawal_succeeds_when_inactive_and_idle() {
    let mut ctx = ctx(OWNER, 30);
    let clock = clock::create_for_testing(&mut ctx);
    let mut registry = registered_registry(&clock, &mut ctx);

    node_registry::set_worker_active(&mut registry, 1, false, &clock, &mut ctx);
    node_registry::withdraw_worker_stake(&mut registry, 1, &mut ctx);

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

// ── New tests: capacity ─────────────────────────────────────────────

#[test]
#[expected_failure(abort_code = E_INVALID_CAPACITY, location = xaisen_contract::node_registry)]
fun hire_worker_zero_capacity_aborts() {
    let mut owner_ctx = ctx(OWNER, 40);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 41);

    node_registry::hire_worker(
        &mut registry,
        1,
        room(),
        0,
        payment(&mut client_ctx),
        &clock,
        &mut client_ctx,
    );

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

// ── New tests: room ordering and voting ─────────────────────────────

#[test]
fun order_room_creates_pending_proposal() {
    let mut owner_ctx = ctx(OWNER, 50);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 51);

    node_registry::order_room(
        &mut registry,
        room(),
        CAPACITY,
        payment(&mut client_ctx),
        &clock,
        &mut client_ctx,
    );

    assert!(node_registry::rental_exists(&registry, 1));
    assert!(node_registry::rental_status(&registry, 1) == node_registry::rental_awaiting_assignment_for_testing());
    assert!(node_registry::rental_capacity(&registry, 1) == CAPACITY);
    assert!(node_registry::rental_client(&registry, 1) == CLIENT);
    assert!(node_registry::rental_payment_amount(&registry, 1) == PRICE);
    assert!(!node_registry::room_proposal_finalized(&registry, 1));

    node_registry::remove_room_proposal_for_testing(&mut registry, 1);
    node_registry::remove_rental_for_testing(&mut registry, 1, &mut client_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_CAPACITY, location = xaisen_contract::node_registry)]
fun order_room_invalid_capacity_aborts() {
    let mut owner_ctx = ctx(OWNER, 52);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);
    let mut client_ctx = ctx(CLIENT, 53);

    node_registry::order_room(
        &mut registry,
        room(),
        0,
        payment(&mut client_ctx),
        &clock,
        &mut client_ctx,
    );

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun cast_room_vote_records_vote_without_finalizing() {
    let mut owner_ctx = ctx(OWNER, 54);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    // Register 3 workers
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = ctx(WORKER_B, 55);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = ctx(WORKER_C, 56);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wc_ctx), &clock, &mut wc_ctx);

    assert!(node_registry::active_worker_count_for_testing(&registry) == 3);

    // Client orders room
    let mut client_ctx = ctx(CLIENT, 57);
    node_registry::order_room(&mut registry, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    // Only 1 of 3 votes - should not finalize
    let mut vote_ctx = ctx(OWNER, 58);
    node_registry::cast_room_vote(&mut registry, 1, 1, 1, &clock, &mut vote_ctx);

    assert!(!node_registry::room_proposal_finalized(&registry, 1));

    // Cleanup
    node_registry::remove_room_proposal_for_testing(&mut registry, 1);
    node_registry::remove_rental_for_testing(&mut registry, 1, &mut client_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 2, &mut wb_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 3, &mut wc_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun cast_room_vote_majority_finalizes_assignment() {
    let mut owner_ctx = ctx(OWNER, 60);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    // Register 3 workers
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = ctx(WORKER_B, 61);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = ctx(WORKER_C, 62);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wc_ctx), &clock, &mut wc_ctx);

    // Client orders room
    let mut client_ctx = ctx(CLIENT, 63);
    node_registry::order_room(&mut registry, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    // 2 of 3 workers vote for worker 1 → majority
    let mut wb_vote_ctx = ctx(WORKER_B, 64);
    node_registry::cast_room_vote(&mut registry, 2, 1, 1, &clock, &mut wb_vote_ctx);
    let mut wc_vote_ctx = ctx(WORKER_C, 65);
    node_registry::cast_room_vote(&mut registry, 3, 1, 1, &clock, &mut wc_vote_ctx);

    assert!(node_registry::room_proposal_finalized(&registry, 1));
    assert!(node_registry::rental_status(&registry, 1) == node_registry::rental_active_for_testing());
    assert!(node_registry::rental_worker_node_id(&registry, 1) == 1);
    assert!(node_registry::worker_active_rental_id(&registry, 1) == 1);

    // Complete the rental to free worker
    let mut complete_ctx = ctx(CLIENT, 66);
    node_registry::complete_rental(&mut registry, 1, &clock, &mut complete_ctx);

    // Cleanup
    node_registry::remove_room_proposal_for_testing(&mut registry, 1);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 2, &mut wb_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 3, &mut wc_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_NODE_OWNER, location = xaisen_contract::node_registry)]
fun cast_room_vote_non_owner_aborts() {
    let mut owner_ctx = ctx(OWNER, 70);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);

    let mut client_ctx = ctx(CLIENT, 71);
    node_registry::order_room(&mut registry, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    // OTHER tries to vote using OWNER's node_id
    let mut other_ctx = ctx(OTHER, 72);
    node_registry::cast_room_vote(&mut registry, 1, 1, 1, &clock, &mut other_ctx);

    node_registry::remove_room_proposal_for_testing(&mut registry, 1);
    node_registry::remove_rental_for_testing(&mut registry, 1, &mut client_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_ALREADY_VOTED, location = xaisen_contract::node_registry)]
fun cast_room_vote_duplicate_aborts() {
    let mut owner_ctx = ctx(OWNER, 73);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    // Register 3 workers so a single vote doesn't auto-finalize
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = ctx(WORKER_B, 74);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = ctx(WORKER_C, 75);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wc_ctx), &clock, &mut wc_ctx);

    let mut client_ctx = ctx(CLIENT, 76);
    node_registry::order_room(&mut registry, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    let mut vote_ctx1 = ctx(OWNER, 77);
    node_registry::cast_room_vote(&mut registry, 1, 1, 1, &clock, &mut vote_ctx1);
    let mut vote_ctx2 = ctx(OWNER, 78);
    node_registry::cast_room_vote(&mut registry, 1, 1, 1, &clock, &mut vote_ctx2);

    node_registry::remove_room_proposal_for_testing(&mut registry, 1);
    node_registry::remove_rental_for_testing(&mut registry, 1, &mut client_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 2, &mut wb_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 3, &mut wc_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_PROPOSAL_EXPIRED, location = xaisen_contract::node_registry)]
fun cast_room_vote_expired_aborts() {
    let mut owner_ctx = ctx(OWNER, 80);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);

    let mut client_ctx = ctx(CLIENT, 81);
    node_registry::order_room(&mut registry, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    // Advance clock past deadline
    clock::set_for_testing(&mut clock, node_registry::default_vote_deadline_ms_for_testing() + 1);
    let mut vote_ctx = ctx(OWNER, 82);
    node_registry::cast_room_vote(&mut registry, 1, 1, 1, &clock, &mut vote_ctx);

    node_registry::remove_room_proposal_for_testing(&mut registry, 1);
    node_registry::remove_rental_for_testing(&mut registry, 1, &mut client_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun cancel_expired_order_refunds_client() {
    let mut owner_ctx = ctx(OWNER, 85);
    let mut clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);

    let mut client_ctx = ctx(CLIENT, 86);
    node_registry::order_room(&mut registry, room(), CAPACITY, payment(&mut client_ctx), &clock, &mut client_ctx);

    assert!(node_registry::rental_exists(&registry, 1));

    // Advance past deadline
    clock::set_for_testing(&mut clock, node_registry::default_vote_deadline_ms_for_testing() + 1);
    node_registry::cancel_expired_order(&mut registry, 1, &clock, &mut client_ctx);

    assert!(!node_registry::rental_exists(&registry, 1));

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

// ── New tests: role proposals and voting ────────────────────────────

#[test]
fun propose_role_creates_proposal() {
    let mut owner_ctx = ctx(OWNER, 90);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);

    let mut propose_ctx = ctx(OWNER, 91);
    node_registry::propose_role(
        &mut registry,
        1,
        1,
        node_registry::role_sfu_for_testing(),
        &clock,
        &mut propose_ctx,
    );

    assert!(node_registry::role_proposal_exists(&registry, 1));
    // With only 1 worker, auto-passes
    assert!(node_registry::has_worker_role(&registry, 1));
    assert!(node_registry::worker_role(&registry, 1) == node_registry::role_sfu_for_testing());

    node_registry::remove_role_proposal_for_testing(&mut registry, 1);
    node_registry::remove_role_map_entry_for_testing(&mut registry, 1);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
fun cast_role_vote_majority_assigns_role() {
    let mut owner_ctx = ctx(OWNER, 95);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    // Register 3 workers
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = ctx(WORKER_B, 96);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = ctx(WORKER_C, 97);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wc_ctx), &clock, &mut wc_ctx);

    // OWNER proposes node 2 as COORDINATOR
    let mut propose_ctx = ctx(OWNER, 98);
    node_registry::propose_role(
        &mut registry,
        1,
        2,
        node_registry::role_coordinator_for_testing(),
        &clock,
        &mut propose_ctx,
    );

    // Should not be finalized yet (1 of 3)
    assert!(!node_registry::has_worker_role(&registry, 2));

    // WORKER_B votes → 2 of 3 = majority
    let mut wb_vote_ctx = ctx(WORKER_B, 99);
    node_registry::cast_role_vote(&mut registry, 2, 1, &clock, &mut wb_vote_ctx);

    assert!(node_registry::has_worker_role(&registry, 2));
    assert!(node_registry::worker_role(&registry, 2) == node_registry::role_coordinator_for_testing());

    node_registry::remove_role_proposal_for_testing(&mut registry, 1);
    node_registry::remove_role_map_entry_for_testing(&mut registry, 2);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 2, &mut wb_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 3, &mut wc_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_INVALID_ROLE, location = xaisen_contract::node_registry)]
fun propose_role_invalid_role_aborts() {
    let mut owner_ctx = ctx(OWNER, 100);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = registered_registry(&clock, &mut owner_ctx);

    let mut propose_ctx = ctx(OWNER, 101);
    node_registry::propose_role(
        &mut registry,
        1,
        1,
        5,
        &clock,
        &mut propose_ctx,
    );

    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

#[test]
#[expected_failure(abort_code = E_NOT_ACTIVE_WORKER, location = xaisen_contract::node_registry)]
fun inactive_worker_cannot_vote_on_role() {
    let mut owner_ctx = ctx(OWNER, 105);
    let clock = clock::create_for_testing(&mut owner_ctx);
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(&mut owner_ctx);

    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut owner_ctx), &clock, &mut owner_ctx);
    let mut wb_ctx = ctx(WORKER_B, 106);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wb_ctx), &clock, &mut wb_ctx);
    let mut wc_ctx = ctx(WORKER_C, 107);
    node_registry::register_worker(&mut registry, uri(), hash(1), PRICE, stake(&mut wc_ctx), &clock, &mut wc_ctx);

    // Propose role
    let mut propose_ctx = ctx(OWNER, 108);
    node_registry::propose_role(&mut registry, 1, 2, node_registry::role_sfu_for_testing(), &clock, &mut propose_ctx);

    // Deactivate WORKER_B then try to vote
    node_registry::set_worker_active_for_testing(&mut registry, 2, false);
    let mut wb_vote_ctx = ctx(WORKER_B, 109);
    node_registry::cast_role_vote(&mut registry, 2, 1, &clock, &mut wb_vote_ctx);

    node_registry::remove_role_proposal_for_testing(&mut registry, 1);
    node_registry::remove_worker_for_testing(&mut registry, 1, &mut owner_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 2, &mut wb_ctx);
    node_registry::remove_worker_for_testing(&mut registry, 3, &mut wc_ctx);
    node_registry::destroy_registry_for_testing(registry);
    clock::destroy_for_testing(clock);
}

// ── Test helpers ────────────────────────────────────────────────────

fun registered_registry(
    clock: &clock::Clock,
    ctx: &mut tx_context::TxContext,
): node_registry::Registry<TEST_COIN> {
    let mut registry = node_registry::new_registry_for_testing<TEST_COIN>(ctx);
    node_registry::register_worker(
        &mut registry,
        uri(),
        hash(1),
        PRICE,
        stake(ctx),
        clock,
        ctx,
    );
    registry
}

fun ctx(sender: address, hint: u64): tx_context::TxContext {
    tx_context::new_from_hint(sender, hint, 0, 0, 0)
}

fun stake(ctx: &mut tx_context::TxContext): coin::Coin<TEST_COIN> {
    coin::mint_for_testing<TEST_COIN>(node_registry::min_worker_stake_for_testing(), ctx)
}

fun payment(ctx: &mut tx_context::TxContext): coin::Coin<TEST_COIN> {
    coin::mint_for_testing<TEST_COIN>(PRICE, ctx)
}

fun uri(): vector<u8> {
    b"ipfs://xaisen-worker"
}

fun updated_uri(): vector<u8> {
    b"ipfs://xaisen-worker-updated"
}

fun room(): vector<u8> {
    b"xaisen-room"
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
