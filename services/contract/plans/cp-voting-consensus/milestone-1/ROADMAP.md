# Milestone 1 — ROADMAP: On-chain PVR Contract

## Metadata
```yaml
quangflow_version: "1.1.0"
milestone: 1
phases: 5
total_tasks: 8
domain: OnChain (Sui Move)
```

## Dependency Graph
```
Phase 1 (constants) ──→ Phase 2 (pairing_score) ──→ Phase 3 (room_manager + cp_registry)
                                                          │
                                                          ↓
                                                    Phase 4 (tests)
                                                          │
                                                          ↓
                                                    Phase 5 (regression)
```

---

## Phase 1: Constants & Foundation
**Goal**: Add all PVR scoring constants to `constants.move`
**Covers**: PVR-02 (partial)
**Agent**: onchain-agent

### Tasks
| # | Task | File | Done Criteria |
|---|------|------|---------------|
| 1.1 | Add 15 PVR constants + accessors | `sources/core/constants.move` | All constants defined: PVR_W_RTT (3000), PVR_W_LOAD (2500), PVR_W_STAKE (1500), PVR_W_LIVENESS (1000), PVR_W_REGION (1000), PVR_W_HISTORY (1000), PVR_MAX_RTT (500), PVR_MAX_LOAD (100), PVR_STAKE_CAP (5B), PVR_HEARTBEAT_FRESH (3), PVR_HEARTBEAT_STALE (7), PVR_DEFAULT_HISTORY (5000), PVR_VALIDATOR_RATIO (3), PVR_MAX_VALIDATORS_PER_ROOM (5), PVR_PROPOSER_REWARD (100). All have `public fun` accessors. Weights sum to 10000. `sui move build` passes. |

**Quality gate**: Weights must sum to exactly 10_000 bps. Each constant has exactly one accessor.

---

## Phase 2: Scoring Module
**Goal**: Create `pairing_score.move` — pure math, no shared objects
**Covers**: PVR-02, PVR-07
**Agent**: onchain-agent
**Depends on**: Phase 1

### Tasks
| # | Task | File | Done Criteria |
|---|------|------|---------------|
| 2.1 | Create `pairing_score.move` with `compute_node_score()` | `sources/scoring/pairing_score.move` | Pure function. Takes (rtt, load, stake, heartbeat_age, region_match, history_score) → returns u64 (0-10000). Uses constants from Phase 1. No shared objects. No `entry` functions. |
| 2.2 | Add `compute_pairing_score()` and `required_validators()` | `sources/scoring/pairing_score.move` | `compute_pairing_score(node_scores: &vector<u64>) → u64` averages scores. `required_validators(expected_participants: u64) → u64` returns `max(MIN_VALIDATORS, expected / RATIO)` capped at MAX. |

**Quality gate**: Module has zero `use` of any registry. Only imports `dvconf::constants`. Single responsibility: math only.

---

## Phase 3: Contract Integration
**Goal**: Modify `room_manager.move` and `control_plane_registry.move` for PVR
**Covers**: PVR-01, PVR-03, PVR-04, PVR-05, PVR-06, PVR-08, PVR-09, PVR-10, PVR-11
**Agent**: onchain-agent
**Depends on**: Phase 2

### Tasks
| # | Task | File | Done Criteria |
|---|------|------|---------------|
| 3.1 | Add `reputation: u64` to CPNodeInfo + `increment_reputation()` | `sources/registry/control_plane_registry.move` | Field added (init 0 in `register_cp`). `public(package) fun increment_reputation()` exists. `info_reputation()` accessor exists. `init_for_testing` updated. |
| 3.2 | Modify `RoomInfo` + `create_room()` | `sources/registry/room_manager.move` | RoomInfo has `expected_participants: u64` and `assigned_validators: vector<ID>`. `create_room` takes `expected_participants` param. RoomCreated event unchanged (or add field). |
| 3.3 | Replace RelayBallot → PairingProposal, room_votes → room_proposals | `sources/registry/room_manager.move` | Old structs removed. PairingProposal struct: `(cp_id, relay_ids, validator_ids, signaling_id, verified_score)`. Table type updated. close_room cleans up room_proposals. |
| 3.4 | Implement `submit_pairing_proposal()` | `sources/registry/room_manager.move` | Full function: takes 4 registries + cap + room_id + relay_ids + validator_ids + signaling_id. (1) Paused/PENDING/registered checks. (2) Liveness check for all nodes. (3) Compute score via `pairing_score`. (4) Store proposal. (5) Check threshold. (6) Finalize: highest score wins, tie-break by reputation then submission order. (7) Emit ProposalSubmitted. (8) On finalize: set assigned_relays + assigned_validators + assigned_signaling, emit RoomAssigned + ProposerRewarded, increment reputation. |

**Quality gate**: `assign_relay_and_signaling()` untouched (PVR-11). All error codes follow namespace. Paused check on every entry function. `public(package)` on all internal mutations.

---

## Phase 4: PVR Tests
**Goal**: Comprehensive test coverage for new PVR functionality
**Covers**: PVR-02, PVR-04, PVR-05, PVR-06, PVR-07, PVR-08, PVR-09, PVR-10, PVR-12
**Agent**: onchain-agent
**Depends on**: Phase 3

### Tasks
| # | Task | File | Done Criteria |
|---|------|------|---------------|
| 4.1 | Scoring formula unit tests | `tests/pairing_score_tests.move` | Tests: (1) known inputs → expected score. (2) max RTT → rtt_score=0. (3) zero stake → stake_score=0. (4) stale heartbeat → liveness=5000. (5) dead heartbeat → liveness=0. (6) region match vs no match. (7) average of multiple scores. (8) required_validators scaling + cap. All pass. |
| 4.2 | PVR integration tests | `tests/pvr_integration_tests.move` | Tests: (1) submit_pairing_proposal stores verified_score. (2) duplicate proposal rejected (E_DUPLICATE_PROPOSAL). (3) inactive node rejected. (4) insufficient validators rejected. (5) finalization at 2/3 threshold — highest score wins. (6) tie-break by reputation. (7) ProposerRewarded event emitted. (8) fallback assign_relay_and_signaling still works. All pass. |

**Quality gate**: Every PVR requirement has at least 1 test. Edge cases from REQUIREMENTS.md covered.

---

## Phase 5: Regression
**Goal**: Verify all 153 existing tests still pass alongside new PVR tests
**Covers**: PVR-12
**Agent**: onchain-agent
**Depends on**: Phase 4

### Tasks
| # | Task | File | Done Criteria |
|---|------|------|---------------|
| 5.1 | Run full test suite, fix any regressions | all test files | `sui move test` reports 153 + N new tests passing (0 failures). Any broken tests from signature changes (create_room) fixed. |

**Quality gate**: Zero test failures. No `#[allow(unused)]` added to suppress new warnings.
