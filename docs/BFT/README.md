# Byzantine Fault Scenarios

This folder walks through, actor by actor, what happens when some number of
nodes ("F") stop following the rules — whether from a bug, a hack, or someone
deliberately trying to cheat.

- [User](user.md) — the person joining a call (or a bot pretending to be one)
- [Relay](relay.md) — forwards the audio/video
- [Validator](validator.md) — measures relay quality, votes nodes dead
- [Control Plane (CP)](cp.md) — assigns relays/validators to rooms, issues access tokens
- [Network-level attacks](network-attacks.md) — eclipse attack, and a cross-actor
  summary of Sybil/DoS/majority-takeover patterns that show up in every file above

Background on what each actor normally does is in [`../../Governance.md`](../../Governance.md).
This folder only covers what changes when some of them go bad.

## How to read "F"

F is just "how many bad nodes of this type exist at once." The scenarios in
each file walk F up from small to large, and also change *where* the bad
nodes are positioned — spread across the whole network vs. concentrated in
one room — because those two situations behave very differently. A rule like
"needs two-thirds of the network to agree" is strong protection at the whole
network level, but a single room is often served by only 2-3 nodes of a given
type, so the same rule offers much weaker protection *inside one room*.

## Quick index of scenarios

| Actor | Scenarios |
|---|---|
| User | spam registration, fake escrow-draining room, false "room is dead" report, mass fake-load bot swarm |
| Relay | one dishonest relay caught by validators, colluding primary+standby, relay flooding with load claims, majority of network relays malicious |
| Validator | lone liar, two malicious validators controlling one room's verification, malicious minority under 1/3 network-wide, malicious majority network-wide takeover |
| CP | one dishonest CP outvoted, two of three CPs colluding on a room's access tokens, CPs deadlocking a room on purpose, all CPs malicious (no slashing safety net), CP majority takeover, service disruption |
| Network | RPC-level eclipse attack, inter-relay link spoofing, cross-actor Sybil/DoS/majority summary |
