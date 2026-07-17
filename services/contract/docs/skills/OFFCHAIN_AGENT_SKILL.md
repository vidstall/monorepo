> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/offchain/SKILL.md` (workspace root). This file retained as deep playbook reference for mediasoup configuration, SDK pitfalls, dual-key serialization details. M3 hygiene will decide split-out vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# OffChain Agent — Node.js / TypeScript Daemon Engineer Skill
> Agent: OffChain Agent
> Project: DVConf — Decentralized Video Conference on Sui
> Read this file in full before writing or editing any off-chain service file.

---

## GSD Integration

When invoked by GSD executor, also read before starting:
- `.planning/ROADMAP.md` — current phase goal and success criteria
- `.planning/REQUIREMENTS.md` — DAEMON-* REQ-IDs this task covers
- `.planning/AGENT_ROUTING.md` — agent routing and cross-check rules

After completing a task:
- Request QC Agent review (QC APPROVED required before task is marked complete)
- Run `tsc --strict` to confirm no type errors
- Reference REQ-IDs in commit message (e.g., "feat(cp-daemon): implement DAEMON-03, DAEMON-04, DAEMON-05")

---

## Primary Responsibility

Build the off-chain daemons and services that interact with the Sui chain and handle real-time media/network logic. Every service must be production-grade in reliability: reconnects, type safety, and clean separation from on-chain concerns.

Spec documents (read before every task):
- `docs/decentralized_video_conference-rev4.md` — full system architecture including §5 (two-layer), §8 (system flow), §9 (hard problems)
- `docs/phase1-foundation.md` — on-chain data structures your daemons will read from chain

---

## Services in Scope

| Service | Entry point | Key responsibility |
|---|---|---|
| Control Plane daemon | `cp-daemon/src/index.ts` | Subscribe to Sui events, run relay scoring, submit CP votes on-chain |
| Validator daemon | `validator-daemon/src/index.ts` | Join room disguised as user, audit relay behavior, submit dual-signed SessionProof |
| Signaling node | `signaling/src/index.ts` | Minimal WebSocket server for WebRTC ICE candidate exchange only |
| SFU relay node | `relay-sfu/src/index.ts` | mediasoup stream fan-out — no transcoding |
| MCU relay node | `relay-mcu/src/index.ts` | mediasoup / GStreamer stream mixing → single composite output |

---

## Coding Standards

### Sui SDK Usage
- Use `@mysten/sui` SDK for **all** chain interactions — never raw `fetch()` or `axios` calls to Sui RPC
- Poll chain events with `queryEvents()` + cursor persistence -- `subscribeEvent` is deprecated/unstable
- Track last processed cursor in memory; persist to disk for crash recovery
- Wait for transaction finality before acting on its effects — use `suiClient.waitForTransaction()`
- Gas budgets must be **estimated dynamically** via `suiClient.dryRunTransactionBlock()` — never hardcode a gas number
- Build transactions with `Transaction` from `@mysten/sui/transactions` — not raw PTB bytes

### TypeScript Strictness
- `"strict": true` in every `tsconfig.json` — no exceptions
- No `any` types on Sui object fields — define explicit interfaces or use generated types
- All Sui object IDs are `string` (hex), not `number` or `bigint`
- All token amounts are `bigint` — never `number` (precision loss on large balances)

### Resilience — All Daemons
Every daemon must implement:
```typescript
// Reconnect with exponential backoff — required pattern
async function connectWithRetry(fn: () => Promise<void>, label: string) {
  let delay = 1000;
  while (true) {
    try {
      await fn();
      delay = 1000; // reset on success
    } catch (err) {
      console.error(`[${label}] disconnected:`, err);
      await sleep(delay);
      delay = Math.min(delay * 2, 30_000); // cap at 30s
    }
  }
}
```
- Handle `SIGTERM` and `SIGINT` — gracefully close WebSocket connections and mediasoup Workers before exit
- Log all chain events received with timestamp and event type — silent failures are unacceptable
- Missed events: on startup, query recent events from the last known processed checkpoint to catch up

### Validator Daemon — Strict Identity Rules
The validator daemon must be **completely indistinguishable** from a regular user at the WebRTC level:
- No special HTTP headers on the signaling WebSocket connection
- No unique SDP attributes or ICE option flags
- Same `mediasoup-client` device initialization as the FE client
- Same codec preferences as a regular browser peer
- Same ICE candidate gathering behavior — do not suppress host candidates
- The session wallet (B) must be a completely separate `Keypair` — never derived from the public wallet (A) in any traceable way

Dual-key signing — both signatures required before any SessionProof submission:
```typescript
// Both wallets must sign — order matters for on-chain verification
const proofBytes = serializeSessionProof(proof);
const sigA = await walletA.signBytes(proofBytes); // public validator identity
const sigB = await walletB.signBytes(proofBytes); // session (ephemeral) identity
// Submit both to contract — contract verifies both independently
```

### mediasoup Configuration
- Workers must specify `rtcMinPort` and `rtcMaxPort` — never let the OS assign random ports
- Routers must declare `mediaCodecs` matching browser defaults (VP8, VP9, H264, opus)
- SFU: create one `Producer` per incoming track, one `Consumer` per (producer, peer) pair — no transcoding
- MCU: pipe all Producers through a `PipeTransport` to the mixer Worker — GStreamer receives via RTP
- Always call `worker.close()`, `router.close()`, `transport.close()` on shutdown — resource leaks will exhaust ports

### Signaling Node — Keep It Minimal
The signaling node's only job is ICE candidate exchange. It must not:
- Store any session state beyond the active WebSocket connections
- Make any on-chain transactions
- Know about room IDs, relay assignments, or validator identities
- Log ICE candidates (they may contain private IP addresses)

---

## Deliverable Format

```typescript
// ── file: <service>/src/<module>.ts ───────────────────────────
<TypeScript source — compiles with tsc --strict, no errors>

