# Network-level attacks

Some attacks don't belong to one actor — they target *how nodes learn
what's true* rather than what any single node does once it knows. This
file covers those, plus a cross-actor summary of the attacks that do
appear per-role but follow the same shape everywhere.

## Eclipse attack

An eclipse attack isolates one node's view of the world and feeds it false
information, without needing to compromise its stake, identity, or the
actual network-wide honest majority at all — it just controls what that
one node *thinks* is true.

### How this system is exposed

Every relay, validator, and CP daemon learns everything — who's
registered, which rooms exist, who's assigned where — by reading it off
the blockchain through one configured RPC connection. There's no
peer-to-peer gossip between DVConf nodes carrying this information
independently; the blockchain read *is* the only source of truth each
node has.

That's normally a strength (a real blockchain read is much harder to fake
than gossip from a handful of peers), but it comes with a specific weak
point: each node trusts exactly **one** RPC endpoint, with no second
opinion and no cross-checking against another provider. If an attacker can
control what that one connection actually returns — by hijacking DNS,
intercepting the route, or tricking an operator into pointing at a
malicious "custom" endpoint — they can feed that single node a completely
fabricated view of the chain: fake room assignments, fake registrations,
a fake "you were never actually ejected" or "you were never actually
assigned this room," without ever touching the real blockchain or needing
any stake at all.

### Scenario 1 — F = 1 node, RPC-level eclipse

One relay's connection to its configured RPC endpoint is hijacked. The
attacker's fake endpoint tells this one relay it's still assigned to
rooms it was actually removed from, or hides room assignments it should
be responding to.

- Every *other* node in the network still sees the real chain state, so
  the eclipsed relay's own actions (heartbeats, submissions) are still
  checked against real chain rules by everyone else — it can't forge
  anything the rest of the network would accept.
- The practical damage is availability, not safety: the eclipsed node
  behaves incorrectly (serving the wrong rooms, missing real ones), which
  looks to the rest of the network like a node going stale/dead, and gets
  handled by the normal failover/liveness process (see the room-level and
  network-wide liveness checks described in `../../Governance.md`).

**Verdict:** an eclipse attack against a single node degrades that node's
own behavior but can't corrupt the shared ledger, since every write the
eclipsed node makes is still checked by everyone else against the real
chain. The real cost is that recovery depends on the honest network's
liveness detection noticing and failing the node over — there's no
built-in defense (like a second RPC source) that lets the node detect the
eclipse itself.

### Scenario 2 — F = 1, chain-external link spoofing (a narrower, related attack)

Separate from RPC eclipsing: the direct connection a standby relay opens
to its primary (used for live backup/handoff, entirely outside the chain)
resolves its target address from the chain once, but the live session
itself only requires an access token if one has been explicitly
configured. If that token is left unset in a deployment, anything that can
intercept or spoof that specific connection can pretend to be the primary
or the standby.

- This doesn't touch anyone's stake, identity registration, or payout —
  it's purely a live-call disruption vector (a fake standby link, or a
  hijacked handoff).
- Unlike the RPC eclipse above, this is a configuration gap, not a
  structural one — turning the access token on for that link closes it.

**Verdict:** a real but avoidable gap, and worth flagging separately from
the RPC eclipse because it's a different channel (direct node-to-node
media-plane link) with a different, simpler fix (always set the token).

### Mitigation notes (not currently implemented)

- Querying more than one independent RPC endpoint and requiring them to
  agree would close the single-point-of-trust gap described in Scenario 1.
- Always setting the inter-relay access token in every deployment closes
  Scenario 2 outright; this isn't a protocol change, just an operational
  one.

## Cross-actor summary

These four already have a dedicated, detailed scenario in each actor's own
file — this table is just a quick index across all of them, since the
underlying mechanism is the same shape no matter which role is attacking.

| Attack | User | Relay | Validator | CP |
|---|---|---|---|---|
| Sybil / registration spam | [free, but toothless](user.md) | [priced by stake, no cooldown](relay.md) | [cheapest role to Sybil](validator.md) | [most expensive, self-limiting](cp.md) |
| Service disruption / DoS | [costs real money at scale](user.md) | [self-taxing on-chain; real gap in the standby link, see above](relay.md) | [self-taxing on-chain](validator.md) | [free-riding disguised as disruption — still gets paid](cp.md) |
| 1/3 threshold | n/a | n/a | [blocks false ejections *and* can stall true ones (liveness)](validator.md) | n/a |
| ≥2/3 majority ("51%"-style) takeover | n/a | [degrades quality broadly, payouts still correct if validators honest](relay.md) | [total compromise — the system's baseline trust assumption](validator.md) | [total compromise, and no slashing to punish it after](cp.md) |

The pattern worth noting: **validator and CP are the only two roles where
a majority-level attack means total compromise**, because they're the only
two roles whose network-wide honest-supermajority assumption *is* the
security model, not just one layer of it. Relay and user never reach that
level of leverage no matter how large F gets, because neither role gets a
vote that binds the rest of the network.
