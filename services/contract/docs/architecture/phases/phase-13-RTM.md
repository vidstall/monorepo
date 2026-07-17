# REQUIREMENTS TRACEABILITY MATRIX -- Phase 13: Economic Layer
Date: 2026-03-12
Verified by: Verification Agent

---

## REQ-ID Coverage

| REQ-ID | Requirement Description | Test File | Test Function(s) | Verified? |
|--------|------------------------|-----------|-------------------|-----------|
| ECON-01 | Reward distribution based on SessionProofs (BASE_RATE x median_bytes x quality_multiplier) | economic_layer_tests.move | test_distribute_rewards_happy_path, test_quality_multiplier_excellent/good/acceptable/slash, test_median_computation, test_escrow_remainder_returns_to_creator | YES |
| ECON-02 | Slashing for misbehavior returns Coin to economic layer (never burns) | economic_layer_tests.move | test_slash_returns_coin | YES |
| ECON-03 | Validator dual-key signed SessionProofs submitted on-chain post-session | economic_layer_tests.move | test_submit_proof_happy_path (storage via test helper), test_submit_proof_invalid_sig_aborts (proves ed25519 check exists), test_submit_proof_no_session_wallet_aborts, test_submit_proof_duplicate_aborts | YES (partial -- ed25519 happy path requires integration test) |

## PHASE SUCCESS CRITERIA

| # | Criterion | Test(s) proving it | Verified? |
|---|-----------|-------------------|-----------|
| SC-1 | Validator submits dual-key signed SessionProof on-chain post-session | test_submit_proof_happy_path (storage path), test_submit_proof_invalid_sig_aborts (sig verification gate) | YES (partial -- full ed25519 in integration) |
| SC-2 | Reward distribution uses BASE_RATE x median_bytes x quality_multiplier formula | test_distribute_rewards_happy_path, test_escrow_remainder_returns_to_creator | YES |
| SC-3 | Slashing for misbehavior returns Coin to economic layer (never burns) | test_slash_returns_coin | YES |

## ERROR CODE COVERAGE (650-661)

| Code | Constant | expected_failure test | Verified? |
|------|----------|-----------------------|-----------|
| 650 | E_PAUSED | NONE | NO -- GAP |
| 651 | E_NOT_ROOM_CREATOR | test_create_escrow_not_creator_aborts | YES |
| 652 | E_ROOM_NOT_FOUND | NONE (tested indirectly via escrow.room_id check) | NO -- GAP |
| 653 | E_ROOM_NOT_PENDING | NONE | NO -- GAP |
| 654 | E_INVALID_SIGNATURE | test_submit_proof_invalid_sig_aborts | YES |
| 655 | E_SESSION_WALLET_NOT_FOUND | test_submit_proof_no_session_wallet_aborts | YES |
| 656 | E_ALREADY_SUBMITTED | test_submit_proof_duplicate_aborts | YES |
| 657 | E_ROOM_NOT_CLOSED | test_distribute_rewards_room_not_closed_aborts | YES |
| 658 | E_INSUFFICIENT_PROOFS | test_distribute_rewards_insufficient_proofs_aborts | YES |
| 659 | E_ALREADY_DISTRIBUTED | test_distribute_rewards_already_distributed_aborts | YES |
| 660 | E_ZERO_ESCROW | test_create_escrow_zero_payment_aborts | YES |
| 661 | E_RELAY_NOT_REGISTERED | NONE | NO -- GAP |

## CROSS-DOMAIN INTEGRATION CONTRACTS

| IC | Description | Verdict | Notes |
|----|-------------|---------|-------|
| IC-1 | submit_session_proof TX Argument Contract | MATCH | 17 args (4 objects + 2 IDs + 7 u64 + 4 vector<u8>) + ctx implicit. TS PTB has 17 args. Order matches. |
| IC-2 | BCS Message Byte Layout Contract | MATCH | Field order identical: room_id, relay_miner_id, 7x u64. TS uses hexToBytes for IDs (32 bytes) + bcs.u64() for numerics. Move uses bcs::to_bytes. Both produce 120-byte message. |
| IC-3 | EscrowCreated Event Contract | MATCH | On-chain emits escrow_id, room_id, creator, amount. TS ErrorCodes reference correct codes. |
| IC-4 | Dual-Key Public Key Passing Contract | MATCH | TS passes pubkeyPublic/pubkeySession as vector<u8> via bcs.vector(bcs.u8()). Move verifies via blake2b256(0x00 || pubkey). |
| IC-5 | Event Name/Field Alignment Contract | MATCH | EscrowCreated, SessionProofSubmitted, RewardsDistributed, RelaySlashed names match. |

## ERROR CODE CROSS-DOMAIN SYNC

