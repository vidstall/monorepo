# Requirements: DVConf v3.0 Relay + Signaling Infrastructure

**Defined:** 2026-03-09 (v2.0), updated 2026-03-13 (v3.0)
**Core Value:** Users can hold real-time video conferences through decentralized relay nodes where honest operators are economically rewarded and dishonest ones are slashed -- all verifiable on-chain.

## v2 Requirements

Requirements for Milestone 2: React web client with wallet integration, room management, and P2P WebRTC sessions.

### Client Foundation

- [x] **CLIENT-01**: User can connect/disconnect Sui wallet via dapp-kit ConnectButton
- [x] **CLIENT-02**: Client checks UserRegistry on load and prompts unregistered users to register
- [x] **CLIENT-03**: User can register with a display name via on-chain UserRegistry TX
- [x] **CLIENT-04**: All chain TX operations show loading, success, and error states

### Room Management

- [x] **ROOM-01**: User can create a room via on-chain RoomManager TX and receive room_id from RoomCreated event
- [x] **ROOM-02**: Client polls room status (Pending/Ready/Active/Closed) from chain at configurable interval
- [x] **ROOM-03**: User can share a room via URL (`/rooms/:id`) for others to join
- [x] **ROOM-04**: Room creator can close the room via on-chain TX
- [x] **ROOM-05**: Client guards all write operations when NetworkRegistry is paused

### WebRTC Session

- [x] **RTC-01**: Client requests camera/mic permissions with proper error handling for denied/unavailable
- [x] **RTC-02**: Client connects to signaling server WebSocket and exchanges ICE/SDP for P2P session
- [x] **RTC-03**: Multiple peers can join the same room with independent RTCPeerConnections (one per peer)
- [x] **RTC-04**: User can see remote peer video/audio streams in a tiled layout
- [x] **RTC-05**: Leaving a room properly cleans up all WebRTC connections and local media streams
- [x] **RTC-06**: Client displays real-time connection quality (RTT, packet loss, jitter) from WebRTC stats

### Client Polish

- [ ] **POLISH-01**: System status dashboard shows live user count, room count, relay/CP/validator node counts from chain
- [ ] **POLISH-02**: User's DVCONF token balance displayed in header
- [ ] **POLISH-03**: Participant list shows display names from UserRegistry for current room members

### Bug Fixes (Existing Code)

- [x] **FIX-01**: localStreamRef uses useRef instead of plain object literal
- [x] **FIX-02**: WebSocket join waits for open event instead of setTimeout
- [x] **FIX-03**: createRoom throws on missing RoomCreated event instead of falling back to digest
- [x] **FIX-04**: Multiple RTCPeerConnections tracked in a Map keyed by peerId (not single pcRef)
- [x] **FIX-05**: Camera/mic errors caught and displayed to user
- [x] **FIX-06**: Object IDs read from VITE_ environment variables, not hardcoded

## v3 Requirements

Requirements for Milestone 3: Relay + Signaling Node infrastructure and economic layer.

### Signaling Nodes

- [x] **SIG-01**: Signaling node registers on-chain with stake (new SignalingRegistry module)
- [x] **SIG-02**: Signaling node sends periodic heartbeat to maintain active status
- [x] **SIG-03**: Client discovers available signaling nodes from on-chain registry (no hardcoded URL)
- [x] **SIG-04**: Client selects signaling node by region/load scoring (reuse CP scoring logic)
- [ ] **SIG-05**: Signaling node earns rewards for successfully routing SDP/ICE messages (accepted limitation)
- [ ] **SIG-06**: Signaling node can be slashed for dropping connections or misbehavior (accepted limitation)

### Relay Nodes (SFU/MCU)

- [x] **RELAY-01**: Client connects via mediasoup-client to SFU relay node
- [x] **RELAY-02**: Client connects via mediasoup-client to MCU relay node
- [x] **RELAY-03**: Adaptive SFU/MCU session view branched by on-chain relay_mode
- [x] **RELAY-04**: Join room resolves relay endpoint from RelayRegistry on chain
- [x] **RELAY-05**: Relay node forwards media streams via mediasoup (SFU or MCU mode)
- [x] **RELAY-06**: Relay node earns rewards based on bytes forwarded and quality metrics

### Economic Layer

- [x] **ECON-01**: Reward distribution based on SessionProofs (BASE_RATE x median_bytes x quality_multiplier)
- [x] **ECON-02**: Slashing for misbehavior returns Coin to economic layer (never burns)
- [x] **ECON-03**: Validator dual-key signed SessionProofs submitted on-chain post-session

