# Relay — malicious node scenarios

A relay can never report its own quality — that number only ever comes from
validator measurements — so a relay's ability to lie is much narrower than a
validator's or CP's. Its main attack surface is *behaving* badly (dropping
data, tampering with test signals) and hoping not to get caught, not
*claiming* to be good on-chain.

## Scenario 1 — F = 1, a relay quietly drops packets

One relay assigned as primary in a room forwards media poorly (packet loss)
to save on bandwidth costs, hoping no one notices.

- Two different validators watching the room independently measure its
  actual packet loss.
- At payout, the relay's quality score comes out as "too bad to pay," which
  also triggers a stake slash.
- The slashed stake is redistributed to the room's other (verified, good)
  relays and to the room's creator.

**Verdict:** caught and punished automatically — a lone bad relay cannot
hide behind self-reporting because it has none.

## Scenario 2 — F = 1, a relay tampers with a validator's canary

A relay detects the validator's secret "canary" test packets and either
drops them or forwards them incorrectly, hoping to pass quality checks
while actually cutting corners elsewhere.

- Tampering is only confirmed once at least two different validators
  independently catch it.
- Once confirmed, the relay is slashed a separate honesty penalty (on top
  of, or instead of, the quality-based one), and that penalty goes entirely
  to the room's creator.

**Verdict:** same outcome as Scenario 1 — the two-validator confirmation
requirement is what makes this attack detectable rather than the relay's
own behavior being trusted.

## Scenario 3 — F = 2, primary and standby collude in the same room

Both the primary relay *and* its standby are malicious and coordinate to
degrade the call — e.g., both silently drop the same portion of traffic so
a failover to the standby wouldn't help anyway.

- Real-time call quality for the users in that room is genuinely bad — this
  is the one case where a malicious relay pair can hurt the actual
  experience, not just the on-chain accounting.
- On-chain, this doesn't help the relays: validators still measure both of
  them independently and both come back with bad quality scores, so both
  get slashed and neither gets paid.
- The room's users can still report the room as struggling, feeding into
  the room-level health check, potentially triggering a CP-authorized
  additional relay to be brought in (scaling up) or a swap.

**Verdict:** this is the relay-side attack with real user-facing impact, but
it's economically irrational for the attacker — both colluding relays lose
stake and get nothing, with no way to make the collusion pay off on-chain.

## Scenario 4 — F = 1, a relay lies about its own load

A relay reports a lower session load than it's actually carrying, hoping to
get assigned to more rooms than it can actually serve well.

- Load is self-reported (unlike quality), so this claim is taken at face
  value by the CP proposing assignments.
- Overloading itself this way degrades the relay's actual forwarding
  quality across all its rooms, which validators will independently detect
  and score badly, converging on the same slashing outcome as Scenario 1,
  just spread across more rooms.

**Verdict:** load-lying is possible but self-defeating — it just multiplies
the relay's own future slashing exposure rather than gaining anything,
since quality (not claimed load) is what actually gets paid.

## Scenario 5 — F = majority, most relays on the network are malicious

A large fraction of all registered relays are dishonest, and CPs keep
proposing them because they still meet the availability/heartbeat bar (the
protocol doesn't currently screen relays out for anything except being
offline).

- Every room assigned a malicious relay still gets it independently
  measured by that room's validators — being a majority of the *relay*
  population doesn't change how any individual room's quality gets scored.
- The practical damage here is systemic call quality degrading network-wide
  and lots of stake churn (constant slashing/re-assignment) rather than any
  single false payout, *as long as the validators watching each room are
  still honest*.
- This scenario becomes genuinely dangerous only if it's combined with
  malicious validators too — see [validator.md](validator.md) Scenario 2,
  where a room's small validator set, not the relay's honesty, is the
  actual point of failure.

**Verdict:** relay honesty alone never breaks the accounting — the system's
real dependency is on validator honesty. A relay-only attack, no matter how
large F gets, degrades experience and burns the attacker's own stake but
cannot corrupt payouts by itself.

## Scenario 6 — F = 1, task hijacking attempt

A malicious node tries to act as if it were a relay it doesn't own — for
example, sending heartbeats or claiming assignment credit for a room using
another relay's identity, hoping to intercept that relay's work or payout.

- Every state-changing action a relay can take (heartbeat, updating its own
  address, submitting anything tied to its identity) is gated to the exact
  operator that registered that relay — nobody else can act on its behalf,
  no matter what they know about it.
- There is one small, known exception: an old "report degradation" style
  entrypoint doesn't check who's calling it, but it's flagged as legacy/
  test-only in the code and doesn't affect who gets paid.

