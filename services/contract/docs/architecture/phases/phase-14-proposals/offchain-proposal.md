DESIGN PROPOSAL -- OffChain: Phase 14 Integration & Hardening
Author: OffChain Agent
Phase: 14
Date: 2026-03-12

---

## Module 1: metrics-server.ts (Relay Daemon)

PURPOSE:
  Expose relay session metrics over HTTP so that validator daemons and monitoring
  tools can query per-room bandwidth, peer counts, and quality data without
  touching the relay's WebSocket signaling channel.

OWNS:
  - HTTP server lifecycle on METRICS_PORT (default 4001)
  - Route handling for `/metrics` (global) and `/metrics/:roomId` (per-room)

STRUCTS / TYPES:
  ```typescript
  /** JSON response for GET /metrics/:roomId */
  interface RoomMetricsResponse {
    bytesForwarded: string;   // bigint serialized as string
    uniquePeers: number;
    packetsLost: number;
    jitter: number;
    duration: number;         // seconds since first peer joined
    activePeers: number;
  }

  /** JSON response for GET /metrics (global health check) */
  interface GlobalMetricsResponse {
    totalBytesForwarded: string;
    activeSessions: number;
    roomCount: number;
  }
  ```

PUBLIC API:
  ```typescript
  /** Start the HTTP metrics server. Returns a close function for graceful shutdown. */
  export function startMetricsServer(
    metrics: MetricsTracker,
    getRoomCount: () => number,
    port?: number,
    logger?: Logger,
  ): { close: () => void };
  ```

DEPENDS ON:
  - `./metrics.ts` -- MetricsTracker (getRoomMetrics, getRoomUniquePeers)
  - Node.js built-in `http` module (no Express dependency)
  - `@dvconf/shared` -- Logger

EVENTS CONSUMED: None (reads MetricsTracker state directly)
EVENTS EMITTED: None (HTTP responses only)

### Changes to existing files

**metrics.ts** -- Add two new methods to MetricsTracker:
  ```typescript
  /** Aggregate all peer entries for a room into a single RoomMetricsResponse. */
  getRoomMetrics(roomId: string): RoomMetricsResponse | null;

  /** Return count of unique peers that have ever joined a room. */
  getRoomUniquePeers(roomId: string): number;
  ```

**signaling.ts** -- Track unique peer IDs per room:
  - Add a `uniquePeers: Map<string, Set<string>>` to the signaling server closure
  - On `join` message: add peerId to the Set for that roomId
  - On room teardown (all peers gone): do NOT clear the Set -- metrics must survive
    until the room is fully settled on-chain. Clear only via explicit `clearRoom()`.
  - Expose the uniquePeers map to MetricsTracker via constructor injection or getter.

**index.ts** -- Wire metrics server into startup:
  - After creating MetricsTracker and signaling server, call `startMetricsServer()`
  - Add `metricsServer.close()` to the graceful shutdown handler

---

## Module 2: probe.ts (Validator Daemon)

PURPOSE:
  Replace simulated measurements with real network probing against a relay node.
  Two strategies: STUN-based RTT measurement and HTTP metrics fetch from the
  relay's metrics endpoint.

OWNS:
  - STUN probe logic (UDP STUN Binding Requests for RTT measurement)
  - HTTP metrics fetch from relay's `/metrics/:roomId` endpoint
  - Probe result aggregation (avg latency, jitter, packet loss)

STRUCTS / TYPES:
  ```typescript
  /** Raw result from a STUN probe batch. */
  interface StunProbeResult {
    avgLatencyMs: bigint;
    jitterMs: bigint;
    packetLossRate: bigint;   // basis points (probes lost / probes sent * 10000)
    probesSent: number;
    probesReceived: number;
  }

  /** Metrics fetched from relay HTTP endpoint. */
  interface RelayMetricsFetch {
    bytesForwarded: bigint;
    uniquePeers: bigint;
    packetsLost: number;
    jitter: number;
    duration: number;
  }
  ```

