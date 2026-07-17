# PM REVIEW -- Phase 13: Economic Layer ADD

Phase: 13
Spec reference: PRD sections 7, 8.6, 9.3, 11; REQUIREMENTS.md ECON-01/02/03; ROADMAP.md SC-1/2/3
Reviewer: PM Agent
Date: 2026-03-12
ADD version: DRAFT (2026-03-12)

---

## SUMMARY

The Phase 13 ADD defines a new `economic_layer.move` module that implements room escrow, dual-key signed SessionProof submission with on-chain ed25519 verification, median aggregation of validator reports, work-based reward distribution (BASE_RATE x median_bytes x quality_multiplier), and slashing that returns Coin (never burns). It also covers off-chain validator daemon proof submission and shared type updates. The ADD is a well-structured top-layer addition with no circular dependencies, clear integration contracts, and thorough resolution of proposal disagreements.

---

## REQUIREMENTS COVERAGE

| Requirement | ADD Coverage | Status |
|-------------|-------------|--------|
| ECON-01: Reward distribution (BASE_RATE x median_bytes x quality_multiplier) | `distribute_rewards()` implements exact formula. Quality multiplier thresholds defined in constants. 70/15/15 split from NetworkRegistry. | COVERED |
| ECON-02: Slashing returns Coin (never burns) | `staking::slash()` returns `Coin<TOKEN>`, transferred to escrow creator. RelaySlashed event emitted. | COVERED |
| ECON-03: Dual-key signed SessionProofs on-chain post-session | `submit_session_proof()` with ed25519 verification of both wallet A and wallet B signatures. IC-2 BCS layout defined. | COVERED |

## SUCCESS CRITERIA COVERAGE

| Criterion | ADD Enables | Status |
|-----------|-------------|--------|
| SC-1: Validator submits dual-key signed SessionProof on-chain post-session | Yes -- `submit_session_proof()` entry function, IC-1 TX contract, IC-4 dual-key contract | PASS |
| SC-2: Reward distribution uses BASE_RATE x median_bytes x quality_multiplier | Yes -- `distribute_rewards()` with `compute_median()`, `compute_quality_multiplier()`, constants | PASS |
| SC-3: Slashing for misbehavior returns Coin to economic layer (never burns) | Yes -- slash path in `distribute_rewards()` calls `staking::slash()`, transfers Coin to creator | PASS |

---

## LENS RESULTS

[Economics]       PASS -- Work-based rewards eliminate self-reporting. Median aggregation resists < N/2 malicious validators. Quality thresholds in basis points. Slash returns Coin, never burns. Sybil attack requires controlling > half of validators per room.

[Distributed Sys] PASS -- Proofs submitted post-session (no real-time consensus needed). MIN_PROOFS=2 is the minimum for a median. Median of even count is (a+b)/2 which is fine for u64 integer arithmetic.

[Security]        WARNING -- See P1-1 below. Identity concealment maintained: session wallet revealed only at proof submission time. Dual-key ed25519 verification with on-chain pubkey-to-address binding prevents forgery.

[Chain Boundary]  PASS -- Only metrics touch the chain (bytes, loss, latency). No media data. EscrowCreated event includes escrow_id for daemon discovery (IMP-1). IC-2 BCS layout is the critical integration point and is well-specified.

[Sui Move]        WARNING -- See P1-2 and P1-3 below. RoomEscrow as separate shared object per room is correct (avoids breaking RoomManager). Dependency direction is clean. `staking::slash` is `public(package)` so economic_layer can call it.

[WebRTC/Media]    PASS -- Not directly relevant. No media on chain. Validator measurement data (bytes, latency, jitter, loss) comes from off-chain observation. unique_peers deferred (0 placeholder) is acceptable.

---

## CRITICAL ISSUES (must resolve before implementation)

None.

---

## WARNINGS (should resolve, will not block implementation)

