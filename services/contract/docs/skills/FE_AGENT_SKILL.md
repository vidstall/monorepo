> **MIGRATED 2026-05-23 (agent-harness-env M2 Phase 2)** → canonical = `.claude/skills/fe/SKILL.md` (workspace root). This file retained as deep playbook reference for React Query patterns, adaptive view branching, mediasoup-client lifecycle details. M3 hygiene will decide split-out vs keep-as-reference. See `plans/agent-harness-env/CONTEXT.md` § D17a.

---

# FE Agent — React / TypeScript Client Engineer Skill
> Agent: FE Agent
> Project: DVConf — Decentralized Video Conference on Sui
> Read this file in full before writing or editing any frontend file.

---

## GSD Integration

When invoked by GSD executor (as `FE Agent` subagent), also read before starting:
- `.planning/ROADMAP.md` — current phase goal and success criteria
- `.planning/REQUIREMENTS.md` — CLIENT-* REQ-IDs this task covers
- `.planning/AGENT_ROUTING.md` — agent routing and cross-check rules

After completing a task:
- Request QC Agent review (QC APPROVED required before task is marked complete)
- Run `tsc --strict` to confirm no type errors
- Reference REQ-IDs in commit message (e.g., "feat(client): implement CLIENT-01, CLIENT-02")

---

## Primary Responsibility

Build the web client that reads on-chain state and connects users to their assigned relay via WebRTC. The UI must always reflect chain state as the source of truth — local state is for UI-only concerns (loading, animation) and nothing else.

Spec documents (read before every task):
- `docs/decentralized_video_conference-rev4.md` — especially §3 (SFU vs MCU), §6 (object map), §8 (system flow §6 client app)
- `docs/phase1-foundation.md` — Cap object structures your hooks will read from chain

---

## Pages & Features in Scope

| Feature | Route | Description |
|---|---|---|
| Registration | `/register` | Create wallet, stake tokens, receive `UserCap` on-chain |
| Create room | `/rooms/new` | Escrow tokens, watch Room transition Pending → Ready |
| Join room | `/rooms/:id` | Read relay endpoint + mode from chain, connect via WebRTC |
| SFU session view | `/rooms/:id/session` | Render one `<video>` per remote stream (N^(1/2) tiles) |
| MCU session view | `/rooms/:id/session` | Render exactly one `<video>` (composite stream) |
| Room status | `/rooms/:id` | Live on-chain polling: status, member count, relay mode |

---

## Coding Standards

### Chain Reads — Always from Chain, Never from Local State
- Room status, relay endpoint, relay mode, member list — read from chain, not from React state
- Use **React Query** (`@tanstack/react-query`) or **SWR** for all chain polling — never raw `useEffect` + `fetch`
- Invalidate queries on transaction confirmation — don't wait for the next poll interval
- Never cache relay assignment locally — re-read from chain if the component remounts

### Wallet Integration
- All wallet interactions (sign, send transaction) go through `useWallet()` from `@mysten/dapp-kit`
- Never access a private key directly in the FE — all signing happens through the wallet adapter
- Show a clear "connect wallet" prompt before any chain interaction — never silently fail

### WebRTC — mediasoup-client Only
- Use `mediasoup-client` — do not use browser-native `RTCPeerConnection` directly
- ICE candidate exchange goes through the signaling node WebSocket — never on-chain, never via React state
- Initialize the `Device` once per session, not per component render
- SFU mode: one `Consumer` per remote `Producer`, render each in its own `<video ref={...}>` element
- MCU mode: one `Consumer` for the single composite `Producer`, render in one `<video ref={...}>` element
- Always call `transport.close()` and `device` cleanup on component unmount — prevent ghost connections

### Loading & Error States — Every Async Operation
Every chain call and WebRTC action must have three UI states handled:
1. **Loading** — spinner or skeleton, user cannot double-submit
2. **Success** — clear confirmation, update query cache
3. **Error** — human-readable message, retry option where appropriate

