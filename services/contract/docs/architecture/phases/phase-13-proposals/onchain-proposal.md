DESIGN PROPOSAL -- OnChain: economic_layer.move
Author: OnChain Agent
Phase: 13
Date: 2026-03-12

PURPOSE:
  Implements the full economic layer: room escrow, dual-key signed SessionProof
  submission with on-chain ed25519 verification, median aggregation across
  validator reports, work-based reward distribution, and slashing for poor quality.

OWNS:
  - RoomEscrow (shared object per room -- holds escrowed TOKEN balance)
  - SessionProof (struct stored inside RoomEscrow -- validator-attested work records)
  - Reward computation logic (quality multiplier, median aggregation, accuracy scoring)
  - Slash trigger logic (delegates actual slash to staking::slash)

---

## STRUCTS / TYPES

### SessionProof (has store, copy, drop)

Stored inside `RoomEscrow.proofs`. One per validator per room session.

```move
public struct SessionProof has store, copy, drop {
    validator_id:      ID,          // miner_id of the validator
    room_id:           ID,          // room this proof covers
    relay_miner_id:    ID,          // relay node being attested
    packets_forwarded: u64,         // work metric
    bytes_transferred: u64,         // work metric (primary for reward calc)
    unique_peers:      u64,         // distinct users observed
    duration_seconds:  u64,         // session duration
    avg_latency_ms:    u64,         // quality metric
    packet_loss_bps:   u64,         // quality metric (basis points, 200 = 2%)
    jitter_ms:         u64,         // quality metric
    submitted_at:      u64,         // epoch of submission
}
```

Design note: `packet_loss_bps` uses basis points (not percent u8 from PRD) for consistency
with the all-basis-points rule. 200 bps = 2% loss. The PRD says `packet_loss_percent: u8`
but we convert to bps at the contract boundary for integer-only math.

### RoomEscrow (has key)

Separate shared object per room. NOT embedded in RoomInfo to avoid breaking existing
room_manager interfaces. Linked by `room_id`.

```move
public struct RoomEscrow has key {
    id:          UID,
    room_id:     ID,
    creator:     address,
    escrow:      Balance<TOKEN>,
    proofs:      vector<SessionProof>,
    distributed: bool,
}
```

Design note: RoomEscrow is a shared object (not owned) so that any validator can submit
proofs to it and anyone can trigger distribute_rewards after room closes. `has key` only
(no `store`) -- requires a `transfer_to` pattern if we ever need to move it, but since
it's shared this is not needed.

### Events

```move
public struct EscrowCreated has copy, drop {
    room_id: ID,
    creator: address,
    amount:  u64,
}

public struct SessionProofSubmitted has copy, drop {
    room_id:      ID,
    validator_id: ID,
    relay_id:     ID,
    bytes:        u64,
    loss_bps:     u64,
}

public struct RewardsDistributed has copy, drop {
    room_id:       ID,
    relay_reward:  u64,
    validator_pool: u64,
    cp_pool:       u64,
    remainder:     u64,
}

public struct RelaySlashed has copy, drop {
    room_id:       ID,
    relay_miner_id: ID,
    slash_amount:  u64,
}
```

---

## PUBLIC API

### Entry Functions

#### create_escrow

```move
public fun create_escrow(
    net_reg:      &NetworkRegistry,
    room_mgr:     &RoomManager,
    room_id:      ID,
    payment:      Coin<TOKEN>,
    ctx:          &mut TxContext,
)
```

- Checks: not paused (E_PAUSED=600), room exists (E_ROOM_NOT_FOUND=602),
  sender is room creator (E_NOT_ROOM_CREATOR=601), room status is PENDING (E_ROOM_NOT_PENDING=603),
  coin value > 0 (E_ZERO_ESCROW=610)
- Creates a RoomEscrow shared object with the payment balance
- Emits EscrowCreated event

#### submit_session_proof

```move
public fun submit_session_proof(
    net_reg:           &NetworkRegistry,
    escrow:            &mut RoomEscrow,
    validator_reg:     &mut ValidatorRegistry,
    relay_reg:         &mut RelayRegistry,
    room_id:           ID,
    relay_miner_id:    ID,
    packets_forwarded: u64,
    bytes_transferred: u64,
    unique_peers:      u64,
    duration_seconds:  u64,
    avg_latency_ms:    u64,
    packet_loss_bps:   u64,
    jitter_ms:         u64,
    sig_public:        vector<u8>,
    sig_session:       vector<u8>,
    ctx:               &mut TxContext,
)
```