PUBLIC API:
  ```typescript
  /** Send N STUN Binding Requests to relay endpoint, measure RTT. */
  export async function stunProbe(
    relayHost: string,
    relayPort: number,
    probeCount?: number,       // default 10
    timeoutMs?: number,        // per-probe timeout, default 3000
  ): Promise<StunProbeResult>;

  /** Fetch room metrics from relay HTTP endpoint. */
  export async function fetchRelayMetrics(
    metricsBaseUrl: string,
    roomId: string,
  ): Promise<RelayMetricsFetch | null>;

  /** Combined probe: STUN for RTT + HTTP for bandwidth/peers. */
  export async function probeRelay(
    relayHost: string,
    relayStunPort: number,
    metricsBaseUrl: string,
    roomId: string,
  ): Promise<MeasurementResult>;
  ```

DEPENDS ON:
  - Node.js built-in `dgram` module for UDP STUN probes
  - Node.js built-in `http` module for metrics fetch
  - `./measurements.ts` -- MeasurementResult interface (kept unchanged)

EVENTS CONSUMED: None
EVENTS EMITTED: None

### Changes to existing files

**measurements.ts** -- Update `collectMeasurements()`:
  ```typescript
  /** Collect measurements for a relay. Uses real probing if relay endpoint is
   *  configured, falls back to simulation with a warning log. */
  export async function collectMeasurements(
    relayMinerId: string,
    relayHost?: string,
    relayStunPort?: number,
    metricsBaseUrl?: string,
    roomId?: string,
  ): Promise<MeasurementResult>;
  ```
  - Signature changes from sync to async (callers must await)
  - When relayHost is provided, delegates to `probeRelay()` from probe.ts
  - When relayHost is undefined/null, falls back to existing simulation logic
  - Logs a WARN when falling back to simulation

### STUN probing strategy

STUN probes target the relay's mediasoup RTC port range. mediasoup WebRTC
transports with `enableUdp: true` respond to STUN Binding Requests on their
allocated ports. The probe uses the relay's public IP + a port within the
configured `rtcMinPort`-`rtcMaxPort` range.

Configuration via environment variables:
  - `RELAY_STUN_HOST` -- relay public IP/hostname (default: parsed from RELAY_ENDPOINT_URL)
  - `RELAY_STUN_PORT` -- port for STUN probes (default: rtcMinPort from relay, typically 10000)
  - `RELAY_METRICS_URL` -- base URL for relay metrics HTTP endpoint (default: `http://<relayHost>:4001`)

**Decision: Use the relay's mediasoup RTC port, NOT a separate probe port.**
Rationale: mediasoup transports already handle STUN on their RTC ports. Adding a
dedicated probe port would require relay-side changes. Using the existing RTC
port range measures the actual path that media will traverse, giving more
realistic RTT numbers. If the relay has no active transports (no rooms), the
STUN probe will timeout -- this is handled by the fallback to simulation.

---

## Module 3: room-assignment.ts (CP Daemon)

PURPOSE:
  Score available relay and signaling nodes, select the best candidates for a
  newly created room, and submit the assignment on-chain via
  `room_manager::assign_relay_and_signaling` PTB.

OWNS:
  - Relay scoring algorithm (weighted multi-factor)
  - Signaling node scoring algorithm (region + load)
  - On-chain assignment PTB construction and submission

STRUCTS / TYPES:
  ```typescript
  /** Decoded relay info from devInspect of get_active_relays(). */
  interface RelayCandidate {
    minerId: string;
    operator: string;
    stakeAmount: bigint;
    mode: number;           // 0=SFU, 1=MCU
    reputation: bigint;
    region: string;
    endpointUrl: string;
    rtt: bigint;            // from rtt_scores table
    load: bigint;           // from loads table
  }

  /** Decoded signaling info from devInspect of get_active_nodes(). */
  interface SignalingCandidate {
    minerId: string;
    operator: string;
    region: string;
    endpointUrl: string;
    load: bigint;
  }

  /** Result of the assignment operation. */
  interface AssignmentResult {
    relayMinerId: string;
    signalingMinerId: string;
    txDigest: string;
  }
  ```