## v4 Requirements

Requirements for Milestone 4: Decentralized consensus and multi-validator trust model.

### CP Voting Consensus

- [x] **VOTE-01**: Each CP node submits an independent relay vote for a room via on-chain TX
- [x] **VOTE-02**: Contract tallies votes and auto-finalizes assignment when ≥2/3 active CPs agree
- [x] **VOTE-03**: Disagreement (all voted, no majority) triggers vote reset for re-evaluation
- [x] **VOTE-04**: CP daemon submits votes instead of direct `assign_relay_and_signaling()` calls

### Multi-Validator Assignment

- [x] **MVAL-01**: RoomInfo tracks assigned validators per room
- [x] **MVAL-02**: CP assigns N validators to a room during vote finalization
- [x] **MVAL-03**: Validator daemon detects its room assignment via on-chain event and starts measurement
- [x] **MVAL-04**: Multiple validators submit independent SessionProofs, enabling median aggregation and accuracy scoring

## Out of Scope

| Feature | Reason |
|---------|--------|
| Screen sharing | Edge cases for zero thesis value |
| Chat / messaging | Requires centralized server or P2P message layer |
| Recording / playback | CDN dependency, deferred |
| Email/password auth | Wallet IS the auth model |
| Mobile / responsive | Desktop-first for thesis demo |
| Node operator registration UI | Operator-facing, not user-facing |
| Governance / admin UI | AdminCap operations are CLI only |
| Multi-relay failover | Deferred to v3.0 |
| Token purchase / faucet UI | Dev operation, document in README |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FIX-01 | Phase 7 | Complete |
| FIX-02 | Phase 7 | Complete |
| FIX-03 | Phase 7 | Complete |
| FIX-04 | Phase 7 | Complete |
| FIX-05 | Phase 7 | Complete |
| FIX-06 | Phase 7 | Complete |
| CLIENT-01 | Phase 8 | Complete |
| CLIENT-02 | Phase 8 | Complete |
| CLIENT-03 | Phase 8 | Complete |
| CLIENT-04 | Phase 8 | Complete |
| ROOM-01 | Phase 8 | Complete |
| ROOM-02 | Phase 8 | Complete |
| ROOM-03 | Phase 8 | Complete |
| ROOM-04 | Phase 8 | Complete |
| ROOM-05 | Phase 8 | Complete |
| RTC-01 | Phase 9 | Complete |
| RTC-02 | Phase 9 | Complete |
| RTC-03 | Phase 9 | Complete |
| RTC-04 | Phase 9 | Complete |
| RTC-05 | Phase 9 | Complete |
| RTC-06 | Phase 9 | Complete |
| POLISH-01 | Phase 10 | Pending |
| POLISH-02 | Phase 10 | Pending |
| POLISH-03 | Phase 10 | Pending |
| SIG-01 | Phase 11 | Complete |
| SIG-02 | Phase 11 | Complete |
| SIG-03 | Phase 11 | Complete |
| SIG-04 | Phase 11 | Complete |
| SIG-05 | Phase 11 | Accepted limitation |
| SIG-06 | Phase 11 | Accepted limitation |
| RELAY-01 | Phase 12 | Complete |
| RELAY-02 | Phase 12 | Complete |
| RELAY-03 | Phase 12 | Complete |
| RELAY-04 | Phase 12 | Complete |
| RELAY-05 | Phase 12 | Complete |
| RELAY-06 | Phase 12 | Complete |
| ECON-01 | Phase 13+15+18 | Complete |
| ECON-02 | Phase 13+18 | Complete |
| ECON-03 | Phase 13 | Complete |
| VOTE-01 | Phase 17 | Complete |
| VOTE-02 | Phase 17 | Complete |
| VOTE-03 | Phase 17 | Complete |
| VOTE-04 | Phase 17 | Complete |
| MVAL-01 | Phase 18 | Complete |
| MVAL-02 | Phase 18 | Complete |
| MVAL-03 | Phase 18 | Complete |
| MVAL-04 | Phase 18 | Complete |

**Coverage:**
- v2 requirements: 24 total, 21 complete, 3 pending (POLISH-*)
- v3 requirements: 15 total, 13 complete, 2 accepted limitations (SIG-05/06)
- v4 requirements: 8 total, 8 complete
- Unmapped: 0

---
*Requirements defined: 2026-03-09*
*Traceability updated: 2026-03-27*
