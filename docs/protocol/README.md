# Protocol Reference

This folder documents every distinct wire protocol and on-chain call
pattern in the system, at message level: exact message/field names, who
sends what to whom in what order, and the security checks (signatures,
tokens, expiries) attached to each step.

It's a level deeper than [`docs/topology/app.md`](../topology/app.md) and
[`docs/topology/worker.md`](../topology/worker.md), which cover the
higher-level picture — who talks to whom, over what transport, and why —
without getting into individual message shapes. Read those first if you
want the big picture; come here when you need the details of one specific
protocol.

Each file follows the same shape: why the protocol exists, a numbered
message flow in plain language, a diagram, a reference table, and a
security-notes section. Related files cross-link to each other rather than
repeating shared context.

## Index

### Call setup and media (client-facing)

| Protocol | Parties | Transport | Purpose |
|---|---|---|---|
| [`call-setup-relay.md`](call-setup-relay.md) | Client, Relay | WebSocket (mediasoup signaling) | The real, currently-used protocol for joining a room and negotiating media. |
| [`legacy-p2p-signaling.md`](legacy-p2p-signaling.md) | Client, Signaling | WebSocket | An earlier join/offer/answer/ICE design, not used by the shipped client — kept for reference. |
| [`end-to-end-encryption.md`](end-to-end-encryption.md) | Client, Client (via Relay, blind) | Opaque messages riding the call-setup WebSocket | How call content stays unreadable to the relay and signaling, and how the key changes as people join/leave. |
| [`relay-failover.md`](relay-failover.md) | Client, Relay (primary and standby) | WebSocket + HTTP health probe | How a client's call survives its relay going down mid-call. |

### Client and Contract

| Protocol | Parties | Transport | Purpose |
|---|---|---|---|
| [`client-chain-discovery.md`](client-chain-discovery.md) | Client, Contract | Sui RPC, read-only simulated calls | How a client finds available relays/signaling nodes and tracks room/network state. |
| [`client-chain-transactions.md`](client-chain-transactions.md) | Client, Contract | Sui RPC, signed transactions | Registering, creating a room, funding escrow, and the wallet/auth model. |

### Worker and Contract lifecycle

| Protocol | Parties | Transport | Purpose |
|---|---|---|---|
| [`worker-registration.md`](worker-registration.md) | Worker daemons, Contract | Sui RPC, signed transactions | How a worker stakes, registers, and enrolls in a role registry. |
| [`worker-heartbeat.md`](worker-heartbeat.md) | Worker daemons, Contract | Sui RPC, signed transactions | Periodic on-chain liveness (and load) reporting. |
| [`health-and-slashing.md`](health-and-slashing.md) | Worker daemons, Validators, Contract | Sui RPC, signed transactions | Self-reported degradation vs. the three distinct ways a worker can lose stake. |
| [`role-voting.md`](role-voting.md) | Control-plane nodes, Contract | Sui RPC, signed transactions | How a newly-registered node is assigned a relay/signaling/validator role. |
| [`cap-token.md`](cap-token.md) | Control-plane nodes, Signaling, Contract | Sui RPC + WebSocket admission check | Quorum-issued room-admission tokens for the legacy signaling protocol. |
| [`turn-credentials.md`](turn-credentials.md) | cp-daemon, Relay, Contract | HTTP + Sui RPC | Short-lived TURN server credentials for clients' ICE connections. |
| [`room-lifecycle.md`](room-lifecycle.md) | Client, cp-daemon, Contract | Sui RPC, signed transactions | Room creation, assignment, expiry, and relay failover/promotion on-chain. |

### Worker and Worker

| Protocol | Parties | Transport | Purpose |
|---|---|---|---|
| [`inter-relay-warm-pipe.md`](inter-relay-warm-pipe.md) | Relay, Relay | WebSocket, bearer-token subprotocol | The warm standby media pipe between relays, and the tree topology for larger rooms. |
| [`canary-audit.md`](canary-audit.md) | Validator, Relay | WebSocket (same protocol as a real client) | Covert media-integrity probing to catch a relay tampering with or dropping content. |
| [`quorum-claims.md`](quorum-claims.md) | Validators, or Control-plane nodes | HTTP (optional mTLS), bearer-token | The shared pull-based rendezvous pattern behind both canary and cap-token quorum agreement. |

### Economic

| Protocol | Parties | Transport | Purpose |
|---|---|---|---|
| [`rewards-and-escrow.md`](rewards-and-escrow.md) | Client, Validators, Relay, Contract | Sui RPC, signed transactions | Funding a call, measuring relay performance, and paying out or slashing. |

## Glossary

Proper names and recurring terms used across these files, defined once
here so individual files don't repeat them:

- **Sui** — the blockchain this system's shared contract runs on. Every
  "on-chain" call in these docs is a transaction or read against Sui.
- **PTB (programmable transaction block)** — a Sui transaction made of
  several chained calls that either all succeed or all fail together.
  Several protocols here bundle multiple related on-chain steps into one
  PTB so they can't partially apply.
- **BCS** — the binary serialization format Sui uses for on-chain data.
  A few protocols (like cap-tokens and canary proofs) sign over raw,
  frozen byte layouts rather than a generic serialization, specifically so
  the contract can reconstruct the exact same bytes when checking a
  signature.
- **mediasoup** — the open-source media server (SFU) the relay worker is
  built on. It forwards audio/video between participants without
  decoding or re-encoding it.
- **coturn** — the open-source TURN server software the relay worker runs
  alongside mediasoup, used as a fallback path for clients whose network
  blocks direct peer connections.
- **ed25519** — the digital signature scheme used throughout this system,
  both for wallet transactions and for the various quorum/attestation
  schemes.
- **epoch** — Sui's own notion of time (an incrementing counter the
  network advances periodically), not a wall-clock timestamp. Expiries
  tied to "epochs" move at the network's pace, not a fixed number of
  seconds.
- **SFrame** — the per-frame media encryption format used for end-to-end
  encryption (see [`end-to-end-encryption.md`](end-to-end-encryption.md)):
  it encrypts each audio/video frame individually, so a relay can still
  see enough (timing, size) to forward media correctly without ever
  decrypting the content.
- **devInspect** — shorthand for Sui's `devInspectTransactionBlock`, a
  free, read-only simulation of a call. No wallet signature, no gas cost,
  no state change — used throughout for polling/discovery reads.
- **MinerCap / StakePosition** — the two objects a worker receives when it
  registers (see [`worker-registration.md`](worker-registration.md)):
  `MinerCap` proves membership and role; `StakePosition` holds its staked
  deposit.
- **Quorum** — general term for "enough independent parties agreeing
  before something is trusted." This system uses it in several different
  places with different group sizes and thresholds (control-plane nodes
  agreeing on a cap-token, validators agreeing on a canary-audit slash,
  and so on) — each protocol file states its own specific threshold.
