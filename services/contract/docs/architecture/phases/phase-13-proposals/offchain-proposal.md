DESIGN PROPOSAL -- OffChain: Economic Layer Integration
Author: OffChain Agent
Phase: 13
Date: 2026-03-12

---

PURPOSE:
  Upgrade off-chain daemons to interact with the on-chain economic_layer.move module:
  shared types for error codes/events, validator daemon proof submission via PTB,
  and signaling daemon session-routing metrics for future reward eligibility.

OWNS:
  - Shared TypeScript types matching on-chain economic_layer.move structs and events
  - Validator daemon proof-to-chain submission flow (BCS serialization, PTB construction, dual-key signing)
  - Signaling daemon session-routing counter and reward eligibility tracking

---

## 1. Task 4: Shared Types Update

### 1.1 Error Codes -- constants.ts

Add `economicLayer` namespace to `ErrorCodes` in
`dvconf-daemons/packages/shared/src/types/constants.ts`:

```typescript
economicLayer: {
  E_PAUSED: 600,
  E_NOT_ROOM_CREATOR: 601,
  E_ROOM_NOT_FOUND: 602,
  E_ROOM_NOT_PENDING: 603,
  E_INVALID_SIGNATURE: 604,
  E_SESSION_WALLET_NOT_FOUND: 605,
  E_ALREADY_SUBMITTED: 606,
  E_ROOM_NOT_CLOSED: 607,
  E_INSUFFICIENT_PROOFS: 608,
  E_ALREADY_DISTRIBUTED: 609,
  E_ZERO_ESCROW: 610,
  E_RELAY_NOT_REGISTERED: 611,
},
```

Also add economic constants to constants.ts:

```typescript
/** Flat reward per session routed by signaling node (in token units). */
export const SIGNALING_SESSION_REWARD = 50n;

/** Quality multiplier thresholds (basis points). */
export const QualityMultiplier = {
  EXCELLENT_BPS: 10_000,
  GOOD_BPS: 8_000,
  ACCEPTABLE_BPS: 5_000,
  SLASH_BPS: 0,
} as const;

/** Packet loss thresholds (basis points). */
export const LossThreshold = {
  EXCELLENT: 200,   // <= 2%
  GOOD: 500,        // <= 5%
  ACCEPTABLE: 1000, // <= 10%
} as const;

/** Reward split ratios (basis points, sum = 10_000). */
export const RewardRatios = {
  RELAY_BPS: 7_000,
  VALIDATOR_BPS: 1_500,
  CP_BPS: 1_500,
} as const;
```

NOTE: `signalingRegistry` error codes already occupy 600-604 in the current constants.ts.
This is a NAMESPACE COLLISION. The on-chain economic_layer.move uses 600-611. Resolution
options (escalate to Architect):

  **Option A**: Renumber signaling registry errors to 550-554 (on-chain change required).
  **Option B**: Renumber economic layer errors to 700-711 (on-chain change required).
  **Option C**: Accept overlap -- signaling (600-604) and economic (600-611) are different
    modules, and the Sui SDK returns the module name alongside the abort code, so daemons
    can disambiguate.

  RECOMMENDED: Option A -- renumber signaling to 550-554, since Phase 11 is not yet
  deployed to mainnet. This avoids ambiguity.

  This is an OPEN QUESTION for the Architect.

### 1.2 Event Types -- events.ts

Add to `dvconf-daemons/packages/shared/src/types/events.ts`:

```typescript
// -- Economic layer events (economic_layer module) ----------------------

export interface EscrowCreated {
  room_id: string;
  creator: string;
  amount: string;  // u64 as string
}

export interface SessionProofSubmitted {
  room_id: string;
  validator_id: string;
  relay_miner_id: string;
  bytes_transferred: string;
  packet_loss_bps: string;
}

export interface RewardsDistributed {
  room_id: string;
  relay_reward: string;
  validator_rewards: string;  // total validator portion
  cp_reward: string;
  quality_multiplier: string;
}

export interface NodeSlashed {
  miner_id: string;
  slash_amount: string;
  reason: string;  // e.g. "quality_multiplier_zero"
}
```

Update the `DvconfEvent` union type to include these four new interfaces.

### 1.3 Chain Config -- chain.ts

Add module name constant for TX target building:

```typescript
/** Move module name for economic layer entry functions. */
export const ECONOMIC_LAYER_MODULE = 'economic_layer';
```