**Verdict:** not possible as a serious attack — relay identity is bound
tightly enough that hijacking someone else's assigned slot isn't a real
path in, apart from one harmless legacy leftover.

## Scenario 7 — F = 1, malicious data injection

A relay tries to inject falsified data about itself into the on-chain
record — not quality (it can't report that), but things like its own load
or address, hoping to manipulate how it gets assigned or perceived.

- Load and address are the only things a relay self-reports, and both are
  already covered by Scenario 4 (lying about load) — there's no broader
  surface for a relay to inject fabricated *quality* or *proof* data, since
  that pipeline only ever accepts validator-submitted numbers, never
  anything from the relay itself.

**Verdict:** relays simply don't have a channel to inject the kind of data
that would matter (quality/proof data) — their only injectable numbers
(load, address) are self-defeating if abused, as already covered.

## Scenario 8 — F = 1, free-riding

A relay gets itself assigned to a room and then does nothing — no real
forwarding work — hoping to still collect a share of the payout just for
having been assigned.

- Payout for a relay depends on validators actually confirming real
  traffic passed through it (measured coverage and liveness), not merely
  on having been assigned.
- A relay that does no work produces no measurable traffic, fails that
  coverage/liveness check, and earns nothing.

**Verdict:** free-riding doesn't work for relays — the payout math is tied
to proof of real work, not assignment status.

## Scenario 9 — F = many, Sybil / registration spam

An attacker registers a large number of relay identities under one
operator, either to dominate room assignments (Sybil) or just to clutter
the registry and waste CP attention (spam) — hoping cheap, repeated
registration gives them outsized influence.

- There's no cooldown or rate limit on registering a new relay identity —
  the only real cost is putting up the stake required for *each* identity.
- So this attack is possible, but its cost scales linearly with how many
  identities the attacker wants: N relay identities costs N times the
  relay stake requirement, with no bulk discount and no way around paying
  per-identity.
- Each of those Sybil relays, once assigned to real rooms, still goes
  through the same validator-measured payout process as any other relay
  (Scenarios 1-3), so simply having many identities doesn't help them get
  paid unfairly — it only lowers the *cost of acquiring* many assignment
  slots, not the cost of faking good performance once assigned.

**Verdict:** possible, but priced — an attacker pays full stake per fake
identity and still can't cheat the per-room verification once assigned.
This is a capacity/griefing concern (crowding out honest relays from
assignment slots) more than a payout-correctness concern.

## Scenario 10 — F = 1, service disruption

A malicious relay doesn't try to cheat the payout system at all — it just
tries to disrupt service: flooding on-chain calls (heartbeats, address
updates), or on the media side, refusing real connections while still
answering heartbeats so it looks "alive" without doing its job.

- On-chain spam costs the attacker gas per call, same as any other role —
  not free.
- A relay that keeps heartbeating but doesn't actually forward media
  eventually shows up as failing the coverage/liveness check at payout
  (same mechanism as Scenario 8's free-riding case) and gets nothing —
  but in the meantime, the room it was serving had degraded/no service for
  real users until a failover or CP swap kicked in.
- The direct relay-to-standby link used for live backup/handoff is a
  connection outside the chain entirely; if it's ever run without its
  optional access token turned on, a network-position attacker could
  interfere with or impersonate that specific link — this is really an
  eclipse-style attack against the data plane rather than the on-chain
  identity, covered in [network-attacks.md](network-attacks.md).

**Verdict:** the on-chain side is self-taxing and self-defeating like other
roles; the more interesting exposure is the live relay-standby link, which
is a chain-external channel with authentication that depends on
deployment configuration rather than protocol guarantee.

## Summary

| F | Behavior | Outcome |
|---|---|---|
| 1 | Drop packets | Caught by validators, slashed |
| 1 | Tamper with canary | Caught by 2 validators, slashed |
| 2 (colluding) | Primary + standby both bad | Real call quality suffers, but both still slashed, no payoff |
| 1 | Lie about load | Self-defeating, still caught via quality |
| majority | Network-wide dishonest relays | Degrades quality broadly, but payouts stay correct if validators are honest |
| 1 | Task hijacking | Blocked — identity-bound actions, no impersonation path |
| 1 | Malicious data injection | No real injection surface beyond self-defeating load/address claims |
| 1 | Free-riding | Blocked — payout requires proof of real work |
| many | Sybil / registration spam | Possible but costs full stake per fake identity; doesn't beat per-room verification |
| 1 | Service disruption | Self-taxing on-chain; real exposure is the chain-external standby link, see [network-attacks.md](network-attacks.md) |

The relay role's security rests entirely on the assumption that whichever
validators are watching a given room are honest — relays have no way to
protect or misreport themselves.
