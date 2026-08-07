# Relay Failover: Standby Cutover

This describes what a client does when the relay it's connected to stops
working mid-call. It builds directly on
[`call-setup-relay.md`](call-setup-relay.md) — failover doesn't introduce
new message types, it reuses that protocol's `join`/`consume` on a second
relay ahead of time so the switch, when it happens, is fast. The relay
side of how a standby already has the room's media ready to serve is
covered in [`inter-relay-warm-pipe.md`](inter-relay-warm-pipe.md).

## Why this protocol exists

Rooms can be assigned more than one relay — a primary and a standby. If
the primary dies mid-call, the client shouldn't have to rejoin from
scratch and lose seconds of audio/video while it does. This protocol
describes how the client stays one step ahead: quietly warming up a
connection to the standby the whole time, so cutting over is just "start
using the connection that's already there" instead of "build a brand new
one."

## Message flow

1. **Warm standby pre-connect** — once the client's primary session is up
   and running, it also opens a second connection to the room's standby
   relay, using the same `join` protocol as normal (though without a room
   password, and without asking for a sending transport — this connection
   is receive-only). It requests to `consume` the room's media without
   specifying a producer id, since the standby relay figures out on its
   own, from its own link to the primary (see
   [`inter-relay-warm-pipe.md`](inter-relay-warm-pipe.md)), what it should
   be serving.
2. **Kept paused** — as soon as that standby stream is set up, the client
   immediately pauses it. It keeps just enough traffic alive to prove the
   connection still works (a keep-alive heartbeat), but renders nothing
   from it and uses essentially no bandwidth beyond that. This setup is
   entirely best-effort: if it fails, the call simply continues on the
   primary relay alone, without any error shown to the user.
3. **Cutover trigger, Layer A — silence detection**: if the client stops
   receiving any media at all from the primary, it treats that as a
   possible outage. Before cutting over, it does one quick, short-timeout
   health check against the standby relay. If that check clearly comes
   back "not ready," the cutover is held off; but if the check times out,
   errors, or the standby doesn't answer at all, the client cuts over
   anyway — the system is deliberately biased toward acting on a failure
   rather than waiting for certainty.
4. **Cutover trigger, Layer B — connection drop**: if the WebSocket to the
   primary relay closes outright, that's a much stronger signal. The
   client immediately fires off a best-effort, fire-and-forget notice to
   the standby (so other systems watching for trouble can react faster —
   this is a hint, not something the client waits on or trusts on its
   own), and then attempts the cutover right away. If there's no warmed-up
   standby connection to cut over to, it instead retries the primary
   connection itself, waiting a little longer between each attempt.
5. **Cutover** — switching over is simply un-pausing the already-connected
   standby stream and telling the rest of the app's UI that media is now
   coming from the standby. Because the standby relay may only be able to
   serve individual streams rather than a pre-mixed composite view, the
   call's display may change (for example: from one composited video to a
   grid of separate video tiles) at the same moment.
6. **Testing override** — a URL option lets a browser be told to connect
   to the standby (or a specific relay by position) instead of the normal
   primary, useful for demoing or testing failover without having to
   actually take a relay down.

## Diagram

![Sequence diagram of relay failover: client pre-connects and joins the standby relay as receive-only, pauses the standby stream, primary relay connection closes, client sends a best-effort down-hint to the standby, then resumes the paused standby stream to complete the cutover.](../imgen/output/proto-relay-failover.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-relay-failover.tsx`](../imgen/src/diagrams/proto-relay-failover.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Message reference

This protocol reuses [`call-setup-relay.md`](call-setup-relay.md)'s
`join`/`createTransport`/`consume` messages against the standby relay
ahead of time, plus one extra, standby-side-only notice:

| Direction | Message | Carries | Purpose |
|---|---|---|---|
| Client → Standby relay | `join` | `roomId`, `peerId` (no password) | Pre-warm, receive-only |
| Client → Standby relay | `consume` | `roomId`, `peerId`, `rtpCapabilities` (no `producerId`) | Standby resolves the right stream itself |
| Client → Standby's metrics endpoint | `relay-down-hint` (HTTP POST) | `roomId`, `peerId` | Best-effort early warning; never authoritative |

## Security notes

- **No new authentication happens for failover** — the standby join reuses
  whatever admission model the room already has (see
  [`call-setup-relay.md`](call-setup-relay.md)'s security notes); failover
  doesn't weaken or bypass it.
- **The health-check before cutting over fails open, not closed**: an
  unreachable or slow standby is treated as "probably fine, proceed,"
  because in this design a missed cutover (staying stuck on a dead
  primary) is considered worse than an occasional unnecessary one.
- **The `relay-down-hint` notice is never trusted on its own** — it's an
  accelerant for other parts of the system that independently verify relay
  health (see [`room-lifecycle.md`](room-lifecycle.md)'s room health
  voting), not a claim the system acts on by itself.
- **End-to-end encrypted calls fail closed on an incomplete handoff**: if
  the standby's reply doesn't include enough information to tell the
  client whose stream it actually is, the client refuses to guess — it
  degrades to running without a second relay rather than risk garbling or
  misattributing decrypted media. See
  [`end-to-end-encryption.md`](end-to-end-encryption.md) for why that
  attribution matters.
