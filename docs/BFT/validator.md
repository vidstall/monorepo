# Validator — malicious node scenarios

Validators are the network's source of truth for relay quality and node
liveness, which makes them the most sensitive role to compromise. Two very
different thresholds apply depending on scope: a strong two-thirds
supermajority rule at the *whole network* level, versus a much weaker
fixed count (just 2) at the level of a *single room*. The scenarios below
show why that gap matters.

## Scenario 1 — F = 1, a lone lying validator

One validator, watching a room alongside at least one honest validator,
submits inflated (or deflated) quality numbers for a relay it doesn't like
or is colluding with.

- Payout splits the validator share by *accuracy* — whoever's numbers are
  closest to what other validators reported gets a bigger cut, not an
  equal one.
- The lone liar's numbers stand out against the honest majority in that
  room, so it earns less, not more, and the relay's score is still set
  correctly by the honest report(s).

**Verdict:** a single dishonest validator, outnumbered by honest ones in the
same room, is self-defeating — it loses income and changes nothing.

## Scenario 2 — F = 2, malicious validators control one room's verification

A room happens to have exactly two validators assigned, and both are
malicious. Since a relay only needs reports from **two different
validators** to count as "verified" at all, these two fully control that
room's outcome.

- They can jointly certify a genuinely bad relay as high quality (so it
  gets paid and avoids slashing), or jointly certify a genuinely good relay
  as bad (forcing an unfair slash) — either way, their two reports "agree,"
  so the accuracy-based payout split doesn't flag them as outliers, because
  there's no honest report in that room to compare against.
- They can also falsely confirm a canary-tampering accusation against an
  honest relay, since that also only requires two matching validator
  reports.
- This is possible **regardless of what the network-wide two-thirds rule
  says**, because that rule governs *ejecting a node from the whole
  registry*, not *verifying a single room's measurements* — the two never
  interact.

**Verdict:** this is the sharpest weak point in the whole system. The
network-wide honest-majority assumption does not protect any individual
room that happens to draw a small, unlucky validator assignment. If F=2 can
land on the same room, that room's economic outcome is entirely theirs to
decide.

## Scenario 3 — F just under one-third of active validators, network-wide

Just under a third of all currently active validators are malicious and try
to get an honest relay, validator, or CP ejected from the registry by
accusing it of being dead.

- Ejection requires roughly two-thirds of active validators to agree.
- With F under a third, even if every single malicious validator votes yes
  and every honest one votes correctly, the malicious side cannot reach the
  threshold on its own.
- The honest majority's "no" (or non-participation) keeps the false
  accusation from ever passing.

**Verdict:** the network-wide ejection vote works exactly as intended here —
this is the scenario the two-thirds threshold was designed to survive.

## Scenario 4 — F at or above two-thirds, network-wide takeover

A large majority of all active validators are malicious — for example, the
attacker has staked enough sock-puppet validator identities to dominate the
active set.

- The malicious majority can now vote any honest relay, validator, or CP
  out of the registry at will, returning that node's stake (ejection isn't
  framed as a punishment, so the target doesn't even lose funds — it's just
  removed) and taking over its position in the network.
- They also dominate quality/canary reporting in essentially every room,
  so relay slashing and payouts become whatever the malicious majority
  decides across the whole network, not just one unlucky room.
- Because reaching this requires actually staking as *that many* validator
  identities, the attacker's cost scales with the stake requirement times
  roughly two-thirds of the active validator count — this is the
  system's assumed worst case that no on-chain rule can defend against; the
  defense is economic (make it too expensive to acquire that much stake),
  not procedural.

**Verdict:** total network compromise if reached, by design — every
liveness and quality mechanism assumes an honest supermajority of
validators. This scenario isn't "handled," it's the trust assumption the
whole system rests on.

## Scenario 5 — F = 1, task hijacking attempt

A malicious node tries to submit a measurement or heartbeat pretending to
be a validator that was actually assigned to a room, hoping to intercept
that validator's role and payout.

- Submitting a measurement requires proving control of both the
  validator's normal identity *and* its separate per-call session identity,
  with both signatures checked and matched against who was actually
  assigned to that room.
- Heartbeats and other self-reported actions are likewise locked to the
  specific registered identity.

**Verdict:** blocked — a validator's dual-identity signing requirement
makes impersonating an assigned validator harder than for any other role,
not easier.

## Scenario 6 — F = 1 (or a colluding few), malicious data injection

A validator submits a fabricated quality measurement for a relay it never
actually watched — inventing plausible-looking numbers instead of doing
the real work of probing latency and packet loss.

- The chain checks that the submission is properly signed and that the
  validator was genuinely assigned to that room — but it does **not**
  check whether the numbers reflect anything that actually happened. A
  measurement is only ever compared against *other validators' submitted
  numbers*, never against independent ground truth.
- If the fabricated numbers land close to what honest validators
  independently report, the accuracy-based payout treats the fabrication
  as if it were a real measurement, and it gets paid the same as genuine
  work.
- This is the same mechanism behind Scenario 2: a lone fabricator close to
  an honest crowd just gets lucky and unnoticed; a colluding pair or more
  in a small room can make their shared fabrication *be* the "accurate"
  answer, since there's no honest reference to compare against locally.

