# Control Plane (CP) — malicious node scenarios

CPs decide who gets assigned to a room and who gets a valid access token to
join it, and they're the only role that can never be slashed — misbehaving
CPs lose reputation, not stake. That combination (real power, no financial
penalty) makes CP the role where dishonesty is cheapest to attempt.

## Scenario 1 — F = 1, a lone dishonest CP is outvoted

One CP proposes a bad room assignment (e.g., proposing relays it secretly
controls, or ones with poor real reputations) hoping it gets adopted.

- Assignment requires roughly two-thirds of active CPs to submit the exact
  same proposal before it wins.
- If the honest CP majority proposes something different (and matching each
  other), the malicious CP's proposal simply never reaches quorum and is
  ignored.
- The honest proposal wins, and the CP that first submitted it gets a
  reputation bonus — the dishonest CP gets nothing and loses standing.

**Verdict:** a lone dishonest CP is powerless against an honest majority —
same shape as the lone validator liar case.

## Scenario 2 — F = 2 out of a 3-CP access-token quorum

A room's access tokens are gated by a default quorum of 2-of-3 CPs. Two of
the three CPs assigned to sign off on tokens for a specific room are
malicious and collude.

- Two signatures is exactly the quorum requirement, so these two alone can
  authorize tokens for that room — letting unauthorized people join, or
  refusing to authorize legitimate participants — without needing the third
  (honest) CP's cooperation at all.
- Because token validity checks only verify that *enough* real, currently-
  registered CPs signed the *same* thing — not which specific ones, and not
  whether the room's honest CP was even asked — this passes all on-chain
  checks cleanly.
- This mirrors the F=2-validators-per-room problem: the network-wide
  two-thirds CP rule (used for role promotions and room assignment) never
  gets invoked for token issuance, because token quorum is a separate,
  smaller, room-local number.

**Verdict:** the same structural weak point as validators — a small, fixed
local quorum (2 signatures) is much easier to compromise than the
network-wide honest-majority assumption suggests, and there's no stake at
risk for the two colluding CPs even if this is later discovered.

## Scenario 3 — F small minority, deliberately deadlocking a room

A handful of malicious CPs don't try to win the assignment vote — they just
refuse to agree with anyone, submitting proposals that never match what the
honest majority is proposing, hoping to stall the room forever.

- Since the malicious CPs are a minority, the honest majority can still
  reach two-thirds among themselves and the room proceeds normally.
- Even in the extreme case where CPs genuinely can't converge (e.g., a
  three-way split), the room's creator can force a decision after a short
  cooldown, and the chain scores all submitted proposals itself and picks
  the best one — sidestepping the stuck CPs entirely.

**Verdict:** griefing-by-deadlock is explicitly handled by the deadlock
fallback; a malicious minority can add delay (up to the cooldown) but can't
permanently block a room.

## Scenario 4 — F = all currently-assigned CPs are malicious, no slashing safety net

Every CP a given room ever interacts with — including the one it's
ultimately assigned — turns out to be malicious, and this goes undetected
for a while.

- The malicious CP takes its full share of that room's payment and can
  freely issue tokens or manipulate TURN credentials for the room, since it
  needs no other CP's agreement for actions where it's already the sole
  assigned CP.
- Its reputation should fall once bad behavior surfaces (e.g., through user
  complaints or other CPs noticing bad proposals over time), which hurts it
  in future assignment competitions — but nothing claws back what it
  already earned, because **CP cannot be slashed** in the current design.
- There is no automatic detection mechanism described for this case
  comparable to the validator quality-measurement pipeline — CP behavior
  is checked mainly through the two-thirds *assignment* vote and the 2-of-3
  *token* quorum, both of which this scenario assumes are already
  compromised for this room.

**Verdict:** this is the system's most exposed corner. Every other role
(user, relay, validator) has an economic penalty baked into the protocol
when caught misbehaving; CP does not. A compromised CP's damage is capped
only by reputation loss and by whatever oversight happens off-chain, not by
any on-chain slashing mechanism.

## Scenario 5 — F = 1, task hijacking attempt

A malicious node tries to act as a CP it doesn't control — sending
heartbeats, or otherwise acting under another CP's identity — hoping to
intercept that CP's assigned room and its payout.

- Every CP self-reported action (heartbeat and similar) is locked to the
  specific registered identity that holds that CP's credentials; nobody
  else can act in its place.

**Verdict:** blocked — same identity-binding protection as relay and
validator. CP task hijacking isn't a real path in.

## Scenario 6 — F = 1, free-riding (confirmed, not just theoretical)

A CP gets itself assigned to a room and then does the bare minimum — or
nothing at all — after that, hoping to still collect its full share of the
room's payment just for being the assigned CP.

