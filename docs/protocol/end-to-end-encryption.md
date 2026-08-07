# End-to-End Encryption Key Exchange

This protocol runs *client-to-client*, layered on top of
[`call-setup-relay.md`](call-setup-relay.md). It decides who can read a
call's audio and video, and it's built so that the relay and signaling
worker carrying those messages never see anything except opaque encrypted
bytes — they route the key-exchange messages the same way they route
everything else, without ever holding, deriving, or needing the actual
room key.

## Why this protocol exists

Normally, the party that forwards your video (the relay) is also the party
that *could* read it, if it wanted to. End-to-end encryption removes that
possibility: every browser encrypts its media with a key that only the
other participants in the room know, so the relay is forwarding sealed
boxes it cannot open. This file documents how that shared key gets agreed
on, refreshed as people join and leave, and kept out of reach of anyone
who isn't supposed to have it.

## Message flow

1. **`rosterPeer`** — whenever a client joins a room that has encryption
   enabled (see `roomMode` in [`call-setup-relay.md`](call-setup-relay.md)),
   the relay tells it every other current member's session public key, and
   tells every current member the newcomer's key. This roster — who's in
   the room, and their public keys — is the only thing the relay
   contributes to encryption. It never sees a private key or the room key
   itself.
2. **Coordinator election** — every member independently computes the same
   answer to "who coordinates key distribution right now?" by picking
   whoever has the smallest public key in the roster (a deterministic,
   agreement-free way to pick one member without an extra vote). If that
   member has gone quiet, the others fall back to the next reachable one.
3. **Bootstrap** — once the room has at least two members, the coordinator
   generates a random room key and sends it to every member, individually
   sealed to each one's public key (an anonymous "sealed box" — nobody but
   the intended recipient, not even the coordinator afterward, can prove
   who sent it). This travels as one `e2eeKeyBundle` message containing one
   sealed copy per member.
4. **Rekey on someone joining** — every *existing* member independently
   derives the same new key from the old one using a one-way function
   (a "ratchet"): anyone who joins later can never work backward to
   recover an earlier key from a later one. The coordinator (elected among
   the members who were already there) additionally seals a copy of the
   new key to the joining member only.
5. **Rekey on someone leaving** — this time the coordinator throws the old
   key away and generates a completely fresh, unrelated one, then reseals
   it to everyone who's left. Unlike a join, this can't be derived
   mathematically from the old key — it's a hard cut, so someone who just
   left has no way to keep listening even if they kept the old key.
6. **`e2eeKeyBundle`** — the wire message carrying all of the above: a
   room id, an epoch/key-id number that increases every time the key
   changes, the coordinator's public key (so recipients can sanity-check
   who issued it), and a list of individually-sealed copies, one per
   recipient. The relay checks only that the room id in the message
   matches the room the sender is actually in (blocking a peer from
   claiming to speak for a different room) — it never inspects, filters,
   or needs to understand the sealed contents, and re-broadcasts the whole
   bundle byte-for-byte to the rest of the room.
7. **Per-message key derivation** — the shared room key isn't used to
   encrypt video frames directly. Each sender derives its own,
   frame-encryption key from the room key, mixed with the room id, the
   current key-id, and that sender's own identity. This matters because
   without mixing in "who's sending," two different people's streams could
   accidentally reuse the exact same encryption pattern under the same
   room key — mixing the sender's identity in avoids that.
8. **Grace window** — for a couple of seconds after a rekey, the *previous*
   key is still kept around so that any video frame that was already in
   flight when the key changed can still be decrypted, instead of being
   dropped.

## Two privacy levels: Path A and Path C

Not every room gets the same guarantee, and the system is upfront about
the difference:

- **Path A (default, open rooms)** — the room key is derived with no extra
  secret mixed in. Anyone who's a legitimate member of the roster (which
  includes anyone who validly joined, including an auditing party — see
  [`canary-audit.md`](canary-audit.md)) can derive the same content key.
  The privacy property here is closer to "the relay operator specifically
  can't read this," not "nobody but the intended participants can."
- **Path C (invite links with a `#`-fragment secret)** — joining via an
  invite link carries an extra secret in the URL fragment, the part after
  `#`, which browsers never transmit to any server. That secret gets
  mixed into the key derivation. Anyone who has the room key but *not*
  this out-of-band secret — including a party that joined the room through
  the normal protocol but was never handed the actual invite link —
  derives a *different*, wrong key, and simply cannot decrypt the content.
  This is what structurally keeps even a covertly-admitted auditor (see
  [`canary-audit.md`](canary-audit.md)) out of real participants' actual
  conversation, without needing to trust it to behave.

## Host cleartext avoidance

There's one edge case worth calling out: the very first person in an
invite-based room would, naively, have nobody to get a key from yet — the
coordinator only hands out a key once the roster has two or more people.
The client handles this by simply waiting to send any audio/video at all
until a usable key is in place, rather than ever sending even one frame
unencrypted while waiting.

## Diagram

![Sequence diagram of the end-to-end encryption key exchange: rosterPeer roster sync, coordinator bootstrapping the room key and sealing it per-recipient in an e2eeKeyBundle, a rekey on a new member joining via ratchet, and a rekey on a member leaving via a fresh random key.](../imgen/output/proto-end-to-end-encryption.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-end-to-end-encryption.tsx`](../imgen/src/diagrams/proto-end-to-end-encryption.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Message reference

| Direction | Message | Carries |
|---|---|---|
| Relay → Client | `rosterPeer` | `peerId`, `sessionPubkey` |
| Client → Relay → other Clients | `e2eeKeyBundle` | `roomId`, `epoch`/`kid`, `coordinatorPubkey`, `envelopes: [{ recipientPubkey, sealedKey }]` |

## Security notes

- **The relay and signaling worker never hold or derive the room key** —
  they only ever see already-sealed bytes and a roster of public keys.
  This is what "blind transport" means in this system.
- **Leaving is a hard cut, joining is a soft one**: a member who leaves
  gets a fresh unrelated key (can't be derived from what they already
  had); a member who joins only gets *future* keys, never anything from
  before they arrived (forward secrecy).
- **Sender identity is mixed into every frame's actual encryption key**,
  specifically to stop two different publishers from ever reusing the
  exact same encryption pattern.
- **Known limitation (accepted for this project's current stage)**: there
  isn't yet a cryptographic guarantee against two coordinators
  disagreeing under network partition and both issuing a bundle for the
  same key-id. The system detects that condition and raises an alarm
  rather than silently resolving it — a stronger guarantee (in the style
  of the MLS protocol's epoch authentication) is a possible future
  improvement, not something currently enforced.
- **Path C's privacy depends on the invite link's fragment never being
  sent to a server** — this is a property of how browsers handle URL
  fragments, not something this protocol enforces itself.