**Verdict:** this is a real gap — fabricating data is easier than lying
about it in a way that stands out, because nothing on-chain confirms a
measurement reflects an actual probe. Detection depends entirely on enough
independent honest validators being in the same room to make a fabrication
stick out statistically.

## Scenario 7 — F = 1, free-riding

A validator skips the real work of probing relays entirely and just
copies or guesses numbers close to what it expects the "average" report
will look like, hoping to get paid without doing any actual measurement.

- Since payout doesn't verify that a real probe happened — only that the
  submitted numbers are plausible relative to peers — a validator that
  never measures anything, but guesses well, is paid exactly like one that
  did the real work.
- This only fails if the guess is far enough from what honest validators
  actually measured, which is not guaranteed, especially for a stable or
  predictable relay.

**Verdict:** possible in principle — this is the same underlying gap as
Scenario 6, viewed as "skip the work" rather than "fake the work." The
system currently has no way to distinguish a lazy validator that guesses
well from one that measured properly.

## Scenario 8 — F = many, Sybil / registration spam

An attacker registers many validator identities under one operator to
gain outsized influence over network-wide votes and room assignments, or
just to clutter the active validator set.

- Validator registration has no cooldown or rate limit — the only cost is
  putting up the (smallest of all three staked roles') stake requirement
  per identity.
- Because validator stake is the cheapest of the three staked roles, this
  is the least expensive role in the system to Sybil at scale — an
  attacker reaches meaningful influence over network-wide thresholds (the
  1/3 or 2/3 marks from Scenarios 3-4) for less total stake than doing the
  same thing with relay or CP identities.

**Verdict:** possible and comparatively cheap — validator being the
lowest-stake role means the network-wide honest-supermajority assumption
(Scenario 3/4) is the one most exposed to being bought, not just achieved
through organic node growth.

## Scenario 9 — F ≈ 1/3 (network-wide), liveness-stall attack

Rather than trying to force a *false* outcome, roughly a third of active
validators just refuse to vote on anything — ejection votes, in
particular — hoping to permanently deny quorum instead of winning one.

- This is a different goal from Scenario 3: Scenario 3 asks "can F just
  under a third force a *wrong* result" (no); this asks "can that same F
  *block a correct result forever* by withholding, rather than opposing."
- Since ejection needs roughly two-thirds of *active* validators to agree,
  a third that simply never participates can, in the worst case, make that
  threshold permanently unreachable for votes it wants to stall — a
  genuinely dead or malicious node that should be ejected might just never
  get ejected if the abstaining third is large enough relative to who else
  is actively voting.
- This is a liveness problem, not a safety one: no false state gets
  written on-chain, but a needed cleanup action can be stuck indefinitely.

**Verdict:** the same one-third boundary that protects *safety* (Scenario
3) is also the network's *liveness* pressure point — it defends against
being forced into a wrong answer, but doesn't guarantee a right answer
gets through if enough validators simply stop participating.

## Scenario 10 — F = 1, service disruption (heartbeat/traffic flood)

A malicious validator doesn't try to corrupt any data — it just floods the
network with excessive heartbeats, redundant measurement submissions, or
other high-frequency on-chain calls, hoping to slow things down or run up
costs for everyone else.

- Every on-chain call costs the caller gas, so this attack costs the
  attacker money proportional to how much noise they generate — it's not
  free spam.
- Duplicate measurement submissions for something already reported are
  rejected outright rather than processed twice, limiting how much a flood
  of *measurement* calls specifically can actually achieve.

**Verdict:** possible but self-taxing — the attacker pays for every wasted
call, and duplicate submissions are rejected rather than compounding, so
this mostly just burns the attacker's own funds rather than degrading the
network.

## Summary

| F (scope) | Behavior | Outcome |
|---|---|---|
| 1 (in a room with honest peers) | Lies about quality | Outvoted by accuracy scoring, earns less |
| 2 (concentrated in one small room) | Jointly certify anything | Full control of that room's payout/slashing — network-wide rule doesn't apply here |
| <1/3 (network-wide) | Try to force ejections | Blocked, two-thirds threshold holds |
| ≥2/3 (network-wide) | Full validator majority | Total compromise — the system's baseline trust assumption is broken |
| 1 | Task hijacking | Blocked — dual-signature identity binding |
| 1 or colluding few | Malicious data injection | Real gap — fabricated data indistinguishable from real if close to peer numbers |
| 1 | Free-riding | Real gap — no on-chain proof that a measurement came from an actual probe |
| many | Sybil / registration spam | Possible and cheapest of the three staked roles to scale up |
| ≈1/3 (network-wide) | Liveness stall (abstain, don't oppose) | Can block correct ejections indefinitely — same 1/3 boundary, opposite failure mode |
| 1 | Service disruption / flood | Self-taxing — costs the attacker gas, duplicates rejected |

The takeaway: validator security is strong at the network level but only as
strong as "2 out of however many validators are assigned to your specific
room" at the local level — a much softer number that doesn't scale with the
size of the honest majority elsewhere in the network. And unlike relays,
validators are never checked against independent ground truth — only
against each other — so fabrication and free-riding are the same
underlying weakness wearing two names.
