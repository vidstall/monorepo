# Quorum Claims

Several places in this system need multiple independent parties to agree
on the same fact before it's trusted enough to act on — a relay is really
misbehaving ([`canary-audit.md`](canary-audit.md)), or a control-plane node
should co-sign a room admission token
([`cap-token.md`](cap-token.md)). This protocol is the shared pattern both
of those use to collect that agreement.

## Why this protocol exists

If one validator's or one control-plane node's word were enough to trigger
a slash or issue a credential, a single compromised or buggy node could
cause real damage. Requiring several *independent* parties to each reach
the same conclusion on their own — not by trusting each other, but by each
checking for themselves — makes that much harder to fake. This protocol is
the coordination point where those independent conclusions get gathered up
before anyone submits anything on-chain.

## Message flow

1. **Independent observation.** Each party (a validator running a canary
   audit, or a control-plane node processing an admission request) reaches
   its own conclusion entirely on its own — it never takes another party's
   word for what happened.
2. **Post evidence for a specific claim.** A party posts its own evidence
   to a shared board, identified by a claim key (which room, which relay,
   which specific event this is about). Critically, a party is only
   allowed to post evidence for a claim if its own independent observation
   actually matches what it's posting — it's structurally impossible to
   just vouch for someone else's claim on trust.
3. **Accumulate.** The board collects one entry per distinct party for
   that claim, ignoring duplicate posts from the same party (posting twice
   is harmless, not double-counted).
4. **Quorum reached.** Once enough distinct parties (currently two) have
   posted matching evidence for the same claim, it's ready to submit.
5. **Assemble and submit.** Any party that notices the claim has reached
   quorum can read the accumulated evidence back, bundle it into a single
   proof, and submit that proof on-chain. It doesn't have to be the same
   party that posted first.
6. **Cleanup.** Claims that never reach quorum within a reasonable window
   are automatically discarded, so the board doesn't accumulate stale,
   abandoned entries forever.

This is deliberately a **pull-based rendezvous, not a direct message
between parties** — nobody addresses evidence "to" a specific other
validator or control-plane node. This matters for
[`canary-audit.md`](canary-audit.md) in particular: if validators had to
message each other directly to coordinate, that traffic pattern itself
could leak which relay is currently under audit.

## Diagram

![Sequence diagram of the quorum-claims protocol: two validators each independently observe the same divergence and post their own evidence to a shared claim board, which reaches quorum once two distinct signers agree, after which either party assembles and submits the combined proof.](../imgen/output/proto-quorum-claims.png)

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/proto-quorum-claims.tsx`](../imgen/src/diagrams/proto-quorum-claims.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

## Message reference

| Direction | Route | Carries |
|---|---|---|
| Party to Board | `POST /claims` | the claim key plus this party's own signed evidence |
| Party to Board | `GET /claims/open` | list of claims currently accumulating evidence |
| Party to Board | `POST /claims/get` | look up one specific claim by key |
| Party to Board | `POST /claims/mark-submitted` | mark a claim as already handled, once its proof has gone on-chain |
| Party to Board | `POST /claims/gc` | trigger cleanup of stale, never-quorumed claims |

## Security notes

- **A strict allow-list, not a blacklist, governs what fields are
  accepted.** A claim or a piece of evidence can only ever contain the
  specific fields this protocol expects — anything extra a poster tries to
  attach (its own identity, unrelated metadata) is rejected outright before
  it's ever stored, closing off any sneaky side-channel through this board.
- **Access requires a shared secret token**, with an optional stronger mode
  that adds mutual TLS — where instead of trusting any certificate signed by
  a recognized authority, each side checks the other's certificate against
  one specific, pre-approved fingerprint. That means trust here doesn't
  depend on any outside certificate authority at all — only on fingerprints
  the operators have explicitly agreed to in advance.
- **Anti-fabrication is enforced at posting time, not verification time** —
  a party can only add evidence for something it genuinely, independently
  observed, so quorum reflects real independent agreement rather than one
  party's claim being echoed by others.
