PHASE ARCHITECTURE VERIFICATION -- Phase 13: Economic Layer
Date: 2026-03-12
ADD reference: docs/architecture/phases/phase-13-ADD.md
Reviewer: Architect Agent (Tech Lead Gate)

---

## TEST RESULTS

All 19 economic_layer_tests pass. 0 failures.
No open bugs in `.planning/bugs/`.

---

## BLUEPRINT vs AS-BUILT

### economic_layer.move (NEW)

  Boundary:     MATCH -- clean top-layer module, no module imports it
  Dependencies: MATCH -- imports network_registry, room_manager, validator_registry,
                relay_registry, staking, constants, token, sui::ed25519, sui::bcs, sui::hash
  Visibility:   MATCH -- entry functions are `public fun`, helpers are `public(package) fun`
  Verdict:      CONFORMS

### SessionProof struct

  ADD fields: validator_id, room_id, relay_miner_id, packets_forwarded,
              bytes_transferred, unique_peers, duration_seconds, avg_latency_ms,
              packet_loss_bps, jitter_ms, submitted_at
  Code fields: EXACT MATCH (all 11 fields, same types, same order)
  Abilities: ADD says `has store, copy, drop` -- code matches
  Verdict:      CONFORMS

### RoomEscrow struct

  ADD fields: id (UID), room_id (ID), creator (address), escrow (Balance<TOKEN>),
              proofs (vector<SessionProof>), distributed (bool)
  Code fields: EXACT MATCH (all 6 fields)
  Abilities: ADD says `has key` -- code matches
  Verdict:      CONFORMS

### Events

  EscrowCreated:          MATCH (escrow_id, room_id, creator, amount -- IMP-1 applied)
  SessionProofSubmitted:  MATCH (room_id, validator_id, relay_miner_id, bytes_transferred, packet_loss_bps)
  RewardsDistributed:     MATCH (room_id, relay_reward, validator_pool, cp_pool, remainder)
  RelaySlashed:           MATCH (room_id, relay_miner_id, slash_amount)
  Verdict:      CONFORMS

### Function Signatures

  create_escrow:
    ADD: (net_reg, room_mgr, room_id, payment, ctx)
    Code: EXACT MATCH
    Verdict: CONFORMS

  submit_session_proof:
    ADD: (net_reg, escrow, validator_reg, relay_reg, room_id, relay_miner_id,
          packets_forwarded, bytes_transferred, unique_peers, duration_seconds,
          avg_latency_ms, packet_loss_bps, jitter_ms, pubkey_public, pubkey_session,
          sig_public, sig_session, ctx)
    Code: EXACT MATCH (18 params)
    Verdict: CONFORMS

  distribute_rewards:
    ADD: (net_reg, escrow, room_mgr, relay_reg, validator_reg, relay_stake, ctx)
    Code: EXACT MATCH (7 params)
    Verdict: CONFORMS

  Package functions:
    compute_quality_multiplier: MATCH
    compute_median:             MATCH
    compute_accuracy_score:     MATCH
    Verdict: CONFORMS

  Read accessors:
    escrow_room_id, escrow_creator, escrow_balance, escrow_proof_count, escrow_is_distributed
    Code: EXACT MATCH
    Verdict: CONFORMS

### Error Codes (650-661)

  | Code | ADD Constant                   | Code Constant                  | MATCH |
  |------|-------------------------------|-------------------------------|-------|
  | 650  | E_PAUSED                      | E_PAUSED                      | YES   |
  | 651  | E_NOT_ROOM_CREATOR            | E_NOT_ROOM_CREATOR            | YES   |
  | 652  | E_ROOM_NOT_FOUND              | E_ROOM_NOT_FOUND              | YES   |
  | 653  | E_ROOM_NOT_PENDING            | E_ROOM_NOT_PENDING            | YES   |
  | 654  | E_INVALID_SIGNATURE           | E_INVALID_SIGNATURE           | YES   |
  | 655  | E_SESSION_WALLET_NOT_FOUND    | E_SESSION_WALLET_NOT_FOUND    | YES   |
  | 656  | E_ALREADY_SUBMITTED           | E_ALREADY_SUBMITTED           | YES   |
  | 657  | E_ROOM_NOT_CLOSED             | E_ROOM_NOT_CLOSED             | YES   |
  | 658  | E_INSUFFICIENT_PROOFS         | E_INSUFFICIENT_PROOFS         | YES   |
  | 659  | E_ALREADY_DISTRIBUTED         | E_ALREADY_DISTRIBUTED         | YES   |
  | 660  | E_ZERO_ESCROW                 | E_ZERO_ESCROW                 | YES   |
  | 661  | E_RELAY_NOT_REGISTERED        | E_RELAY_NOT_REGISTERED        | YES   |
  Verdict: CONFORMS