| Move constant | Move value | TS constant | TS value | Match? |
|---------------|-----------|-------------|----------|--------|
| E_PAUSED | 650 | ErrorCodes.economicLayer.E_PAUSED | 650 | YES |
| E_NOT_ROOM_CREATOR | 651 | ErrorCodes.economicLayer.E_NOT_ROOM_CREATOR | 651 | YES |
| E_ROOM_NOT_FOUND | 652 | ErrorCodes.economicLayer.E_ROOM_NOT_FOUND | 652 | YES |
| E_ROOM_NOT_PENDING | 653 | ErrorCodes.economicLayer.E_ROOM_NOT_PENDING | 653 | YES |
| E_INVALID_SIGNATURE | 654 | ErrorCodes.economicLayer.E_INVALID_SIGNATURE | 654 | YES |
| E_SESSION_WALLET_NOT_FOUND | 655 | ErrorCodes.economicLayer.E_SESSION_WALLET_NOT_FOUND | 655 | YES |
| E_ALREADY_SUBMITTED | 656 | ErrorCodes.economicLayer.E_ALREADY_SUBMITTED | 656 | YES |
| E_ROOM_NOT_CLOSED | 657 | ErrorCodes.economicLayer.E_ROOM_NOT_CLOSED | 657 | YES |
| E_INSUFFICIENT_PROOFS | 658 | ErrorCodes.economicLayer.E_INSUFFICIENT_PROOFS | 658 | YES |
| E_ALREADY_DISTRIBUTED | 659 | ErrorCodes.economicLayer.E_ALREADY_DISTRIBUTED | 659 | YES |
| E_ZERO_ESCROW | 660 | ErrorCodes.economicLayer.E_ZERO_ESCROW | 660 | YES |
| E_RELAY_NOT_REGISTERED | 661 | ErrorCodes.economicLayer.E_RELAY_NOT_REGISTERED | 661 | YES |

---

## TEST GAP ANALYSIS

### [GAP-001] E_PAUSED (650) -- no expected_failure test for any entry function
- **Type**: MISSING TEST
- **Risk**: MEDIUM -- paused check exists in code but no test proves it fires abort 650
- **Tests needed**: test_create_escrow_when_paused_aborts, test_submit_proof_when_paused_aborts, test_distribute_rewards_when_paused_aborts
- **Affects**: ECON-01, ECON-02, ECON-03

### [GAP-002] E_ROOM_NOT_FOUND (652) -- no expected_failure test
- **Type**: MISSING TEST
- **Risk**: LOW -- create_escrow checks has_room; tested indirectly by submit_session_proof's room_id == escrow.room_id check
- **Test needed**: test_create_escrow_room_not_found_aborts
- **Affects**: ECON-01

### [GAP-003] E_ROOM_NOT_PENDING (653) -- no expected_failure test
- **Type**: MISSING TEST
- **Risk**: MEDIUM -- a room in ACTIVE or CLOSED status should not accept escrow creation
- **Test needed**: test_create_escrow_room_not_pending_aborts
- **Affects**: ECON-01

### [GAP-004] E_RELAY_NOT_REGISTERED (661) -- no expected_failure test
- **Type**: MISSING TEST
- **Risk**: MEDIUM -- submit_session_proof check for relay registration not tested
- **Test needed**: test_submit_proof_relay_not_registered_aborts
- **Affects**: ECON-03

---

## SUMMARY

| Metric | Count |
|--------|-------|
| Total REQ-IDs | 3 |
| Covered by tests | 3 |
| REQ-ID coverage | 100% |
| Total success criteria | 3 |
| Covered by tests | 3 |
| SC coverage | 100% |
| Total error codes (650-661) | 12 |
| Covered by expected_failure tests | 8 |
| Error code coverage | 67% (4 gaps) |
| Integration Contracts (IC-1 to IC-5) | 5 MATCH, 0 MISMATCH |
| Error code cross-domain sync | 12/12 MATCH |

---

## TEST EXECUTION REPORT

### MOVE TESTS
- **Total**: 132
- **Passed**: 132
- **Failed**: 0
- **Result**: ALL PASS

### OVERALL: ALL PASS

---

## VERDICT

Phase 13 requirements (ECON-01, ECON-02, ECON-03) are covered by tests. All 3 success criteria have test proof. All 5 integration contracts MATCH between Move and TypeScript. All 12 error codes sync between Move and TS constants.

**4 error code abort paths lack dedicated expected_failure tests** (E_PAUSED x3 entry points = 1 gap since same pattern, E_ROOM_NOT_FOUND, E_ROOM_NOT_PENDING, E_RELAY_NOT_REGISTERED). These are MEDIUM risk gaps -- the code contains the assert! checks, but no test proves they fire correctly.

**Recommendation**: Generate 4 gap-closure tests in `tests/verification/phase-13-unit-gaps.move` to reach 100% abort code coverage before marking Phase 13 complete.

**ed25519 happy-path note**: The test suite correctly uses `add_proof_for_testing` to bypass ed25519 signature construction (which cannot be done in Move test framework). The `test_submit_proof_invalid_sig_aborts` test proves the ed25519 gate exists by providing garbage signatures. Full happy-path ed25519 verification requires an integration test with a real validator daemon TX.
