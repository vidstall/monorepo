# Phase 3: Off-chain Daemons - Research

**Researched:** 2026-03-05
**Domain:** Node.js/TypeScript daemons interacting with Sui Move contracts via @mysten/sui SDK
**Confidence:** MEDIUM-HIGH

## Summary

Phase 3 builds three Node.js daemons (Signaling, Control Plane, Validator) and a shared types package as a pnpm workspace monorepo in `c:\Thesis\dvconf\dvconf-daemons/`. The daemons consume on-chain events from Phase 2 registry contracts and interact with the Sui chain via the `@mysten/sui` SDK.

Critical finding: the Sui TypeScript SDK has undergone significant changes. The WebSocket `subscribeEvent` method has been **deprecated** (as of testnet-v1.28.2, July 2024). The recommended approach is **polling with `queryEvents` and cursor-based pagination**. A new `SuiGrpcClient` from `@mysten/sui/grpc` is the recommended client class, though `SuiClient` from `@mysten/sui/client` still works for now. The CONTEXT.md decision to use "WebSocket subscription as primary" needs to be adapted to the current SDK reality: polling with checkpoint cursor is now the primary pattern, not WebSocket subscription.

**Primary recommendation:** Use `@mysten/sui` v2.5.x with `SuiClient` (from `@mysten/sui/client`) for transaction execution and `queryEvents` with cursor-based polling for event consumption. Structure as pnpm workspace with `@dvconf/shared` package containing types, chain helpers, and logger. Use `pino` for structured logging and `ws` for the signaling WebSocket server.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Sibling repo: `c:\Thesis\dvconf\dvconf-daemons/` (separate from dvconf-contracts)
- pnpm workspaces (no Turborepo -- thesis-scale project)
- TypeScript throughout -- all daemons and shared package
- Shared package (`@dvconf/shared`) contains: type definitions (matching Move events/structs), Sui SDK chain helpers, structured logger, constants (object IDs from .env)
- WebSocket subscription as primary event source, polling with checkpoint cursor as fallback on reconnect
- Env-based keypairs for daemon wallets (private key loaded from `.env` or environment variable)
- Thin TX wrapper in shared package: build TX -> sign -> execute -> wait for effects -> extract events. Handles retry internally.
- Exponential backoff: 1s base, 2x multiplier, 30s ceiling, max 5 retries then log error and skip
- CP daemon: subscribes to registry events, sends heartbeat(), runs relay scoring algorithm, **logs scores but does NOT submit votes** (Room lifecycle contracts don't exist yet)
- CP daemon: auto-registers on startup via registration.move + ControlPlaneRegistry
- Validator daemon: registers on-chain via registration.move + ValidatorRegistry, assigns session wallet, simulates measurements, **does NOT submit SessionProofs** (Economic layer contracts don't exist yet)
- Validator daemon: auto-registers on startup
- Signaling node: room-based WebSocket server for ICE/SDP exchange, stateless, no chain dependency, no authentication
- Windows-native development -- no mediasoup needed
- Local Sui network for chain testing
- Vitest as test framework
- Basic smoke integration tests: start local Sui -> deploy contracts -> start daemons -> verify heartbeat/events on-chain

### Claude's Discretion
- Logger library choice (pino, winston, or other)
- Exact pnpm workspace package layout (packages/ vs apps/ naming)
- WebSocket library for signaling (ws, socket.io, or other)
- TypeScript build tool (tsc, tsup, tsx for dev)
- Exact event type mappings from Move structs

### Deferred Ideas (OUT OF SCOPE)
- SFU/MCU relay nodes (mediasoup) -- v2 RELAY-01/02
- Actual relay assignment voting (needs Room lifecycle contracts) -- v2 ROOM-02
- SessionProof submission (needs Economic layer contracts) -- v2 ECON-02/03
- Room existence validation in signaling (adds chain dependency) -- future enhancement
- WSL2/Docker setup only needed when relay nodes with mediasoup are built
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DAEMON-01 | Signaling node exchanges WebRTC ICE candidates via WebSocket | ws library for WebSocket server, room-based message routing |
| DAEMON-02 | Signaling node is stateless and does not depend on chain state | No chain imports in signaling package; pure WebSocket relay |
| DAEMON-03 | CP daemon subscribes to Sui events (room creation, relay updates) | queryEvents polling with cursor (subscribeEvent deprecated); event type mappings from Move structs |
| DAEMON-04 | CP daemon runs relay scoring algorithm using on-chain data | Scoring formula from spec: `w1*reputation + w2*(1/rtt) + w3*(1/load) + w4*stake + w5*region_match`; weights from NetworkRegistry |
| DAEMON-05 | CP daemon submits relay assignment votes on-chain | **Scoped down**: logs scores only, does NOT submit votes (Room lifecycle contracts don't exist). TX wrapper prepared for future use. |
| DAEMON-06 | CP daemon sends heartbeat() to ControlPlaneRegistry at configured interval | Transaction building with `Transaction` class; heartbeat requires NetworkRegistry + ControlPlaneRegistry + ControlPlaneCap objects |
| DAEMON-07 | CP daemon uses exponential backoff on chain interaction failures | Shared retry utility: 1s base, 2x multiplier, 30s ceiling, 5 max retries |
| DAEMON-08 | Validator daemon joins rooms disguised as regular user (session wallet) | **Scoped down**: registers and assigns session wallet; does not actually join rooms (no Room lifecycle). Ed25519Keypair for session wallet generation. |
| DAEMON-09 | Validator daemon measures packet integrity, latency, loss, bytes forwarded | **Scoped down**: simulates measurements with mock data, logs what a SessionProof would contain |
| DAEMON-10 | Validator daemon submits dual-key signed SessionProof on-chain | **Scoped down**: simulates dual-key signing flow, does NOT submit (Economic layer contracts don't exist) |
| DAEMON-11 | All daemons share types via monorepo shared package | `@dvconf/shared` package with TypeScript interfaces matching Move event structs |
| DAEMON-12 | All daemons use @mysten/sui SDK for chain interactions | `@mysten/sui` v2.5.x with SuiClient + Transaction class |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@mysten/sui` | ^2.5.0 | Sui chain interactions (client, transactions, keypairs) | Official Mysten Labs SDK, only supported option |
| `ws` | ^8.x | WebSocket server for signaling node | Fastest, most battle-tested Node.js WebSocket library, no unnecessary overhead |
| `pino` | ^10.3.x | Structured JSON logging | Fastest Node.js logger, JSON-native, non-blocking, perfect for daemon processes |
| `vitest` | ^4.0.x | Test framework | User decision; ESM-native, fast, TypeScript built-in |
| `typescript` | ^5.5 | Type safety | Required by project |
| `tsx` | ^4.x | Dev runner (ts-node alternative) | Fast TypeScript execution for development, zero-config ESM support |
| `dotenv` | ^16.x | Environment variable loading | Load .env files for object IDs and keypairs |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pino-pretty` | ^13.x | Human-readable log output | Development only (never production) |
| `@types/ws` | ^8.x | TypeScript types for ws | Always alongside ws |
| `tsup` | ^8.x | Build tool for shared package | Bundle @dvconf/shared for consumption by daemon packages |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pino | winston | Winston is slower, heavier; pino is 5-10x faster for structured JSON. Pino wins for daemons. |
| ws | socket.io | socket.io adds rooms/namespaces/fallbacks we don't need; signaling is simple relay. ws is lighter. |
| tsx | ts-node | tsx is faster, zero-config ESM support; ts-node requires more configuration for ESM |
| tsup | tsc | tsup bundles cleanly for monorepo consumption; tsc works but needs more path alias config |

**Installation (root):**
```bash
pnpm init
# Root devDependencies
pnpm add -Dw typescript vitest tsx tsup @types/node

# Shared package
pnpm --filter @dvconf/shared add @mysten/sui dotenv pino
pnpm --filter @dvconf/shared add -D @types/ws

# CP daemon
pnpm --filter @dvconf/cp-daemon add @dvconf/shared

# Validator daemon
pnpm --filter @dvconf/validator-daemon add @dvconf/shared

# Signaling
pnpm --filter @dvconf/signaling add ws @dvconf/shared
pnpm --filter @dvconf/signaling add -D @types/ws
```

## Architecture Patterns

### Recommended Project Structure
```
dvconf-daemons/
├── pnpm-workspace.yaml
├── package.json                    # root: scripts, devDeps
├── tsconfig.base.json              # shared TS config
├── .env                            # PACKAGE_ID, object IDs, daemon keypairs
├── .env.example                    # template without secrets
├── packages/
│   └── shared/                     # @dvconf/shared
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│           ├── index.ts            # barrel export
│           ├── types/
│           │   ├── events.ts       # Move event type definitions
│           │   ├── chain.ts        # Sui object types (registry info structs)
│           │   └── constants.ts    # Role codes, relay modes, error codes
│           ├── chain/
│           │   ├── client.ts       # SuiClient factory with network config
│           │   ├── tx.ts           # Thin TX wrapper: build -> sign -> execute -> retry
│           │   ├── events.ts       # Event poller with cursor persistence
│           │   └── keypair.ts      # Load Ed25519Keypair from env
│           └── logger.ts           # Pino logger factory
├── apps/
│   ├── cp-daemon/                  # Control Plane daemon
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── index.ts            # Entry: register, start heartbeat, start event loop
│   │       ├── scoring.ts          # Relay scoring algorithm
│   │       ├── heartbeat.ts        # Periodic heartbeat submission
│   │       └── event-handler.ts    # Process relay/room/CP events
│   ├── validator-daemon/           # Validator daemon
│   │   ├── package.json
│   │   ├── tsconfig.json
│   │   └── src/
│   │       ├── index.ts            # Entry: register, assign session wallet, start loop
│   │       ├── measurements.ts     # Simulated metric collection
│   │       └── session-proof.ts    # Mock SessionProof construction + dual-key signing
│   └── signaling/                  # Signaling node
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│           ├── index.ts            # Entry: start WebSocket server
│           └── rooms.ts            # Room-based message routing
└── tests/
    └── integration/
        └── smoke.test.ts           # Start local Sui, deploy, run daemons, verify
```

### Pattern 1: Event Polling with Cursor Persistence
**What:** Poll `queryEvents` with a cursor, persist last-processed cursor to resume after restart.
**When to use:** All daemons that need on-chain event feeds (CP daemon, Validator daemon).
**Why:** `subscribeEvent` WebSocket API is deprecated in Sui SDK. Polling with cursor is the official recommended pattern.

```typescript
// Source: Sui examples/trading/api/indexer/event-indexer.ts pattern
import { SuiClient, type EventId } from '@mysten/sui/client';

interface EventPoller {
  packageId: string;
  module: string;
  client: SuiClient;
  cursor: EventId | null;
  pollingIntervalMs: number;
}

async function pollEvents(
  poller: EventPoller,
  handler: (event: SuiEvent) => Promise<void>,
): Promise<void> {
  const { data, nextCursor, hasNextPage } = await poller.client.queryEvents({
    query: {
      MoveEventModule: {
        package: poller.packageId,
        module: poller.module,
      },
    },
    cursor: poller.cursor,
    limit: 50,
  });

  for (const event of data) {
    await handler(event);
  }

  if (data.length > 0 && nextCursor) {
    poller.cursor = nextCursor;
    // Persist cursor to file/memory for restart recovery
  }

  // Schedule next poll
  const delay = hasNextPage ? 0 : poller.pollingIntervalMs;
  setTimeout(() => pollEvents(poller, handler), delay);
}
```

### Pattern 2: Thin TX Wrapper with Exponential Backoff
**What:** Shared utility that builds, signs, executes a Sui transaction with automatic retry.
**When to use:** Every on-chain write (heartbeat, registration, etc.).

```typescript
// Source: @mysten/sui SDK patterns + project CONTEXT.md decisions
import { SuiClient } from '@mysten/sui/client';
import { Transaction } from '@mysten/sui/transactions';
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';

interface TxResult {
  digest: string;
  effects: any;
  events: any[];
}

async function executeWithRetry(
  client: SuiClient,
  signer: Ed25519Keypair,
  buildTx: (tx: Transaction) => void,
  label: string,
  logger: Logger,
): Promise<TxResult | null> {
  let delay = 1000;
  const MAX_RETRIES = 5;
  const MAX_DELAY = 30_000;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const tx = new Transaction();
      buildTx(tx);

      const result = await client.signAndExecuteTransaction({
        signer,
        transaction: tx,
        options: { showEffects: true, showEvents: true },
      });

      await client.waitForTransaction({ digest: result.digest });
      logger.info({ digest: result.digest, attempt }, `${label} succeeded`);
      return result as TxResult;
    } catch (err) {
      logger.warn({ err, attempt, delay }, `${label} failed, retrying`);
      if (attempt === MAX_RETRIES) {
        logger.error({ err }, `${label} exhausted retries, skipping`);
        return null;
      }
      await new Promise(r => setTimeout(r, delay));
      delay = Math.min(delay * 2, MAX_DELAY);
    }
  }
  return null;
}
```

### Pattern 3: Room-Based WebSocket Routing (Signaling)
**What:** Clients connect to the signaling server, join a room by ID, and messages are broadcast to other peers in the same room.
**When to use:** Signaling node only.

```typescript
// Source: ws library patterns
import { WebSocketServer, WebSocket } from 'ws';

const rooms = new Map<string, Set<WebSocket>>();

const wss = new WebSocketServer({ port: 8080 });

wss.on('connection', (ws) => {
  let currentRoom: string | null = null;

  ws.on('message', (data) => {
    const msg = JSON.parse(data.toString());

    if (msg.type === 'join') {
      currentRoom = msg.roomId;
      if (!rooms.has(currentRoom)) rooms.set(currentRoom, new Set());
      rooms.get(currentRoom)!.add(ws);
      return;
    }

    // Forward to all peers in the same room (except sender)
    if (currentRoom && rooms.has(currentRoom)) {
      for (const peer of rooms.get(currentRoom)!) {
        if (peer !== ws && peer.readyState === WebSocket.OPEN) {
          peer.send(data.toString());
        }
      }
    }
  });

  ws.on('close', () => {
    if (currentRoom && rooms.has(currentRoom)) {
      rooms.get(currentRoom)!.delete(ws);
      if (rooms.get(currentRoom)!.size === 0) rooms.delete(currentRoom);
    }
  });
});
```

### Anti-Patterns to Avoid
- **Using subscribeEvent for event consumption:** Deprecated, will break. Use queryEvents polling.
- **Hardcoding gas budgets:** Always let the SDK estimate gas dynamically.
- **Comparing Sui addresses with ===:** Always normalize to lowercase hex first.
- **Logging private keys or ICE candidates:** Security violation. ICE candidates contain private IPs.
- **Using `number` for token amounts:** Use `bigint` always -- precision loss on large balances.
- **Synchronous logging in hot paths:** Use pino (async by default) instead of console.log.
- **Polling too aggressively:** Use 2-5s interval for event polling, not sub-second. Sui fullnodes will rate-limit.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured logging | Custom logger | pino | Async, JSON-native, 10x faster than console.log |
| WebSocket server | Raw net.createServer | ws | Handles protocol upgrades, ping/pong, close frames correctly |
| Sui transaction building | Raw RPC fetch calls | @mysten/sui Transaction class | Handles gas estimation, object resolution, BCS serialization |
| Retry with backoff | Custom setTimeout chains | Shared utility in @dvconf/shared | Encapsulate once, reuse everywhere, consistent behavior |
| Keypair management | Manual crypto | Ed25519Keypair from @mysten/sui/keypairs/ed25519 | Handles bech32/hex formats, signing, Sui-specific encoding |
| Environment config | Manual process.env parsing | dotenv + typed config object | Type-safe, validates required vars at startup |

**Key insight:** Every daemon needs the same chain interaction pattern (connect, sign, retry, poll). Building this once in `@dvconf/shared` prevents divergent implementations and ensures consistent retry/logging behavior across all three daemons.

## Common Pitfalls

### Pitfall 1: subscribeEvent is Deprecated
**What goes wrong:** Code uses `client.subscribeEvent()` which no longer works reliably on Sui networks. WebSocket connections drop silently under load.
**Why it happens:** Training data and older docs still show subscribeEvent as the primary pattern.
**How to avoid:** Use `client.queryEvents()` with cursor-based polling. Store the cursor (EventId with txDigest + eventSeq) and resume from it on restart.
**Warning signs:** WebSocket connection drops, silent event loss, no events received after reconnect.

### Pitfall 2: SuiClient vs SuiGrpcClient Confusion
**What goes wrong:** Using the wrong client class or import path.
**Why it happens:** SDK is mid-migration from JSON-RPC to gRPC. Both exist.
**How to avoid:** For this phase, use `SuiClient` from `@mysten/sui/client` -- it still works for all operations needed (queryEvents, signAndExecuteTransaction, getObject). `SuiGrpcClient` from `@mysten/sui/grpc` is newer but may not yet support all write operations needed. Monitor for future migration.
**Warning signs:** Import errors, missing methods on client instance.

### Pitfall 3: ESM-Only Package
**What goes wrong:** `@mysten/sui` is ESM-only. Projects using CommonJS (`require()`) will fail.
**Why it happens:** Package.json missing `"type": "module"` or tsconfig using wrong moduleResolution.
**How to avoid:** Every `package.json` must have `"type": "module"`. Use `"moduleResolution": "NodeNext"` or `"Bundler"` in tsconfig.
**Warning signs:** `ERR_REQUIRE_ESM` errors, `Cannot use import statement outside a module`.

### Pitfall 4: Transaction Pure Value API Changes
**What goes wrong:** Using old `tx.pure('0x123')` or `tx.pure(123, 'u64')` patterns that no longer work.
**Why it happens:** SDK 1.0 changed pure value API.
**How to avoid:** Use typed methods: `tx.pure.address('0x...')`, `tx.pure.u64(123n)`, `tx.pure.string('hello')`.
**Warning signs:** Runtime errors on transaction building, "invalid argument" from RPC.

### Pitfall 5: Owned Object Contention on Registration
**What goes wrong:** Registration requires multiple owned objects (StakePosition, MinerCap/ControlPlaneCap) that must be fetched and passed correctly. Concurrent transactions on the same owned object will fail.
**How to avoid:** Registration is a one-time startup operation. Serialize registration steps: 1) register as miner (creates StakePosition + Cap), 2) wait for objects, 3) register in specific registry. Never parallelize transactions touching the same owned objects.
**Warning signs:** "Object locked by another transaction" errors from Sui.

### Pitfall 6: Event Ordering
**What goes wrong:** Assuming events arrive in chronological order.
**Why it happens:** queryEvents returns events in order, but if polling multiple modules, interleaving can occur.
**How to avoid:** Process events by checkpoint sequence number, not arrival time. The EventId contains txDigest and eventSeq which provide total ordering.
**Warning signs:** State inconsistencies, processing events from a room that hasn't been created yet.

### Pitfall 7: Daemon Registration Flow Complexity
**What goes wrong:** CP/Validator daemon registration requires a multi-step on-chain flow that must succeed atomically.
**Why it happens:** `registration::register()` creates StakePosition + Cap objects. Then `control_plane_registry::register_cp()` or `validator_registry::register_validator()` requires those objects. These are separate transactions.
**How to avoid:** Step 1: Call `registration::register()` with sufficient stake (2 DVCONF for CP, 0.5 DVCONF for Validator). Step 2: Wait for transaction finality. Step 3: Query for the newly created StakePosition and Cap objects. Step 4: Call the registry-specific registration function with those objects.
**Warning signs:** "Object not found" errors on step 2, insufficient stake errors.

## Code Examples

### Creating SuiClient
```typescript
// Source: @mysten/sui SDK docs
import { SuiClient, getFullnodeUrl } from '@mysten/sui/client';

// For testnet
const client = new SuiClient({ url: getFullnodeUrl('testnet') });

// For local network
const client = new SuiClient({ url: 'http://127.0.0.1:9000' });
```

### Loading Keypair from Environment
```typescript
// Source: @mysten/sui SDK docs
import { Ed25519Keypair } from '@mysten/sui/keypairs/ed25519';

// From bech32 secret key (starts with 'suiprivkey')
const keypair = Ed25519Keypair.fromSecretKey(process.env.DAEMON_SECRET_KEY!);

// Generate a fresh session wallet
const sessionKeypair = new Ed25519Keypair();
const sessionAddress = sessionKeypair.getPublicKey().toSuiAddress();
```

### Building and Executing a Heartbeat Transaction
```typescript
// Source: Move contract analysis + @mysten/sui SDK patterns
import { Transaction } from '@mysten/sui/transactions';

function buildHeartbeatTx(
  tx: Transaction,
  packageId: string,
  networkRegistryId: string,
  cpRegistryId: string,
  cpCapId: string,
): void {
  tx.moveCall({
    target: `${packageId}::control_plane_registry::heartbeat`,
    arguments: [
      tx.object(networkRegistryId),   // &NetworkRegistry
      tx.object(cpRegistryId),        // &mut ControlPlaneRegistry
      tx.object(cpCapId),             // &ControlPlaneCap
    ],
  });
}
```

### Registration Flow (Multi-Step)
```typescript
// Step 1: Register as miner (creates StakePosition + Cap)
const registerTx = new Transaction();
const [coin] = registerTx.splitCoins(registerTx.gas, [registerTx.pure.u64(2_000_000_000n)]); // 2 DVCONF for CP
registerTx.moveCall({
  target: `${PACKAGE_ID}::registration::register`,
  arguments: [
    registerTx.object(NETWORK_REGISTRY_ID),
    registerTx.object(MINER_STORE_ID),
    coin,
    registerTx.pure.string('127.0.0.1'),      // ip
    registerTx.pure.u16(8080),                  // port
    registerTx.pure.string('stun:stun.l.google.com:19302'), // stun_url
    registerTx.pure.string(''),                 // turn_url
    registerTx.pure.string('us-east'),          // region
    registerTx.pure.u64(1000n),                 // bandwidth_mbps
    registerTx.pure.u64(100n),                  // max_concurrent
    registerTx.pure.u64(8n),                    // cpu_cores
    registerTx.pure.u8(0),                      // relay_mode (SFU)
    registerTx.pure(bcs.vector(bcs.U8).serialize([])), // turn_credential_hash
  ],
});

// Note: registration::register uses Coin<TOKEN>, not gas coin.
// Daemon wallet needs DVCONF tokens, not just SUI for gas.
// On testnet: mint tokens first using TreasuryCap.
```

### Relay Scoring Algorithm
```typescript
// Source: docs/decentralized_video_conference-rev4.md Section 9.1
interface RelayCandidate {
  minerId: string;
  reputation: bigint;   // 0-10000 basis points
  rtt: bigint;          // milliseconds (validator-probed)
  load: bigint;         // current load count
  stakeAmount: bigint;  // MIST
  region: string;       // e.g. "us-east"
}

interface ScoringWeights {
  reputation: bigint;   // basis points
  rtt: bigint;
  load: bigint;
  stake: bigint;
  regionMatch: bigint;
}

function scoreRelay(
  relay: RelayCandidate,
  weights: ScoringWeights,
  targetRegion: string,
): bigint {
  const BASIS = 10_000n;

  // Normalize each factor to 0-10000 range
  const repScore = relay.reputation; // already 0-10000
  const rttScore = relay.rtt > 0n ? BASIS * 100n / relay.rtt : BASIS; // inverse, capped
  const loadScore = relay.load > 0n ? BASIS * 10n / (relay.load + 1n) : BASIS; // inverse
  const stakeScore = (relay.stakeAmount * BASIS) / (10n * 1_000_000_000n); // normalize to 10 DVCONF max
  const regionBonus = relay.region === targetRegion ? BASIS : 0n;

  return (
    weights.reputation * repScore +
    weights.rtt * rttScore +
    weights.load * loadScore +
    weights.stake * stakeScore +
    weights.regionMatch * regionBonus
  ) / BASIS;
}
```

### Pino Logger Setup
```typescript
// Source: pino documentation
import pino from 'pino';

export function createLogger(service: string) {
  return pino({
    name: service,
    level: process.env.LOG_LEVEL || 'info',
    transport: process.env.NODE_ENV === 'development'
      ? { target: 'pino-pretty', options: { colorize: true } }
      : undefined,
  });
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@mysten/sui.js` | `@mysten/sui` | SDK 1.0 (2024) | New package name, renamed classes |
| `TransactionBlock` | `Transaction` | SDK 1.0 | Class renamed |
| `tx.pure('0x...')` | `tx.pure.address('0x...')` | SDK 1.0 | Typed pure values required |
| `subscribeEvent()` WebSocket | `queryEvents()` polling | testnet-v1.28.2 (Jul 2024) | WebSocket subscriptions deprecated |
| `SuiClient` (JSON-RPC) | `SuiGrpcClient` (gRPC) | SDK ~2.x (2025) | gRPC recommended for reads, JSON-RPC still works |
| `keypair.signData()` | `keypair.sign()` | SDK 1.0 | Method renamed |
| `waitForTransactionBlock()` | `waitForTransaction()` | SDK 1.0 | Method renamed |

**Deprecated/outdated:**
- `subscribeEvent()`: Deprecated. Use queryEvents polling with cursor.
- `@mysten/sui.js`: Old package name. Use `@mysten/sui`.
- `TransactionBlock`: Renamed to `Transaction`.
- `transaction.serialize()`: Use `transaction.toJSON()`.

## IMPORTANT: SDK Client Strategy

The `SuiGrpcClient` from `@mysten/sui/grpc` is the newer recommended client. However, research indicates it may not yet fully support all write operations (signAndExecuteTransaction) needed by the daemons. **Recommendation for this phase:**

1. Use `SuiClient` from `@mysten/sui/client` -- stable, well-documented, supports all needed operations.
2. Abstract the client behind an interface in `@dvconf/shared` so migration to `SuiGrpcClient` is a one-line change.
3. The event polling pattern works the same way with either client.

## Open Questions

1. **DVCONF Token Funding for Daemon Wallets**
   - What we know: Daemons need DVCONF tokens for staking (2 DVCONF for CP, 0.5 DVCONF for Validator). On testnet, tokens must be minted using TreasuryCap.
   - What's unclear: Should daemon startup auto-mint tokens using the admin key, or should tokens be pre-funded manually?
   - Recommendation: For development/testing, create a helper script that mints DVCONF tokens to daemon wallets. Document the manual process for testnet.

2. **Cursor Persistence Strategy**
   - What we know: Event polling needs to resume from the last-processed cursor after daemon restart.
   - What's unclear: Where to persist the cursor -- file on disk, in-memory only, or a lightweight store?
   - Recommendation: Simple JSON file (`cursor.json`) in each daemon's data directory. Sufficient for thesis scope. No database needed.

3. **Registration Object Discovery**
   - What we know: After `registration::register()`, the daemon needs to find its newly created StakePosition and Cap objects to pass to registry-specific registration.
   - What's unclear: Best way to discover owned objects post-transaction.
   - Recommendation: Use `client.getOwnedObjects({ owner: address, filter: { StructType: '...' } })` to find the specific object types after the registration transaction confirms.

4. **Heartbeat Interval**
   - What we know: Heartbeat timeout is 10 epochs (from constants.move). Sui testnet epochs are roughly 24 hours.
   - What's unclear: Optimal heartbeat interval relative to the 10-epoch timeout.
   - Recommendation: Heartbeat every 30-60 seconds for dev/demo purposes. The on-chain timeout is epoch-based, so even 1 heartbeat per epoch would suffice, but more frequent heartbeats demonstrate the daemon is running.

5. **SuiGrpcClient Readiness**
   - What we know: SuiGrpcClient is recommended for read operations. Write support may be incomplete.
   - What's unclear: Whether signAndExecuteTransaction works on SuiGrpcClient in v2.5.0.
   - Recommendation: Start with SuiClient. Abstract behind interface. Migrate later if gRPC proves stable for writes.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest 4.0.x |
| Config file | `vitest.config.ts` at monorepo root (Wave 0) |
| Quick run command | `pnpm test` |
| Full suite command | `pnpm -r test` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DAEMON-01 | Signaling exchanges ICE candidates | unit | `pnpm --filter @dvconf/signaling test` | Wave 0 |
| DAEMON-02 | Signaling has no chain dependency | unit (import check) | `pnpm --filter @dvconf/signaling test` | Wave 0 |
| DAEMON-03 | CP subscribes to events | unit (mock client) | `pnpm --filter @dvconf/cp-daemon test` | Wave 0 |
| DAEMON-04 | CP runs scoring algorithm | unit | `pnpm --filter @dvconf/cp-daemon test -- scoring` | Wave 0 |
| DAEMON-05 | CP logs scores (no vote submission) | unit | `pnpm --filter @dvconf/cp-daemon test -- scoring` | Wave 0 |
| DAEMON-06 | CP sends heartbeat | unit (mock TX) | `pnpm --filter @dvconf/cp-daemon test -- heartbeat` | Wave 0 |
| DAEMON-07 | CP uses exponential backoff | unit | `pnpm --filter @dvconf/shared test -- retry` | Wave 0 |
| DAEMON-08 | Validator assigns session wallet | unit (mock TX) | `pnpm --filter @dvconf/validator-daemon test` | Wave 0 |
| DAEMON-09 | Validator simulates measurements | unit | `pnpm --filter @dvconf/validator-daemon test -- measurements` | Wave 0 |
| DAEMON-10 | Validator simulates dual-key signing | unit | `pnpm --filter @dvconf/validator-daemon test -- session-proof` | Wave 0 |
| DAEMON-11 | Shared types package compiles | unit (type check) | `pnpm --filter @dvconf/shared test` | Wave 0 |
| DAEMON-12 | Chain helpers use @mysten/sui | unit (mock client) | `pnpm --filter @dvconf/shared test -- chain` | Wave 0 |
| SMOKE | Integration: deploy + daemon + heartbeat | integration | `pnpm test:integration` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pnpm --filter <affected-package> test`
- **Per wave merge:** `pnpm -r test`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `dvconf-daemons/` repo -- entire repo needs to be created
- [ ] `pnpm-workspace.yaml` -- workspace configuration
- [ ] `vitest.config.ts` -- root vitest configuration
- [ ] `tsconfig.base.json` -- shared TypeScript configuration
- [ ] All `package.json` files for workspace packages
- [ ] All test files (unit tests for each daemon + shared package)
- [ ] Integration test infrastructure (local Sui network start/stop helpers)

## Move Event Type Reference

Complete mapping of on-chain event structs to TypeScript interfaces. The package ID prefix for event type filters is `0xf7cf30b14c70c62271674f45098ba7c912d5bcf9e44896e1fb700723c45d3ef3`.

### Registration Events (registration module)
```typescript
interface MinerRegistered {
  miner_id: string;    // ID (hex)
  owner: string;       // address (hex)
  role: number;        // u8: 0=User, 1=Validator, 2=Relay, 3=CP
  stake_amount: string; // u64 as string (bigint)
}

interface MinerUnregistered {
  miner_id: string;
  owner: string;
}

interface RoleChanged {
  miner_id: string;
  old_role: number;
  new_role: number;
  new_stake: string;
}
```

### Control Plane Events (control_plane_registry module)
```typescript
interface CPRegistered {
  miner_id: string;
  operator: string;
  stake_amount: string;
}

interface CPHeartbeat {
  miner_id: string;
  epoch: string; // u64 as string
}

interface CPAssignedToRoom {
  miner_id: string;
  room_id: string;
}
```

### Relay Events (relay_registry module)
```typescript
interface RelayRegistered {
  miner_id: string;
  operator: string;
  mode: number;          // u8: 0=SFU, 1=MCU
  region: number[];      // vector<u8> as byte array
  stake_amount: string;
}

interface RelayLoadUpdated {
  miner_id: string;
  new_load: string; // u64 as string
}

interface RelayRTTUpdated {
  miner_id: string;
  rtt: string; // u64 as string
}
```

### Validator Events (validator_registry module)
```typescript
interface ValidatorRegistered {
  miner_id: string;
  operator: string;
  stake_amount: string;
}

interface SessionWalletAssigned {
  session_wallet: string; // address
}

interface SessionWalletRevealed {
  miner_id: string;
  session_wallet: string;
}
```

### Room Events (room_manager module)
```typescript
interface RoomCreated {
  room_id: string;
  creator: string;
  relay_mode: number; // u8
}

interface RoomClosed {
  room_id: string;
  closed_by: string;
  epoch: string;
}

interface RoomRulesUpdated {
  min_relay: string;
  min_cp: string;
  min_validator: string;
}
```

### User Events (user_registry module)
```typescript
interface UserRegistered {
  user: string;
  display_name: number[]; // vector<u8>
}

interface UserProfileUpdated {
  user: string;
  display_name: number[]; // vector<u8>
}
```

## Sources

### Primary (HIGH confidence)
- Move source code in `dvconf-contracts/sources/` -- all event structs, function signatures, error codes
- `.env.testnet` -- deployed object IDs for testnet
- `docs/decentralized_video_conference-rev4.md` -- scoring algorithm, system flow, daemon responsibilities
- `docs/skills/OFFCHAIN_AGENT_SKILL.md` -- coding standards, resilience patterns, identity rules

### Secondary (MEDIUM confidence)
- [@mysten/sui npm page](https://www.npmjs.com/package/@mysten/sui) -- v2.5.0 confirmed
- [Sui SDK 1.0 Migration Guide](https://sdk.mystenlabs.com/typescript/migrations/sui-1.0) -- class renames, API changes
- [GitHub Issue #19493](https://github.com/MystenLabs/sui/issues/19493) -- subscribeEvent deprecation confirmed
- [Sui events documentation](https://docs.sui.io/guides/developer/sui-101/using-events) -- queryEvents API
- [Sui event indexer example](https://github.com/MystenLabs/sui/blob/main/examples/trading/api/indexer/event-indexer.ts) -- polling pattern reference
- [pino npm](https://www.npmjs.com/package/pino) -- v10.3.x, structured JSON logging
- [ws npm](https://www.npmjs.com/package/ws) -- v8.x, Node.js WebSocket library
- [vitest](https://vitest.dev/) -- v4.0.x test framework
- [pnpm workspaces](https://pnpm.io/workspaces) -- monorepo configuration

### Tertiary (LOW confidence)
- SuiGrpcClient write operation support -- based on SDK docs text, not verified by testing. Needs validation during implementation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified npm packages, official SDK docs, well-established libraries
- Architecture: HIGH - monorepo structure follows pnpm best practices, event polling pattern from official Sui example
- Event type mappings: HIGH - directly read from Move source code
- SDK API patterns: MEDIUM - SDK 1.0 migration guide verified, but SuiGrpcClient status uncertain
- Pitfalls: MEDIUM-HIGH - subscribeEvent deprecation confirmed via GitHub issue, ESM requirement verified via SDK docs
- Scoring algorithm: HIGH - directly from architecture spec rev4

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (30 days -- Sui SDK evolves fast, recheck gRPC client status before Phase 4)