- Checks: not paused (600), escrow.room_id matches room_id, relay is registered (E_RELAY_NOT_REGISTERED=611)
- **Dual-key ed25519 verification** (see section below)
- Checks no duplicate submission from same validator (E_ALREADY_SUBMITTED=606)
- Creates SessionProof struct, pushes to escrow.proofs
- Calls `validator_registry::reveal_session_wallet(validator_reg, session_wallet)` to reveal identity
- Calls `validator_registry::increment_session_count(validator_reg, miner_id)`
- Calls `relay_registry::update_rtt(relay_reg, relay_miner_id, avg_latency_ms)` for RTT writeback
- Emits SessionProofSubmitted event

#### distribute_rewards

```move
public fun distribute_rewards(
    net_reg:       &NetworkRegistry,
    escrow:        &mut RoomEscrow,
    room_mgr:      &RoomManager,
    relay_reg:     &mut RelayRegistry,
    validator_reg: &mut ValidatorRegistry,
    relay_stake:   &mut StakePosition,
    ctx:           &mut TxContext,
)
```

- Checks: not paused (600), room is closed (E_ROOM_NOT_CLOSED=607),
  sufficient proofs (E_INSUFFICIENT_PROOFS=608), not already distributed (E_ALREADY_DISTRIBUTED=609)
- Computes median of bytes_transferred and packet_loss_bps across all proofs
- Computes quality_multiplier from median_packet_loss_bps
- If quality_multiplier == 0: slash relay via `staking::slash(relay_stake, slash_amount, ctx)`
  - slash_amount = `staking::amount(relay_stake) * SLASH_PERCENTAGE_BPS / BASIS_POINTS`
  - Slashed coin is transferred to escrow creator (economic layer decides redistribution)
  - Emits RelaySlashed event
  - Updates relay reputation to 0 via `relay_registry::set_reputation`
- If quality_multiplier > 0: distribute from escrow balance
  - Read reward_ratios from NetworkRegistry (70/15/15)
  - `total_reward = base_rate_per_mb * median_bytes / 1_000_000 * quality_multiplier / BASIS_POINTS`
  - Cap total_reward at escrow balance
  - relay_share = total_reward * ratio_relay / BASIS_POINTS
  - validator_share = total_reward * ratio_validator / BASIS_POINTS
  - cp_share = total_reward * ratio_cp / BASIS_POINTS
  - Transfer relay_share as Coin to relay operator
  - Distribute validator_share proportionally by accuracy_score to each validator
  - Transfer cp_share to a CP pool address (or split equally among active CPs -- Phase 13 uses equal split since CP voting consensus is not yet built)
  - Update relay reputation based on quality_multiplier
  - Update validator reputations based on accuracy scores
- Remainder of escrow balance returned to creator as Coin
- Mark escrow.distributed = true
- Emits RewardsDistributed event

### Package Functions

#### compute_quality_multiplier

```move
public(package) fun compute_quality_multiplier(median_packet_loss_bps: u64): u64
```

Returns basis-point multiplier based on thresholds from constants.move:
- loss <= LOSS_THRESHOLD_EXCELLENT (200 bps / 2%) -> QUALITY_EXCELLENT_BPS (10_000)
- loss <= LOSS_THRESHOLD_GOOD (500 bps / 5%) -> QUALITY_GOOD_BPS (8_000)
- loss <= LOSS_THRESHOLD_ACCEPTABLE (1000 bps / 10%) -> QUALITY_ACCEPTABLE_BPS (5_000)
- loss > 1000 bps -> QUALITY_SLASH_BPS (0) -- triggers slash

#### compute_median

```move
public(package) fun compute_median(values: &vector<u64>): u64
```

- Copies the vector, sorts via insertion sort (O(n^2) but n <= ~10 validators, acceptable)
- Returns middle element for odd count, average of two middle elements for even count
- Asserts vector is non-empty

#### compute_accuracy_score

```move
public(package) fun compute_accuracy_score(validator_value: u64, median: u64): u64
```

- Returns a basis-point score (0-10000) measuring how close the validator's reported value
  is to the median
- Formula: `10_000 - min(10_000, abs_diff * 10_000 / max(median, 1))`
- A validator whose report exactly matches the median gets 10_000
- A validator whose report is 100% off gets 0
- Used to weight validator reward distribution and detect outliers