### [P1-1] submit_session_proof caller identity: who calls the TX?

The ADD's sequence diagram shows "Validator Daemon (session wallet B)" calling `submit_session_proof`. The function checks `lookup_session_wallet(sender)` where sender is `tx_context::sender(ctx)`. This means the TX must be sent FROM session wallet B.

However, the function also takes `pubkey_session` as a parameter and verifies `to_sui_address(pubkey_session) == session_wallet_address`. If the TX sender IS wallet B, then the contract can derive the session wallet address from `tx_context::sender(ctx)` and the pubkey_session parameter merely confirms the caller passed their own pubkey. This is correct and sound -- the lookup_session_wallet call validates that the sender is an authorized session wallet.

The concern: the validator daemon must sign the Sui transaction itself with wallet B's keypair (not wallet A). This is already how the validator daemon works (it operates from the session wallet). No issue, just flagging for implementer awareness.

**Recommendation**: Add a comment in the ADD under IC-1 stating explicitly: "The Sui transaction MUST be signed by wallet B (session wallet). The contract uses tx_context::sender(ctx) to look up the session wallet mapping."

### [P1-2] distribute_rewards takes `relay_stake: &mut StakePosition` as parameter

The `distribute_rewards` function signature takes `relay_stake: &mut StakePosition` as a direct parameter. StakePosition is an Owned object (owned by the relay operator). This means:

- The relay operator must cooperate to provide their StakePosition for slashing.
- If the relay refuses to present their StakePosition, the reward distribution cannot proceed.

In practice, this is mitigated because:
(a) The caller of `distribute_rewards` is "anyone" -- it does not require the relay operator to call it.
(b) However, the StakePosition must be passed as a TX argument, and only the owner can include an Owned object in a TX.

This creates a design tension. If the relay operator is being slashed, they have no incentive to cooperate. The ADD should clarify who is expected to call `distribute_rewards` and how the StakePosition is obtained.

**Options**:
- Option A: Make StakePosition a Shared object (breaking change from Phase 1 design).
- Option B: Only attempt slash when the relay operator themselves calls distribute_rewards. If someone else calls it and quality is slash-worthy, skip the slash and just zero out the relay reward. This preserves the "slash returns Coin" invariant for cooperative slashing while not blocking reward distribution.
- Option C: Use a two-phase approach -- distribute_rewards marks the relay for slashing (sets a flag), and a separate `execute_slash` function is called by the relay operator (or governance) with the StakePosition.

**PM Recommendation**: Option C is cleanest. But for thesis scope, Option B is pragmatic -- zero out relay reward when quality is slash-worthy and the StakePosition is not provided, with slash execution deferred. The OnChain agent should decide during implementation. This does NOT block the ADD.

### [P1-3] PLAN.md is stale relative to ADD

The PLAN.md still references error codes 600-611 (Task 2) and uses `NodeSlashed` event naming (Task 4). The ADD correctly resolves these to 650-661 and `RelaySlashed`. The PLAN should be updated to match the ADD before execution begins, to avoid confusion during task routing.

**Recommendation**: Update PLAN.md error codes from 600-611 to 650-661 and event names from `NodeSlashed` to `RelaySlashed` before executing Task 2 or Task 4.

### [P1-4] PRD deviation: escrow in separate RoomEscrow vs embedded in Room

The PRD (section 7) specifies `escrow: Balance<TOKEN>` and `session_proofs: vector<SessionProof>` as fields inside the Room object. The ADD creates a separate `RoomEscrow` shared object linked by `room_id` instead.

This deviation is JUSTIFIED because:
- The existing `RoomInfo` struct has `has store, copy, drop` abilities. Adding `Balance<TOKEN>` would require removing `copy` and `drop`, which is a breaking change to all existing room_manager callers.
- `RoomManager` stores rooms in a `Table<ID, RoomInfo>`. Embedding a Balance in a Table value requires the value to have only `store` (no `copy`/`drop`), which again breaks the existing API.
- A separate shared object per room has minimal contention (see ADD contention analysis).