PUBLIC API:
  ```typescript
  /** Fetch active relays via devInspect, score them, return sorted list. */
  export async function scoreRelays(
    client: SuiClient,
    config: NetworkConfig,
    roomRegion: string,
    relayMode: number,
  ): Promise<RelayCandidate[]>;

  /** Fetch active signaling nodes via devInspect, score them, return sorted. */
  export async function scoreSignalingNodes(
    client: SuiClient,
    config: NetworkConfig,
    roomRegion: string,
  ): Promise<SignalingCandidate[]>;

  /** Score relays + signaling, pick top of each, submit assignment PTB. */
  export async function assignRoom(
    client: SuiClient,
    signer: Ed25519Keypair,
    config: NetworkConfig,
    roomId: string,
    relayMode: number,
    roomRegion?: string,
  ): Promise<AssignmentResult | null>;
  ```

DEPENDS ON:
  - `@mysten/sui/client` -- SuiClient (devInspect for registry queries)
  - `@mysten/sui/transactions` -- Transaction (PTB for assign_relay_and_signaling)
  - `@mysten/bcs` -- BCS decoding of devInspect results
  - `@dvconf/shared` -- NetworkConfig, Logger, executeWithRetry

EVENTS CONSUMED:
  - `room_manager::RoomCreated` -- triggers assignment (handled in index.ts event handler)

EVENTS EMITTED: None (the on-chain TX emits `RoomAssigned`)

### Scoring formula

Relay scoring uses NetworkRegistry weights (fetched via devInspect):
  ```
  score = w_reputation * (reputation / MAX_REP)
        + w_rtt        * (1 - rtt / MAX_RTT)
        + w_load       * (1 - load / MAX_LOAD)
        + w_stake      * (stake / MAX_STAKE)
        + w_region     * region_match   // 1.0 if same region, 0.0 otherwise
  ```
  All arithmetic in integer basis points. Division by MAX values done in basis
  points to avoid floating point.

Signaling scoring (simpler, no on-chain weights):
  ```
  score = 5000 * region_match + 5000 * (1 / (load + 1))
  ```

Filter: relays must match the room's `relay_mode` (SFU or MCU).

### Changes to existing files

**index.ts** -- Wire room assignment into event handling:
  - Import `assignRoom` from `./room-assignment.js`
  - In the `roomPoller` event handler, when a `RoomCreated` event is received:
    1. Extract `room_id` and `relay_mode` from event parsed JSON
    2. Call `assignRoom(client, signer, config, roomId, relayMode)`
    3. Log success/failure
  - Refactor `createEventHandler` to accept `client`, `signer`, `config` params
    so it can call `assignRoom` (currently it only logs events)

---

## Module 4: reward-trigger.ts (Validator Daemon)

PURPOSE:
  Detect room closures, wait for sufficient validator proofs, and trigger
  `economic_layer::distribute_rewards` on-chain to complete the economic cycle.

OWNS:
  - Room closure detection (RoomClosed event handling)
  - Proof sufficiency polling (check escrow proof count)
  - distribute_rewards PTB construction and submission
  - Relay StakePosition discovery

STRUCTS / TYPES:
  ```typescript
  /** Tracks an active room the validator is measuring. */
  interface ActiveRoom {
    roomId: string;
    escrowId: string | null;     // null until EscrowCreated is received
    relayMinerId: string | null; // discovered from RoomAssigned event or proofs
    relayStakeId: string | null; // discovered via getOwnedObjects query
    createdAt: number;
  }
  ```

PUBLIC API:
  ```typescript
  /** Trigger reward distribution for a closed room.
   *  Discovers relay StakePosition, waits for proofs, submits PTB. */
  export async function triggerDistribution(
    client: SuiClient,
    signer: Ed25519Keypair,
    config: NetworkConfig,
    escrowId: string,
    roomId: string,
    relayMinerId: string,
    logger: Logger,
  ): Promise<boolean>;

  /** Poll escrow object to check if sufficient proofs exist. */
  export async function waitForProofs(
    client: SuiClient,
    escrowId: string,
    minProofs: number,
    timeoutMs: number,
    logger: Logger,
  ): Promise<boolean>;

  /** Find a relay's StakePosition object ID by querying owned objects. */
  export async function findRelayStakePosition(
    client: SuiClient,
    relayOperatorAddress: string,
    packageId: string,
  ): Promise<string | null>;
  ```