### Read Accessors

```move
public fun escrow_room_id(e: &RoomEscrow): ID
public fun escrow_creator(e: &RoomEscrow): address
public fun escrow_balance(e: &RoomEscrow): u64
public fun escrow_proof_count(e: &RoomEscrow): u64
public fun escrow_is_distributed(e: &RoomEscrow): bool
```

### Test-Only

```move
#[test_only]
public fun init_for_testing(ctx: &mut TxContext)
```

Creates a minimal shared RoomEscrow for testing. Not needed for the module itself (escrows
are created via create_escrow), but useful if other future modules need to test against
an existing escrow.

---

## DEPENDS ON

| Module | What we import | Why |
|--------|---------------|-----|
| `network_registry` | `is_paused`, `reward_ratios`, `base_rate_per_mb`, `ratio_relay/validator/cp` | Pause check, reward parameters |
| `room_manager` | `has_room`, `borrow_room`, `room_creator`, `room_status` | Verify room exists, creator, status |
| `validator_registry` | `has_session_wallet`, `reveal_session_wallet`, `set_reputation`, `increment_session_count` | Dual-key verify, post-proof updates |
| `relay_registry` | `is_registered`, `update_rtt`, `set_reputation`, `borrow_info`, `info_operator` | Relay existence check, RTT writeback, operator lookup |
| `staking` | `slash`, `amount` | Slash relay/validator stake |
| `constants` | Quality thresholds, basis_points, room statuses, min proofs | Threshold constants |
| `token` | `TOKEN` type | Balance/Coin type parameter |
| `sui::ed25519` | `ed25519_verify` | Dual-key signature verification |

Dependency direction: economic_layer depends on existing lower modules (registry, staking,
constants). No existing module depends on economic_layer. This is a clean top-layer addition.

---

## ERROR CODES

Namespace: 600-611 (from reserved Phase 3+ range 750-1099 in skill file, but actual
codes 600+ are free since relay_registry uses 520-525, validator_registry uses 530-535).

| Code | Constant | Trigger |
|------|----------|---------|
| 600 | E_PAUSED | System paused via NetworkRegistry |
| 601 | E_NOT_ROOM_CREATOR | Caller is not the room creator |
| 602 | E_ROOM_NOT_FOUND | Room ID not in RoomManager |
| 603 | E_ROOM_NOT_PENDING | Room status is not PENDING (for create_escrow) |
| 604 | E_INVALID_SIGNATURE | ed25519 signature verification failed |
| 605 | E_SESSION_WALLET_NOT_FOUND | Session wallet not registered in ValidatorRegistry |
| 606 | E_ALREADY_SUBMITTED | Validator already submitted a proof for this escrow |
| 607 | E_ROOM_NOT_CLOSED | Room is not CLOSED (for distribute_rewards) |
| 608 | E_INSUFFICIENT_PROOFS | Fewer than MIN_PROOFS_FOR_DISTRIBUTION proofs submitted |
| 609 | E_ALREADY_DISTRIBUTED | Rewards already distributed for this escrow |
| 610 | E_ZERO_ESCROW | Payment coin has zero value |
| 611 | E_RELAY_NOT_REGISTERED | Relay miner_id not in RelayRegistry |

---

## EVENTS EMITTED

| Event | When |
|-------|------|
| EscrowCreated | create_escrow succeeds |
| SessionProofSubmitted | submit_session_proof succeeds (after signature verification) |
| RewardsDistributed | distribute_rewards completes (with reward breakdown) |
| RelaySlashed | quality_multiplier = 0 triggers relay slash |

---

## ED25519 DUAL-KEY VERIFICATION

### Background

Validators have two identities:
1. **Public wallet (A)** -- their registered miner address, known on-chain
2. **Session wallet (B)** -- an ephemeral address assigned before the session, hidden during session

The dual-key pattern ensures:
- During the session, nobody knows which registered validator is B
- After the session, the validator proves they controlled both A and B

### Verification Flow in submit_session_proof

