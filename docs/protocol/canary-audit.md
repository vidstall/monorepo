# Canary Audit

Relays are trusted to forward media faithfully — but "trusted" isn't the
same as "verified." This protocol is how a validator secretly checks
whether a relay is actually doing that honestly, by injecting synthetic
media into a room and watching whether it comes back out unchanged.

See also: [`call-setup-relay.md`](call-setup-relay.md) for the protocol a
canary probe reuses to join a room in the first place,
[`health-and-slashing.md`](health-and-slashing.md) for what happens when a
canary catches a relay misbehaving, and
[`quorum-claims.md`](quorum-claims.md) for how multiple validators' evidence
gets combined before anything is submitted on-chain.

## Why this protocol exists

A relay that drops or tampers with media is hard to catch after the fact —
by the time anyone notices a call sounded bad, there's no way to prove
whose fault it was. A canary probe solves this by injecting media whose
*exact correct output* is knowable in advance only to the validator that
sent it — so if what comes back out doesn't match, that's hard evidence,
not a guess.

## Message flow

1. **Covert join.** The validator joins the room using the exact same
   protocol a real participant would (see
   [`call-setup-relay.md`](call-setup-relay.md)), but deliberately skips the
   steps that would announce it to other participants — no password-derived
   roster entry, no identity broadcast. To the relay, it's a normal join; to
   everyone else already in the room, it's invisible.
2. **Derive a canary key.** Before sending anything, the validator derives
   an encryption key that only it — and any other validators auditing the
   same relay as part of the same "cell" — can derive. This key is built
   from the room's own key material plus a secret specific to that
   auditing cell, so a relay (or anyone else) who only knows the room's key
   cannot compute a matching one and cannot forge a convincing fake.
3. **Publish synthetic canary media.** The validator sends encrypted
   audio/video like any other participant would (`produce`, from
   [`call-setup-relay.md`](call-setup-relay.md)) — except the content is
   synthetic, generated specifically for this check.
4. **Capture what comes back out.** The validator captures the raw bytes
   the relay actually forwards, without decoding them.
5. **Recompute the expected result, independently.** Using its own copy of
   the canary key and its own record of what it originally sent, the
   validator recomputes what a byte-for-byte faithful forward *should* have
   produced — entirely on its own, never trusting anything the relay
   reports back.
6. **Compare.** If the captured bytes match the recomputed expectation, the
   relay forwarded it intact. If a different, wrong version shows up, that's
   evidence of tampering. If nothing shows up at all, that's evidence of a
   drop.

## Keeping the auditor anonymous

If a relay could tell which validator was auditing it, it could simply
behave honestly toward that one validator and misbehave toward everyone
else. To prevent that, a validator never signs its audit evidence with its
main, publicly-known network identity. Instead it uses a separate, rotating
"session" key — one that isn't linked to its main identity anywhere on
chain until the very moment it's actually needed to submit real evidence of
a violation (see [`quorum-claims.md`](quorum-claims.md) and
[`health-and-slashing.md`](health-and-slashing.md)). Until then, from the
relay's perspective, the canary participant is indistinguishable from any
other quiet, low-traffic peer.

## Diagram

![Sequence diagram of the canary audit protocol: a validator joins a room without announcing itself, derives a private canary key, publishes synthetic encrypted media, captures what the relay forwards back out, and independently recomputes and compares the expected result.](../imgen/output/proto-canary-audit.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-canary-audit.tsx`](../imgen/src/diagrams/proto-canary-audit.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Message reference

This protocol reuses [`call-setup-relay.md`](call-setup-relay.md)'s `join`
and `produce` messages verbatim (with a covert, roster-silent join). The
only genuinely new step is entirely internal to the validator: capturing
forwarded bytes and comparing them against a locally-recomputed
expectation — nothing about that comparison is visible on the wire.

## Security notes

- **Ground truth lives entirely with the validator.** It never asks the
  relay or anyone else what the "correct" output should have been — it
  computes that itself, from data only it holds, so there's nothing for a
  dishonest relay to intercept or influence.
- **The canary key is cell-scoped, not room-wide.** Anyone who only has
  access to the room's ordinary key (including the relay itself) derives a
  *different* key and cannot produce matching ciphertext, so a relay cannot
  fabricate a "correct-looking" forward even if it suspects it's being
  tested.
- **Identity separation is deliberate and load-bearing** — see
  [`health-and-slashing.md`](health-and-slashing.md) for how this
  evidence eventually gets attributed on-chain without exposing which
  validator caught it, until the evidence is actually being submitted.