No changes to `NetworkConfig` interface -- RoomEscrow objects are created dynamically
(not a singleton), so they are not stored in config. The daemon discovers escrow
object IDs by querying chain events (EscrowCreated).

---

## 2. Task 5: Validator Daemon Proof Submission

### 2.1 Overview

Replace the current "NOT submitting" stub in `session-proof.ts` with actual on-chain
`economic_layer::submit_session_proof` transaction execution. The flow:

```
collectMeasurements(relayMinerId)
  -> buildSessionProof(...)
     -> serializeProofBCS(proof)        // NEW: BCS instead of JSON
        -> dualKeySign(bcsBytes, ...)
           -> submitProofOnChain(...)   // NEW: PTB construction + execution
```

### 2.2 BCS Serialization -- Replace JSON.stringify

The current `serializeProof()` uses `JSON.stringify` with a bigint replacer. This
must be replaced with deterministic BCS serialization that matches the on-chain
`ed25519_verify` message format.

The on-chain `submit_session_proof` function reconstructs the message bytes from
the individual fields passed as arguments, then calls `ed25519::ed25519_verify(sig, pubkey, msg)`.
Therefore, the off-chain serialization must produce EXACTLY the same byte sequence.

**Approach**: Use `@mysten/bcs` to define a BCS schema matching the on-chain
reconstruction order:

```typescript
import { bcs } from '@mysten/sui/bcs';

/**
 * BCS-serialize the proof fields in the exact order the Move contract
 * reconstructs them for ed25519 verification.
 *
 * Field order (must match economic_layer.move verify_proof_message):
 *   room_id: address (32 bytes)
 *   relay_miner_id: address (32 bytes)
 *   packets_forwarded: u64
 *   bytes_transferred: u64
 *   unique_peers: u64
 *   duration_seconds: u64
 *   avg_latency_ms: u64
 *   packet_loss_bps: u64
 *   jitter_ms: u64
 */
export function serializeProofBCS(proof: SessionProof): Uint8Array {
  const writer = new bcs.BcsWriter();
  // room_id and relay_miner_id as 32-byte addresses
  writer.writeBytes(bcs.Address.serialize(proof.roomId).toBytes());
  writer.writeBytes(bcs.Address.serialize(proof.relayMinerId).toBytes());
  // Measurement fields as u64
  writer.write64(proof.measurement.packetsSent);        // packets_forwarded
  writer.write64(proof.measurement.bytesForwarded);      // bytes_transferred
  writer.write64(BigInt(0));                             // unique_peers (placeholder)
  writer.write64(proof.measurement.measurementDurationMs / 1000n); // duration_seconds
  writer.write64(proof.measurement.avgLatencyMs);
  writer.write64(proof.measurement.packetLossRate);      // packet_loss_bps
  writer.write64(proof.measurement.jitterMs);
  return writer.toBytes();
}
```

DESIGN NOTE: The exact BCS layout depends on how economic_layer.move reconstructs
the message for `ed25519_verify`. The OnChain agent must document the byte layout
in the ADD or as a code comment. This is the #1 integration contract between
on-chain and off-chain.

### 2.3 Dual-Key Signing -- Ed25519 Format

The existing `dualKeySign()` function uses `Ed25519Keypair.sign(bytes)` from `@mysten/sui`.
This produces a raw Ed25519 signature (64 bytes). The on-chain `sui::ed25519::ed25519_verify`
expects:

- `signature: vector<u8>` -- 64 bytes raw Ed25519 signature
- `public_key: vector<u8>` -- 32 bytes Ed25519 public key
- `msg: vector<u8>` -- the message bytes

The Sui SDK `Ed25519Keypair.sign()` returns the raw 64-byte signature (no Sui signature
scheme prefix), which matches what `ed25519_verify` expects.

Public key extraction:

```typescript
const pubKeyBytesA = mainKeypair.getPublicKey().toRawBytes();   // 32 bytes
const pubKeyBytesB = sessionKeypair.getPublicKey().toRawBytes(); // 32 bytes
```

The on-chain contract verifies:
1. `ed25519_verify(sig_public, pubkey_A, message)` -- validator public identity
2. `ed25519_verify(sig_session, pubkey_B, message)` -- session wallet identity
3. `pubkey_B` matches the session wallet registered in `ValidatorRegistry`