```
1. Caller provides: sig_public (64 bytes), sig_session (64 bytes)

2. Construct the message to verify:
   message = BCS::serialize(room_id, relay_miner_id, packets_forwarded,
             bytes_transferred, unique_peers, duration_seconds,
             avg_latency_ms, packet_loss_bps, jitter_ms)

   The message is deterministic -- same fields, same order, same encoding.

3. Look up the caller's session wallet:
   session_wallet = ctx.sender()
   assert!(validator_registry::has_session_wallet(validator_reg, session_wallet),
           E_SESSION_WALLET_NOT_FOUND)

   The caller is the SESSION wallet. The on-chain mapping session_wallet -> miner_id
   exists in ValidatorRegistry.session_wallets.

4. Derive the validator's public key from the session wallet mapping:
   miner_id = from the session_wallets table (retrieved during reveal)
   validator_info = validator_registry::borrow_info(validator_reg, miner_id)
   public_wallet = validator_info.operator

5. Verify sig_session:
   sui::ed25519::ed25519_verify(
       &sig_session,
       &address_to_public_key(session_wallet),  // session wallet's ed25519 pubkey
       &message
   )

   This proves the session wallet holder signed this proof.

6. Verify sig_public:
   sui::ed25519::ed25519_verify(
       &sig_public,
       &address_to_public_key(public_wallet),  // public wallet's ed25519 pubkey
       &message
   )

   This proves the public wallet holder also signed the same proof.

7. Both pass -> validator controlled both wallets -> identity confirmed.
```

### Implementation Note on Public Keys

Sui's `ed25519_verify` requires the raw 32-byte ed25519 public key, not the Sui address.
The caller must provide the public keys as additional parameters, OR we derive them.

**Chosen approach**: The caller (validator daemon) passes the public keys alongside the
signatures. The contract verifies that `sui::address::from_bytes(hash(pubkey))` matches
the expected address. This avoids storing public keys on-chain while still verifying
the key-to-address binding.

Updated signature for submit_session_proof includes:
- `pubkey_public: vector<u8>` (32 bytes -- ed25519 public key of public wallet A)
- `pubkey_session: vector<u8>` (32 bytes -- ed25519 public key of session wallet B)

The contract:
1. Verifies `to_sui_address(pubkey_public) == validator_info.operator`
2. Verifies `to_sui_address(pubkey_session) == session_wallet`
3. Verifies `ed25519_verify(sig_public, pubkey_public, message)`
4. Verifies `ed25519_verify(sig_session, pubkey_session, message)`

This is 4 checks total -- 2 address bindings + 2 signature verifications.

---

## MEDIAN COMPUTATION APPROACH

### Algorithm

Insertion sort on a copy of the values vector, then pick middle.

```
fun compute_median(values: &vector<u64>): u64 {
    let n = values.length();
    assert!(n > 0);

    // Copy into mutable vector
    let mut sorted = vector::empty<u64>();
    let mut i = 0;
    while (i < n) {
        sorted.push_back(*values.borrow(i));
        i = i + 1;
    };

    // Insertion sort -- O(n^2) but n is small (2-10 validators)
    let mut i = 1;
    while (i < n) {
        let key = *sorted.borrow(i);
        let mut j = i;
        while (j > 0 && *sorted.borrow(j - 1) > key) {
            *sorted.borrow_mut(j) = *sorted.borrow(j - 1);
            j = j - 1;
        };
        *sorted.borrow_mut(j) = key;
        i = i + 1;
    };

    // Pick median
    if (n % 2 == 1) {
        *sorted.borrow(n / 2)
    } else {
        (*sorted.borrow(n / 2 - 1) + *sorted.borrow(n / 2)) / 2
    }
}
```

### Gas Cost Analysis

With MIN_PROOFS_FOR_DISTRIBUTION = 2 and typical 3-5 validators, the sort is
trivially cheap. Even with 10 validators, insertion sort on u64 values is negligible
compared to the ed25519 verification cost.

---

## CONSTANTS TO ADD (Task 1)

New constants in `sources/core/constants.move`:

```move
// -- Quality multiplier thresholds (basis points) --
const QUALITY_EXCELLENT_BPS: u64    = 10_000;  // 100% reward
const QUALITY_GOOD_BPS: u64         =  8_000;  // 80% reward
const QUALITY_ACCEPTABLE_BPS: u64   =  5_000;  // 50% reward
const QUALITY_SLASH_BPS: u64        =      0;  // 0% reward, triggers slash

// -- Packet loss thresholds (basis points; 100 bps = 1%) --
const LOSS_THRESHOLD_EXCELLENT: u64  =   200;  // <= 2%
const LOSS_THRESHOLD_GOOD: u64       =   500;  // <= 5%
const LOSS_THRESHOLD_ACCEPTABLE: u64 = 1_000;  // <= 10%

// -- Slash parameters --
const SLASH_PERCENTAGE_BPS: u64 = 1_000;  // 10% of stake

// -- Signaling economics --
const SIGNALING_SESSION_REWARD: u64 = 50;  // flat rate per session routed

// -- Proof aggregation --
const MIN_PROOFS_FOR_DISTRIBUTION: u64 = 2;  // minimum validator proofs needed
```