DEPENDS ON:
  - `@mysten/sui/client` -- SuiClient (getOwnedObjects, getObject)
  - `@mysten/sui/transactions` -- Transaction (PTB for distribute_rewards)
  - `@dvconf/shared` -- NetworkConfig, Logger, ErrorCodes, executeWithRetry

EVENTS CONSUMED:
  - `room_manager::RoomClosed` -- triggers distribution (handled in index.ts)
  - `room_manager::RoomCreated` -- starts measuring new rooms (handled in index.ts)
  - `room_manager::RoomAssigned` -- discovers relay assignment for room (Task 1 event)
  - `economic_layer::EscrowCreated` -- already handled, maps roomId to escrowId

EVENTS EMITTED: None (the on-chain TX emits `RewardsDistributed` or `RelaySlashed`)

### Relay StakePosition discovery

**OPEN QUESTION RESOLVED: How does the validator daemon discover the relay's
StakePosition object ID for distribute_rewards?**

Strategy: **Query owned objects of the relay operator address.**

1. The `RelayNodeInfo` struct (from `relay_registry::get_active_relays()`) contains
   the `operator` address field.
2. The validator daemon devInspects `relay_registry::borrow_info(registry, relay_miner_id)`
   to get the relay's operator address.
3. Then calls `client.getOwnedObjects({ owner: operatorAddress, filter: { StructType: '<packageId>::staking::StakePosition' } })`
   to find StakePosition objects owned by that operator.
4. Filters by `miner_id` field matching the relay's miner ID (in case the operator
   has multiple StakePositions for different roles).
5. The matching StakePosition object ID is cached in the `ActiveRoom` state.

This approach requires no on-chain changes. It uses existing `getOwnedObjects`
Sui RPC which is efficient for small result sets (operators typically have 1-3
StakePositions). The result is cached per relay, so repeated lookups are avoided.

Fallback: If the query returns no results (relay transferred stake, or object was
consumed), log an error and skip distribution for this room. The escrow remains
on-chain for manual resolution.

### Changes to existing files

**index.ts** -- Major rewiring for dynamic room lifecycle:
  - Replace single `ROOM_ID` env var with dynamic room discovery
  - Add `activeRooms: Map<string, ActiveRoom>` to DaemonState
  - Add `room_manager` EventPoller for `RoomCreated` and `RoomClosed` events
  - Add `RoomAssigned` event handling (from Task 1 on-chain event)
  - On `RoomCreated`: add to activeRooms, start measuring
  - On `RoomAssigned`: record relayMinerId in ActiveRoom
  - On `EscrowCreated`: update ActiveRoom with escrowId
  - On `RoomClosed`: if escrow exists, call `triggerDistribution()`
  - Measurement loop: iterate over all activeRooms instead of single room
  - Fix `unique_peers`: before building proof, fetch `GET /metrics/:roomId` from
    relay metrics endpoint to get real `uniquePeers` count (fallback to 0 if unreachable)

---

## Module 5: Shared Types Updates (packages/shared)

PURPOSE:
  Sync TypeScript event interfaces and module constants with on-chain changes
  from Phase 14 Tasks 1-2.

OWNS:
  - RoomAssigned event type definition
  - Module name constants for event polling

### Changes to existing files

**events.ts** -- Add RoomAssigned event:
  ```typescript
  /** Emitted when CP daemon assigns relay+signaling to a room. */
  export interface RoomAssigned {
    room_id: string;
    relay_id: string;
    signaling_id: string;
  }
  ```
  Add to DvconfEvent union type.

**chain.ts** -- Add module name constants:
  ```typescript
  export const roomManagerModuleName = 'room_manager' as const;
  export const relayRegistryModuleName = 'relay_registry' as const;
  export const signalingRegistryModuleName = 'signaling_registry' as const;
  ```
  Note: `economicLayerModuleName` already exists. Adding the others for
  consistency across all daemon event pollers.

**constants.ts** -- No new error codes expected from Tasks 1-2. If
  `registration::unregister()` signature changes (TD-P11-04), no error code
  change is needed -- it is a parameter addition. Verify after OnChain tasks complete.

---

## Module 6: load-test.ts (Scripts)

