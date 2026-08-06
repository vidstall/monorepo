# Metrics Catalog

This document catalogs what is actually measured by the four evaluation
dashboards, grouped by the same four vantage points the dashboards
themselves use: individual participant, room, worker node, and host
infrastructure. It complements `observation.md`, which explains *how*
telemetry is collected and transported — this document explains *what*
is collected and *why* it matters for evaluating the system.

The first three vantage points (User, Room, Worker) together build the
case for **experience quality**: is a participant's call actually good,
room by room and person by person. The Worker section carries a second,
distinct purpose worth stating up front: because of a hard budget
constraint, it was not possible to give every worker process its own
dedicated machine — multiple worker roles share the same instance. The
Worker and Infrastructure sections exist specifically to demonstrate that
this sharing does not starve any individual process or saturate the
underlying host; they are the resource-headroom evidence behind the
quality numbers, not just more quality numbers themselves.

## 1. User metrics

Scope: one row of data per (room, participant) pair, filterable down to a
single room or a single participant. Includes a way to distinguish a real
browser participant from a synthetic, automated load-testing participant,
since both populate the same metric family.

**Live connection quality** — sampled continuously while a participant is
connected:
- Round-trip latency, jitter, and packet loss.
- Packet reordering (a jitter-buffer-delay-based signal, tracked
  separately from packet loss because the two behave differently and
  shouldn't share one chart axis).
- Upload and download bitrate.
- Video resolution and frame rate.
- Media encode and decode latency.
- Freeze and pause event counts.

**Connection lifecycle** — one-time or occasional events rather than a
continuous stream:
- Initial connection setup time.
- Reconnect time, when a participant's connection drops and recovers.
- ICE negotiation success rate (whether the peer-to-peer/relayed
  transport was established successfully at all).

**Session-level aggregates** — running average, minimum, and maximum of
the core live-quality signals (latency, jitter, packet loss, bitrate),
computed over the participant's entire session rather than the current
instant. This distinguishes a brief quality dip from a sustained problem,
which the live values alone cannot.

**Synthetic-participant internals** — additional, load-agent-only detail
not available for real browser participants:
- A breakdown of how long each phase of joining a call took
  (registration, room creation, transport connection, media start),
  including percentile timing.
- Session start and error rates, and how many synthetic sessions are
  currently active.
- The load agent's own process resource usage (CPU, memory) — so its
  footprint can be distinguished from the system under test.
- Health of the agent's internal synthetic-media pipeline (dropped
  frames, buffer underruns, encoder/transcoder restarts) — this exists so
  a quality dip seen in synthetic-participant data can be attributed to
  the load generator itself rather than mistaken for a real system
  problem.

## 2. Room metrics

Scope: one row of data per active room — the same underlying quality
signals as User metrics, but aggregated (average/minimum/maximum) across
every participant currently in that room. Where User metrics answers "how
good is this one person's call," Room metrics answers "how good is this
call, overall."

**Occupancy and lifecycle**:
- Number of currently active rooms, cluster-wide.
- Participants per room — deliberately built to count synthetic and real
  participants alike (an earlier, signaling-layer-only version of this
  count silently missed synthetic participants, since they connect at a
  lower layer and never touch signaling).
- Distribution of how long rooms stay open before closing.

**Aggregated quality**: room-wide average/minimum/maximum for every
live-quality category listed under User metrics — latency, jitter, packet
loss, packet reordering, bitrate, resolution, frame rate, encode/decode
latency, freeze/pause counts, connection setup time, reconnect time, and
ICE success rate.

## 3. Worker metrics

Scope: per worker node, broken out by role (media-relay, signaling,
control-plane, validator) and, for signals common to every role, also
combined across all roles. As noted above, this section's central purpose
is proving that co-locating multiple worker roles per instance — a cost
necessity, not the original design — does not leave any individual
worker process resource-starved.

**Process resource headroom** — tracked per role and in aggregate:
- CPU utilization.
- Resident memory usage.
- Event-loop lag: a more direct saturation signal for a JavaScript
  runtime than CPU percentage alone, since it captures blocking or
  backpressure that a CPU average can mask entirely.

**Blockchain-interaction performance** — common to every worker role,
since every role independently talks to the ledger:
- Time spent waiting for an on-chain role assignment to be confirmed,
  tracked with a success/timeout split rather than just a latency
  percentile — a flat percentile alone can look identical whether
  everything is succeeding slowly or half of it is silently timing out.
- Transaction latency, broken down by the type of on-chain call made.
- Transaction retry rate (a rising retry rate is a leading indicator of
  outright transaction failures).
- Chain event-polling duration and processing throughput.

**Role-specific protocol health**:
- *Control-plane role*: latency from discovering a work item to casting
  its corresponding vote.
- *Validator role*: the validator's own independent reachability probe of
  each media-relay node (round-trip time, jitter, loss) — an
  independently-verified canary signal, distinct from a relay's
  self-reported numbers — plus cross-validator consensus signals: how
  many validators are covering the same probe target, whether quorum was
  reached, and how often validators' independent observations diverge.
- *Media-relay role*: server-observed media stream round-trip time and
  jitter, active session/room counts, total data forwarded, count of
  internal media-engine worker crashes, media-engine worker resource
  usage, and failover event rate/duration broken down by phase (this is
  the same failover mechanism described in the room-lifecycle discussion
  elsewhere in this evaluation).

## 4. Infrastructure

Scope: per physical/virtual host, using standard operating-system-level
resource metrics — the layer directly beneath Worker metrics. Where
Worker metrics report what each process believes about its own resource
usage, Infrastructure metrics report the host's own view, which is what
actually settles whether shared hosting is overloading a machine.

**Reachability**: whether each host's metrics exporter is currently
reporting at all (tracked separately for the TURN/STUN relay host, which
sits outside the regular fleet and is provisioned independently).

**CPU and queueing**:
- CPU busy percentage.
- Load average (1/5/15-minute) — a queueing/saturation signal that can be
  elevated even when CPU percentage alone looks fine, since it reflects
  work waiting, not just work executing.

**Memory**: available memory versus total memory.

**Storage**: available disk space, disk space used (as a percentage), and
disk read/write throughput.

**Network**: throughput, plus error and drop rates tracked as their own
signal — a healthy-looking throughput graph can still hide a rising error
or drop rate underneath it.

**Kernel/system limits** — resources that can be exhausted well before
CPU or memory show any stress, which matters here because
WebRTC/TCP-heavy roles are exactly the kind of workload that hits these
limits first:
- Open file descriptor and TCP socket counts.
- Connection-tracking table usage against its configured limit.

**Reliability signals**:
- Host uptime — surfaces a silent VM reboot, a failure mode nothing else
  on this dashboard would otherwise catch.
- Linux pressure-stall information for CPU, memory, and I/O — a more
  direct "how much time is actually spent waiting" signal than CPU
  percentage or load average alone.
- Out-of-memory kill events.