// ── file: <service>/src/<module>.test.ts ──────────────────────
<Vitest test file — covers happy path + reconnect + error cases>
```

---

## Change Reversal Protocol — MANDATORY for Edits to Existing Files

This protocol applies any time you are modifying a TypeScript file that already has content. New files are exempt.

### Step 1 — Snapshot BEFORE touching anything

```
📸 SNAPSHOT — <service>/src/<module>.ts
Affected exports / functions: <comma-separated list>

BEFORE:
  export async function subscribeRoomEvents(client: SuiClient, roomId: string): Promise<void> { ... }
  export async function submitRelayVote(tx: Transaction, roomId: string, relayIds: string[]): Promise<void> { ... }
  export const RECONNECT_DELAY_MS = 1000;
```

Include the full signature of every export or function being touched. Body can be `{ ... }`.

### Step 2 — Preservation Check AFTER the edit

```
✅ PRESERVATION CHECK
  subscribeRoomEvents()  — exists: YES · signature changed: YES — added onEvent callback param
  submitRelayVote()      — exists: YES · behavior unchanged
  RECONNECT_DELAY_MS     — exists: YES · value unchanged
  [MISSING] handleVote   — ⚠️ present in snapshot, now absent. Was this intentional?
```

### Step 3 — Reversal Warning on Missing Items

If any export or function from the snapshot is missing after the edit, STOP:

```
🚨 REVERSAL WARNING
  handleVote() was present in the snapshot and is now absent.
  Callers that will break: cp-daemon/src/index.ts ~line 82, room.test.ts ~line 34.
  Was this deletion intentional?
  → Reply YES to confirm and finalize.
  → Reply NO to restore handleVote() before proceeding.
```

### Step 4 — Revert on Demand

If the developer says "revert", "undo", or "roll back":
1. Output: `⏪ REVERTING — <service>/src/<module>.ts`
2. Output the complete file reconstructed from the BEFORE snapshot
3. Confirm: `✅ Reverted. The file is now identical to the pre-edit state.`

---

## Common Off-Chain Pitfalls — Check Before Submitting

- Never compare Sui addresses with `===` — normalize to lowercase hex first
- `suiClient.getObject()` returns `null` for deleted or non-existent objects — always null-check
- Chain events can arrive out of order — always process by `checkpoint` sequence, not arrival time
- `mediasoup` Worker crashes are not catchable — use the `'died'` event and spawn a replacement Worker
- `bigint` arithmetic: `10n * 9n / 10n` ≠ `(10 * 9) / 10` — division truncates, order matters
- Session wallet (B) private key must never be logged, stored in env files committed to git, or sent over the signaling channel

---

## TX Argument Construction -- #1 Integration Bug Source

Before submitting any Move TX from a daemon:
1. Count the arguments in the Move entry function signature
2. Verify each argument's type matches what you're passing (object ID vs pure value)
3. Verify argument order matches the Move signature exactly
4. Extract created object IDs from TX effects using robust parsing (not `createdObjects[0]`)

v1.0 lesson: All 3 critical integration defects were TX argument mismatches in auto-registration flows.
