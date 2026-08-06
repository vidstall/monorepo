# Observation Method

## 1. Overview

Evaluating the system requires more than watching a scenario run live — it
requires durable evidence that can be queried, compared across runs, and
turned into report figures after the fact. The observation subsystem is
responsible for capturing this evidence continuously across three
categories of telemetry — **metrics** (numerical time series), **logs**
(structured event records), and **distributed traces** (causally linked
request spans) — from every layer of the deployed system: the worker
network (relay, signaling, control-plane, and validator nodes), the
end-user client, and the on-chain smart contract.

The design follows the standard **three-pillars-of-observability** model
(metrics, logs, traces) common in production distributed-systems
monitoring, implemented entirely with established, self-hosted, open-source
tooling rather than a commercial SaaS observability platform. A dedicated
operator tool drives deployment, host registration, and data retrieval
against this stack, and a scenario-execution harness periodically samples
it during evaluation runs to materialize durable, per-entity time series
for later analysis.

## 2. Topology

The monitoring stack is centralized on one or more dedicated **observer
nodes**, logically separate from the worker fleet they observe but joined
to the same deployment inventory so that service discovery covers the
entire fleet regardless of which host is being deployed to at any given
time. Because the fleet is distributed across independent hosts with no
shared private network, all telemetry transport — metric scraping, log
shipment, and trace export — travels over public HTTPS, protected by
bearer-token or basic authentication. Every monitoring backend service
itself binds only to its host's local loopback interface; the sole
externally reachable entry point is an authenticated reverse-proxy layer,
supplemented by SSH tunneling for direct/debug access.

