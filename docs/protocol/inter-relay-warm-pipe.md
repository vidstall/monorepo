# Inter-Relay Warm Pipe

When a room has more than one relay assigned to it — a primary and one or
more standbys — the standby needs a copy of the room's media ready to serve
*instantly* the moment it's promoted (see
[`relay-failover.md`](relay-failover.md)). Waiting to fetch that media only
after a failure would mean several seconds of frozen video while the
standby catches up. This protocol is how relays keep that copy warm ahead
of time, without wasting bandwidth on it while nothing has gone wrong.

See also: [`relay-failover.md`](relay-failover.md) for what the client
experiences during a swap, and
[`call-setup-relay.md`](call-setup-relay.md) for how a `consumed` message's
`producerPeerId` field — which client this stream actually came from — gets
populated when a stream arrives via this system instead of directly from
its publisher.

## Why this protocol exists

A relay only knows about the media a client publishes directly to it. If a
different relay is going to take over that client's stream on short notice,
it needs its own live, ready-to-resume copy of that media — not a note to
"come and get it later." This protocol is a relay-to-relay connection
purpose-built for exactly that: moving media between relays, and keeping
the receiving end idle-but-ready until it's actually needed.

## Message flow

1. **Connect.** The standby relay opens a dedicated WebSocket connection to
   the primary, authenticated with a shared bearer token (so only relays
   that are supposed to be paired can open this link — a normal client
   connecting here is rejected).
2. **`pipe-connect` (standby to primary).** The standby creates its own
   media transport for receiving piped streams and sends the primary its
   connection details (IP and port).
3. **`pipe-connect` (primary to standby, reply).** The primary creates a
   matching transport, connects it to the standby's details, and replies
   with its own — completing a private media path between just these two
   relays.
4. **`pipe-producer` (primary to standby).** Whenever the primary has a
   client publishing audio or video, it forwards that stream down the pipe
   and announces it to the standby.
5. **Consume and pause.** The standby immediately starts receiving that
   forwarded stream — but pauses it right away. A paused stream still sends
   just enough traffic to keep the connection alive (so there's no
   reconnection delay later), while using roughly 80% less bandwidth than
   actually decoding and re-forwarding it. It stays paused until a real
   failover happens.
6. **The reverse direction.** If a client is homed on the *standby*
   instead (which can happen — clients pick a relay independently, see
   [`client-chain-discovery.md`](client-chain-discovery.md)), that
   client's own stream needs to reach the primary and the rest of the room
   too. The standby sends its own `pipe-producer` announcement back up to
   the primary, which mints a local copy on its own router and fans it out
   to everyone else — so the room works the same regardless of which relay
   each participant happens to be connected to.

## Rooms with more than two relays

For larger rooms, this generalizes from a single primary/standby pair into
a small tree: every relay assigned to the room independently computes the
*same* tree shape from the sorted list of assigned relay IDs — a
deterministic rule, not something the relays negotiate with each other —
so each one immediately knows its parent and children without any
coordination round-trip. Media flows down the tree the same way it flows
across a single pipe: each relay forwards to its children, minus whichever
neighbor it received the stream from in the first place.

Two safeguards keep this from misbehaving:

- **A hop-count limit.** Every forwarded stream carries a countdown that
  starts at the tree's height and decreases by one at each hop. If it ever
  reaches zero, forwarding stops — this is what prevents a stream from
  looping around the tree forever if something is misconfigured.
- **Make-before-break re-parenting.** If the tree shape has to be
  recalculated (say, a relay was added or removed), a relay opens and
  starts using its new parent connection *before* tearing down the old
  one, so there's no gap in the media. Streams are deduplicated by an
  identifier that stays constant across every hop, so briefly receiving the
  same stream from two paths during the handover doesn't cause double
  video.

## Diagram

![Sequence diagram of the inter-relay warm-pipe protocol: standby connects to primary, exchanges pipe-connect details, receives a pipe-producer announcement, consumes and immediately pauses the stream, and the reverse direction for a standby-homed client's own stream.](../imgen/output/proto-inter-relay-warm-pipe.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-inter-relay-warm-pipe.tsx`](../imgen/src/diagrams/proto-inter-relay-warm-pipe.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Message reference

| Direction | Message | Carries |
|---|---|---|
| Standby to Primary | `pipe-connect` | its transport's IP/port (and SRTP params if enabled) |
| Primary to Standby | `pipe-connect` | its own transport's IP/port, in reply |
| Primary to Standby | `pipe-producer` | the id of a stream now available to pipe, its kind (audio/video), the original publisher's identity, and a hop-count budget |
| Standby to Primary | `pipe-producer` | same shape, for a standby-homed client's own stream (reverse direction) |

## Security notes

- **Bearer-token authentication** on the inter-relay connection means only
  relays holding the shared token can open this channel — a regular client
  connecting to the same port cannot inject these messages.
- **Paused-by-default consumption** isn't just a bandwidth optimization —
  it also means a standby never actively decodes or serves media it hasn't
  been asked to, keeping "spare capacity" genuinely idle until needed.
- **The hop-count budget is a structural loop guard**, not just an
  efficiency measure — without it, a misconfigured tree could keep the same
  stream circulating indefinitely.
