# Phase 3: Off-chain Daemons - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Build three Node.js daemons (Signaling, Control Plane, Validator) and a shared types package, organized as a pnpm monorepo. Daemons consume on-chain events from Phase 2 registries and interact with the Sui chain via `@mysten/sui` SDK. SFU/MCU relay nodes are NOT in scope (deferred to v2 RELAY-01/02).

</domain>

<decisions>
## Implementation Decisions

### Monorepo Structure
- Sibling repo: `c:\Thesis\dvconf\dvconf-daemons/` (separate from dvconf-contracts)
- pnpm workspaces (no Turborepo — thesis-scale project)
- TypeScript throughout — all daemons and shared package
- Shared package (`@dvconf/shared`) contains: type definitions (matching Move events/structs), Sui SDK chain helpers, structured logger, constants (object IDs from .env)

### Chain Interaction Pattern
- Cursor-based polling via queryEvents() as primary event source (subscribeEvent deprecated since Sui testnet-v1.28.2)
- Env-based keypairs for daemon wallets (private key loaded from `.env` or environment variable)
- Thin TX wrapper in shared package: build TX → sign → execute → wait for effects → extract events. Handles retry internally.
- Exponential backoff: 1s base, 2x multiplier, 30s ceiling, max 5 retries then log error and skip

### CP Daemon Scope
- Subscribes to registry events (relay registration, load updates, RTT probes)
- Sends heartbeat() to ControlPlaneRegistry on-chain at configured interval
- Runs relay scoring algorithm against real on-chain data (reputation, RTT, load, stake, region)
- **Logs scores but does NOT submit votes** — Room lifecycle contracts don't exist yet (v2)
- Auto-registers on startup via registration.move + ControlPlaneRegistry (requires funded wallet with stake)

### Validator Daemon Scope
- Registers on-chain via registration.move + ValidatorRegistry
- Assigns session wallet via ValidatorRegistry (dual-key flow)
- Simulates measurement collection (packet stats, latency, loss, bytes) — logs what a SessionProof would contain
- **Does NOT submit SessionProofs** — Economic layer contracts don't exist yet (v2)
- Auto-registers on startup (requires funded wallet with stake)

### Signaling Node Scope
- Room-based WebSocket server for ICE candidate and SDP offer/answer exchange
- Clients join by room ID, messages forwarded to peers in the same room
- Stateless — no chain dependency, no authentication
- Production-ready signaling logic (not a minimal echo server)

### Dev Environment & Testing
- Windows-native development — no mediasoup needed (SFU/MCU relay deferred to v2)
- Local Sui network (`sui start --force-regenesis --with-faucet`) for chain testing
- Vitest as test framework
- Basic smoke integration tests: start local Sui → deploy contracts → start daemons → verify heartbeat/events on-chain (2-3 tests)

### Claude's Discretion
- Logger library choice (pino, winston, or other)
- Exact pnpm workspace package layout (packages/ vs apps/ naming)
- WebSocket library for signaling (ws, socket.io, or other)
- TypeScript build tool (tsc, tsup, tsx for dev)
- Exact event type mappings from Move structs

</decisions>

<specifics>
## Specific Ideas

- `.env.testnet` in dvconf-contracts already has all deployed object IDs — shared package should reference these
- Phase 2 registry events are the daemon inputs: RoomCreated, RoomClosed, CPRegistered, CPHeartbeat, CPAssignedToRoom, RelayRegistered, RelayLoadUpdated, RelayRTTUpdated, ValidatorRegistered, SessionWalletAssigned, SessionWalletRevealed, UserRegistered, UserProfileUpdated, MinerRegistered, MinerUnregistered
- CP scoring algorithm uses: relay reputation, validator_probed_rtt (from RelayRegistry), current load, stake amount, region — all available on-chain now
- Validator dual-key: main wallet registers, session wallet is assigned via ValidatorRegistry.assign_session_wallet() (package-gated)

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `.env.testnet` — deployed testnet object IDs (Package, NetworkRegistry, MinerStore, TreasuryCap, AdminCap, UpgradeCap)
- `docs/decentralized_video_conference-rev4.md` — full architecture spec with scoring formula, node roles, relay assignment flow
- Phase 2 Move events — all registries emit typed events that daemons will subscribe to

### Established Patterns
- Error code namespaces: registration 400s, room_manager 500s, CP 510s, relay 520s, validator 530s, user 540s
- `registration::register()` signature: requires registry, store, coin (for stake), plus endpoint/capability fields
- RTT is always validator-probed (RelayRegistry.update_rtt is package-gated)
- Session wallets are package-gated in ValidatorRegistry

### Integration Points
- Daemons call `registration::register()` to self-register as miners
- CP daemon calls `control_plane_registry::heartbeat()` on-chain
- CP daemon reads relay data from RelayRegistry (RTT, load, mode) for scoring
- Validator daemon calls `validator_registry::assign_session_wallet()` and later `reveal_session_wallet()`
- All daemons subscribe to events from their respective registries

</code_context>

<deferred>
## Deferred Ideas

- SFU/MCU relay nodes (mediasoup) — v2 RELAY-01/02
- Actual relay assignment voting (needs Room lifecycle contracts) — v2 ROOM-02
- SessionProof submission (needs Economic layer contracts) — v2 ECON-02/03
- Room existence validation in signaling (adds chain dependency) — future enhancement
- WSL2/Docker setup only needed when relay nodes with mediasoup are built

</deferred>

<revision_log>
## Revision Log

- **2026-03-05 (checker revision):** Changed "Chain Interaction Pattern" from "WebSocket subscription as primary event source, polling with checkpoint cursor as fallback on reconnect" to "Cursor-based polling via queryEvents() as primary event source (subscribeEvent deprecated since Sui testnet-v1.28.2)." Research confirmed subscribeEvent was deprecated; plans already implemented polling correctly.

</revision_log>

---

*Phase: 03-off-chain-daemons*
*Context gathered: 2026-03-05*