Never leave the user without feedback during a transaction. Sui transactions can take 1–3 seconds — show a pending state.

### TypeScript
- `"strict": true` — no `any` types on Sui objects or chain responses
- Sui object IDs are `string` — never `number`
- Token amounts are `bigint` — never `number`
- Use `@mysten/sui` generated types or explicit interfaces for all on-chain object shapes

### Adaptive Session View — SFU vs MCU
The session view component must branch on `room.relay_mode` read from chain:

```typescript
// Correct pattern — always driven by chain state
const { data: room } = useRoom(roomId); // reads from chain

if (room.relay_mode === 'SFU') {
  // Render one <video> tile per remote producer
  return <SFUSessionView producers={remoteProducers} />;
}

if (room.relay_mode === 'MCU') {
  // Render exactly one <video> for the composite stream
  return <MCUSessionView compositeProducer={compositeProducer} />;
}
```

Never hardcode the mode. Never decide mode from local state. The Control Plane on-chain decides it — the FE just reads and renders.

---

## Deliverable Format

```typescript
// ── file: src/<feature>/<Component>.tsx ───────────────────────
<React component — no anys, all async states handled>

// ── file: src/hooks/<hookName>.ts ─────────────────────────────
<Custom hook — reads chain, returns typed data + loading + error>

// ── file: src/<feature>/<Component>.test.tsx ──────────────────
<Vitest + Testing Library test — covers render, loading, error, success>
```

---

## Change Reversal Protocol — MANDATORY for Edits to Existing Files

This protocol applies any time you are modifying a component, hook, or utility file that already exists. New files are exempt.

### Step 1 — Snapshot BEFORE touching anything

```
📸 SNAPSHOT — src/hooks/useRoom.ts
Affected exports / functions: useRoom, RoomState

BEFORE:
  export function useRoom(roomId: string): { data: RoomState | null; isLoading: boolean; error: Error | null } { ... }
  export type RoomState = { status: string; relayEndpoint: string; mode: 'SFU' | 'MCU' }
```

Include the full signature of every export, type, or prop interface being touched.

### Step 2 — Preservation Check AFTER the edit

```
✅ PRESERVATION CHECK
  useRoom()    — exists: YES · return type changed: YES — added memberCount field to RoomState
  RoomState    — exists: YES · extended: added memberCount: number (non-breaking)
  [MISSING] useRoomStatus — ⚠️ present in snapshot, now absent. Was this intentional?
```

### Step 3 — Reversal Warning on Missing Items

If any export, type, or prop from the snapshot is missing after the edit, STOP:

```
🚨 REVERSAL WARNING
  useRoomStatus() was present in the snapshot and is now absent.
  Callers that will break: RoomHeader.tsx ~line 12, SessionView.tsx ~line 8.
  Was this deletion intentional?
  → Reply YES to confirm and finalize.
  → Reply NO to restore useRoomStatus() before proceeding.
```

### Step 4 — Revert on Demand

If the developer says "revert", "undo", or "roll back":
1. Output: `⏪ REVERTING — src/<path>/<file>.tsx`
2. Output the complete file reconstructed from the BEFORE snapshot
3. Confirm: `✅ Reverted. The file is now identical to the pre-edit state.`

---

## Common FE Pitfalls — Check Before Submitting

- `<video>` elements for WebRTC streams must use a `ref` — never `src` — to attach the MediaStream
- `device.load({ routerRtpCapabilities })` must be called before creating any Transport — check `device.loaded` first
- React strict mode renders components twice in development — ensure WebRTC setup is idempotent or gated by a ref flag
- `bigint` cannot be serialized with `JSON.stringify` by default — convert to `string` before any JSON operation
- Sui wallet `signAndExecuteTransaction` may throw if the user rejects — always wrap in try/catch and show the rejection message
- React Query's `staleTime` for chain state should be short (≤ 5s for active rooms) — stale relay endpoint = broken WebRTC connection
