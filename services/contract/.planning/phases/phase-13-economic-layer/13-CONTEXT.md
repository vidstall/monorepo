# Phase 13: Economic Layer - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

## Phase Boundary

Phase 13 implements the full economic layer: SessionProof submission with on-chain ed25519 dual-key verification, median aggregation from multiple validators, work-based reward distribution (BASE_RATE x median_bytes x quality_multiplier), slashing that returns Coin (never burns), room escrow (user deposits tokens on creation, distributed post-session), and signaling node reward/slash criteria. This phase is SPLIT into two sub-phases:

- **Phase 13a (OnChain):** New `economic_layer.move` module + Room struct extensions (escrow, session_proofs, assignments). All reward/slash/proof logic on-chain.
- **Phase 13b (OffChain + Integration):** Validator daemon proof submission, shared types, signaling reward criteria, cross-domain integration.

## Implementation Decisions

### Escrow Flow
- Full escrow: Room creation deposits `Coin<TOKEN>` into Room's `Balance<TOKEN>`
- Session close triggers reward distribution from escrow to relays/validators/CPs
- Undistributed remainder returns to room creator

### Signature Verification
- On-chain ed25519 verification using `sui::ed25519::ed25519_verify`
- Both public key + session wallet key signatures required on SessionProof
- Chain verifies: (1) sig_public matches registered validator, (2) sig_session matches assigned session wallet

### Reward Formula (from PRD, locked in)
- `relay_reward = BASE_RATE(100) x median_bytes_transferred x quality_multiplier`
- Quality multiplier thresholds: ≤2% loss → 10000bp, ≤5% → 8000bp, ≤10% → 5000bp, >10% → 0 (slash)
- Split: 70% relay, 15% validator, 15% CP (from NetworkRegistry.reward_ratios)
- Validator reward: accuracy_score based on closeness to median
- All math in basis points (u64)

### Slashing
- quality_multiplier = 0 → slash relay's StakePosition via `staking::slash()`
- Returns `Coin<TOKEN>` — never burns, economic layer decides redistribution
- Validator false proof (far from median) → slash validator stake

### Signaling Node Economics (inherited from Phase 11 deferral)
- Signaling nodes earn rewards for routing SDP/ICE messages
- Slashing for: dropping connections, offline during assigned sessions
- Reward formula: simpler than relay (flat rate per session routed, not bytes-based)

### Median Aggregation
- Minimum validators per room: 3 (from constants.move DEFAULT_MIN_VALIDATORS_PER_ROOM=2, but PRD says 3 for statistical validity)
- Median of bytes_transferred, packet_loss, latency, jitter across all validator proofs
- Outlier detection: validator whose report is >2 standard deviations from median gets accuracy penalty

### Phase Split
- **13a (OnChain):** economic_layer.move, Room extensions, SessionProof struct, ed25519 verify, median aggregation, quality multiplier, reward calculation, slash logic, escrow deposit/distribute, signaling reward constants
- **13b (OffChain):** Validator daemon proof assembly + dual-key signing + TX submission, shared types (SessionProof, events), signaling daemon reward tracking

### Claude's Discretion
- Error code namespace for economic_layer.move (next available range in 600+)
- Whether to extend room_manager.move or create a separate economic_layer.move
- Exact signaling reward rate (suggest: fixed SESSION_ROUTE_REWARD constant)
- Whether median aggregation uses sorting or incremental approach

## Specific Ideas

- Quality multiplier thresholds as constants in constants.move (not magic numbers)
- SessionProof struct in economic_layer.move (not room_manager — separation of concerns)
- Room extensions: add `escrow: Balance<TOKEN>`, `session_proofs: vector<SessionProof>`, `assigned_validators: vector<ID>`
- `submit_session_proof()` is an entry function callable by any address (chain verifies via ed25519)
- `distribute_rewards()` is callable after room closes and sufficient proofs are submitted
- RTT writeback: after proof submission, call `relay_registry::update_rtt()` with validator-measured latency

## Existing Code Insights

### Reusable Assets
- `staking::slash()` — returns Coin, ready to use
- `validator_registry::reveal_session_wallet()` — post-session identity reveal
- `validator_registry::set_reputation()` — update validator accuracy score
- `relay_registry::update_rtt()` — write back validator-probed RTT
- `relay_registry::set_reputation()` — update relay reputation
- `constants.move` — BASE_RATE=100, reward ratios 7000/1500/1500
- `relay/src/metrics.ts` — MetricsTracker already tracks bytesForwarded, packetsLost, jitter

### Established Patterns
- Registry modules: `create(&AdminCap)` for deploy, `init_for_testing()` for tests
- `public(package)` for internal mutations, entry functions for external calls
- Error codes in named constants, never inline magic numbers
- All math in basis points (u64), sums to 10_000
- `setup_phase2()` in helpers.move for test bootstrapping — Phase 13 adds `setup_phase3()`

### Integration Points
- `room_manager.move` — Room struct needs escrow + session_proofs fields
- `validator_registry.move` — reveal_session_wallet, set_reputation, increment_session_count
- `relay_registry.move` — update_rtt, set_reputation
- `staking.move` — slash() for misbehavior
- `network_registry.move` — read reward_ratios, base_rate
- Validator daemon — new proof submission flow
- Shared types — new SessionProof + economic events

## Deferred Ideas

- Governance mechanism for BASE_RATE — use fixed constant for thesis
- Hybrid SFU+MCU mode — resolved NO, one mode per room
- Relay failover mid-session — Phase 14 integration
- Cross-registry cleanup on unregister — Phase 14+ (TD-P11-04)
- ZK proof for validator identity — post-thesis

## Revision Log

- **2026-03-12 (initial):** Context gathered via /dvconf:discuss-phase 13
  - Decisions: full escrow, on-chain ed25519, include signaling economics
  - Split into Phase 13a (OnChain) and Phase 13b (OffChain)
