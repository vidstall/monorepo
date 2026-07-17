# Context — cp-voting-consensus

## Metadata
```yaml
quangflow_version: "1.1.0"
pm_mode: hands-on
project_type: existing
scan_depth: deep
created: 2026-03-17T00:00:00Z
phase: 17
milestone: v4.0
```

## Feature Overview
Phase 17 — CP Voting Consensus: Replace the single-CP direct assignment (`assign_relay_and_signaling()`) with a multi-CP voting mechanism where each Control Plane node independently scores relay candidates, submits votes on-chain, and the contract auto-finalizes room assignment when ≥2/3 (66.67%) of active CPs agree.

## Tech Stack
- **On-chain**: Sui Move (Sui framework 2025.x), deployed on testnet
- **Off-chain daemons**: Node.js + TypeScript (pnpm monorepo), `@mysten/sui` SDK
- **Client**: React 18 + Vite + TypeScript, `@mysten/dapp-kit`, `mediasoup-client`
- **Testing**: Move `#[test]`, Vitest (daemons + client)
- **Package ID (testnet)**: `0xf7cf30b14c70c62271674f45098ba7c912d5bcf9e44896e1fb700723c45d3ef3`

## Project Structure
```
dvconf-contracts/                   # Sui Move contracts (main repo)
├── sources/
│   ├── core/                       # constants, token, network_registry
│   ├── access/                     # caps, cp_queries
│   ├── miner/                      # miner_store, staking, registration
│   └── registry/                   # room_manager, control_plane_registry,
│                                   # relay_registry, validator_registry,
│                                   # user_registry, signaling_registry,
│                                   # economic_layer
├── tests/                          # Move test modules (153 tests passing)
├── .planning/                      # GSD phase plans, roadmap, requirements
│   ├── ROADMAP.md
│   ├── REQUIREMENTS.md
│   └── phases/phase-17-cp-voting-consensus/PLAN.md
├── docs/
│   ├── decentralized_video_conference-rev4.md   # Canonical system spec
│   ├── architecture/phases/                      # ADDs, RTMs per phase
│   └── skills/                                   # Agent skill files
└── plans/cp-voting-consensus/                    # QuangFlow artifacts (this dir)

dvconf-daemons/                     # Off-chain Node.js daemons
├── packages/shared/                # Shared types, events, utils
└── apps/
    ├── cp-daemon/                  # Control Plane (scoring, assignment, heartbeat)
    ├── validator-daemon/           # Validator (measurements, probes, session proofs)
    ├── signaling/                  # WebSocket signaling server (ICE/SDP relay)
    └── relay/                      # mediasoup SFU/MCU relay node

dvconf-client/                      # React web client
├── src/
│   ├── pages/                      # HomePage, RoomPage, OperatorPage
│   ├── components/                 # VideoGrid, MediaControls, NetworkStatus, etc.
│   └── hooks/                      # 31 hooks (wallet, registration, room, WebRTC, relay)
```

## Existing Patterns
- **Basis-point math everywhere**: All weights/ratios are `u64` summing to 10,000. No floating point.
- **Cap-gated entry functions**: `ControlPlaneCap`, `MinerCap` are `public(package)` — never externally mintable.
- **Paused flag check**: Every state-mutating function starts with `assert!(!is_paused(net_reg))`.
- **Error code namespaces**: 100s=network_registry, 200s=staking, 300s=miner_store, 400s=registration, 500s=room_manager, 510s=cp_registry, 520s=relay, 530s=validator, 540s=user, 600s=signaling, 650s=economic_layer.
- **Event-driven daemons**: Daemons use `EventPoller` (cursor-based chain event polling) to react to on-chain events.
- **Dual-key identity**: Validators register (public_key, session_key); session proofs verify both via on-chain ed25519.
- **Reward formula**: `BASE_RATE × median_bytes × quality_multiplier / BASIS_POINTS`, split 70/15/15 relay/validator/CP.

## Current State (Phase 17 — In Progress)

