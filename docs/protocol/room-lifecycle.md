# Room Lifecycle

A room isn't just a chat between a client and a relay — it's also an
on-chain object with a life of its own: created, assigned workers, watched
for staleness, and eventually closed. This document covers that on-chain
side, which is what makes the system's failover behavior auditable rather
than something happening silently inside one process.

See also: [`client-chain-transactions.md`](client-chain-transactions.md)
for how a room gets created in the first place, and
[`relay-failover.md`](relay-failover.md) for the client-side behavior
racing against the on-chain promotion described here.

## Message flow

1. **Creation.** A client submits `room_manager::create_room` (covered in
   [`client-chain-transactions.md`](client-chain-transactions.md)). This
   just records that a room exists and is waiting for workers — it doesn't
   assign anyone yet.
2. **Assignment.** This is the event that turns an empty room record into
   something a client can actually connect to — and it's decided by the
   control-plane daemons scoring candidates, not by an admin manually
   picking one:
   - Once the room's escrow is funded, every cp-daemon independently ranks
     the available relays and validators using the same scoring formula
     (round-trip time, current load, staked amount, liveness, region, and
     track record), and picks whichever signaling node currently reports
     the lowest load. For relays specifically, a second capacity-aware
     placement pass makes sure nobody gets assigned more than their load
     budget can actually take.
   - Each cp-daemon submits its resulting ballot on-chain
     (`room_manager_pairing::submit_pairing_proposal`) — its chosen relays,
     signaling node, validator set, and (from that same ranked list) the
     top three validators to serve as this room's fast dead-worker
     watchers. The contract doesn't compute any of this itself here — it
     only checks the ballot is shaped correctly and tallies agreement.
   - Once **two thirds of active CPs submit matching scores**, that
     proposal wins, and the contract writes the whole assignment — relays,
     signaling, validators, and health-watchers — in one state change,
     flipping the room from pending to ready.
   - Two fallbacks exist for when that doesn't happen cleanly: if CPs never
     reach quorum, the room's creator can trigger `finalize_room` after a
     cooldown, which has the contract itself score the stored proposals and
     pick the best one. Separately, `assign_relay_and_signaling` is a
     genuine admin-signed manual override — but it's explicitly a
     testing/fallback bypass (and doesn't touch validators at all), not the
     normal path.

   See [`client-chain-discovery.md`](client-chain-discovery.md) for how a
   client learns which relay/signaling node it got.
3. **Expiry sweep.** cp-daemon periodically checks every room's age against
   two limits, based on plain event timestamps rather than any on-chain
   clock: a room stuck **pending** (created but nobody ever joined) expires
   after about 15 minutes; a room that's gone **ready/active** but stays
   open expires after about 12 hours. When either limit is hit, cp-daemon
   submits a close call that includes the status it *expects* the room to
   still be in — if the room's real status has already changed (someone
   else closed it, or it moved on to a different state) the call is simply
   rejected rather than closing something that's no longer what cp-daemon
   thought it was watching. This makes the sweep safe to run from more than
   one cp-daemon without coordination.
4. **Relay heartbeat watch.** Separately, cp-daemon watches each active
   room's assigned relay(s) for on-chain heartbeats (see
   [`worker-heartbeat.md`](worker-heartbeat.md)). If the room's primary
   relay's heartbeat goes stale past a threshold, cp-daemon promotes the
   freshest live standby relay to primary — a plain on-chain state change,
   not a message to any relay telling it to do anything differently
   (relays independently read the current assignment and adjust their own
   behavior in response, per [`inter-relay-warm-pipe.md`](inter-relay-warm-pipe.md)).
5. **Standby replacement.** If it's a *standby* relay (not the primary)
   that goes stale, the response is different: rather than an immediate
   promotion, cp-daemon proposes a specific replacement candidate, which
   goes through the same CP quorum-vote pattern used elsewhere in the
   system (see [`cap-token.md`](cap-token.md) for the general pattern) —
   a stronger bar than the primary case, since there's no active session
   depending on it right this second.
6. **Room health voting.** Independently of the heartbeat watch,
   validator-daemons assigned to a specific room each run their own
   reachability probe against that room's relay/signaling nodes. A
   validator only casts a vote if it's actually one of the validators
   assigned to that room *and* its own probe agrees the target looks
   unreachable — a validator never votes purely on hearsay from another
   validator's report. "Assigned to that room" here means the room's
   **health-watcher set** specifically — the top three validators from
   step 2's ranking, a smaller, faster-reacting subset of the room's full
   validator set (which is sized larger, for reward/quality auditing
   rather than fast dead-worker detection).

## Diagram

![Sequence diagram of a room's on-chain lifecycle: create_room, cp-daemons independently scoring candidate relays/signaling/validators and submitting matching pairing proposals until two-thirds quorum ratifies one, cp-daemon's periodic expiry sweep with a status guard, and cp-daemon promoting a standby relay after the primary's heartbeat goes stale.](../imgen/output/proto-room-lifecycle.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-room-lifecycle.tsx`](../imgen/src/diagrams/proto-room-lifecycle.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Security notes

- **No single party picks a room's workers** — assignment is an off-chain
  scoring computation, run independently by every cp-daemon, ratified only
  once two thirds of active CPs agree on the same ballot. The contract
  itself never runs the scoring in the normal path, and the one manual
  admin-assignment call that exists is explicitly a testing/fallback
  bypass, not something the production system relies on.
- **Every lifecycle transition is a chain write, not a message between
  processes.** cp-daemon doesn't tell a relay "you're primary now" — it
  writes that fact on-chain, and every party independently reads it from
  there. That's what makes this auditable: there's no hidden coordination
  channel to trust.
- **The expiry sweep's status guard prevents double-closing races** — since
  multiple cp-daemon instances can run this sweep independently, the
  "still matches what I expect" check means only one of them actually
  succeeds if two race on the same stale room.
- **Standby replacement requires a quorum vote; primary promotion doesn't**
  — promoting an already-known, already-warmed-up standby into the active
  role during a live outage is time-sensitive, while replacing a standby
  that isn't currently serving anyone has room for the slower, more
  deliberate quorum process.
- **Room health votes require both assignment and independent
  verification** — a validator can't vote a node down just because someone
  else claimed it's down, and can't vote on a room it wasn't assigned to
  watch in the first place.
