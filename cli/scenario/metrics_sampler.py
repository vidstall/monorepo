from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime, timezone
from typing import Any

from .. import context, infra, observer
from ..observer import metrics_infra, metrics_room, metrics_user, metrics_worker
from ..observer.metrics_writer import MetricsFileRegistry, write_metrics_entry
from .system_status import _worker_key

# Independent of DuringActionSampler's SAMPLE_INTERVAL_SECONDS (action-scoped,
# sampling only while one action's blocking dispatch call is in flight) --
# this sampler runs for the whole scenario run's duration on its own fixed
# timer, per the user's explicit direction. Same numeric value as that one
# is coincidental, not a shared constant -- keep them independently settable.
INTERVAL_SECONDS = 5

# room/ and user/ metrics aren't naturally scoped to one infra provider (a
# room's relay could be on any provider). Historically filed under a fixed
# "chain" pseudo-provider directory for that reason -- but that split a
# single scenario run's output across two top-level folders (its real
# provider(s) for infra/worker, "chain" for room/user) even once
# infra/worker/room/user all shared the same <run_timestamp>. Now MetricsSampler
# is constructed with the SAME top-level key SystemLog's run_dir uses
# (scenario_name / the scenario file's stem, see run.py) so one run's
# entire logs/<key>/<run_timestamp>/ tree -- actions, run.json, infra,
# worker, room, user -- lands in one folder. Kept as the fallback default
# for the rare direct construction (e.g. tests) that doesn't pass one in.
_CHAIN_PSEUDO_PROVIDER = "chain"


def _active_workers(env: str) -> list[dict[str, Any]]:
    """Unlike system_status._all_workers (deliberately "everything the
    system has ever known about", for a durable log), a run-scoped metrics
    sampler should only cover this scenario's live workers: filtered to
    `env` and excluding desired_state == "deleted"."""
    topology = infra.ensure_topology(env)
    workers = topology.get("workers", [])
    return [w for w in workers if w.get("env") == env and w.get("desired_state") != "deleted"]


