# Rewards and Escrow

This is the economic protocol that ties a call's payment to how well it was
actually served. A room creator locks payment up front; independent
validators measure how well each relay carried the call; and once the room
closes, that payment is split among the relays based on those measurements
— or reduced, if a relay was caught misbehaving.

See also: [`client-chain-transactions.md`](client-chain-transactions.md)
for the `create_escrow` call itself, [`canary-audit.md`](canary-audit.md)
for how a relay gets caught tampering with media in the first place, and
[`health-and-slashing.md`](health-and-slashing.md) for how this escrow
slash fits alongside the system's other two ways a worker can lose stake.

## Why this protocol exists

Nobody wants to pay for a call that was dropped, laggy, or tampered with.
Rather than trusting a relay to self-report how well it did, the system has
independent third parties (validators) measure it, and only pays out based
on their measurements — with a real, on-chain penalty if a relay is proven
to have cheated.

## Message flow

1. **`create_escrow`** — when a room is created, its creator locks a sum of
   money into it, held by the contract in a shared escrow object tied to
   that room. This is the only step the **client** itself performs in this
   whole protocol — see
   [`client-chain-transactions.md`](client-chain-transactions.md) for the
   exact call. The contract checks the creator is really the room's
   creator, the room hasn't started yet, and the amount isn't zero.
2. **The call happens** — media flows directly between client and relay
   (see [`call-setup-relay.md`](call-setup-relay.md)); nothing here touches
   the chain.
3. **Validators measure the relay(s)** — while (or after) the call runs,
   each validator assigned to the room independently records how the relay
   performed: packets forwarded, bytes transferred, how many distinct
   people were in the call, how long it ran, average latency, packet loss,
   and jitter.
4. **`submit_session_proof`** — each validator submits its measurement to
   the contract, one submission per validator per relay. Each submission is
   signed **twice**: once with the validator's normal, permanently
   registered identity, and once with a one-time key generated just for
   that submission. The registered-identity signature is what lets the
   chain confirm a real, staked validator made the claim (not an outsider);
   the one-time key is what actually gets attached to the readable record.
   The effect is that anyone can verify a genuine validator backed this
   measurement, without it becoming a permanent public record of exactly
   which relays that specific validator has been watching over time.
5. **`close_room`** — once the call is over, the room is closed (see
   [`room-lifecycle.md`](room-lifecycle.md) for the full room lifecycle).
6. **`distribute_rewards`** — after enough validators have submitted their
   measurements, rewards are calculated from the **median** of all
   submissions for a given relay (so one outlier — too generous or too
   harsh — can't skew the payout), multiplied by a quality factor, and paid
   out of the room's escrow.
7. **`pay_slash`** — if a relay was separately proven to have tampered with
   or dropped media (via the canary-audit process described in
   [`canary-audit.md`](canary-audit.md) and
   [`health-and-slashing.md`](health-and-slashing.md)), its share is
   reduced instead, and the difference is redistributed — partly back to
   the room's creator, partly to the other, well-behaved relays in the
   room.
8. **Dashboard events** — the client never submits proofs or triggers a
   payout itself. Its only remaining involvement is passive: it can watch
   `RewardsDistributed`, `RelaySlashed`, and `RelaySlashRedistributed`
   events on-chain to show a call's outcome in a dashboard, purely for
   display.

## Diagram

![Sequence diagram of the rewards and escrow protocol: client creates escrow, the call happens over the relay, validators independently measure relay performance and submit dual-signed session proofs, the room closes, rewards are distributed from the median of proofs, and a slash payout happens instead if a relay was proven to misbehave.](../imgen/output/proto-rewards-and-escrow.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-rewards-and-escrow.tsx`](../imgen/src/diagrams/proto-rewards-and-escrow.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Call reference

| Caller | Entry call | Carries | Effect |
|---|---|---|---|
| Client | `create_escrow` | room id, payment | Locks payment into a shared escrow tied to the room. |
| Validator | `submit_session_proof` | room id, relay id, performance metrics, dual signature | Records one validator's independent measurement of one relay. |
| Anyone (crank-style) | `close_room` | room id | Ends the room's active lifecycle. |
| cp-daemon / crank | `distribute_rewards` | room id | Pays relays from escrow based on the median of submitted proofs. |
| cp-daemon / crank | `pay_slash` | room id, relay id | Reduces a proven-bad relay's payout and redistributes the difference. |

## Security notes

- **The client only ever funds the escrow** — it has no ability to submit a
  fake proof or trigger its own payout; those steps require validator or
  control-plane involvement.
- **Median aggregation, not average** — a single dishonest or broken
  validator submission can't unfairly move the payout on its own; it takes
  the same kind of independent multi-party agreement used elsewhere in
  this system (see [`canary-audit.md`](canary-audit.md) and
  [`quorum-claims.md`](quorum-claims.md)) to actually penalize a relay.
- **Dual-key signing protects validator privacy** — verifying a claim came
  from a real validator doesn't require exposing a durable, linkable
  identity for every claim that validator has ever made.
- **Slashing is redistributive, not just punitive** — money taken from a
  misbehaving relay doesn't disappear; it goes back to the people the
  misbehavior actually harmed (the room's creator and the other relays that
  did their job correctly).
