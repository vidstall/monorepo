# User — malicious node scenarios

Users don't stake anything to register, and they don't get a vote in
anything that affects other people's rooms. So most of what a malicious
user can do is limited to their own room, or is a nuisance/spam problem
rather than a safety problem. The scenarios below cover both.

## Scenario 1 — F = 1, a lone spammer

One malicious user registers over and over under different identities and
creates dozens of empty rooms, never funding any of them.

- Each room sits in "pending" doing nothing.
- Since a room that's pending too long without ever getting assigned expires
  automatically, the spam rooms eventually clean themselves up.
- No relay, validator, or CP was ever actually assigned to these rooms (that
  only happens once a room has funding to attract proposals), so no real
  resources were wasted beyond a bit of on-chain storage and CP polling.

**Verdict:** annoying, self-limiting, no real damage. Registration being free
makes this cheap to attempt but the impact is capped by the expiry sweep.

## Scenario 2 — F = 1, a user tries to shortchange the network

A malicious user creates a room, funds it with a small amount, and pulls
maximum value out of the relays/validators/CP without ever intending to pay
a fair price.

- The escrow is fixed at funding time — relays/validators/CP can only ever
  be paid out of what's actually in that escrow, capped no matter how much
  work was done.
- The room's participants (including the malicious creator) still need CP-
  issued access tokens to join, so the malicious user can't force extra
  people into the call for free either.

**Verdict:** the malicious user can waste some relay/validator effort on an
underpaid room, but they can never make the network pay out more than what
they put in. The damage is bounded by their own deposit.

## Scenario 3 — F = 1, a user falsely reports "the room is dead"

A malicious user in an otherwise-healthy room reports that the relay or CP
seems to be down, hoping to trigger an unnecessary failover.

- The room-level health check requires *both* enough users *and* enough of
  the room's dedicated validators to agree before anything happens.
- If the relay/CP is actually fine, the room's validators won't confirm the
  report, so nothing gets triggered.

**Verdict:** a single false report from a user does nothing on its own. This
only becomes dangerous if it's combined with malicious *validators* in the
same room (see [validator.md](validator.md) Scenario 2) — a pure user-side
attack has no effect.

## Scenario 4 — F = many, a bot swarm (Sybil load attack)

Since registration is free, an attacker spins up hundreds or thousands of
bot "users," each creating and funding a small room simultaneously, hoping
to overload the relay/validator/CP capacity of the network.

- Every one of these rooms still goes through the normal assignment-voting
  process — CPs still have to reach two-thirds agreement per room, and
  relays/validators still have to be actually available to be assigned.
- If there genuinely aren't enough relays/validators/CPs to cover the
  sudden demand, some rooms simply stay in "pending" until capacity frees
  up or they expire — the network degrades gracefully rather than breaking.
- Because each room needs its own real funding, this attack costs the
  attacker real money proportional to how much load they want to generate —
  it's not free at scale, only free per identity.

**Verdict:** this is a capacity/availability concern (can the network scale
its relay/validator/CP pool fast enough), not a correctness or security
break — no money can be stolen and no false state gets written on-chain.
This is exactly the scenario the project's `bot` load-testing harness is
built to simulate on purpose.

## Summary

| F | Behavior | Outcome |
|---|---|---|
| 1 | Spam empty rooms | Self-cleans via expiry |
| 1 | Underfund, overuse | Capped by own escrow |
| 1 | False health report | No effect without malicious validators too |
| many | Sybil bot swarm | Costs real money per room; degrades capacity, not safety |

Users are the least dangerous actor in the system: no stake, no vote, no
ability to forge tokens or move other people's money. Their worst-case
impact is wasted resources or self-funded noise, never a false on-chain
outcome.