### constants.move (EXTENDED)

  ADD specifies 10 new constants. Implementation has all 10:
    QUALITY_EXCELLENT_BPS (10000), QUALITY_GOOD_BPS (8000),
    QUALITY_ACCEPTABLE_BPS (5000), QUALITY_SLASH_BPS (0),
    LOSS_THRESHOLD_EXCELLENT (200), LOSS_THRESHOLD_GOOD (500),
    LOSS_THRESHOLD_ACCEPTABLE (1000), SLASH_PERCENTAGE_BPS (1000),
    SIGNALING_SESSION_REWARD (50), MIN_PROOFS_FOR_DISTRIBUTION (2)
  All values match ADD. All have public fun accessors.
  Verdict: CONFORMS

### validator_registry.move (EXTENDED)

  ADD: add `lookup_session_wallet(r, wallet) -> ID` as `public(package)`
  Code: EXACT MATCH -- lines 181-186
  Also added: `has_session_wallet(r, wallet) -> bool` as `public(package)` (line 175)
    This is an additional helper not in ADD but used by economic_layer before lookup.
  Also added: `add_validator_for_testing` (test-only helper)
  Verdict: JUSTIFIED DEVIATION -- has_session_wallet is a non-breaking addition
           needed by economic_layer to check before aborting. Clean pattern.

### Integration Contracts

  IC-1 (submit_session_proof TX args):
    OffChain PTB construction in session-proof.ts matches:
    - 4 object refs (networkRegistry, escrow, validatorRegistry, relayRegistry)
    - 2 ID pure values (roomId, relayMinerId)
    - 7 u64 pure values
    - 2 vector<u8> pubkeys, 2 vector<u8> signatures
    Error handling: 654, 655, 656, 661 all handled per ADD
    Verdict: CONFORMS

  IC-2 (BCS Message Byte Layout):
    On-chain: economic_layer.move lines 198-209 -- exact field order, bcs::to_bytes
    Off-chain: session-proof.ts serializeProofBcs() lines 84-135 -- exact field order
    Both reference "IC-2" in comments.
    Total: 120 bytes (32+32+7*8) -- MATCH
    Verdict: CONFORMS

  IC-3 (EscrowCreated event):
    On-chain: emits escrow_id (IMP-1 applied) -- line 136
    Off-chain: EscrowCreated interface has escrow_id field -- events.ts line 149
    Verdict: CONFORMS

  IC-4 (Dual-Key Public Key Passing):
    On-chain: derives addresses from pubkeys via blake2b256(0x00 || pubkey) -- lines 217-228
    Off-chain: passes raw 32-byte pubkeys as TX args -- session-proof.ts lines 242-243
    Both sign with raw Ed25519Keypair.sign() -- session-proof.ts lines 167-168
    Verdict: CONFORMS

  IC-5 (Event Name/Field Alignment):
    EscrowCreated:          on-chain MATCH off-chain (events.ts)
    SessionProofSubmitted:  on-chain MATCH off-chain
    RewardsDistributed:     on-chain MATCH off-chain (uses validator_pool, cp_pool, remainder)
    RelaySlashed:           on-chain MATCH off-chain (not NodeSlashed -- IMP-2 applied)
    Verdict: CONFORMS

### OffChain shared types

  constants.ts: economicLayer error codes 650-661 -- MATCH on-chain
  events.ts: all 4 economic event interfaces -- MATCH on-chain structs (IC-5)
  SIGNALING_SESSION_REWARD = 50 -- MATCH on-chain constant
  Verdict: CONFORMS

### signaling_registry.move

  ADD says: keep error codes at 600-604, NO changes.
  Implementation: NOT MODIFIED (confirmed -- no signaling_registry changes in Phase 13)
  Verdict: CONFORMS

---

## DEVIATIONS

  [DEV-1] validator_registry -- added has_session_wallet() accessor
    Type: JUSTIFIED DEVIATION
    Reason: economic_layer needs to check session wallet existence before calling
            lookup_session_wallet to produce a cleaner error (E_SESSION_WALLET_NOT_FOUND=655
            instead of E_NO_SESSION=535). This is a non-breaking public(package) addition.
            The ADD only specified lookup_session_wallet but the guard function is a clean
            pattern consistent with other registry modules (e.g., relay_registry::is_registered).

  [DEV-2] Test count: 19 tests instead of 18
    Type: JUSTIFIED DEVIATION
    Reason: ADD test plan listed 18 tests. Implementation has 19 -- the extra test is
            test_slash_returns_coin which verifies the Source of Truth rule "Slash returns
            a Coin -- slashing never burns or redistributes." This is additive coverage.

  [DEV-3] PLAN error codes (600-611) vs ADD/implementation (650-661)
    Type: NOT A DEVIATION -- PLAN was written before the ADD resolved the namespace collision.
            The ADD is the canonical design document. Implementation correctly follows the ADD.