Each constant gets a `public fun` accessor following the existing pattern.

---

## INTEGRATION POINTS

### staking::slash (existing)

```move
public(package) fun slash(
    position: &mut StakePosition, amount: u64, ctx: &mut TxContext,
): Coin<TOKEN>
```

economic_layer calls this when quality_multiplier = 0. The returned Coin is transferred
to the room creator (simplest redistribution for Phase 13). Future phases may implement
a slash treasury.

### validator_registry::reveal_session_wallet (existing)

```move
public(package) fun reveal_session_wallet(
    registry: &mut ValidatorRegistry,
    session_wallet: address,
)
```

Called in submit_session_proof after successful dual-key verification. This removes the
session_wallet -> miner_id mapping from the table (identity is now public).

**Note**: reveal_session_wallet currently removes the mapping. We need to read the
miner_id BEFORE calling reveal. Flow:
1. Read miner_id from session_wallets table (need a new accessor or use has_session_wallet + a lookup function)
2. Verify signatures
3. Call reveal_session_wallet (which removes the mapping)

**New accessor needed in validator_registry.move**:

```move
public(package) fun lookup_session_wallet(
    r: &ValidatorRegistry, wallet: address
): ID
```

This returns the miner_id for a session wallet without removing it. The economic_layer
reads it, verifies, then calls reveal_session_wallet to clean up.

### validator_registry::increment_session_count (existing)

Called after successful proof submission. No changes needed.

### validator_registry::set_reputation (existing)

Called after reward distribution with updated reputation based on accuracy_score.

### relay_registry::update_rtt (existing)

Called in submit_session_proof to write back the validator-measured avg_latency_ms.
This is the "validator_probed_rtt" mentioned in the PRD -- replaces any self-reported RTT.

### relay_registry::set_reputation (existing)

Called after reward distribution to update relay reputation based on quality_multiplier.

### room_manager (read-only)

economic_layer reads room info via `has_room`, `borrow_room`, `room_creator`, `room_status`.
No mutations to room_manager from economic_layer.

### network_registry (read-only)

economic_layer reads `reward_ratios`, `base_rate_per_mb`, `is_paused`.
No mutations to network_registry from economic_layer.

---

## REQUIRED CHANGES TO EXISTING MODULES

### validator_registry.move -- Add lookup_session_wallet

```move
/// Look up which validator owns a session wallet (without removing it).
public(package) fun lookup_session_wallet(
    r: &ValidatorRegistry, wallet: address
): ID {
    assert!(table::contains(&r.session_wallets, wallet), E_NO_SESSION);
    *table::borrow(&r.session_wallets, wallet)
}
```

This is a non-breaking addition (new function, no signature changes to existing functions).

---

## OPEN QUESTIONS

1. **Public key passing vs on-chain storage**: The design passes ed25519 public keys as
   parameters to submit_session_proof. An alternative is to store public keys during
   validator registration. Passing as params keeps the registry simpler and avoids
   a migration, but adds 64 bytes to each proof TX. Given the low frequency of proof
   submissions (once per session per validator), this overhead is acceptable.

2. **CP reward distribution mechanism**: Phase 13 distributes the CP share equally among
   all active CPs since CP voting consensus is not built yet (Phase 3 Room Lifecycle).
   The `distribute_rewards` function will need a reference to ControlPlaneRegistry to
   enumerate active CPs, or it can transfer the CP pool to a designated CP treasury
   address for later distribution. Simpler approach: transfer CP pool to escrow creator
   along with remainder, with a note that CP distribution is deferred. This avoids
   coupling to ControlPlaneRegistry in Phase 13.

   **Proposed resolution**: Transfer the CP share to the escrow creator along with the
   remainder. The RewardsDistributed event records the CP pool amount so off-chain
   systems can track it. Full CP distribution is deferred to the Room Lifecycle phase.

3. **Validator reward distribution in distribute_rewards**: Each validator needs to receive
   their accuracy-weighted share. This requires knowing each validator's operator address
   to send them Coins. Since we already have validator_id (miner_id) in the proofs, we
   can look up the operator address via `validator_registry::borrow_info`.