![Observation system diagram (simplified), read left to right. Column 1, data sources: Smart contract, Worker, and End-user client. Column 2, observation nodes: Metrics database (Prometheus), Log aggregation store (Loki), and Trace aggregation store (Tempo). The smart contract feeds only the metrics database; the worker and the end-user client each feed all three stores. Column 3, dashboard: the metrics database, log store, and trace store all feed the Grafana dashboard, the system's single unified query and visualization layer.](../imgen/output/observation-system.png)

<sub>Simplified for readability — see the prose above for the actual collection paths (e.g. the end-user client's telemetry is relayed through its connected worker rather than reported directly).</sub>

<sub>Diagram built from React source in [`docs/imgen/src/diagrams/observation-system.tsx`](../imgen/src/diagrams/observation-system.tsx) — run `pnpm build` in `docs/imgen/` to regenerate.</sub>

Key architectural properties:

- **Pull-based metrics, push/export-based everything else.** The metrics
  database actively polls each worker node's exposed metrics endpoint on a
  fixed interval; logs and traces instead flow outward from their source.
- **The client is never a first-class telemetry source.** It has no direct
  connection to any observability backend; all client-originated telemetry
  is relayed through the worker node it is actively connected to, which
  re-emits it into the same collection pipelines used for its own
  first-party data.
- **The ledger is sampled, not scraped.** The metrics database has no way
  to reach the blockchain directly, so on-chain state is instead
  periodically read by an operator-side process and pushed into the stack
  as a point-in-time snapshot.
- **Synthetic load agents mirror real clients.** Automated bot participants
  report the same telemetry shape a real browser client would, so
  evaluation runs at scale produce data indistinguishable in structure from
  a human-operated session.

## 3. Components & tech stack

| Layer | Technology | Role |
|---|---|---|
| Metrics collection & storage | **Prometheus** (pull-based time-series database) | Scrapes every worker node and the push gateway on a fixed interval; serves as the query backend for dashboards and ad-hoc analysis. |
| Log aggregation | **Loki** | Receives structured log streams shipped directly from each worker node's container runtime — no separate log-shipping agent process. |
| Distributed tracing | **Tempo** | Receives spans via the OpenTelemetry Protocol (OTLP); backs request-level latency and causality analysis across worker nodes. |
| Dashboarding & visualization | **Grafana** | Unified query/visualization layer over the metrics, log, and trace stores. |
| Metrics push gateway | **Prometheus Pushgateway** | Landing zone for telemetry that cannot be scraped directly — chiefly the periodic on-chain state snapshot and ad-hoc benchmarking scripts run off-fleet. |
| Ingress / access control | **Reverse proxy with token-gated routing** | The sole externally reachable path into an otherwise loopback-only backend stack. |
| Host-level metrics | **System metrics exporter** (node-level) | Standard OS-level resource metrics (CPU, memory, disk, network) per host. |
| Operator tooling | Purpose-built **command-line interface** | Registers and deploys observer infrastructure; issues ad-hoc metric queries; derives higher-level occupancy views; exports on-chain state as metrics; renders dashboard panels to static images for report figures. |
| Evaluation-run sampling | Scenario-execution harness | Periodically samples the live metrics store during an evaluation run and materializes durable, per-entity (per-room / per-user / per-worker) time-series files for later offline analysis. |
| Instrumentation library (worker side) | **Prometheus client library**, structured JSON logger, **OpenTelemetry SDK** | Exposes metrics endpoints, emits structured logs, and auto-instruments outbound/inbound network calls for tracing. |

## 4. Collecting & storing telemetry — Worker nodes

Each class of worker node (relay, signaling, control-plane, validator,
and synthetic load agent) independently emits all three telemetry pillars;
none of the collection depends on a per-host shipping agent.

- **Metrics.** Every worker node exposes a metrics endpoint in the
  standard Prometheus text-exposition format. The metrics database polls
  each node's endpoint over authenticated HTTPS on a fixed short interval
  (on the order of seconds). Host-level and TURN/STUN-relay metrics are
  scraped the same way but without application-level authentication, since
  those exporters are unauthenticated by design.
- **Logs.** Each node emits structured (JSON) log records to its standard
  output stream. Rather than running a separate log-forwarding agent, the
  container runtime's native logging driver ships those records directly
  to the log aggregation store, tagging each entry with service-, role-,
  and host-identifying labels at the transport layer.
- **Traces.** Each node bootstraps an OpenTelemetry SDK at process start,
  auto-instrumenting its network layer so inbound and outbound requests
  produce spans exported via OTLP to the trace store. Tracing is
  conditionally enabled — nodes without a configured trace-collector
  endpoint simply skip export. A request identifier is propagated across
  node boundaries and embedded into structured log records as well,
  allowing a single logical request to be followed through both the trace
  view and the log view.
- **Durable evaluation data.** During a scenario run, a sampling process
  ticks on a fixed interval, discovers which rooms and participants are
  currently active from the live metrics store, and writes one durable
  time-series record per room, per user, and per worker to disk. This step
  exists because the live metrics store only retains a bounded rolling
  window — durable per-entity files are what make post-hoc, run-over-run
  comparison possible.

## 5. Collecting & storing telemetry — Client

The end-user (browser) client is not directly instrumented against the
observability stack at all — it has no network path to the metrics, log,
or trace backends. Instead, all client telemetry is relayed through
whichever worker node the client is actively connected to at the time.

- **Logs.** The client batches its own structured log events client-side
  and periodically reports them to its connected worker node over an
  authenticated HTTP call. The worker node validates and re-emits these
  entries through its own logging pipeline, so client-originated logs
  travel the identical path — and land in the same log store, with the
  same labeling — as the worker node's own first-party logs.
- **Metrics.** The client periodically samples browser-native WebRTC
  connection statistics (packet loss, jitter, round-trip time, bitrate,
  etc.) and reports them to its connected worker node, which folds them
  into the same peer-connection metric family the worker node exposes for
  its own scraping.
- **Synthetic clients.** Automated load-testing agents deliberately
  replicate the same statistics-extraction and reporting logic a real
  client uses, so that at evaluation scale, synthetic participants are
  indistinguishable from real ones in the resulting telemetry. This
  matters for occupancy accounting specifically: one occupancy metric
  (derived from the signaling layer) only ever sees real clients, while a
  second (derived from the shared peer-connection metric family both real
  and synthetic clients populate) counts both — dashboards and evaluation
  scripts intentionally use the latter for a true occupancy figure.
- No client-side distributed tracing exists; trace export is a
  server(worker)-side-only capability.

## 6. Collecting & storing telemetry — Smart contract

On-chain state cannot be scraped the way a worker node's metrics endpoint
can — the metrics database has no native way to query a blockchain ledger.
This leg of the pipeline is therefore **pull-then-push** rather than
pull-only:

- An operator-side exporter process periodically reads on-chain state —
  registered-participant pools by role, staking/wallet balances,
  contract-publication status, and related registry metadata — and
  reshapes it into a flat set of metric samples. Each logical section of
  this read is independent and best-effort: a failure reading one part of
  chain state (e.g. an object not yet created) only drops that section's
  samples rather than aborting the whole export.
- Those samples are pushed as a batch into the metrics push gateway, which
  the metrics database then scrapes on its normal interval like any other
  target — this is what allows on-chain state to appear alongside
  worker-fleet metrics in the same dashboards despite never being scraped
  directly.
- A separate, purely **internal** event-subscription mechanism also exists
  within the worker nodes, used to let daemons react to on-chain events in
  real time (for example, triggering a graceful self-shutdown on a
  specific contract event). This mechanism is not part of the observation
  pipeline: its own diagnostic output does incidentally reach the log
  store as ordinary worker-node log noise, but it produces no metrics and
  has no dedicated dashboard presence. The periodic state exporter
  described above is the only component that deliberately turns chain
  state into observable, dashboarded data.

## 7. Performance, quality, and error characteristics

Because the observation subsystem is itself part of the evaluation
apparatus, its own performance and correctness properties bound how much
trust can be placed in the evaluation results it produces. This section
states those properties explicitly, in the interest of experimental
transparency, rather than treating the observation system as a perfectly
faithful oracle of ground truth.

### 7.1 Performance

- **Sampling granularity.** Metrics are collected on a fixed short polling
  interval (on the order of seconds), not continuously — any event whose
  effect on a gauge or counter both begins and ends within one interval is
  invisible to the metrics pillar, though it may still surface in logs or
  traces. This bounds the temporal resolution of every metrics-derived
  evaluation figure to that interval.
- **Visibility latency.** There is an inherent pipeline delay between an
  event occurring on a worker node and that event becoming queryable in
  the observation stack: one polling interval for metrics, plus network
  and batching delay for logs (log records are buffered and shipped in
  batches rather than one-by-one, trading a small delay for materially
  lower transport overhead) and for trace export. None of the telemetry
  pillars are synchronous with the event they describe.
- **Collection overhead.** Instrumentation on the worker side (metrics
  exposition, structured logging, trace auto-instrumentation) adds a small
  constant CPU/memory/network overhead to every worker node, and polling
  traffic itself consumes a small, fixed amount of bandwidth per node per
  interval. This overhead is not separately isolated from the workload
  under evaluation, so very tight latency/throughput measurements should
  account for it as a (small, roughly constant) source of noise rather
  than assume a zero-overhead observer.
- **On-chain sampling cost.** Reading ledger state is comparatively
  expensive and slow relative to scraping a worker node, so it is sampled
  at a coarser cadence than worker-fleet metrics. On-chain-derived figures
  therefore have materially lower temporal resolution than worker-fleet
  ones and should not be used to reason about sub-interval chain
  dynamics.

### 7.2 Quality and completeness

- **Best-effort delivery, not exactly-once.** Log shipment and metrics
  push both use bounded retry with a fixed retry budget rather than
  guaranteed delivery — a sustained transport failure (e.g. a saturated or
  unreachable observation backend) can result in silently dropped log
  lines or a missed push cycle, with no downstream signal that data is
  missing. Absence of data in the observation stack is therefore not
  reliable evidence of absence of the underlying event.
- **Partial-failure isolation in chain sampling.** The on-chain state
  exporter reads several independent sections of ledger/registry state per
  cycle; a failure reading any one section (for example, an object that
  has not yet been created) drops only that section for that cycle rather
  than the whole sample. This keeps the exporter resilient but means a
  given on-chain metric series can have gaps that do not correspond to any
  real-world discontinuity.
- **Definitional mismatches between equivalent-looking metrics.** More
  than one metric can plausibly answer the same evaluative question and
  disagree by design because they are derived from different vantage
  points. The clearest example: a signaling-layer-derived occupancy count
  and a relay-layer-derived occupancy count differ because synthetic load
  agents bypass the signaling layer entirely — only the relay-derived
  figure is a true occupancy count. Using the wrong one silently
  undercounts. Any use of this data for evaluation should identify, for
  each figure, which vantage point it was derived from.
- **Staleness of pulled (non-streamed) fields.** Fields that are only
  refreshed on specific triggering actions rather than continuously
  streamed (for example, a wallet balance refreshed only at the moment a
  balance-affecting action last occurred) are only as current as their
  last trigger, not as current as the query time — treat these as
  "last known," not "live."
- **Retention bounds.** Each telemetry pillar retains data for a bounded
  window (durable per-entity extraction during a scenario run exists
  specifically to escape this bound for metrics; trace data in particular
  is retained for a fixed number of days). Any analysis performed after a
  pillar's retention window has elapsed can only draw on whatever was
  separately materialized to durable storage, not on the live stores
  directly.

### 7.3 Known limitations and error sources

- **No formal correctness guarantee.** The observation system is built
  from standard, widely used open-source components in their default
  operating modes; none of the three pillars offers a formal delivery or
  consistency guarantee (e.g. no exactly-once semantics, no strict
  ordering guarantee across pillars). It is designed for operational and
  evaluative visibility, not as a source of cryptographically or formally
  verifiable evidence.
- **No independent verification of client-reported telemetry.** Because
  client metrics and logs are self-reported by the client and merely
  relayed (not independently verified) by the worker node that receives
  them, a compromised or misbehaving client could in principle report
  fabricated telemetry. This is an accepted trust boundary for evaluation
  purposes (synthetic load agents are trusted by construction; real
  clients are assumed non-adversarial during evaluation runs) rather than
  a gap that is defended against.
- **Coarse time granularity on the ledger side.** The smart-contract
  layer's own on-chain sense of time is significantly coarser than the
  observation stack's — on-chain time can advance in units far larger than
  the real-world durations the evaluation cares about. Any evaluation
  metric that mixes an on-chain timestamp with wall-clock-derived
  timestamps from the rest of the stack should treat the on-chain
  component as low-resolution.
- **Authentication, not confidentiality, is the security boundary.**
  Telemetry transport between worker nodes and the observer node(s)
  travels over the public network (there is no private network between
  hosts) and is protected by bearer- or basic-authentication credentials
  plus transport encryption, not by network isolation. This is an
  accepted operational tradeoff for a research/evaluation deployment, not
  a production-hardened security posture.
- **Single point of aggregation.** All three telemetry pillars are
  aggregated on a small number of observer nodes with no described
  high-availability or failover configuration for the observation stack
  itself; an outage of an observer node during a scenario run degrades or
  interrupts data collection for the remainder of that run.

## 8. Dashboards & consumption

A small set of purpose-built dashboards sits on top of this stack, each
scoped to one evaluation concern: fleet-wide overview, host infrastructure
health, room/session activity, peer-connection quality, per-worker-role
detail, and on-chain/contract activity. For reproducible report figures,
the operator tooling can programmatically resolve a dashboard panel's live
template variables against the metrics database and render each panel to a
static image — turning a live, interactive dashboard into a fixed artifact
suitable for inclusion in written evaluation results.

See `metrics.md` for the full catalog of what each dashboard measures.