---

## TECH DEBT REVIEW

### Findings

  [TD-P13-001] Overflow risk in distribute_rewards reward calculation
    Severity: LOW (documented, bounded by practical session sizes)
    Dimension: Error handling gaps
    Location: economic_layer.move line 374 (base_rate * median_bytes * quality_multiplier / bp)
    Description: u64 multiplication could overflow for extreme values.
                 Documented inline with boundary analysis showing thesis-scope safety.
                 Production would need checked_mul or u128 intermediate.
    Refactor cost: SMALL (< 1 hour)
    Suggested fix: Use u128 cast for intermediate multiplication
    Blocks: none (safe within thesis parameters)

  [TD-P13-002] No test for E_ROOM_NOT_FOUND (652) in create_escrow
    Severity: LOW
    Dimension: Test coverage gaps
    Location: tests/registry/economic_layer_tests.move
    Description: Error code 652 (room not found) is not exercised by any test.
                 The test suite covers 651, 653, 660 for create_escrow but not 652.
    Refactor cost: SMALL (add one test)
    Suggested fix: Add test_create_escrow_room_not_found_aborts
    Blocks: none

  [TD-P13-003] No test for E_PAUSED (650) on any entry function
    Severity: LOW
    Dimension: Test coverage gaps
    Location: tests/registry/economic_layer_tests.move
    Description: The paused check is the first assert in all three entry functions
                 but no test verifies it. Consistent with prior phases (paused tests
                 are often deferred to integration).
    Refactor cost: SMALL (add one test)
    Suggested fix: Add test_create_escrow_paused_aborts
    Blocks: none

---

## MODULES ADDED/CHANGED

  - sources/registry/economic_layer.move -- NEW: escrow, proofs, rewards, slashing
  - sources/core/constants.move -- EXTENDED: 10 economic constants + accessors
  - sources/registry/validator_registry.move -- EXTENDED: lookup_session_wallet, has_session_wallet, add_validator_for_testing
  - tests/registry/economic_layer_tests.move -- NEW: 19 tests
  - tests/helpers.move -- EXTENDED: setup_phase3()
  - dvconf-daemons/packages/shared/src/types/constants.ts -- EXTENDED: economicLayer error codes
  - dvconf-daemons/packages/shared/src/types/events.ts -- EXTENDED: 4 economic event interfaces
  - dvconf-daemons/apps/validator-daemon/src/session-proof.ts -- REWRITTEN: BCS + PTB + submission

---

## ARCHITECTURE HEALTH TREND

  Phase 12: 8/10
  Phase 13: 8/10
  Direction: STABLE

  Coupling:    9/10 (economic_layer is clean top-layer; no module imports it)
  Cohesion:    9/10 (one module owns escrow + proofs + rewards + slash -- all related)
  Testability: 8/10 (ed25519 bypass via test helpers is pragmatic; 19 tests is thorough)
  Consistency: 8/10 (naming consistent, all ICs referenced in code comments)

---

## CROSS-PHASE INTEGRATION

  Phase 12 (relay_registry) --> Phase 13: CLEAN
    - economic_layer reads relay_registry::is_registered, borrow_info, update_rtt, set_reputation
    - All signatures match existing Phase 12 API
    - No Phase 12 code was broken

  Phase 11 (signaling_registry) --> Phase 13: CLEAN
    - Error code collision resolved by ADD (signaling keeps 600-604, economic uses 650-661)
    - No signaling code modified

  Phase 2 (room_manager, validator_registry) --> Phase 13: CLEAN
    - room_manager test helper add_room_for_testing added (non-breaking)
    - validator_registry extended with 2 package functions + 1 test helper (non-breaking)
    - staking extended with test helpers (non-breaking)

---

## VERIFICATION VERDICT: CONFORMS

All structs, function signatures, error codes, events, and integration contracts match
the approved ADD exactly. Two justified deviations (has_session_wallet accessor and
extra test) are additive improvements. Three low-severity tech debt items identified
(overflow documentation, two missing error path tests). No critical or structural issues.

All 19 on-chain tests pass. Off-chain types align with on-chain events per IC-5.
BCS serialization field order verified identical across Move and TypeScript per IC-2.
