# Worker-Side Architecture

The worker side of the system is four independent process types — deployed
as separate VM-backed daemons (`vidctl scenario` provisions and runs one or
more of each) — plus a synthetic load-testing client that isn't a real
network role. This document covers the topology *between* them: who talks
to whom, over what protocol, and why.

## Node types

- **Signaling** — the client-facing WebSocket admission gate. Authenticates
  a joining client, resolves that room's assigned relay pair from on-chain
  `RoomAssigned` state, and pushes a `relay-assigned {primary_url,
  standby_url}` message down to the client. It never proxies media and
  never talks to relay directly.
- **Relay** — the SFU (mediasoup). Terminates each client's WebRTC session
  and forwards media. When a room has a primary and a standby, the standby
  dials the primary directly to receive a warm mediasoup pipe, ready to take
  over on failover. Which relay is primary vs. standby is decided on-chain
  (`RoomAssigned`), not negotiated between the relays themselves. For larger
  rooms this generalizes beyond a single pair to a deterministic D-ary
  spanning tree over relay IDs
  (`packages/inter-relay-client/src/tree-topology.ts`).
- **cp-daemon** ("control-plane") — a chain-driven admin/attestation
  service. Reacts to on-chain events: `RoomCreated` triggers a
  relay+signaling assignment; a stale relay heartbeat triggers
  `promote_relay`; role-voting quorum triggers issuing a `RoomCapability`
  token. Multiple cp-daemon instances also cosign quorum attestations with
  each other directly, and cp-daemon runs an HTTP endpoint that relay calls
  directly for TURN credentials.
- **validator-daemon** — the QoE/fraud-detection "canary". Joins rooms as a
  covert WebSocket client of relay's own protocol (indistinguishable from a
  real participant, with no roster broadcast) to probe and verify media
  integrity. Multiple validator-daemons exchange divergence attestations
  with each other directly to jointly build slashing proof before
  submitting it on-chain.
- **bot** — a synthetic load-test participant, not a network role. It only
  speaks the same client-facing protocol a real browser does (signaling +
  relay), and touches the chain the same way a real client would.

## Diagram

![Worker-only topology diagram, showing just the four worker roles (no browser client or smart contract pictured -- see the Relationships section below for how they fit in). Four group rectangles, counter-clockwise from top-left: Relay, Validator, Control plane, Signaling. Each group contains two worker-instance chips. Relay's two chips (primary, standby) are connected by an internal line (inter-relay pipe, WS); Control plane's two chips (leader, follower) are connected internally (quorum cosign, HTTP); Validator's two chips (co-auditor A, co-auditor B) are connected internally (divergence attestation, HTTP); Signaling's two chips (instance A, instance B) have no internal line, since signaling instances don't talk to each other. Between groups, only two lines exist: Relay to Validator (covert canary join, WS) and Relay to Control plane (TURN credential, HTTP). No line connects Signaling to any other group, and no line connects Validator to Control plane -- those pairs never communicate directly.](../imgen/output/worker-topology.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/worker-topology.tsx`](../imgen/src/diagrams/worker-topology.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Relationships

| # | Source → target | Protocol | Purpose |
|---|---|---|---|
| 1 | Browser client → Signaling | WebSocket | Join/auth; client receives its relay assignment. |
| 2 | Browser client → Relay | WebSocket (mediasoup) | The actual media session. |
| 3 | Relay (standby) ↔ Relay (primary) | WebSocket, bearer-token subprotocol | Warm-standby mediasoup pipe; generalizes to a spanning tree for rooms with more than two relays. |
| 4 | Relay → cp-daemon | HTTP `POST /turn/issue`, bearer-token | TURN credential for the client's ICE servers. |
| 5 | cp-daemon ↔ cp-daemon | HTTP (optional mTLS), bearer-token | Quorum cosigning of `CapTokenIssueClaim`s before submitting on-chain. |
| 6 | validator-daemon → Relay | WebSocket, same protocol as a real client, covert (no roster broadcast) | Canary media probe for QoE/fraud detection. |
| 7 | validator-daemon ↔ validator-daemon | HTTP, bearer-token (optional mTLS) | Exchange `DivergenceAttestation`s to build slashing proof. |

**What's deliberately absent:** there is no direct Signaling↔Relay link and
no direct cp-daemon↔Relay link for *assignment* purposes (only the TURN-RPC
link above). Signaling, Relay, cp-daemon, and validator-daemon each
independently read and write the shared on-chain state (via each process's
own `chain-event-listener` package) to learn about room/relay assignments
and to coordinate — none of them call each other directly to hand off that
information. This is the key architectural property of the worker side:
**the chain is the coordination mechanism**, and the handful of direct
process-to-process links that do exist (#3, #4, #5, #6, #7 above) are all
narrow, purpose-built exceptions to that rule — a media pipe, a credential
fetch, and two attestation/quorum exchanges — not a general daemon-to-daemon
control plane.
