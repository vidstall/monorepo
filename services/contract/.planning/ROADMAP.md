# Roadmap: DVConf

## Milestones

- v1.0 **Foundation + Registries + Daemons** -- Phases 1-6 (shipped 2026-03-09)
- v2.0 **Client App** -- Phases 7-10 (shipped 2026-03-10)
- v3.0 **Relay + Signaling Infrastructure** -- Phases 11-16 (shipped 2026-03-17)

## Phases

<details>
<summary>v1.0 Foundation + Registries + Daemons (Phases 1-6) -- SHIPPED 2026-03-09</summary>

- [x] Phase 1: Foundation Validation (2/2 plans) -- completed 2026-03-04
- [x] Phase 2: Registry Layer (3/3 plans) -- completed 2026-03-05
- [x] Phase 3: Off-chain Daemons (3/3 plans) -- completed 2026-03-05
- [x] Phase 4: Fix Daemon Auto-Registration (1/1 plan, gap closure) -- completed 2026-03-07
- [x] Phase 5: Formal Verification & Deploy (1/1 plan, gap closure) -- completed 2026-03-07
- [x] Phase 6: Daemon Tech Debt Cleanup (1/1 plan, gap closure) -- completed 2026-03-07

See: [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)

</details>

### v2.0 Client App (SHIPPED 2026-03-10)

**Milestone Goal:** Build a React web client that connects to Sui wallet, interacts with v1.0 registries, and establishes P2P WebRTC video sessions through the signaling server.

- [x] **Phase 7: Client Stabilization** - Fix 6 critical bugs in existing client code that block all feature work -- completed 2026-03-09
- [x] **Phase 8: Chain Integration & Room Management** - Wallet auth, user registration, room lifecycle, and chain polling hooks -- completed 2026-03-10
- [x] **Phase 9: P2P WebRTC Sessions** - Camera/mic capture, signaling-based peer connections, tiled video, and connection stats -- completed 2026-03-10
- [x] **Phase 10: Client Polish** - System dashboard, token balance, participant names -- completed 2026-03-10

## Phase Details

### Phase 7: Client Stabilization
**Goal**: Existing client code works correctly as a 2-peer P2P demo without silent failures
**Depends on**: Phase 6 (v1.0 shipped)
**Requirements**: FIX-01, FIX-02, FIX-03, FIX-04, FIX-05, FIX-06
**Success Criteria** (what must be TRUE):
  1. Local video stream persists across re-renders without going stale (useRef, not plain object)
  2. WebSocket join message is never sent before the connection is open
  3. Room creation fails visibly when RoomCreated event is missing (no silent digest fallback)
  4. Two peers can connect and disconnect without orphaned RTCPeerConnections leaking
  5. All on-chain object IDs are read from VITE_ environment variables, not hardcoded in source
**Plans**: 1/1 (5 tasks)

### Phase 8: Chain Integration & Room Management
**Goal**: Users can connect wallet, register on-chain, create rooms, and monitor room status through the full Pending/Ready/Active/Closed lifecycle
**Depends on**: Phase 7
**Requirements**: CLIENT-01, CLIENT-02, CLIENT-03, CLIENT-04, ROOM-01, ROOM-02, ROOM-03, ROOM-04, ROOM-05
**Success Criteria** (what must be TRUE):
  1. User can connect and disconnect Sui wallet from any page
  2. Unregistered user is prompted to register and can submit display name as on-chain TX
  3. User can create a room and see it transition through Pending/Ready/Active/Closed states via chain polling
  4. Room URL (/rooms/:id) can be shared and opened by another user to join the same room
  5. All write operations are blocked with a visible message when NetworkRegistry is paused
**Plans**: 1/1 (7 tasks)

### Phase 9: P2P WebRTC Sessions
**Goal**: Multiple peers can join a room and see/hear each other through P2P WebRTC connections via the signaling server
**Depends on**: Phase 8
**Requirements**: RTC-01, RTC-02, RTC-03, RTC-04, RTC-05, RTC-06
**Success Criteria** (what must be TRUE):
  1. User is prompted for camera/mic permissions with clear error messages when denied or unavailable
  2. Two or more peers in the same room can see and hear each other in a tiled video layout
  3. Leaving a room stops all local media tracks and closes all peer connections with no resource leaks
  4. Real-time connection stats (RTT, packet loss, jitter) are visible during an active session
**Plans**: 1/1 (4 tasks)

### Phase 10: Client Polish
**Goal**: The client surfaces network health and identity information that demonstrates the decentralized architecture in a thesis demo
**Depends on**: Phase 9
**Requirements**: POLISH-01, POLISH-02, POLISH-03
**Success Criteria** (what must be TRUE):
  1. System status dashboard shows live counts of users, rooms, relays, CPs, and validators from on-chain data
  2. User's DVCONF token balance is visible in the header
  3. Participant list in an active room shows display names resolved from UserRegistry
**Plans**: 1/1 (4 tasks)

