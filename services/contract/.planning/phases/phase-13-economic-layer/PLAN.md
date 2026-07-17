# Phase 13 Plan: Economic Layer
Date: 2026-03-12

## Goal
Validators submit dual-key signed SessionProofs on-chain, rewards are distributed work-based, and slashing returns Coin to the economic layer.

## Success Criteria
1. Validator submits dual-key signed SessionProof on-chain post-session
2. Reward distribution uses BASE_RATE x median_bytes x quality_multiplier formula
3. Slashing for misbehavior returns Coin to economic layer (never burns)

## Requirements Covered
- ECON-01: Reward distribution based on SessionProofs (BASE_RATE x median_bytes x quality_multiplier)
- ECON-02: Slashing for misbehavior returns Coin to economic layer (never burns)
- ECON-03: Validator dual-key signed SessionProofs submitted on-chain post-session

## Tasks

### Task 1: Add economic constants to constants.move
- **Agent**: OnChain
- **Files**: `sources/core/constants.move`
- **Requirements**: ECON-01 (partial — quality multiplier thresholds)
- **Depends on**: None
- **Description**: Add quality multiplier threshold constants (basis points):
  - `QUALITY_EXCELLENT_BPS = 10_000` (loss ≤ 200bp / 2%)
  - `QUALITY_GOOD_BPS = 8_000` (loss ≤ 500bp / 5%)
  - `QUALITY_ACCEPTABLE_BPS = 5_000` (loss ≤ 1000bp / 10%)
  - `QUALITY_SLASH_BPS = 0` (loss > 10%)
  - `LOSS_THRESHOLD_EXCELLENT = 200` (2% in bp)
  - `LOSS_THRESHOLD_GOOD = 500` (5%)
  - `LOSS_THRESHOLD_ACCEPTABLE = 1000` (10%)
  - `SLASH_PERCENTAGE_BPS = 1_000` (10% of stake slashed)
  - `SIGNALING_SESSION_REWARD = 50` (flat rate per session routed)
  - `MIN_PROOFS_FOR_DISTRIBUTION = 2` (minimum validators submitting proofs)
  - Accessors for all new constants