---

## TEST PLAN OVERVIEW (Task 3)

### helpers.move Addition

```move
#[test_only]
public fun setup_phase3(ctx: &mut TxContext) {
    setup_phase2(ctx);   // bootstraps Phase 1 + Phase 2 shared objects
    // Phase 3 has no additional shared objects to bootstrap --
    // RoomEscrow objects are created per-room via create_escrow
}
```

### Test Cases (18 tests)

**Escrow creation (3 tests)**:
1. `test_create_escrow` -- happy path, escrow created with correct balance and room_id
2. `test_create_escrow_not_creator_aborts` -- abort 601 when non-creator calls
3. `test_create_escrow_zero_payment_aborts` -- abort 610 when coin value is 0

**Proof submission (4 tests)**:
4. `test_submit_proof_happy_path` -- valid dual-key signed proof accepted, stored in escrow
5. `test_submit_proof_invalid_sig_aborts` -- abort 604 when ed25519 verification fails
6. `test_submit_proof_no_session_wallet_aborts` -- abort 605 when session wallet not registered
7. `test_submit_proof_duplicate_aborts` -- abort 606 when same validator submits twice

**Reward distribution (4 tests)**:
8. `test_distribute_rewards_happy_path` -- median computed, 70/15/15 split correct
9. `test_distribute_rewards_room_not_closed_aborts` -- abort 607
10. `test_distribute_rewards_insufficient_proofs_aborts` -- abort 608
11. `test_distribute_rewards_already_distributed_aborts` -- abort 609

**Quality multiplier (4 tests)**:
12. `test_quality_multiplier_excellent` -- loss 150 bps (<= 200) -> 10000
13. `test_quality_multiplier_good` -- loss 400 bps (<= 500) -> 8000
14. `test_quality_multiplier_acceptable` -- loss 800 bps (<= 1000) -> 5000
15. `test_quality_multiplier_slash` -- loss 1500 bps (> 1000) -> 0, relay slashed

**Median and accuracy (2 tests)**:
16. `test_median_computation` -- odd count (3 values) and even count (4 values)
17. `test_validator_accuracy_scoring` -- exact match = 10000, 50% off = 5000, 100% off = 0

**Edge cases (1 test)**:
18. `test_escrow_remainder_returns_to_creator` -- when total_reward < escrow balance,
    remainder goes back to creator

### Test Infrastructure Notes

- Tests will use `sui::ed25519` test helpers or construct valid ed25519 keypairs in test code
- If ed25519 test signing is not available in the Move test framework, the signature
  verification tests may need to use `#[test_only]` bypass functions that skip signature
  checks. This is a known limitation of Move unit tests for cryptographic operations.
  The actual verification is tested via integration tests (validator daemon submitting real TXs).
- Each test creates its own RoomEscrow via create_escrow, submits proofs, then distributes

---

## FILE LAYOUT

```
sources/
  core/constants.move           -- Task 1: add economic constants + accessors
  registry/economic_layer.move  -- Task 2: new module (SessionProof, RoomEscrow, all logic)

tests/
  helpers.move                  -- Task 3: add setup_phase3()
  registry/economic_layer_tests.move  -- Task 3: 18 tests
```

No new directories needed. `economic_layer.move` goes in `sources/registry/` following
the existing pattern for modules that manage shared registry-like objects.

---

## RISK MITIGATION

1. **ed25519 API compatibility**: Sui's `sui::ed25519::ed25519_verify` function signature
   must be verified during implementation. The exact parameter order (sig, pubkey, msg)
   and encoding (raw bytes vs BCS) needs confirmation against the Sui framework source.

2. **Balance arithmetic overflow**: All reward calculations use basis points (u64).
   The largest intermediate value is `base_rate * median_bytes * quality_multiplier`.
   With base_rate=100, median_bytes up to 10GB (10_000_000_000), and quality=10_000,
   the max intermediate is 100 * 10^10 * 10^4 = 10^16, well within u64 range (max ~1.8*10^19).
   No overflow risk for realistic values.

3. **Shared object contention on RoomEscrow**: Each room has its own RoomEscrow (not a
   singleton). Contention is limited to validators of the same room submitting proofs
   concurrently. With 2-5 validators per room and proofs submitted sequentially (post-session),
   this is low risk.
