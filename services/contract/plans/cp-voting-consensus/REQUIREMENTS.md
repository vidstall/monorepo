# Requirements — cp-voting-consensus

## Metadata
```yaml
quangflow_version: "1.1.0"
feature_slug: cp-voting-consensus
status: M1-FINAL
pm_mode: hands-on
milestones: 2
team_mode: true
team_composition:
  - role: lead
    focus: "Orchestrator — coordinate team, user decisions"
    type: main-session
  - role: onchain-agent
    focus: "Sui Move contracts: formula module, ballot redesign, verification, reputation"
    ownership: "sources/**, tests/**"
    agent_type: gsd-executor
    skill_file: "docs/skills/ONCHAIN_AGENT_SKILL.md"
  - role: offchain-agent
    focus: "CP daemon: scoring rewrite, proposal submission, event handling"
    ownership: "dvconf-daemons/apps/cp-daemon/**"
    agent_type: gsd-executor
    skill_file: "docs/skills/OFFCHAIN_AGENT_SKILL.md"
    blocked_by: [onchain-agent]
  - role: fe-agent
    focus: "React client: expected_participants input, consensus status UI"
    ownership: "dvconf-client/src/**"
    agent_type: gsd-executor
    skill_file: "docs/skills/FE_AGENT_SKILL.md"
    blocked_by: [onchain-agent]
  - role: qc-agent
    focus: "Code review against checklists"
    agent_type: gsd-executor
    skill_file: "docs/skills/QC_AGENT_SKILL.md"
    blocked_by: [onchain-agent, offchain-agent, fe-agent]
```

## Core Problem
The current CP assignment uses simplistic appearance-count voting — CPs submit relay IDs and the most-mentioned relay wins. This doesn't account for relay quality, validator assignment, or scoring accuracy. A mediocre relay can win by popularity alone. Validators are not assigned per-room at all (they self-select). There's no incentive for CPs to find genuinely optimal infrastructure pairings.

## Users & Contexts
- **Room creators**: Want fast, high-quality infrastructure assignment. Specify expected participant count at creation.
- **CP operators**: Compete to find optimal pairings. Rewarded for accuracy. Build reputation over time.
- **Relay/Validator/Signaling operators**: Passively scored by the formula. Better performance → higher scores → more assignments.
- **Network as a whole**: Benefits from meritocratic assignment — rooms get the best available infrastructure.

## Success Metrics
1. Rooms are assigned infrastructure via verified scoring, not popularity
2. The contract can independently verify any CP's submitted score
3. The CP that finds the best pairing earns a proposer reward
4. CP reputation tracks accuracy and affects future prioritization
5. Validators are assigned per-room (hybrid: primary assigned, any can backup-probe)

## The PVR (Propose-Verify-Reward) Model

### Flow
1. `RoomCreated` event fires with `expected_participants` (new field)
2. Active CPs run the **deterministic scoring formula** off-chain over candidate `(relay[], validator[], signaling)` tuples
3. Each CP submits their best pairing + computed score on-chain via `submit_pairing_proposal()`
4. The contract **verifies** the submitted score by re-computing the formula from on-chain data for those specific nodes
5. After ≥2/3 active CPs have submitted (or all active CPs), the **highest verified score wins**
6. Room transitions PENDING → READY with the winning pairing assigned
7. Winning CP gets a **proposer reward**
8. Winning CP's `reputation` (wins counter) increments

### Unified Ballot
Single TX: `(relay_ids, validator_ids, signaling_id, computed_score)`

### On-chain Constraints
- **Liveness**: Voted nodes must have active heartbeat
- **Score verification**: Contract re-derives score from on-chain data, rejects mismatched submissions

### Scoring Formula
6 inputs, all on-chain, weighted to 10,000 bps total:

| Input | Weight (bps) | Source | Computation |
|-------|-------------|--------|-------------|
| RTT | 3000 | relay.validator_probed_rtt | `(MAX_RTT - rtt) * BASIS / MAX_RTT` |
| Load | 2500 | relay.current_load | `(MAX_LOAD - load) * BASIS / MAX_LOAD` |
| Stake | 1500 | node.stake_amount | `min(stake, STAKE_CAP) * BASIS / STAKE_CAP` |
| Liveness | 1000 | heartbeat_epoch vs current | `FRESH(<threshold): 10000, STALE: 5000, else: 0` |
| Region | 1000 | node.region vs room creator | `exact: 10000, same_continent: 5000, else: 0` |
| History | 1000 | node.avg_quality_multiplier | `0-10000 range, default 5000 for new nodes` |

**Pairing score** = average of individual node scores across all selected relays + validators + signaling.

Constants stored in `constants.move` (upgradeable via package upgrade only).

### Validator Assignment
- Count proportional to `expected_participants` (specified by room creator)
- Hybrid model: CPs assign primary validators, any validator can backup-probe any room

### Reputation
- `wins: u64` counter on CP profile in ControlPlaneRegistry
- Tie-breaking: equal scores → higher-reputation CP wins
- Future: reputation affects priority in proposal ordering (post-thesis)

## Requirements

### Milestone 1 — On-chain PVR Contract [M1] — COMPLETE (2026-03-18)

- [x] **PVR-01**: `create_room()` accepts `expected_participants: u64` parameter and stores it in `RoomInfo` [M1]
  - AC: RoomInfo has `expected_participants` field; create_room signature includes the param; RoomCreated event includes it
- [x] **PVR-02**: New `pairing_score.move` module implements the deterministic 6-input scoring formula with weights as named constants in `constants.move` [M1]
  - AC: `compute_node_score()` returns 0-10000 for known inputs; `compute_pairing_score()` averages correctly; `required_validators()` scales and caps; all 15 PVR constants added to constants.move with accessors
