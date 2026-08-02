from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from .. import context, infra, observer
from ..observer import metrics_infra, metrics_room, metrics_user, metrics_worker
from ..observer.metrics_writer import MetricsFileRegistry, write_metrics_entry
from .system_status import _worker_key

# Independent of DuringActionSampler's SAMPLE_INTERVAL_SECONDS=5 (which is
# action-scoped, sampling only while one action's blocking dispatch call is
# in flight) -- this sampler runs for the whole scenario run's duration on
# its own fixed timer, per the user's explicit direction.
INTERVAL_SECONDS = 60

# room/ and user/ metrics aren't naturally scoped to one infra provider (a
# room's relay could be on any provider) -- filing them under a fixed
# pseudo-provider directory keeps the on-disk layout consistent
# (data/metrics/<provider>/<run_timestamp>/...) without guessing which
# physical host "owns" a room.
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


def _capture_room_entry(room_id: str, run_timestamp: str, registry: MetricsFileRegistry) -> None:
    path = context.METRICS_ROOT / _CHAIN_PSEUDO_PROVIDER / run_timestamp / "room" / f"{room_id}.json"
    identity = metrics_room.collect_room_identity(room_id)
    quality = metrics_room.collect_room_peer_quality(room_id)
    entry = {
        "timestamp": infra.timestamp(),
        "interval_seconds": INTERVAL_SECONDS,
        **quality,
    }
    write_metrics_entry(registry, path, identity, "metrics", entry)


def _capture_user_entry(room_id: str, peer_id: str, run_timestamp: str, registry: MetricsFileRegistry) -> None:
    sample = metrics_user.collect_user_sample(room_id, peer_id)
    if sample is None:
        return
    path = context.METRICS_ROOT / _CHAIN_PSEUDO_PROVIDER / run_timestamp / "user" / f"{peer_id}.json"
    identity = {"room_id": room_id, "peer_id": peer_id}
    entry = {
        "timestamp": infra.timestamp(),
        "interval_seconds": INTERVAL_SECONDS,
        "sample": sample,
    }
    write_metrics_entry(registry, path, identity, "metrics", entry)


def capture_metrics_tick(env: str, run_timestamp: str, registry: MetricsFileRegistry) -> None:
    """One sampling tick: infra + worker + room + user metrics, written
    directly to data/metrics/<provider>/<run_timestamp>/{infra,worker,room,user}/*.json.
    Every sub-step is independently defensive (matching system_status.py's
    warn-and-continue convention) so one bad host/query never blanks the
    rest of the tick; the whole function is additionally wrapped by
    MetricsSampler._run so an unexpected failure here can never kill the
    sampler thread or the scenario run."""
    workers = _active_workers(env)

    for host_worker in _distinct_hosts(workers):
        _capture_infra_entry(host_worker, run_timestamp, registry)

    for worker in workers:
        _capture_worker_entry(worker, run_timestamp, registry)

    active_peers = observer.discover_active_peers() or {}
    for room_id, peer_ids in active_peers.items():
        _capture_room_entry(room_id, run_timestamp, registry)
        for peer_id in peer_ids:
            _capture_user_entry(room_id, peer_id, run_timestamp, registry)


class MetricsSampler:
    """Background thread that captures the data/metrics/ schema for the
    whole duration of one `vidctl scenario run`, ticking on its own fixed
    60s timer -- independent of individual actions (unlike
    cli.scenario.system_log.DuringActionSampler, which only samples while
    one action's blocking dispatch call is in flight). Fully additive to
    SystemLog: this never touches logs/ or system_log.record(), and a
    failure here can never abort the scenario run (see capture_metrics_tick's
    docstring and _run's blanket try/except below)."""

    def __init__(self, env: str) -> None:
        self._env = env
        self.run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
                capture_metrics_tick(self._env, self.run_timestamp, self._registry)
            except Exception:  # noqa: BLE001 - a sampler crash must never kill the run
                pass