The off-chain daemon does NOT pass public keys in the TX -- the contract reads them
from `ValidatorRegistry` (the validator's registered public key and session wallet).
The daemon only passes `sig_public` and `sig_session` as `vector<u8>` arguments.

### 2.4 PTB Construction -- submitProofOnChain

New function in `session-proof.ts`:

```typescript
import { Transaction } from '@mysten/sui/transactions';
import { executeWithRetry } from '@dvconf/shared';
import type { NetworkConfig, Logger } from '@dvconf/shared';
import type { SuiClient } from '@mysten/sui/client';
import { ECONOMIC_LAYER_MODULE } from '@dvconf/shared';

/**
 * Submit a dual-key signed SessionProof to the economic_layer on-chain.
 *
 * TX target: economic_layer::submit_session_proof
 * Arguments (must match Move function signature exactly):
 *   1. net_reg: &NetworkRegistry                 (shared object)
 *   2. escrow: &mut RoomEscrow                   (shared object, discovered by room_id)
 *   3. validator_reg: &ValidatorRegistry         (shared object)
 *   4. relay_reg: &RelayRegistry                 (shared object)
 *   5. room_id: ID                               (pure)
 *   6. relay_miner_id: ID                        (pure)
 *   7. packets_forwarded: u64                    (pure)
 *   8. bytes_transferred: u64                    (pure)
 *   9. unique_peers: u64                         (pure)
 *  10. duration_seconds: u64                     (pure)
 *  11. avg_latency_ms: u64                       (pure)
 *  12. packet_loss_bps: u64                      (pure)
 *  13. jitter_ms: u64                            (pure)
 *  14. sig_public: vector<u8>                    (pure)
 *  15. sig_session: vector<u8>                   (pure)
 */
export async function submitProofOnChain(
  client: SuiClient,
  signer: Ed25519Keypair,
  config: NetworkConfig,
  proof: SessionProof,
  signatures: DualKeySignature,
  escrowObjectId: string,
  logger: Logger,
): Promise<boolean> {
  const result = await executeWithRetry(
    client,
    signer,
    (tx: Transaction) => {
      tx.moveCall({
        target: `${config.packageId}::${ECONOMIC_LAYER_MODULE}::submit_session_proof`,
        arguments: [
          tx.object(config.networkRegistryId),
          tx.object(escrowObjectId),
          tx.object(config.validatorRegistryId),
          tx.object(config.relayRegistryId),
          tx.pure.address(proof.roomId),
          tx.pure.address(proof.relayMinerId),
          tx.pure.u64(proof.measurement.packetsSent),
          tx.pure.u64(proof.measurement.bytesForwarded),
          tx.pure.u64(0n),  // unique_peers (placeholder for Phase 13)
          tx.pure.u64(proof.measurement.measurementDurationMs / 1000n),
          tx.pure.u64(proof.measurement.avgLatencyMs),
          tx.pure.u64(proof.measurement.packetLossRate),
          tx.pure.u64(proof.measurement.jitterMs),
          tx.pure(bcs.vector(bcs.u8()).serialize(Array.from(signatures.signatureA))),
          tx.pure(bcs.vector(bcs.u8()).serialize(Array.from(signatures.signatureB))),
        ],
      });
    },
    'submit-session-proof',
    logger,
  );

  if (result) {
    logger.info(
      { digest: result.digest, roomId: proof.roomId },
      `SessionProof submitted on-chain: ${result.digest}`,
    );
    return true;
  }

  logger.error(
    { roomId: proof.roomId, relayMinerId: proof.relayMinerId },
    'SessionProof submission failed after retries',
  );
  return false;
}
```

### 2.5 Escrow Discovery

The validator daemon needs the `RoomEscrow` object ID to pass as a TX argument.
Two approaches:

**Approach A (chosen)**: Poll for `EscrowCreated` events via EventPoller. When the
daemon is assigned to audit a room, it stores the escrow ID from the event. This
aligns with the existing event-driven architecture.

**Approach B (fallback)**: Query owned objects by type
(`{packageId}::economic_layer::RoomEscrow`) filtered by `room_id` field. More
expensive but works if events were missed.

Implementation: Add an `escrowMap: Map<string, string>` (roomId -> escrowObjectId)
to `DaemonState`. Populate from `EscrowCreated` events. The event poller already
runs in `index.ts` -- add a handler for the economic_layer module:

```typescript
// In startDaemon(), add a second EventPoller for economic_layer events
const economicPoller = new EventPoller({
  client,
  packageId: config.packageId,
  module: ECONOMIC_LAYER_MODULE,
  pollingIntervalMs: 10_000,
  cursorPath: '.cursors/economic-events.json',
  logger: log,
});

state.economicPoller = economicPoller;

await economicPoller.start(async (event) => {
  if (event.type.endsWith('::EscrowCreated')) {
    const parsed = event.parsedJson as EscrowCreated;
    state.escrowMap.set(parsed.room_id, /* escrow object ID from event */);
  }
});
```

OPEN QUESTION: The `EscrowCreated` event must include the escrow object ID (not just
room_id). The OnChain agent should emit the escrow's `object::id(&escrow)` in the event.
If it does not, the daemon must fall back to Approach B.

### 2.6 Updated Measurement Cycle

The `runMeasurementCycle` function in `index.ts` changes from fire-and-forget logging
to actual on-chain submission:

```typescript
async function runMeasurementCycle(
  state: DaemonState,
  relayMinerId: string,
  validatorMinerId: string,
  sessionWalletAddress: string,
  mainKeypair: Ed25519Keypair,
  sessionKeypair: Ed25519Keypair,
  log: Logger,
): Promise<void> {
  try {
    const measurement = collectMeasurements(relayMinerId);
    const epoch = BigInt(Math.floor(Date.now() / 1000));
    const roomId = process.env['ROOM_ID'] ?? 'unassigned';

    const proof = buildSessionProof(
      roomId,
      relayMinerId,
      validatorMinerId,
      sessionWalletAddress,
      measurement,
      epoch,
    );

    const proofBytes = serializeProofBCS(proof);
    const signatures = await dualKeySign(proofBytes, mainKeypair, sessionKeypair);

    // Look up escrow object for this room
    const escrowId = state.escrowMap.get(roomId);
    if (!escrowId) {
      log.warn({ roomId }, 'No escrow found for room -- skipping on-chain submission');
      logProofSummary(proof);
      return;
    }

    const submitted = await submitProofOnChain(
      state.client,
      mainKeypair,
      state.config,
      proof,
      signatures,
      escrowId,
      log,
    );

    if (submitted) {
      logProofSummary(proof, true);  // updated to show "submitted on-chain"
    } else {
      logProofSummary(proof, false); // show "submission failed"
    }
  } catch (err) {
    log.error({ err }, 'Measurement cycle failed');
  }
}
```

### 2.7 logProofSummary Update

Update signature to accept an optional submission status:

```typescript
export function logProofSummary(proof: SessionProof, submitted?: boolean): void {
  const status = submitted === true
    ? 'Submitted on-chain'
    : submitted === false
      ? 'Submission FAILED'
      : 'NOT submitted (no escrow)';

  logger.info(
    {
      roomId: proof.roomId,
      relayMinerId: proof.relayMinerId,
      validatorMinerId: proof.validatorMinerId,
      lossRate: proof.measurement.packetLossRate.toString(),
      latency: proof.measurement.avgLatencyMs.toString(),
    },
    `SessionProof -- room=${proof.roomId}, relay=${proof.relayMinerId}, ` +
    `loss=${proof.measurement.packetLossRate}bp. ${status}.`,
  );
}
```

---

## 3. Task 6: Signaling Node Economic Tracking

### 3.1 Overview

The signaling daemon already tracks active rooms and connections via `RoomManager.getStats()`.
Phase 13 adds a `sessionsRouted` counter that tracks completed sessions (rooms where all
peers have disconnected) for future reward eligibility.

The actual reward claim transaction is NOT in scope for Phase 13 (no on-chain signaling
reward function exists yet). This task adds:
1. A cumulative session counter
2. Logging of reward eligibility per completed session
3. Documentation of slashing criteria

### 3.2 RoomManager Extension -- rooms.ts

Add a `sessionsRouted` counter to `RoomManager`:

```typescript
export class RoomManager {
  private rooms = new Map<string, Set<WebSocket>>();
  private peers = new Map<WebSocket, PeerInfo>();

  /** Cumulative count of sessions routed to completion. */
  private _sessionsRouted = 0;

  // ... existing methods ...

  leave(ws: WebSocket): void {
    const info = this.peers.get(ws);
    if (!info) return;

    const { peerId, roomId } = info;
    const room = this.rooms.get(roomId);

    if (room) {
      room.delete(ws);
      // Notify remaining peers ...

      // Track completed sessions: room emptied = session ended
      if (room.size === 0) {
        this.rooms.delete(roomId);
        this._sessionsRouted++;
      }
    }

    this.peers.delete(ws);
  }

  /** Get the number of sessions routed to completion. */
  get sessionsRouted(): number {
    return this._sessionsRouted;
  }

  getStats(): { rooms: number; connections: number; sessionsRouted: number } {
    let connections = 0;
    for (const room of this.rooms.values()) {
      connections += room.size;
    }
    return { rooms: this.rooms.size, connections, sessionsRouted: this._sessionsRouted };
  }
}
```

### 3.3 Heartbeat Reporting -- heartbeat.ts

Include `sessionsRouted` in the heartbeat log. No on-chain field exists yet for this
metric, but logging it enables operational monitoring:

```typescript
const sendHeartbeat = async (): Promise<void> => {
  const stats = roomManager.getStats();
  const currentLoad = stats.connections;

  logger.debug(
    { currentLoad, rooms: stats.rooms, sessionsRouted: stats.sessionsRouted },
    'Sending heartbeat + load update',
  );

  // ... existing PTB build and execute ...
};
```

### 3.4 Session Completion Logging -- index.ts

In the signaling server's room-leave handler, log reward eligibility when a session
completes:

```typescript
// In ws.on('close', ...) handler in index.ts:
ws.on('close', () => {
  const roomId = roomManager.getRoomId(ws);
  const wasLastPeer = roomId && roomManager.getRoomSize(roomId) === 1;

  roomManager.leave(ws);
  peerSockets.delete(peerId);

  if (wasLastPeer && roomId) {
    logger.info(
      { roomId, sessionsRouted: roomManager.getStats().sessionsRouted },
      `Session completed for room ${roomId} -- eligible for SIGNALING_SESSION_REWARD (${SIGNALING_SESSION_REWARD} tokens). Claim deferred to future phase.`,
    );
  }

  logger.info({ peerId }, 'Peer disconnected');
});
```

### 3.5 Signaling Slashing Criteria (Documentation)

Signaling nodes can be slashed for:

1. **Dropping connections mid-session**: A signaling node that closes WebSocket
   connections while a room session is active (peers still in room). Detectable
   by validators who observe ICE renegotiation failures.

2. **Offline during assigned sessions**: A signaling node that is assigned to a room
   (via CP) but fails to accept connections or respond to health checks. Detectable
   via CP heartbeat misses (`heartbeat_missed_count` in SignalingRegistry).

3. **Message tampering**: Altering SDP or ICE candidates in transit. Detectable via
   end-to-end SDP integrity checks (hash comparison at both endpoints). This is a
   severe offense -- full stake slash.

Actual slash enforcement is deferred to Phase 14 integration (no on-chain signaling
slash function in Phase 13).

---

## 4. Integration Contracts with OnChain economic_layer.move

### IC-1: submit_session_proof TX Argument Contract

```
OnChain entry function:
  economic_layer::submit_session_proof(
    net_reg: &NetworkRegistry,
    escrow: &mut RoomEscrow,
    validator_reg: &ValidatorRegistry,
    relay_reg: &RelayRegistry,
    room_id: ID,
    relay_miner_id: ID,
    packets_forwarded: u64,
    bytes_transferred: u64,
    unique_peers: u64,
    duration_seconds: u64,
    avg_latency_ms: u64,
    packet_loss_bps: u64,
    jitter_ms: u64,
    sig_public: vector<u8>,
    sig_session: vector<u8>,
    ctx: &mut TxContext,
  )

OffChain TX construction:
  15 arguments total (ctx is implicit):
    4 object references (networkRegistry, escrow, validatorRegistry, relayRegistry)
    2 address values (room_id, relay_miner_id)
    7 u64 pure values (measurement fields)
    2 vector<u8> pure values (signatures)

Error cases the daemon must handle:
  604 E_INVALID_SIGNATURE -- BCS serialization mismatch, log and investigate
  605 E_SESSION_WALLET_NOT_FOUND -- session wallet not registered, skip room
  606 E_ALREADY_SUBMITTED -- idempotent retry safe, log as info not error
```

### IC-2: BCS Message Byte Layout Contract

This is the CRITICAL integration point. The on-chain contract and off-chain daemon
must produce identical byte sequences for ed25519 verification to succeed.

```
On-chain: economic_layer.move reconstructs message from individual arguments:
  let msg = vector::empty<u8>();
  vector::append(&mut msg, bcs::to_bytes(&room_id));
  vector::append(&mut msg, bcs::to_bytes(&relay_miner_id));
  vector::append(&mut msg, bcs::to_bytes(&packets_forwarded));
  vector::append(&mut msg, bcs::to_bytes(&bytes_transferred));
  vector::append(&mut msg, bcs::to_bytes(&unique_peers));
  vector::append(&mut msg, bcs::to_bytes(&duration_seconds));
  vector::append(&mut msg, bcs::to_bytes(&avg_latency_ms));
  vector::append(&mut msg, bcs::to_bytes(&packet_loss_bps));
  vector::append(&mut msg, bcs::to_bytes(&jitter_ms));

Off-chain: serializeProofBCS() must use @mysten/bcs with the same field order and
  encoding (BCS ID = 32-byte address, BCS u64 = 8-byte little-endian).
```

The OnChain agent MUST document the exact reconstruction code in economic_layer.move
so the OffChain agent can match it byte-for-byte. This is an **Integration Contract**
that both sides must agree on before implementation.

### IC-3: EscrowCreated Event Contract

```
On-chain event emitted by create_escrow():
  event::emit(EscrowCreated {
    room_id: ID,
    creator: address,
    amount: u64,
    escrow_id: ID,    // <-- REQUIRED for daemon to reference in TX
  });

Off-chain consumer: validator daemon EventPoller
  Stores escrow_id keyed by room_id for later submit_session_proof calls.
```

### IC-4: Dual-Key Public Key Source Contract

```
On-chain verification reads public keys from:
  1. ValidatorRegistry -> validator entry -> public_key (wallet A)
  2. ValidatorRegistry -> session_wallet_map -> session_public_key (wallet B)

Off-chain signing uses:
  1. mainKeypair.sign(bcsBytes) -> signatureA (64 bytes raw Ed25519)
  2. sessionKeypair.sign(bcsBytes) -> signatureB (64 bytes raw Ed25519)

The daemon does NOT pass public keys in the TX. The contract looks them up
from the registry using ctx.sender() for wallet A and the session wallet
mapping for wallet B.

IMPORTANT: The daemon must sign with the SAME keypair that was used to register
  in ValidatorRegistry. If the validator re-registers with a new keypair, old
  proofs become invalid.
```

---

## 5. Dependencies

DEPENDS ON:
  - `economic_layer.move` (Task 2) -- entry function signatures, BCS message layout, event definitions
  - `constants.move` (Task 1) -- quality multiplier values (mirrored in shared constants)
  - `@dvconf/shared` -- executeWithRetry, EventPoller, createSuiClient, loadKeypair, NetworkConfig
  - `@mysten/sui` -- Transaction, Ed25519Keypair, bcs
  - `validator_registry.move` -- session wallet mapping (existing, no changes needed)
  - `relay_registry.move` -- relay miner ID validation (existing, no changes needed)

---

## 6. Error Codes

See Section 1.1. The `economicLayer` namespace uses 600-611.
NOTE: Namespace collision with `signalingRegistry` (600-604) flagged as open question.

---

## 7. Events Emitted

The off-chain daemons do NOT emit on-chain events -- they CONSUME events emitted by
economic_layer.move:

| Event | Consumer | Action |
|---|---|---|
| EscrowCreated | Validator daemon | Store escrow_id -> room_id mapping |
| SessionProofSubmitted | CP daemon (future) | Track proof count per room |
| RewardsDistributed | All daemons (info) | Log distribution results |
| NodeSlashed | Affected daemon | Log warning, trigger operator alert |

---

## 8. Open Questions

1. **Error code namespace collision**: signalingRegistry uses 600-604, economicLayer
   wants 600-611. Which namespace moves? (See Section 1.1 for recommendation.)

2. **BCS message layout**: Must be agreed between OnChain and OffChain agents before
   implementation. The byte-for-byte match is critical for ed25519 verification.

3. **EscrowCreated event fields**: Must include `escrow_id` (the object::id of the
   RoomEscrow shared object) for the daemon to reference it in submit_session_proof.

4. **Ed25519Keypair.sign() output format**: Verify that `@mysten/sui` Ed25519Keypair.sign()
   returns raw 64-byte Ed25519 signature without Sui scheme prefix byte. If it includes
   the prefix, the daemon must strip it before passing to the TX.

5. **unique_peers field**: The current MeasurementResult does not track unique peers.
   Pass 0 as placeholder for Phase 13. The Validator daemon would need WebRTC peer
   counting in a future phase to populate this field accurately.