PURPOSE:
  End-to-end load testing script that validates the full session lifecycle with
  concurrent rooms and simulated clients. Verifies: room creation -> escrow ->
  CP assignment -> relay connection -> validator proof -> reward distribution.

OWNS:
  - Test orchestration (room lifecycle management)
  - Simulated client connections (WebSocket to relay)
  - Result reporting and timing

STRUCTS / TYPES:
  ```typescript
  interface LoadTestConfig {
    sessions: number;          // number of concurrent rooms (default 1)
    clientsPerRoom: number;   // simulated clients per room (default 3)
    durationMs: number;        // how long clients stay connected (default 30000)
    rpcUrl: string;
    packageId: string;
    // ... other NetworkConfig fields
  }

  interface SessionReport {
    roomId: string;
    connectionTimeMs: number;
    bytesForwarded: string;
    proofCount: number;
    rewardDistributed: boolean;
    error?: string;
  }

  interface LoadTestReport {
    sessions: SessionReport[];
    totalDurationMs: number;
    successCount: number;
    failureCount: number;
  }
  ```

PUBLIC API:
  ```typescript
  /** Run the full load test. */
  export async function runLoadTest(config: LoadTestConfig): Promise<LoadTestReport>;
  ```

DEPENDS ON:
  - `@mysten/sui/client` -- SuiClient
  - `@mysten/sui/transactions` -- Transaction (room creation, escrow, close)
  - `ws` -- WebSocket client (simulated relay connections)
  - `@dvconf/shared` -- NetworkConfig, EventPoller, Logger

EVENTS CONSUMED:
  - `room_manager::RoomAssigned` -- detect when CP has assigned relay/signaling
  - `economic_layer::RewardsDistributed` -- detect when rewards are distributed

EVENTS EMITTED: None

### Script execution flow

```
1. Parse CLI args (--sessions N, --clients-per-room N, --duration-ms N)
2. Load network config from .env
3. For each session (parallelized):
   a. Create room on-chain (room_manager::create_room PTB)
   b. Create escrow on-chain (economic_layer::create_escrow PTB)
   c. Poll for RoomAssigned event (max 30s timeout)
   d. Read assigned relay endpoint URL from chain
   e. Spawn N WebSocket clients that connect to relay
   f. Each client sends: join -> createTransport(send) -> createTransport(recv)
   g. Wait for configured duration
   h. Disconnect all clients
   i. Close room on-chain (room_manager::close_room PTB)
   j. Wait for RewardsDistributed event (max 60s timeout)
   k. Fetch relay metrics for bytes forwarded
   l. Record SessionReport
4. Aggregate and print LoadTestReport
```

### Daemon dependency handling

**OPEN QUESTION RESOLVED: How does the load test script handle daemons that
aren't running?**

Strategy: **Pre-flight health checks with clear error messages.**

Before running sessions, the script performs health checks:
1. **RPC connectivity**: Attempt `client.getLatestCheckpointSequenceNumber()`.
   If it fails, abort with "Cannot reach Sui RPC at <url>".
2. **CP daemon**: After creating a room, if no `RoomAssigned` event arrives within
   30 seconds, abort that session with "CP daemon not responding -- ensure cp-daemon
   is running". The script does NOT start daemons itself.
3. **Relay daemon**: After reading the assigned relay URL, attempt a WebSocket
   connection. If it fails after 3 retries (exponential backoff), abort that
   session with "Relay at <url> unreachable -- ensure relay daemon is running".
4. **Validator daemon**: After closing the room, if no `RewardsDistributed` event
   arrives within 60 seconds, the session report marks `rewardDistributed: false`
   with a warning, but does NOT fail the test. Reward distribution depends on
   validator proof submission which may take multiple measurement cycles.

The script prints a startup checklist:
```
Load Test Pre-flight:
  [OK] Sui RPC reachable at http://127.0.0.1:9000
  [OK] Network config loaded (package: 0xf7cf...)
  [  ] CP daemon: will verify on first room assignment
  [  ] Relay daemon: will verify on first connection
  [  ] Validator daemon: will verify on reward distribution (optional)
```

---

## OPEN QUESTIONS

### Q1: How does the validator daemon discover the relay's StakePosition object ID for distribute_rewards?