### Task 2: Create economic_layer.move module
- **Agent**: OnChain
- **Files**: `sources/registry/economic_layer.move`
- **Requirements**: ECON-01, ECON-02, ECON-03
- **Depends on**: Task 1
- **Description**: New module implementing the full economic layer:

  **Structs:**
  - `SessionProof { validator_id: ID, room_id: ID, relay_miner_id: ID, packets_forwarded: u64, bytes_transferred: u64, unique_peers: u64, duration_seconds: u64, avg_latency_ms: u64, packet_loss_bps: u64, jitter_ms: u64, sig_public: vector<u8>, sig_session: vector<u8>, submitted_at: u64 }`
  - `RoomEscrow { id: UID, room_id: ID, creator: address, escrow: Balance<TOKEN>, proofs: vector<SessionProof>, distributed: bool }`

  **Entry functions:**
  - `create_escrow(net_reg, room_manager, room_id, payment: Coin<TOKEN>, ctx)` — creator deposits tokens when creating room. Creates shared RoomEscrow object. Aborts if not room creator or room not PENDING.
  - `submit_session_proof(net_reg, escrow, validator_reg, relay_reg, room_id, relay_miner_id, packets_forwarded, bytes_transferred, unique_peers, duration_seconds, avg_latency_ms, packet_loss_bps, jitter_ms, sig_public: vector<u8>, sig_session: vector<u8>, ctx)` — verifies dual-key ed25519 signatures, verifies session wallet mapping in ValidatorRegistry, stores proof. Reveals session wallet. Increments validator session count. Writes back RTT to RelayRegistry.
  - `distribute_rewards(net_reg, escrow, relay_reg, validator_reg, relay_stake: &mut StakePosition, ctx)` — callable after room closed + min proofs submitted. Computes median bytes/loss, calculates quality multiplier, distributes: 70% relay (work-based), 15% validators (accuracy-based), 15% CP pool. Slashes relay if quality_multiplier=0. Returns remainder to creator. Marks escrow distributed.

  **Package functions:**
  - `compute_quality_multiplier(median_packet_loss_bps: u64): u64` — returns bp multiplier from thresholds
  - `compute_median(values: &vector<u64>): u64` — sort + pick middle
  - `compute_accuracy_score(validator_value: u64, median: u64): u64` — closeness to median in bp

  **Error codes (600-615):**
  - 600: E_PAUSED
  - 601: E_NOT_ROOM_CREATOR
  - 602: E_ROOM_NOT_FOUND
  - 603: E_ROOM_NOT_PENDING
  - 604: E_INVALID_SIGNATURE
  - 605: E_SESSION_WALLET_NOT_FOUND
  - 606: E_ALREADY_SUBMITTED (same validator can't submit twice)
  - 607: E_ROOM_NOT_CLOSED
  - 608: E_INSUFFICIENT_PROOFS
  - 609: E_ALREADY_DISTRIBUTED
  - 610: E_ZERO_ESCROW
  - 611: E_RELAY_NOT_REGISTERED

### Task 3: Write economic_layer tests
- **Agent**: OnChain
- **Files**: `tests/registry/economic_layer_tests.move`, `tests/helpers.move`
- **Requirements**: ECON-01, ECON-02, ECON-03 (coverage)
- **Depends on**: Task 2
- **Description**: Comprehensive test suite:
  - `test_create_escrow` — happy path, escrow created with correct balance
  - `test_create_escrow_not_creator_aborts` — abort 601
  - `test_submit_proof_happy_path` — valid proof accepted, stored
  - `test_submit_proof_invalid_sig_aborts` — abort 604 (bad ed25519)
  - `test_submit_proof_no_session_wallet_aborts` — abort 605
  - `test_submit_proof_duplicate_aborts` — abort 606
  - `test_distribute_rewards_happy_path` — median computed, correct split 70/15/15
  - `test_distribute_rewards_room_not_closed_aborts` — abort 607
  - `test_distribute_rewards_insufficient_proofs_aborts` — abort 608
  - `test_distribute_rewards_already_distributed_aborts` — abort 609
  - `test_quality_multiplier_excellent` — loss ≤ 2% → 10000bp
  - `test_quality_multiplier_good` — loss ≤ 5% → 8000bp
  - `test_quality_multiplier_acceptable` — loss ≤ 10% → 5000bp
  - `test_quality_multiplier_slash` — loss > 10% → 0bp, relay slashed
  - `test_median_computation` — odd/even validator counts
  - `test_validator_accuracy_scoring` — close to median = high score
  - `test_escrow_remainder_returns_to_creator` — undistributed tokens go back
  - `test_slash_returns_coin` — slash produces Coin, never burns
  - Add `setup_phase3()` to helpers.move (bootstraps Phase 1+2 objects + economic layer)

### Task 4: Update shared types for economic layer (OffChain)
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/packages/shared/src/types/constants.ts`
  - `dvconf-daemons/packages/shared/src/types/events.ts`
  - `dvconf-daemons/packages/shared/src/types/chain.ts`
- **Requirements**: ECON-03 (partial — type sync)
- **Depends on**: Task 2 (need final Move function signatures)
- **Description**:
  - Add error codes 600-611 to `ErrorCodes.economicLayer` in constants.ts
  - Add `SIGNALING_SESSION_REWARD` constant
  - Add event types: `SessionProofSubmitted`, `RewardsDistributed`, `NodeSlashed`, `EscrowCreated`
  - Add `economicLayerModuleName` to chain.ts for TX building

### Task 5: Upgrade validator daemon proof submission to on-chain TX
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/validator-daemon/src/session-proof.ts`
  - `dvconf-daemons/apps/validator-daemon/src/index.ts`
- **Requirements**: ECON-03
- **Depends on**: Task 4
- **Description**: Update the existing `session-proof.ts` to submit proofs on-chain:
  - Replace "NOT submitting" stub with actual `submit_session_proof` TX call
  - Build PTB: `economic_layer::submit_session_proof(...)` with all measurement fields + dual-key signatures
  - Use BCS serialization matching the Move struct layout (replace JSON.stringify)
  - Handle TX result (success/failure logging)
  - Update `logProofSummary` to reflect on-chain submission
  - Wire into daemon lifecycle: after room closes, collect measurements, build proof, submit TX

### Task 6: Add signaling node reward/slash constants to signaling daemon
- **Agent**: OffChain
- **Files**:
  - `dvconf-daemons/apps/signaling/src/index.ts`
  - `dvconf-daemons/packages/shared/src/types/constants.ts` (if not already in Task 4)
- **Requirements**: ECON-01 (partial — signaling economics)
- **Depends on**: Task 4
- **Description**: Add signaling-specific economic constants and tracking:
  - Track sessions routed count (already partially exists in signaling daemon)
  - Add `sessionsRouted` metric to signaling heartbeat/load reporting
  - Log reward eligibility (actual reward claim is future work — no on-chain signaling reward function yet, just constants and tracking)
  - Document signaling slashing criteria: dropping connections mid-session, offline during assigned sessions

## Execution Order

```
Task 1 (OnChain: constants) ─── sequential ──→ Task 2 (OnChain: economic_layer.move)
                                                    │
                                                    ├── sequential ──→ Task 3 (OnChain: tests)
                                                    │
                                                    └── sequential ──→ Task 4 (OffChain: shared types)
                                                                          │
                                                                          ├── sequential ──→ Task 5 (OffChain: validator proof TX)
                                                                          │
                                                                          └── sequential ──→ Task 6 (OffChain: signaling economics)
```

Tasks 5 and 6 can run **in parallel** (different files, no shared state).
Tasks 3 and 4 can run **in parallel** (OnChain tests vs OffChain types — different repos).

## Risks & Open Questions

1. **ed25519 verification in Move**: Sui's `sui::ed25519::ed25519_verify` expects specific message/signature formats. Need to verify exact API during implementation (message bytes, signature encoding, public key format).

2. **Median computation gas cost**: Sorting a vector of u64 on-chain is O(n log n). With MIN_PROOFS=2 and typical 3-5 validators, this is negligible. No concern.

3. **RoomEscrow as separate shared object**: Chosen over extending RoomInfo to avoid breaking existing room_manager interfaces. RoomEscrow is created alongside room and linked by room_id.

4. **Signaling reward claim**: On-chain function for signaling nodes to claim rewards is NOT in scope for Phase 13 — only constants, tracking, and documentation. Actual claim would need a `SignalingEscrow` or similar mechanism (defer to Phase 14 or post-thesis).

5. **CP reward distribution**: CPs that voted with winning majority share the CP portion. Since CP voting consensus is Phase 3 (room lifecycle, not yet built), Phase 13 distributes the CP portion equally among all CPs that are active. Full voting-weighted distribution is deferred.

6. **Error namespace**: Using 600-611 for economic_layer.move (previously marked as "reserved future 600-1099").