The ADD correctly notes this as a design decision. No spec update is needed since the PRD section 7 is a conceptual model, not a Move implementation specification.

### [P1-5] SessionProof struct in ADD omits signature fields

The ADD's `SessionProof` struct definition (lines 83-95) does not include `sig_public` and `sig_session` fields. The signatures are verified at submission time but not stored. This is correct for storage efficiency -- once verified, storing 128 bytes of signatures per proof is wasteful. However, the PLAN.md Task 2 description includes `sig_public: vector<u8>` and `sig_session: vector<u8>` in the struct.

The ADD's approach (verify-then-discard) is better. The OnChain agent should follow the ADD, not the PLAN.

**Recommendation**: Clarify in the PLAN update that signatures are verified at submission time but NOT stored in the SessionProof struct. The ADD is correct.

### [P1-6] Reward formula: potential u64 overflow

The reward computation is: `BASE_RATE(100) * median_bytes * quality_multiplier / BASIS_POINTS`

If median_bytes is large (e.g., a long session with high throughput), `100 * median_bytes * 10000` could overflow u64. The maximum u64 is ~1.8 x 10^19. With BASE_RATE=100 and quality_multiplier=10000:
- `100 * 10000 = 1_000_000`
- Max median_bytes before overflow: ~1.8 x 10^13 bytes = ~18 petabytes

This is unrealistic for a single session, so overflow is not a practical concern. But the OnChain agent should add a comment documenting the safe range.

**Recommendation**: Add a code comment in the reward computation noting the overflow boundary.

---

## OPEN QUESTIONS RAISED

### [Q1] Who calls distribute_rewards when relay should be slashed?

See P1-2 above. The StakePosition ownership model creates a friction point for adversarial slashing. This does not block Phase 13 implementation but should be tracked for Phase 14 resolution.

**Suggested resolution**: For Phase 13, accept Option B (skip slash if StakePosition not provided, zero out relay reward). Track as tech debt for Phase 14.

---

## SOURCE OF TRUTH COMPLIANCE

| Rule | ADD Status | Verified |
|------|-----------|----------|
| No floating point | PASS | All math in basis points (u64). quality_multiplier values: 0, 5000, 8000, 10000. Loss thresholds: 200, 500, 1000 bps. |
| Cap constructors package-private | N/A | economic_layer has no cap objects. |
| Paused flag checked | PASS | All three entry functions (create_escrow, submit_session_proof, distribute_rewards) check is_paused(net_reg). |
| Slash returns Coin | PASS | staking::slash returns Coin<TOKEN>. economic_layer transfers to creator. Never burns. |
| RTT is validator-probed | PASS | submit_session_proof writes avg_latency_ms to RelayRegistry via update_rtt. |
| Rewards are work-based | PASS | BASE_RATE x median_bytes_transferred x quality_multiplier / BASIS_POINTS. |
| Validator identity hidden during session | PASS | reveal_session_wallet called only at proof submission (post-session). |
| Stake lock enforced | N/A | economic_layer does not call withdraw_stake. |
| Chain carries no media | PASS | Only numeric metrics (bytes count, loss bps, latency ms, jitter ms). |
| Scoring weights sum to 10_000 | PASS | Reward ratios read from NetworkRegistry (validated at set time: relay+validator+cp == 10000). |

---

## INTEGRATION CONTRACTS REVIEW

### IC-1: submit_session_proof TX Argument Contract
**Status**: COMPLETE and UNAMBIGUOUS
- 18 explicit arguments (+ ctx implicit) with types
- Error codes mapped to daemon handling behavior
- Pubkey-passing approach correctly resolved (IMP-5)