**RESOLVED** -- See Module 4 above. The validator queries `relay_registry::borrow_info`
via devInspect to get the relay operator address, then uses `client.getOwnedObjects`
with a StructType filter for `StakePosition`. The result is filtered by miner_id
and cached per relay. No on-chain changes required.

### Q2: Should STUN probes use the relay's mediasoup port or a separate probe port?

**RESOLVED** -- See Module 2 above. Use the relay's mediasoup RTC port (from the
`rtcMinPort`-`rtcMaxPort` range). mediasoup transports respond to STUN Binding
Requests on their RTC ports when `enableUdp: true`. This measures the actual
media path without requiring relay-side changes. Configured via `RELAY_STUN_PORT`
env var (default: 10000, matching typical rtcMinPort).

### Q3: How does the load test script handle daemons that aren't running?

**RESOLVED** -- See Module 6 above. Pre-flight health checks with per-step
timeouts and clear error messages. The script does not start or manage daemon
processes -- it assumes they are running and reports which ones are unreachable.

---

## CROSS-MODULE DEPENDENCIES

```
                  +-----------------+
                  | shared/types    |  (Task 9)
                  | events.ts       |
                  | chain.ts        |
                  | constants.ts    |
                  +-------+---------+
                          |
            +-------------+-------------+
            |             |             |
    +-------v------+ +---v--------+ +--v-----------+
    | cp-daemon    | | validator  | | relay        |
    | room-assign  | | reward-    | | metrics-     |
    | .ts (Task 5) | | trigger.ts | | server.ts    |
    |              | | (Task 6)   | | (Task 3)     |
    +--------------+ +-----+------+ +------+-------+
                           |               |
                           +------+--------+
                                  |
                           +------v--------+
                           | validator     |
                           | probe.ts      |
                           | (Task 4)      |
                           +------+--------+
                                  |
                           +------v--------+
                           | load-test.ts  |
                           | (Task 10)     |
                           +--------------+
```

Dependencies flow downward. The load-test script depends on all daemons being
operational. probe.ts depends on the relay's metrics-server being available.
reward-trigger depends on probe.ts (real measurements) and metrics-server
(unique_peers). All modules depend on shared types.

---

## INTEGRATION CONTRACTS

### IC-P14-1: Relay Metrics HTTP Endpoint
  - Provider: relay daemon (metrics-server.ts)
  - Consumer: validator daemon (probe.ts), load-test script
  - Endpoint: `GET http://<relay-host>:4001/metrics/:roomId`
  - Response: `{ bytesForwarded: string, uniquePeers: number, packetsLost: number, jitter: number, duration: number, activePeers: number }`
  - Error: 404 if roomId not found, 500 on internal error

### IC-P14-2: RoomAssigned Event Contract
  - Provider: on-chain room_manager (Task 1)
  - Consumer: cp-daemon (to confirm assignment), validator-daemon (to discover relay),
    load-test script (to proceed with connection)
  - Event type: `<packageId>::room_manager::RoomAssigned`
  - Fields: `{ room_id: ID, relay_id: ID, signaling_id: ID }`

### IC-P14-3: distribute_rewards TX Argument Contract
  - Provider: on-chain economic_layer
  - Consumer: validator daemon (reward-trigger.ts)
  - Arguments (in order):
    1. `net_reg: &NetworkRegistry`
    2. `escrow: &mut RoomEscrow`
    3. `room_mgr: &RoomManager`
    4. `relay_reg: &mut RelayRegistry`
    5. `validator_reg: &mut ValidatorRegistry`
    6. `relay_stake: &mut StakePosition`
  - Relay StakePosition must have `miner_id` matching the relay attested in escrow proofs

### IC-P14-4: collectMeasurements Signature Change
  - Module: validator-daemon/src/measurements.ts
  - Before: `collectMeasurements(relayMinerId: string): MeasurementResult` (sync)
  - After: `collectMeasurements(relayMinerId, relayHost?, relayStunPort?, metricsBaseUrl?, roomId?): Promise<MeasurementResult>` (async)
  - Impact: All callers in index.ts must `await` the result
  - Backward compatible: When called without optional params, falls back to simulation