def _distinct_hosts(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per distinct (provider, host) -- multiple worker roles can
    share one droplet, and infra/ files are per-host, not per-worker."""
    seen: set[tuple[str, str]] = set()
    hosts: list[dict[str, Any]] = []
    for worker in workers:
        key = (str(worker.get("provider")), str(worker.get("host")))
        if key in seen:
            continue
        seen.add(key)
        hosts.append(worker)
    return hosts


def _capture_infra_entry(host_worker: dict[str, Any], run_timestamp: str, registry: MetricsFileRegistry) -> None:
    provider = str(host_worker.get("provider") or "unknown")
    host = str(host_worker.get("host") or "unknown")
    instance_name = f"{provider}-{host}"
    path = context.METRICS_ROOT / provider / run_timestamp / "infra" / f"{instance_name}.json"

    try:
        public_ip = str(infra.host_address(host))
        entry = metrics_infra.collect_infra_evaluation(public_ip, INTERVAL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - one host's probe must not sink the tick
        entry = {
            "timestamp": infra.timestamp(),
            "interval_seconds": INTERVAL_SECONDS,
            "error": str(exc),
        }

    identity = {
        "provider": provider,
        "instance_name": instance_name,
        "host": host,
        "region": host_worker.get("region"),
        "zone": host_worker.get("zone"),
    }
    write_metrics_entry(registry, path, identity, "evaluation", entry)


def _capture_worker_entry(worker: dict[str, Any], run_timestamp: str, registry: MetricsFileRegistry) -> None:
    provider = str(worker.get("provider") or "unknown")
    service = str(worker.get("service") or "unknown")
    instance = _worker_key(worker)
    path = context.METRICS_ROOT / provider / run_timestamp / "worker" / f"{instance}.json"

    identity = {
        "process_key": instance,
        "host": worker.get("host"),
        "service": service,
        "provider": provider,
        "env": worker.get("env"),
        "backend": worker.get("backend"),
        "worker_index": worker.get("worker_index"),
        "region": worker.get("region"),
        "zone": worker.get("zone"),
    }
    entry = {
        "timestamp": infra.timestamp(),
        "interval_seconds": INTERVAL_SECONDS,
        "application": metrics_worker.collect_worker_application(service),
        # cpu/memory/io/network/limits/health (Node/V8 process internals):
        # no live source confirmed this pass (would need /proc/<pid> +
        # Node-internal instrumentation, neither exposed by any exporter
        # today) -- omitted, see plan's "Known gaps".
    }
    write_metrics_entry(registry, path, identity, "logging", entry)


def _capture_room_entry(room_id: str, run_timestamp: str, room_provider_key: str, registry: MetricsFileRegistry) -> None:
    path = context.METRICS_ROOT / room_provider_key / run_timestamp / "room" / f"{room_id}.json"
    identity = metrics_room.collect_room_identity(room_id)
    quality = metrics_room.collect_room_peer_quality(room_id)
    entry = {
        "timestamp": infra.timestamp(),
        "interval_seconds": INTERVAL_SECONDS,
        **quality,
    }
    write_metrics_entry(registry, path, identity, "metrics", entry)


def _capture_user_entry(
    room_id: str, peer_id: str, run_timestamp: str, room_provider_key: str, registry: MetricsFileRegistry
) -> None:
    sample = metrics_user.collect_user_sample(room_id, peer_id)
    if sample is None:
        return
    path = context.METRICS_ROOT / room_provider_key / run_timestamp / "user" / f"{peer_id}.json"
    identity = {"room_id": room_id, "peer_id": peer_id}
    entry = {
        "timestamp": infra.timestamp(),
        "interval_seconds": INTERVAL_SECONDS,
        "sample": sample,
    }
    write_metrics_entry(registry, path, identity, "metrics", entry)


def capture_metrics_tick(
    env: str, run_timestamp: str, room_provider_key: str, registry: MetricsFileRegistry
) -> None:
    """One sampling tick: infra + worker + room + user metrics, written
    directly to logs/<key>/<run_timestamp>/{infra,worker,room,user}/*.json --
    infra/worker keyed by each worker's own real provider, room/user keyed
    by `room_provider_key` (see MetricsSampler's docstring on why that's
    NOT necessarily a real provider name). Every sub-step is independently
    defensive (matching system_status.py's warn-and-continue convention) so
    one bad host/query never blanks the rest of the tick; the whole
    function is additionally wrapped by MetricsSampler._run so an
    unexpected failure here can never kill the sampler thread or the
    scenario run."""
    workers = _active_workers(env)

    for host_worker in _distinct_hosts(workers):
        _capture_infra_entry(host_worker, run_timestamp, registry)

    for worker in workers:
        _capture_worker_entry(worker, run_timestamp, registry)

    active_peers = observer.discover_active_peers() or {}
    for room_id, peer_ids in active_peers.items():
        _capture_room_entry(room_id, run_timestamp, room_provider_key, registry)
        for peer_id in peer_ids:
            _capture_user_entry(room_id, peer_id, run_timestamp, room_provider_key, registry)


class MetricsSampler:
    """Background thread that captures the logs/ metrics schema for the
    whole duration of one `vidctl scenario run`, ticking on its own fixed
    fixed INTERVAL_SECONDS timer -- independent of individual actions (unlike
    cli.scenario.system_log.DuringActionSampler, which only samples while
    one action's blocking dispatch call is in flight). Fully additive to
    SystemLog: this never touches logs/ or system_log.record(), and a
    failure here can never abort the scenario run (see capture_metrics_tick's
    docstring and _run's blanket try/except below)."""

    def __init__(
        self, env: str, run_timestamp: str | None = None, room_provider_key: str = _CHAIN_PSEUDO_PROVIDER
    ) -> None:
        self._env = env
        # Normally passed in by run() -- generated ONCE, before either
        # SystemLog or MetricsSampler is constructed, so this run's
        # metrics land under the same <run_timestamp> as its event log
        # (logs/<scenario_name>/<run_timestamp>/ vs
        # logs/<provider>/<run_timestamp>/) instead of each independently
        # stamping "now" a few dozen ms apart. run_timestamp represents
        # when `scenario run` was INVOKED, not when this sampler's first
        # tick actually fires (that's always run_timestamp + INTERVAL_SECONDS,
        # see _run() below).
        self.run_timestamp = run_timestamp if run_timestamp is not None else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # room_provider_key: normally also passed in by run() as the SAME
        # scenario_name SystemLog uses, so room/ and user/ land in the same
        # logs/<key>/<run_timestamp>/ folder as infra/worker/actions/run.json
        # instead of a separate "chain" top-level folder -- see module
        # docstring on _CHAIN_PSEUDO_PROVIDER for why room/user were ever
        # split out in the first place.
        self._room_provider_key = room_provider_key
        self._registry = MetricsFileRegistry()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(INTERVAL_SECONDS):
            try:
                capture_metrics_tick(self._env, self.run_timestamp, self._room_provider_key, self._registry)
            except Exception:  # noqa: BLE001 - a sampler crash must never kill the run
                # Previously a silent `pass` -- a tick failing for ANY reason
                # (a transient Prometheus auth hiccup, a query timeout, ...)
                # left that tick's room/user/infra/worker files simply
                # missing with zero trace afterward, indistinguishable from
                # "nothing was active this tick". Print (not raise) so the
                # scenario run still can't be aborted by a sampler bug, but
                # a gap in logs/<provider>/<run_timestamp>/ is now
                # explainable instead of a silent mystery.
                print(
                    f"Warning: metrics sampler tick failed for run {self.run_timestamp!r}:\n"
                    f"{traceback.format_exc()}",
                    file=sys.stderr,
                )
