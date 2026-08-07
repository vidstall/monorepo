# Health Reporting and Slashing

Not every "something's wrong" signal has the same consequences. This
document separates the system's advisory self-reporting (a worker flagging
its own trouble) from the three genuinely distinct ways a worker can lose
its stake.

## Self-degradation reporting (advisory only)

Every worker daemon type watches its own health signals (error rates,
buffered-message depth, and similar) and, when its overall status changes,
reports that on-chain: level 0 (healthy), 1 (degraded), or 2 (unhealthy).
This report is **debounced** — a worker won't spam the chain with repeated
reports at the same level, only when the level actually changes, and even
then not more often than roughly once a minute.

Crucially, **this alone never touches anyone's stake.** It's a signal other
parties can act on (a relay watching for its own self-targeted degradation
event to trigger a graceful self-shutdown, for instance, or an operator's
dashboard), not a punishment. Signaling and cp-daemon are "report-only" in
this sense — nothing in the system currently slashes them directly based
on this signal.

## The three slashing paths

Slashing — actually deducting from a worker's staked coin — happens
through three separate, independent mechanisms, each with a different bar
and a different consequence:

1. **Liveness ejection (non-punitive).** If enough active validators — two
   thirds of them — vote that a specific worker looks dead, that worker is
   ejected from its registry. This isn't a punishment: the presumption is
   the worker genuinely went offline, not that it misbehaved, so its full
   stake is returned rather than cut.
2. **Canary-divergence slash (punitive).** If two or more independent
   validators produce cryptographic proof that a relay tampered with or
   dropped media it was supposed to forward faithfully, that relay's stake
   is cut by a fixed percentage, and the slashed amount goes to the room's
   creator. This is detailed in [`canary-audit.md`](canary-audit.md) — it's
   the only slashing path built entirely on validators independently
   verifying a relay's actual behavior, not just its uptime.
3. **Escrow slash-payout (punitive).** Separately, when a room's escrow
   gets settled at session close, a pre-recorded slash amount (based on the
   relay's measured quality across the session) can be deducted from its
   stake and redistributed proportionally to the room creator and other
   relays that performed better. This ties into
   [`rewards-and-escrow.md`](rewards-and-escrow.md) — it's a
   quality-of-service mechanism, not a fraud-detection one.

## Why only relays face punitive slashing

Relays are the only worker role that actually **custodies live media** —
they're in a position to tamper with or drop someone's audio/video in a way
that's directly harmful and directly attributable. Signaling nodes and
control-plane daemons don't touch media at all, so there's no equivalent
"tampered with the call" failure mode for them to be punitively slashed
over; a report-only degradation signal plus the shared, non-punitive
liveness-ejection path (which applies to every role, not just relays) is
what backs them instead.

## Diagram

![Sequence diagram contrasting the four paths: a worker's own advisory degradation report changing no stake, a two-thirds validator vote ejecting a dead worker with a full stake refund, two validators' canary-divergence proof punitively slashing a relay, and an escrow-settlement slash payout redistributing to other relays and the room creator.](../imgen/output/proto-health-and-slashing.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-health-and-slashing.tsx`](../imgen/src/diagrams/proto-health-and-slashing.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Reference

| Path | Punitive? | Trigger | Applies to |
|---|---|---|---|
| Self-degradation report | No — advisory only | worker's own health signals | all roles |
| Liveness ejection | No — full stake returned | 2/3 active-validator vote | all roles |
| Canary-divergence slash | Yes | 2+ validators' cryptographic proof | relay only |
| Escrow slash-payout | Yes | quality shortfall at session close | relay only |

## Security notes

- **Self-reporting can't be used to punish a worker** — a worker being
  honest about its own trouble is never the thing that costs it money,
  which keeps the incentive to self-report intact.
- **Punitive slashing always requires either multi-party agreement (canary)
  or a settled, auditable quality record (escrow)** — never a single
  party's unilateral claim.
- **Liveness ejection intentionally can't be used to punish** — it exists
  purely to keep the registries accurate when a worker genuinely
  disappears, with the full stake returned so there's no incentive to
  weaponize it against a healthy competitor.
