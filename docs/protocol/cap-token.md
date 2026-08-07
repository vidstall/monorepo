# Room Admission Tokens (Cap-Tokens)

Before a peer can be admitted into a room under
[`legacy-p2p-signaling.md`](legacy-p2p-signaling.md)'s auth path, it needs a
`RoomCapability` token — proof that it's allowed into that specific room, as
a specific role, until a specific expiry. This document covers how that
token gets minted, and why no single operator can mint one alone.

## Why a quorum, not one issuer

Admission tokens are trust-bearing objects: whoever holds a valid one can
join a room. If a single control-plane (CP) operator could mint them
unilaterally, that operator alone could admit anyone into any room. Instead,
issuing a token requires several independent CP daemons to each
independently agree and sign — the system calls this **quorum
cosigning**, and it's the same trust pattern used elsewhere for slashing
proofs (see [`quorum-claims.md`](quorum-claims.md)).

## Message flow

1. A client (or another party requesting admission on its behalf) assembles
   the fields that will make up the token: the target `roomId`, the peer's
   session public key, the requested `role`, an expiry (measured in Sui
   **epochs**, not wall-clock time), and a `nonce`.
2. Those fields are packed into one fixed byte layout — room id bytes,
   32-byte peer public key, one role byte, then the expiry and nonce as
   little-endian 8-byte integers, simply concatenated with nothing in
   between (not length-prefixed the way most structured chain data is —
   every CP has to derive the exact same bytes independently, so the layout
   is frozen and simple on purpose).
3. Each participating CP daemon independently re-derives those same bytes
   from the request and signs them with a raw ed25519 signature — it does
   not trust anyone else's signature or claim about what the bytes should
   be, it recomputes them itself.
4. Once enough distinct CP signatures are collected — 2 out of 3 registered
   CPs by default — they're submitted together on-chain. The contract
   independently re-verifies: that the signer count clears the minimum
   quorum, that every signer is a genuinely registered, distinct CP
   operator (no duplicates padding the count), and that every signature
   verifies against that CP's known public key.
5. Only once all of that passes does the contract mint the `RoomCapability`
   object and hand it to the requester.

There are a few variants of the same underlying quorum pattern:
**issue** (the flow above), **issue for a late-joining peer** (anchored to
an already-issued token for the same room, so a room already running can
admit more people without restarting the whole flow), **refresh** (extend
an existing token's role/expiry), **revoke** (invalidate one early), and a
break-glass **degraded/emergency** path that skips the quorum requirement
entirely but is gated behind an admin capability and leaves an explicit
on-chain marker that it happened — meant for outages, not routine use.

## How signaling checks a token

The [legacy signaling protocol](legacy-p2p-signaling.md) is this system's
current consumer of cap-tokens. Rather than asking the chain fresh on every
join (slow, and a lot of load on the RPC), it keeps a short-lived local
cache (about a minute) fed by continuously polling capability-related chain
events in the background. Two behaviors matter for safety:

- If a token gets revoked on-chain, the cache is guaranteed to notice and
  drop it within a few seconds — a revoked token doesn't stay usable for
  the rest of its cache TTL.
- If the cache loses contact with the chain for too long, it fails
  **closed**: it stops trusting anything it has cached and starts rejecting
  joins outright, rather than silently admitting people based on
  possibly-stale data.

The nonce inside a token also gets checked against a strictly-increasing
high-water mark per token, so a captured join message can't be replayed
later to re-admit a peer that's already been revoked or expired.

## Diagram

![Sequence diagram of the cap-token quorum issuance flow: a client requests a token, three CP daemons each independently re-derive and sign the canonical byte payload, the aggregated quorum signature is submitted on-chain, and the contract verifies signer count, distinctness, and each signature before minting the RoomCapability.](../imgen/output/proto-cap-token.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-cap-token.tsx`](../imgen/src/diagrams/proto-cap-token.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Security notes

- **No single CP can mint a token alone** — the on-chain verifier hard-rejects
  anything below the quorum threshold, so this isn't just a client-side
  courtesy check.
- **Duplicate signers don't count twice** toward quorum — the contract
  deduplicates by signer identity before checking the threshold.
- **Expiry is epoch-based, not clock-based**, which avoids relying on any
  party's local clock being honest or synchronized.
- **The signature check binds a token to a specific room and a specific
  key** — a token issued for one room, or one peer, doesn't verify for
  another.

See also [`worker-registration.md`](worker-registration.md) and
[`role-voting.md`](role-voting.md) for how a daemon becomes a CP in the
first place — only registered, currently-active CPs count toward quorum
here.
