# TURN Credentials

When two peers can't reach each other directly because of NAT or firewall
restrictions, WebRTC falls back to relaying traffic through a TURN server.
This document covers how a relay's TURN server hands out short-lived,
rotating credentials for that fallback, instead of a single static
password anyone could reuse forever.

## Where the TURN server lives

Each relay worker runs a standard TURN server (`coturn`) on the same
machine as its media relay, listening on the usual TURN port. The system
doesn't build its own TURN implementation — it reuses `coturn`'s
well-established `use-auth-secret` credential scheme, which lets a
separate, trusted party mint credentials without coturn itself needing to
know about individual users ahead of time.

## Who issues credentials

**cp-daemon issues TURN credentials, not the relay itself.** This keeps the
relay from being the sole holder of the shared secret its own TURN server
trusts — if a relay were compromised or slashed, its TURN access can be cut
off from the control-plane side without needing to touch the relay at all.

## Message flow

1. The relay needs a TURN credential for a client that's about to join a
   call (see [`call-setup-relay.md`](call-setup-relay.md) — the credential
   ends up inside the `transportCreated` message's `iceServers`).
2. The relay calls cp-daemon's `POST /turn/issue` endpoint over HTTP,
   authenticated with a bearer token, asking for a credential for a target
   user.
3. cp-daemon computes a coturn-standard credential pair: a `username` made
   of an expiry timestamp and the user id, and a `password` that's an
   HMAC of that username using a shared secret only cp-daemon and coturn
   know. This is coturn's normal `use-auth-secret` scheme — nothing custom.
4. cp-daemon also writes a **hash** of the credential (never the plaintext,
   never the secret itself) on-chain as an audit trail, so there's a
   tamper-evident record that a credential was issued, without exposing
   anything usable to intercept.
5. cp-daemon replies to the relay with the username/password pair, an
   expiry (15–30 minutes by default — deliberately short-lived), and the
   audit transaction's digest. If the target relay has been slashed, it
   replies with a "skipped" response instead, and the relay is expected to
   degrade gracefully — the client can still attempt a direct connection,
   it just won't have a TURN fallback for that session.

## Secret rotation and the kill-switch

The shared secret backing the HMAC isn't static. cp-daemon rotates it on a
roughly daily cron schedule, keeping the previous secret valid for a short
overlap window so credentials already issued under the old secret don't
suddenly break mid-call. Outside that routine rotation, there's also an
**emergency kill-switch**: if a relay gets slashed (see
[`health-and-slashing.md`](health-and-slashing.md)) or a rotation event
fires unexpectedly, cp-daemon evicts the secret immediately rather than
waiting for the next scheduled rotation.

## Diagram

![Sequence diagram of the TURN credential protocol: relay requests a credential from cp-daemon over an authenticated RPC, cp-daemon computes the HMAC-based coturn credential, anchors a hash of it on-chain for audit, and replies with the short-lived username/password pair.](../imgen/output/proto-turn-credentials.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-turn-credentials.tsx`](../imgen/src/diagrams/proto-turn-credentials.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Security notes

- **Credentials are short-lived by design** — even if one leaked, it stops
  working within half an hour at most.
- **The shared HMAC secret never appears on-chain**, only a hash of each
  issued credential — the audit trail proves a credential was issued
  without handing out anything an observer could use.
- **A slashed relay's TURN access can be cut immediately**, independent of
  the routine rotation schedule.
- **The relay never holds the shared secret itself** — it only ever
  receives already-computed credentials from cp-daemon, so compromising a
  relay doesn't hand over the means to mint arbitrary TURN credentials for
  every other relay too.