### IC-2: BCS Message Byte Layout Contract
**Status**: COMPLETE and CRITICAL
- Exact field order with byte sizes (120 bytes total)
- On-chain reconstruction pseudocode provided
- Both agents required to reference IC-2 in code comments
- This is the single most fragile integration point. Any field order mismatch = signature verification failure (error 654).

### IC-3: EscrowCreated Event Contract
**Status**: COMPLETE
- escrow_id field included (IMP-1 fix)
- OffChain storage mapping documented

### IC-4: Dual-Key Public Key Passing Contract
**Status**: COMPLETE
- Address derivation formula documented (blake2b256(0x00 || pubkey))
- Raw Ed25519 sign clarified (not Sui TX signing)

### IC-5: Event Name/Field Alignment Contract
**Status**: COMPLETE
- All four events aligned between on-chain and off-chain
- Field names and types matched exactly

---

## ERROR CODE NAMESPACE

The 650-661 range assignment is CORRECT. The full namespace map has no collisions:

| Range   | Module                 |
|---------|------------------------|
| 100-102 | network_registry       |
| 200-202 | staking                |
| 300     | miner_store            |
| 400-404 | registration           |
| 500-506 | room_manager           |
| 510-515 | control_plane_registry |
| 520-525 | relay_registry         |
| 530-535 | validator_registry     |
| 540-542 | user_registry          |
| 600-604 | signaling_registry     |
| 650-661 | economic_layer         |

Gap between 604 and 650 leaves room for signaling expansion (605-649). Good.

---

## ARCHITECT IMPROVEMENTS ASSESSMENT

All six improvements (IMP-1 through IMP-6) are well-justified:

| IMP | Description | Assessment |
|-----|-------------|------------|
| IMP-1 | EscrowCreated event adds escrow_id | Essential -- daemon needs object ID for TX construction |
| IMP-2 | RelaySlashed not NodeSlashed | Correct -- matches on-chain event struct name |
| IMP-3 | RewardsDistributed field alignment | Correct -- off-chain types must match on-chain exactly |
| IMP-4 | Error codes 650-661 not 600-611 | Better than renumbering Phase 11 code. No regression risk. |
| IMP-5 | Pubkeys passed as TX args | Necessary -- ValidatorRegistry stores addresses (hashes), not raw keys |
| IMP-6 | CP reward deferred | Pragmatic -- avoids coupling to unbuilt CP voting consensus |

---

## CALLER AUDIT REQUIRED

```
Function changed: validator_registry::lookup_session_wallet -- NEW function
Callers to verify:
  - economic_layer.move -- primary caller (submit_session_proof)
  - validator_registry_tests.move -- add test for new function
Status: [ ] confirmed all callers updated
```

---

## DEFERRED ITEMS ASSESSMENT

The 7 deferred items are all correctly scoped out of Phase 13. None of them block the three success criteria. The most important deferral is CP reward distribution (IMP-6) -- the RewardsDistributed event still records the CP pool amount, so the data is available when the feature is built later.

---

## VERDICT

### PM APPROVED

The Phase 13 ADD is ready for implementation. It satisfies all three requirements (ECON-01, ECON-02, ECON-03), enables all three success criteria, complies with all Source of Truth rules, and provides complete integration contracts.

**Before execution begins, the following non-blocking items should be addressed:**

1. Update PLAN.md to match ADD error codes (650-661) and event names (RelaySlashed) -- see P1-3.
2. OnChain agent should be aware of the StakePosition ownership question (P1-2) and implement accordingly. Option B (skip slash if StakePosition not provided) is acceptable for thesis scope.
3. OnChain agent should follow the ADD's SessionProof struct (without signature fields), not the PLAN's version -- see P1-5.
4. Add overflow boundary comment in reward computation -- see P1-6.

**Blocking requirement for final sign-off**: QC APPROVED must be obtained after implementation, before phase completion.

---

*Reviewed: 2026-03-12 by PM Agent*
*ADD status: APPROVED for implementation*
*Next step: `/dvconf:execute-phase 13`*