### Already Implemented (on-chain)
The voting contract is **already merged** into `room_manager.move`:
- `RelayBallot` struct (`cp_id`, `relay_ids: vector<ID>`, `signaling_id`)
- `room_votes: Table<ID, vector<RelayBallot>>` field on `RoomManager`
- `submit_relay_vote()` entry function with:
  - Paused check, PENDING guard, ballot size validation
  - Duplicate vote prevention per CP
  - Threshold check: `ballot_count * 10_000 / active_cp_count >= 6667`
  - `tally_top_relays()` — picks relays by appearance count across ballots
  - `tally_top_signaling()` — picks highest-voted signaling node
  - Auto-finalize: sets assigned relay/signaling, PENDING → READY, emits `RoomAssigned`
  - Vote reset when all voted but no consensus → `VoteReset` event
- Error codes: `E_DUPLICATE_VOTE=507`, `E_NOT_PENDING=508`, `E_INVALID_BALLOT=509`
- `assign_relay_and_signaling()` kept as single-CP fallback

### Not Yet Done
| Task | Domain | Status | Description |
|------|--------|--------|-------------|
| Task 2: Voting tests | OnChain | Pending | 7 test cases for voting mechanism |
| Task 3: CP daemon update | OffChain | Pending | `room-assignment.ts` still calls old `assign_relay_and_signaling()` — needs `submit_relay_vote()` |
| Task 4: Client consensus UI | FE | Pending | "Waiting for network consensus..." status while room is PENDING |

### Requirements (v4)
- [ ] **VOTE-01**: Each CP node submits an independent relay vote via on-chain TX
- [ ] **VOTE-02**: Contract tallies votes and auto-finalizes when ≥2/3 active CPs agree
- [ ] **VOTE-03**: Disagreement triggers vote reset for re-evaluation
- [ ] **VOTE-04**: CP daemon submits votes instead of direct assignment calls
- [ ] MVAL-01–04: Phase 18 (Multi-Validator Assignment) — planned, not started

## Dependencies
- `@mysten/sui` SDK (daemons + client)
- `@mysten/dapp-kit` (client wallet integration)
- `mediasoup` + `mediasoup-client` (relay + client media)
- Move stdlib, Sui framework (on-chain)

## Constraints
- **No floating point**: All consensus thresholds are basis-point integers (6667 = 66.67%)
- **Backward compatibility**: Single-CP dev mode must still work (1 vote = 100% > threshold → auto-finalize)
- **No vote reset loop mitigation**: If CPs persistently disagree, votes reset infinitely. Mitigation deferred (not thesis scope).
- **CP liveness**: Offline CPs reduce active count; threshold computed at finalization time against current active set.
- **153 existing Move tests must remain passing** after all changes.

## Locked Decisions
- **Consensus model**: PVR (Propose-Verify-Reward) — replaces appearance-count voting
- **Design option**: C (Contract-Computed) — CPs submit tuples, contract scores on-chain
- **Consensus threshold**: 66.67% (6667 bps) — set in `constants.move`, not configurable per-room
- **Ballot structure**: Unified single TX: `(relay_ids, validator_ids, signaling_id)` — no CP-submitted score
- **Scoring formula**: 6 inputs weighted to 10000 bps: RTT(3000) + Load(2500) + Stake(1500) + Liveness(1000) + Region(1000) + History(1000)
- **Score computation**: Contract-side only — `pairing_score.move` pure module, CPs do NOT submit scores
- **Validator assignment**: Per-room via CP proposal, count proportional to `expected_participants`
- **Validator model**: Hybrid — CPs assign primary, any validator can backup-probe
- **Reputation**: Simple `wins: u64` counter on CPNodeInfo, used for tie-breaking only
- **Proposer reward**: Event-based (ProposerRewarded), actual fund mechanism deferred to M2/economic_layer integration
- **Fallback**: `assign_relay_and_signaling()` preserved for single-CP/dev scenarios
- **Region matching**: Off-chain only (CP scoring), not enforced on-chain
- **New module location**: `sources/scoring/pairing_score.move` — pure math, no shared objects

## Open Questions
- Proposer reward funding source (room escrow vs protocol treasury) — decide in M2
- Region taxonomy (string encoding for node regions) — decide in M2
- History score bootstrapping (sessions before reliable) — accepted as-is for thesis
- Proportional validator formula: N value for `expected / N` — set to 3 in constants