### v3.0 Relay + Signaling Infrastructure (SHIPPED 2026-03-17)

**Milestone Goal:** Add on-chain signaling nodes, mediasoup relay nodes (SFU/MCU), and the economic layer (rewards/slashing) to complete the decentralized architecture.

- [x] **Phase 11: Signaling Node Registry** - On-chain SignalingRegistry module, stake-based registration, heartbeat, client discovery -- completed 2026-03-12
- [x] **Phase 12: Relay Node Implementation** - mediasoup SFU/MCU relay, media forwarding, client integration via mediasoup-client -- completed 2026-03-12
- [x] **Phase 13: Economic Layer** - SessionProof submission, reward distribution (BASE_RATE x median_bytes x quality_multiplier), slashing returns Coin -- completed 2026-03-12
- [x] **Phase 14: Integration & Hardening** - Cross-node failover, E2E signaling+relay+validator flow, load testing -- completed 2026-03-13
- [x] **Phase 15: Economic Flow Fix** - Fix 3 integration bugs blocking reward distribution E2E (gap closure) -- completed 2026-03-13
- [x] **Phase 16: Security Hardening & Documentation** - Fix P0 security vulnerabilities and critical doc gaps from triple review (remediation) -- completed 2026-03-16

### v4.0 Decentralized Consensus (IN PROGRESS)

**Milestone Goal:** Close the remaining PRD gaps: CP voting consensus for relay assignment and multi-validator room assignment, completing the decentralized trust model described in the thesis.

- [x] **Phase 17: CP Voting Consensus** - PVR on-chain scoring (M1), consensus-first model with dispute fallback (M2), daemon scoring alignment, consensus progress UI -- completed 2026-03-27
- [x] **Phase 18: Multi-Validator Assignment** - Two-step relay slashing with proportional distribution, validator assignment enforcement, RoomAssigned event validator_ids, daemon assignment filtering -- completed 2026-03-27

## Phase Details (v3.0)

### Phase 11: Signaling Node Registry
**Goal**: Signaling nodes register on-chain with stake, send heartbeats, and clients discover them from the registry instead of hardcoded URLs
**Depends on**: Phase 10 (v2.0 shipped)
**Requirements**: SIG-01, SIG-02, SIG-03, SIG-04, SIG-05, SIG-06
**Success Criteria** (what must be TRUE):
  1. Signaling node registers on-chain with stake via new SignalingRegistry module
  2. Registered signaling node sends periodic heartbeats to maintain active status
  3. Client discovers available signaling nodes from on-chain registry (no hardcoded URL)
  4. Client selects signaling node using region/load scoring (reuse CP scoring logic)
  5. Signaling node earns rewards for successfully routing SDP/ICE messages
  6. Signaling node can be slashed for dropping connections or misbehavior

### Phase 12: Relay Node Implementation
**Goal**: Relay nodes forward media streams via mediasoup (SFU or MCU mode) and clients connect through mediasoup-client
**Depends on**: Phase 11
**Requirements**: RELAY-01, RELAY-02, RELAY-03, RELAY-04, RELAY-05, RELAY-06
**Success Criteria** (what must be TRUE):
  1. Client connects to SFU relay via mediasoup-client
  2. Client connects to MCU relay via mediasoup-client
  3. Adaptive session view switches based on on-chain relay_mode
  4. Join room resolves relay endpoint from RelayRegistry
  5. Relay node forwards media streams via mediasoup
  6. Relay node earns rewards based on bytes forwarded and quality metrics

### Phase 13: Economic Layer
**Goal**: Validators submit dual-key signed SessionProofs on-chain, rewards are distributed work-based, and slashing returns Coin to the economic layer
**Depends on**: Phase 12
**Requirements**: ECON-01, ECON-02, ECON-03
**Success Criteria** (what must be TRUE):
  1. Validator submits dual-key signed SessionProof on-chain post-session
  2. Reward distribution uses BASE_RATE x median_bytes x quality_multiplier formula
  3. Slashing for misbehavior returns Coin to economic layer (never burns)

### Phase 14: Integration & Hardening
**Goal**: End-to-end flow works: client discovers signaling node, connects to relay, validators measure quality, rewards are distributed
**Depends on**: Phase 13
**Requirements**: All v3.0 requirements (integration testing)
**Success Criteria** (what must be TRUE):
  1. Full session lifecycle works: discover signaling -> connect relay -> measure quality -> submit proof -> distribute reward
  2. Misbehaving nodes are slashed and returned Coin is accessible
  3. Load testing validates concurrent sessions