- [x] **PVR-03**: `RelayBallot` replaced with `PairingProposal` struct: `(cp_id, relay_ids, validator_ids, signaling_id, submitted_score)` [M1]
  - AC: Old RelayBallot removed; PairingProposal has all 5 fields; `room_votes` renamed to `room_proposals`
- [x] **PVR-04**: `submit_pairing_proposal()` verifies liveness of all proposed nodes (heartbeat check) and rejects proposals with inactive nodes [M1]
  - AC: Proposal with a stale-heartbeat relay/validator/signaling aborts with E_NODE_NOT_ACTIVE; takes RelayRegistry, ValidatorRegistry, SignalingRegistry as params
- [x] **PVR-05**: `submit_pairing_proposal()` stores submitted_score on the proposal and emits it in ProposalSubmitted event [M1]
  - AC: M2 evolution: score is now CP-submitted (consensus-first), not contract-computed. ProposalSubmitted event emits the score.
- [x] **PVR-06**: After ≥2/3 of votes cast match the same score, the contract finalizes the room (PENDING → READY) [M1]
  - AC: Finalization triggers at matching_votes * 10000 / total_votes >= 6667; RoomAssigned event emitted; room status transitions to READY; assigned_relays + assigned_validators + assigned_signaling populated
- [x] **PVR-07**: Validator count per room derived from `expected_participants` via `required_validators()` [M1]
  - AC: `submit_pairing_proposal` rejects if `validator_ids.length() < required_validators(expected_participants)`; formula: `max(MIN_VALIDATORS, expected / RATIO)` capped at MAX
- [x] **PVR-08**: Winning CP receives a proposer reward (event emitted, reputation incremented) [M1]
  - AC: ProposerRewarded event emitted with cp_id and reward amount on finalization
- [x] **PVR-09**: ControlPlaneRegistry tracks `reputation: u64` (wins counter) per CP, incremented on proposal win [M1]
  - AC: CPNodeInfo has `reputation` field initialized to 0; `increment_reputation()` is public(package); info_reputation() accessor exists
- [x] **PVR-10**: Tie-breaking uses CP reputation — equal verified scores → higher-reputation CP wins [M1]
  - AC: When two proposals have identical verified_score, the one with higher CP reputation is selected; if still tied, first submitted wins
- [x] **PVR-11**: `assign_relay_and_signaling()` kept as admin fallback (not removed) [M1]
  - AC: Function gated by AdminCap; still callable for testing/admin scenarios
- [x] **PVR-12**: All existing Move tests remain passing after changes [M1]
  - AC: `sui move test` passes with 200 tests (47 new PVR/consensus tests added on top of 153 original)

### Milestone 2 — Off-chain + Client Integration [M2] — COMPLETE (2026-03-27)

- [x] **PVR-13**: CP daemon calls `submit_pairing_proposal()` with submitted_score [M2]
- [x] **PVR-14**: CP daemon scoring mirrors on-chain formula exactly (6 factors, same weights, thresholds, canonical sort) [M2]
- [x] **PVR-15**: CP daemon watches `RoomCreated` events and computes proposals for new PENDING rooms [M2]
- [x] **PVR-16**: `create_room` UI accepts `expected_participants` input from user [M2]
- [x] **PVR-17**: Room status UI shows consensus voting progress while PENDING [M2]
- [x] **PVR-18**: Client displays verified_score and consensus/dispute resolution badge when READY [M2]

### Milestone 2 — New Requirements (from design evolution) [M2]

- [x] **PVR-19**: Contract groups proposals by submitted_score equality, finalizes at ≥2/3 of votes cast [M2]
- [x] **PVR-20**: Dispute fallback: room creator calls finalize_room() after cooldown, contract re-computes via pairing_score [M2]
- [x] **PVR-21**: RoomAssigned event includes verified_score, consensus_reached, winning_cp [M2]
- [x] **PVR-22**: RoomInfo persists verified_score and consensus_reached after finalization [M2]
- [x] **PVR-23**: Daemon applies canonical sort (score desc, node ID asc) for deterministic tuple selection [M2]
- [x] **PVR-24**: Client shows live voting progress grouped by score with progress bars [M2]
- [x] **PVR-25**: Client shows finalize button after cooldown when no consensus reached [M2]

## Edge Cases
1. **All CPs submit identical scores** (deterministic formula, same search): Tie-breaking by reputation, then by submission order (first proposer wins among equal reputation).
2. **No CP finds enough eligible nodes** (all relays overloaded or offline): Room stays PENDING. No vote reset needed — CPs simply can't submit valid proposals. Room creator can close and retry.
3. **`expected_participants` is inaccurate**: Accepted limitation for thesis. Creator could understate to get fewer validators. Production would need dynamic re-evaluation.
4. **CP goes offline mid-proposal window**: Threshold is ≥2/3 of ACTIVE CPs (heartbeat-based), not all registered CPs. Offline CPs don't block finalization.
5. **Score verification gas cost**: Re-computing formula reads from 3+ registries (relay, validator, signaling, CP). Acceptable for thesis — noted as optimization target.

## Out of Scope
- Vote reset loop mitigation (infinite disagreement)
- Signaling node rewards and slashing (SIG-05/06)
- Dynamic validator re-evaluation after room starts
- Reputation affecting voting power (beyond tie-breaking)
- Region enforcement on-chain (off-chain scoring only)
- Weighted reputation decay over time
- `expected_participants` verification or enforcement
- Production gas optimization for score verification
