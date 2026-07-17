# DVConf — Decentralized Video Conference System

## What This Is

A decentralized video conference system built on Sui Move where coordination, trust, and economics live on-chain while media flows through staked relay nodes off-chain. Users register on-chain, rooms are created as shared objects, Control Plane nodes vote on relay assignment (SFU or MCU mode), and secret validator nodes audit relay quality to drive work-based rewards. No central server — the chain is the coordination layer.

## Core Value

Users can hold real-time video conferences through decentralized relay nodes where no single entity controls the infrastructure, and honest relay operators are economically rewarded while dishonest ones are slashed — all verifiable on-chain.

## Requirements

### Validated

- ✓ Token contract (DVCONF fungible token on Sui) — v1.0
- ✓ NetworkRegistry (global config, scoring weights, reward ratios, thresholds) — v1.0
- ✓ Node registration + staking (register, unregister, top-up, withdraw) — v1.0
- ✓ Cap objects (package-private constructors, AdminCap, RelayCap) — v1.0
- ✓ MinerStore (validator set management) — v1.0
- ✓ CP queries (external read access to validator set) — v1.0
- ✓ Constants module (all numeric parameters centralized) — v1.0
- ✓ RoomManager singleton (global room registry & factory) — v1.0
- ✓ ControlPlaneRegistry (CP registration, heartbeat, availability, room assignments) — v1.0
- ✓ RelayRegistry (relay registration, SFU/MCU mode, load, validator_probed_rtt) — v1.0
- ✓ ValidatorRegistry (validator registration, session wallet dual-key mapping) — v1.0
- ✓ UserRegistry (user profiles) — v1.0
- ✓ Signaling node (WebRTC ICE exchange) — v1.0
- ✓ Control Plane daemon (chain events, scoring, heartbeat) — v1.0
- ✓ Validator daemon (session wallet, measurements, dual-signed proof construction) — v1.0
- ✓ All daemons share types via monorepo + @mysten/sui SDK — v1.0

### Active

- [ ] Room state machine (Pending -> Ready -> Active -> Closed)
- [ ] CP relay assignment voting + mode selection (>= 2/3 consensus)
- [ ] Validator secret assignment (encrypted session wallet on-chain)
- [ ] Join/leave room entry points
- [ ] Escrow on room creation
- [ ] SessionProof structure (work + quality metrics + dual-key fields)
- [ ] Dual-key proof submission + verification
- [ ] Median metric aggregation from multiple validators
- [ ] Quality multiplier calculation (packet loss -> reward factor)
- [ ] Work-based relay reward distribution (BASE_RATE x median_bytes x quality_multiplier)
- [ ] Validator accuracy scoring + reward
- [ ] Slashing logic (quality_multiplier = 0 -> slash trigger)
- [ ] RTT writeback from SessionProof -> RelayRegistry.validator_probed_rtt
- [ ] SFU relay node (mediasoup stream fan-out)
- [ ] MCU relay node (mediasoup/GStreamer stream mixing)
- [ ] Client web app (register, create room, join room, session view)
- [ ] WebRTC connection to assigned relay via ICE/STUN
- [ ] Adaptive SFU/MCU session rendering

### Out of Scope

- CDN integration (MCU output distribution + recording) — defer to post-thesis
- Mobile app — web-first
- ZK proof for validator identity — future extension, dual-key for MVP
- Storage/recording service — defer to post-thesis
- Governance mechanism for BASE_RATE — use fixed value for thesis

## Current Milestone: v2.0 Client App

**Goal:** Build a React web client that connects to Sui wallet, interacts with v1.0 registries, and establishes WebRTC video sessions through the signaling server.

**Target features:**
- Wallet connect + user registration against UserRegistry
- View registered nodes (relays, CPs, validators) from on-chain registries
- Create and join rooms (mocked room lifecycle against RoomManager)
- WebRTC video/audio connection via signaling server
- Basic session view with peer video streams

## Context

- **Thesis project** for 2 developers, no fixed deadline
- **v1.0 shipped** (2026-03-09): Foundation contracts + 5 registries + 3 off-chain daemons
- **Sui Move** smart contracts: 8 foundation modules (34 tests), 5 registry modules (79 tests)
- **Off-chain daemons**: pnpm monorepo at `dvconf-daemons/` — signaling, CP daemon, validator daemon
- **React client**: standalone Vite project at `dvconf-client/` (extracted from dvconf-daemons Phase 8)
- **~21,500 LOC** across Sui Move + TypeScript
- Spec document: `docs/decentralized_video_conference-rev4.md` (rev 4, last updated 2026-02-27)
- Error code namespaces: network_registry 100-102, staking 200-202, miner_store 300, registration 400-404, registries 500-1099
- Source structure: `sources/core/`, `sources/access/`, `sources/miner/`
- All math in basis points (u64), never floating point
- Cap constructors are `public(package)` — never `public`
- **Testnet deployed** (Phase 1: 2026-03-04, Phase 2: 2026-03-07)
  - Package: `0xf7cf30b14c70c62271674f45098ba7c912d5bcf9e44896e1fb700723c45d3ef3`
  - All object IDs in `.env.testnet`

## Constraints

- **Tech stack**: Sui Move (contracts), Node.js + mediasoup (off-chain), React + @mysten/dapp-kit (client)
- **No floating point**: All on-chain math uses basis points (integers), weights/ratios sum to 10,000
- **No media on-chain**: Chain carries coordination, trust, and money — never video/audio data
- **Validator secrecy**: Wallet A <-> Wallet B link never appears on-chain until post-session proof
- **RTT source**: Only validator_probed_rtt from RelayRegistry, never self-reported
- **Rewards**: Work-based (BASE_RATE x median_bytes x quality_multiplier), not membership-based

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| SFU for small rooms, MCU for large | SFU = low CPU/latency, MCU = saves client bandwidth | -- Pending (threshold TBD) |
| Dual-key pattern for validator identity | Hides validator during session, proves identity after | ✓ Good (v1.0 — ValidatorRegistry + daemon) |
| Work-based relay rewards | Eliminates self-reporting attack surface, pays for actual bytes forwarded | -- Pending |
| Median aggregation of validator proofs | Outlier detection, statistical robustness with multiple validators | -- Pending |
| Separate registries as shared objects | Avoid transaction contention between independent updates | ✓ Good (v1.0 — Phase 2) |
| Agent team (PM/OnChain/OffChain/FE/QC) | Structured review process, QC required before PM sign-off | ✓ Good |
| pnpm monorepo for daemons | Shared types across signaling/CP/validator, single dependency tree | ✓ Good (v1.0 — Phase 3) |
| EventPoller cursor-based polling | Reliable event consumption without WebSocket subscription complexity | ✓ Good (v1.0 — Phase 3) |
| Gap closure phases (4-6) after audit | Milestone audit identified integration + verification gaps before shipping | ✓ Good (all gaps closed) |

---
*Last updated: 2026-03-09 after v2.0 milestone start*