- Unlike relay and validator payouts, which both depend on independently
  verified proof of work, CP payout is conditioned on nothing more than
  "a CP is assigned to this room." There is no on-chain check of whether
  that CP actually did any of its normal jobs afterward — issuing tokens,
  proposing scaling, sweeping expired state, or anything else.
- Combined with Scenario 4 (no slashing), this means a CP can go completely
  idle right after winning assignment and still be paid in full, with the
  only possible consequence being a reputation hit if someone notices.

**Verdict:** confirmed, not hypothetical — this is the clearest free-riding
opportunity of any role in the system, since CP is the only role paid on
assignment alone rather than on proof of continued work.

## Scenario 7 — F = many, Sybil / registration spam

An attacker registers many CP identities under one operator, hoping to
win a disproportionate share of room assignments or dominate the
network-wide voting thresholds.

- Like the other roles, CP registration has no cooldown — the only cost is
  stake per identity. But CP stake is the *largest* of the three staked
  roles, and it grows further as more CPs join the network.
- That growing-stake design means each additional Sybil CP identity costs
  more than the last, making this the most expensive role in the system to
  Sybil at any meaningful scale — a self-limiting effect the other two
  roles don't have.
- A side effect worth noting: an attacker who registers many CP identities
  purely to spam (not to seriously compete for assignments) still drives
  the stake requirement up for every legitimate CP that registers after
  them, since the requirement scales with total CP count regardless of
  whether those CPs are honest or not.

**Verdict:** technically possible but the most expensive Sybil target in
the system, and self-limiting by design — though pure registration spam
(without ever competing for real work) still has a griefing side effect on
the barrier to entry for honest future CPs.

## Scenario 8 — F ≥ 2/3, network-wide CP majority takeover

A large majority of all active CPs are malicious — the CP-equivalent of
the validator majority scenario, made possible despite the growing stake
cost if the attacker is well-funded enough.

- With two-thirds of active CPs controlled, the malicious majority can
  push through any room assignment it wants network-wide, not just in one
  room's token quorum — every new room gets malicious relays/validators
  proposed, and every proposal the malicious majority agrees on wins
  automatically.
- They also control the outcome of every role-promotion vote (which users
  become relays/validators) network-wide, since that vote uses the same
  two-thirds CP threshold.
- Since CP cannot be slashed at all, there is no way to claw back damage
  even after this is discovered — the only response available is an admin
  pausing the system or adjusting parameters, not any automatic on-chain
  penalty.

**Verdict:** total control if reached, same shape as the validator majority
case — except recovery is worse here, because there's no slashing to even
partially punish the attacker once caught, and CP's growing stake cost is
the *only* thing standing between the network and this outcome, not any
procedural defense.

## Scenario 9 — F = 1, service disruption

A malicious CP doesn't try to steal money or forge tokens — it just stops
doing its job for rooms assigned to it (stalls proposals, never issues
tokens, never sweeps expired rooms it's responsible for), or floods the
chain with heartbeats/proposals to waste other nodes' attention.

- A CP that goes silent on a room it's assigned to blocks that room from
  progressing (no tokens issued means nobody can actually join), but
  doesn't corrupt any on-chain state — it's an availability problem for
  that specific room, not a safety problem.
- Since CP payout only requires being assigned (Scenario 6), this kind of
  disruption is actually compatible with the CP still getting paid — it's
  the free-riding scenario and the service-disruption scenario overlapping.
- On-chain spam (excess heartbeats/proposals) costs gas per call, same
  self-taxing effect as other roles.

**Verdict:** a silent, assigned CP is simultaneously a free-riding attack
and a service-disruption attack — and because CP has no slashing, doing
nothing is not just undetected but actively profitable, which is worse
than the equivalent scenario for relay or validator.

## Summary

| F | Behavior | Outcome |
|---|---|---|
| 1 | Bad assignment proposal | Outvoted by honest 2/3 majority |
| 2 of 3 (room token quorum) | Collude to sign tokens | Full control of that room's access — network-wide rule doesn't apply here |
| small minority | Deliberate deadlock | Delayed by cooldown, then chain auto-resolves |
| all (one room) | Fully compromised CP(s) | No slashing exists — only reputation loss, no funds clawed back |
| 1 | Task hijacking | Blocked — identity-bound actions |
| 1 | Free-riding | **Confirmed real** — payout requires assignment only, no proof of continued work |
| many | Sybil / registration spam | Most expensive role to Sybil (growing stake), but still raises entry cost for honest CPs |
| ≥2/3 (network-wide) | Full CP majority | Total compromise, and unlike validators there's no slashing to even partially punish it |
| 1 | Service disruption | Blocks its own assigned rooms but still gets paid — overlaps with free-riding |

CP mirrors the validator role's "small local quorum vs. strong network-wide
threshold" gap, and adds two unique weaknesses on top: it's the one role
where getting caught costs nothing financially, and the one role that gets
paid for showing up rather than for proven work.