### Phase 15: Economic Flow Fix (Gap Closure)
**Goal**: Fix 3 integration bugs that prevent reward distribution from triggering at runtime, completing the E2E session lifecycle
**Depends on**: Phase 14
**Requirements**: ECON-01, ECON-02 (re-satisfy)
**Gap Closure**: Closes BUG-INT-001, BUG-INT-002, BUG-INT-004 from v3.0 audit
**Success Criteria** (what must be TRUE):
  1. Validator daemon populates relayStakeId from on-chain relay assignment (not env var only)
  2. waitForProofs correctly reads proof count from RoomEscrow's proofs vector length
  3. CP daemon uses tx.pure.id() for Move ID parameters in assign_relay_and_signaling PTB
  4. Full E2E flow completes: create room → deposit escrow → assign → session → submit proof → distribute rewards
**Plans**: 1/1

### Phase 16: Security Hardening & Documentation (Remediation)
**Goal**: Fix all P0 security vulnerabilities and critical documentation gaps identified by triple review before thesis defense
**Depends on**: Phase 15
**Requirements**: SEC-001, SEC-002, SEC-003, SEC-009, SEC-005, SEC-006, DOC-01 through DOC-08
**Remediation**: Closes findings from Documentation Review (B-), Architecture Review (B+), Security Review (Moderate)
**Success Criteria** (what must be TRUE):
  1. `staking::destroy()` aborts with E_STAKE_LOCKED if position is locked (test added)
  2. `distribute_rewards()` requires escrow.creator == ctx.sender() (test added)
  3. Error code namespace in ONCHAIN_AGENT_SKILL.md matches actual code
  4. All broken references in CLAUDE.md are fixed
  5. Both dvconf-daemons and dvconf-client have README.md files
  6. WebSocket servers enforce maxPayload limits
  7. All Move tests pass
  8. QC APPROVED on all changes
**Plans**: 1/1 (11 tasks)

## Phase Details (v4.0)

### Phase 17: CP Voting Consensus
**Goal**: Multiple CP nodes independently score relays, submit votes on-chain, contract auto-finalizes room assignment at ≥2/3 consensus
**Depends on**: Phase 16 (v3.0 shipped)
**Requirements**: VOTE-01, VOTE-02, VOTE-03, VOTE-04
**Success Criteria** (what must be TRUE):
  1. Each CP node submits an independent relay vote for a room via on-chain TX
  2. Contract tallies votes and auto-finalizes when ≥2/3 active CPs agree
  3. Disagreement triggers re-evaluation (votes reset for that room)
  4. Room transitions PENDING→READY only after consensus is reached
  5. CP daemon submits votes instead of direct assignment calls
  6. All existing + new Move tests pass
**Plans**: 1/1 (4 tasks)

### Phase 18: Multi-Validator Room Assignment
**Goal**: CP assigns multiple validators to each room, enabling median aggregation and accuracy scoring across independent SessionProofs
**Depends on**: Phase 17
**Requirements**: MVAL-01, MVAL-02, MVAL-03, MVAL-04
**Success Criteria** (what must be TRUE):
  1. RoomInfo tracks assigned validators
  2. CP assigns N validators to a room during vote finalization
  3. Validator daemon detects its room assignment and joins the session
  4. Multiple validators submit independent SessionProofs for the same room
  5. distribute_rewards() correctly applies median + accuracy scoring across multiple proofs
  6. All existing + new Move tests pass
**Plans**: 1/1 (5 tasks)

## Progress

**Execution Order:** Phase 7 -> 8 -> 9 -> 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation Validation | v1.0 | 2/2 | Complete | 2026-03-04 |
| 2. Registry Layer | v1.0 | 3/3 | Complete | 2026-03-05 |
| 3. Off-chain Daemons | v1.0 | 3/3 | Complete | 2026-03-05 |
| 4. Fix Daemon Auto-Registration | v1.0 | 1/1 | Complete | 2026-03-07 |
| 5. Formal Verification & Deploy | v1.0 | 1/1 | Complete | 2026-03-07 |
| 6. Daemon Tech Debt Cleanup | v1.0 | 1/1 | Complete | 2026-03-07 |
| 7. Client Stabilization | v2.0 | 1/1 | Complete | 2026-03-09 |
| 8. Chain Integration & Room Management | v2.0 | 1/1 | Complete | 2026-03-10 |
| 9. P2P WebRTC Sessions | v2.0 | 1/1 | Complete | 2026-03-10 |
| 10. Client Polish | v2.0 | 1/1 | Complete | 2026-03-10 |
| 11. Signaling Node Registry | v3.0 | 1/1 | Complete | 2026-03-12 |
| 12. Relay Node Implementation | v3.0 | 1/1 | Complete | 2026-03-12 |
| 13. Economic Layer | v3.0 | 1/1 | Complete | 2026-03-12 |
| 14. Integration & Hardening | v3.0 | 1/1 | Complete | 2026-03-13 |
| 15. Economic Flow Fix | v3.0 | 1/1 | Complete | 2026-03-13 |
| 16. Security Hardening & Docs | v3.0 | 1/1 | Complete | 2026-03-16 |
| 17. CP Voting Consensus | v4.0 | 1/1 | Complete | 2026-03-27 |
| 18. Multi-Validator Assignment | v4.0 | 1/1 | Complete | 2026-03-27 |
