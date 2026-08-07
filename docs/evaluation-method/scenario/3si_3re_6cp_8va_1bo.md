# Scenario: `3si_3re_6cp_8va_1bo`

## 1. Overview

This scenario is `scenario/example/akamai.toml` — a 4-host `devnet` fleet
entirely on Akamai — run together with one **local** bot session started
separately on the operator's own machine. The filename follows a compact
`N<role>` shorthand for the fleet's worker composition, one segment per
worker `service` value plus the bot: **3** signaling, **3** relay, **6**
cp-daemon, **8** validator-daemon, **1** bot. Node-role definitions
(signaling, relay, cp-daemon, validator-daemon, bot) are covered in
[`docs/topology/worker.md`](../../topology/worker.md); this document only
describes how many of each this specific scenario runs, on which hosts, and
why.

## 2. Topology

![Scenario topology diagram, read left to right then top to bottom. Three identical host boxes (Host 001, 002, 003) each contain five chips: signaling, relay, cp-daemon #1, cp-daemon #2, validator-daemon. Below the middle host, a fourth host box (Host 004) contains five validator-daemon chips only. To its right, a separate orange-bordered box labeled Local bot represents a process running on the operator's own machine, outside akamai.toml, connected to Host 002 by an orange line labeled "creates room, joins via signaling to relay (client protocol)".](../../imgen/output/scenario-3si-3re-6cp-8va-1bo.png)

<sub>The bot's line is drawn to Host 002 only for legibility — it actually
reaches whichever signaling/relay pair the chain assigns its room to, not a
specific host.</sub>

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/scenario-3si-3re-6cp-8va-1bo.tsx`](../../imgen/src/diagrams/scenario-3si-3re-6cp-8va-1bo.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

| Host | Provider / size | Services |
|---|---|---|
| 001 | akamai · `g6-standard-4` | 1× signaling, 1× relay, 2× cp-daemon, 1× validator-daemon |
| 002 | akamai · `g6-standard-4` | 1× signaling, 1× relay, 2× cp-daemon, 1× validator-daemon |
| 003 | akamai · `g6-standard-4` | 1× signaling, 1× relay, 2× cp-daemon, 1× validator-daemon |
| 004 | akamai · `g6-standard-4` | 5× validator-daemon |
| *(operator machine)* | local, not IaC-managed | 1× bot |

Hosts 001–003 are identical: each colocates one full slice of the
client-facing/control roles (signaling, relay, 2× cp-daemon) plus one
validator-daemon. Host 004 exists purely to add validator capacity.

**Why 8 validators, not 3.** Liveness-voting quorum requires 2/3 of all
*registered-active* validators on-chain, live or not. At the time this
scenario was defined, 7 validators were registered active, but only the 3
running on hosts 001–003 (one each) were actually alive — the other 4 were
stale leftovers from a previously destroyed deployment. With only 3 live
voters, quorum (5 of 7) could never be reached, not even to eject those 4
dead entries. Host 004's 5 extra validator-daemon replicas bring the live
count to 8, making quorum reachable again.

## 3. Bot

The bot is **not** declared anywhere in `akamai.toml` — there is no
`[[actions]]` block invoking it, and it is not one of the file's
`[[workers]]`. It is a separate, non-IaC-managed process
(`services/worker/apps/bot`) started on the operator's own machine via
`vidctl utils bot start <id>`. On start, it registers on-chain, creates a
new room against this scenario's deployed contract, and streams a looping
synthetic video/audio track into it as a headless participant. The operator
then joins that same room by opening the session's returned `joinUrl` in a
browser, from wherever the operator's machine happens to be.

See [`services/worker/apps/bot/README.md`](../../../services/worker/apps/bot/README.md)
for the bot's full HTTP control API and session lifecycle — not repeated
here.

## 4. Providers

Every `[[workers]]` entry in this scenario is `akamai`/`g6-standard-4`; the
Docker image registry is reused from the existing DigitalOcean-hosted one
(`scenario/example/digitalocean.toml`) rather than publishing a second,
separately-billed registry. The scenario also updates an Alibaba
OSS-hosted frontend site, but that's CDN/static-hosting only — it doesn't
run any worker or bot process and is out of scope for this document.
