from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import infra
from ..observer import metrics_infra, metrics_worker
from .lock import read_lock

# Independent of metrics_sampler.INTERVAL_SECONDS (that module imports
# _worker_key from this one, so importing it back here to reuse its
# constant would be circular) -- only affects collect_infra_evaluation's
# rate() window and reported interval_seconds field, not correctness.
_SNAPSHOT_INTERVAL_SECONDS = 5


def _worker_key(worker: dict[str, Any]) -> str:
    service = str(worker.get("service"))
    worker_index = int(worker.get("worker_index", 1) or 1)
    return service if worker_index == 1 else f"{service}-{worker_index}"


def _instance_filter(address: str) -> str:
    """PromQL label matcher narrowing a query to one host's series, matched
    on the dashed public IP the same way cli.observer.metrics_infra does --
    the node_exporter/worker_key prefix Prometheus's `instance` label
    actually starts with isn't independently known to callers here (not
    part of topology.toml), so substring match on the IP is what works."""
    return f'instance=~".*{address.replace(".", "-")}.*"'


def _worker_snapshot(worker: dict[str, Any]) -> dict[str, Any]:
    """One worker's full detail: every topology field plus a Prometheus-
    sourced registration check, a Prometheus-sourced hardware/network
    reading, and (bot workers only) a Prometheus-sourced active-session
    count -- all through the observation system, no direct SSH/HTTP to the
    host. Each call is wrapped independently so one bad host never blanks
    the rest of this worker's data, let alone the whole snapshot."""
    host = str(worker.get("host"))
    snapshot = dict(worker)

    address = ""
    try:
        address = infra.host_address(host)
        snapshot["registry_status"] = metrics_worker.registration_status(_instance_filter(address))
    except Exception as exc:  # noqa: BLE001 - one host's probe must not sink the snapshot
        snapshot["registry_status"] = {"error": str(exc)}

    try:
        snapshot["hardware_network"] = metrics_infra.collect_infra_evaluation(address, _SNAPSHOT_INTERVAL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        snapshot["hardware_network"] = {"error": str(exc)}

    if worker.get("service") == "bot":
        try:
            application = metrics_worker.collect_worker_application("bot", _instance_filter(address))
            snapshot["bot_sessions"] = (
                application if application is not None else {"error": "no matching bot metrics"}
            )
        except Exception as exc:  # noqa: BLE001
            snapshot["bot_sessions"] = {"error": str(exc)}

    return snapshot


def _all_workers(env: str) -> list[dict[str, Any]]:
    # runtime/topology.toml is a single global file (every env's workers
    # live in the same flat "workers" array, each carrying its own "env"
    # field) -- `env` here only seeds ensure_topology()'s bookkeeping if the
    # file doesn't exist yet, it never filters what's returned. Unlike
    # cli.scenario.status._active_workers_for_env, this deliberately does
    # NOT filter by env or drop desired_state == "deleted": the system-status
    # log is meant to cover every worker the whole system knows about, not
    # just the current scenario's live set.
    topology = infra.ensure_topology(env)
    return list(topology.get("workers", []))


def _workers_snapshot(env: str) -> list[dict[str, Any]]:
    try:
        workers = _all_workers(env)
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]
    if not workers:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(workers))) as pool:
        return list(pool.map(_worker_snapshot, workers))


def _observer_host_snapshot(host: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(host)
    try:
        address = str(host.get("address") or "")
        snapshot["hardware_network"] = metrics_infra.collect_infra_evaluation(address, _SNAPSHOT_INTERVAL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        snapshot["hardware_network"] = {"error": str(exc)}
    return snapshot


def _observer_hosts_snapshot() -> list[dict[str, Any]]:
    try:
        from .. import observer

        hosts = observer.read_hosts()
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as pool:
        return list(pool.map(_observer_host_snapshot, hosts))


_RELAY_QUALITY_QUERY = '{__name__=~"dvconf_relay_peer_.*|dvconf_rtc_.*"}'


def _relay_quality_snapshot() -> list[dict[str, Any]] | dict[str, str]:
    """Client-reported (dvconf_relay_peer_*) and server-observed
    (dvconf_rtc_*) per-peer WebRTC quality gauges, fetched in a single
    Prometheus instant query via cli.observer.query() -- reuses that
    module's existing auth/observer-host-lookup/JSON-parsing rather than
    scraping each relay worker's /metrics/prom directly. Best-effort: no
    observer host running prometheus, or any query failure, becomes
    {"error": ...} rather than raising, same as every other section here."""
    try:
        from .. import observer

        result = observer.query(_RELAY_QUALITY_QUERY)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if result is None:
        return {"error": "prometheus query failed or no observer host runs prometheus"}

    samples: list[dict[str, Any]] = []
    for entry in result:
        labels = dict(entry.get("metric") or {})
        metric_name = labels.pop("__name__", "unknown")
        value = entry.get("value")
        if not isinstance(value, list) or len(value) != 2:
            continue
        try:
            numeric_value = float(value[1])
        except (TypeError, ValueError):
            continue
        samples.append({"metric": metric_name, "labels": labels, "value": numeric_value})
    return samples


def _contract_state_snapshot(env: str) -> list[dict[str, Any]] | dict[str, str]:
    try:
        from ..observer.contract_exporter import collect_contract_state

        samples = collect_contract_state(env)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return [{"metric": name, "labels": labels, "value": value} for name, labels, value in samples]


def _lock_snapshot() -> dict[str, Any] | None:
    try:
        return read_lock()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def capture_system_snapshot(env: str) -> dict[str, Any]:
    """Best-effort, maximum-detail snapshot of the whole system at this
    instant, sourced entirely through the observation system (Prometheus) --
    no direct SSH/HTTP to any host: the active scenario lock, every worker
    the system knows about across every env and desired_state (with a
    Prometheus-sourced registration check via cli.observer.metrics_worker's
    dvconf_registered gauge, a node_exporter-sourced hardware/network
    reading via cli.observer.metrics_infra, and for bot workers, a
    Prometheus-sourced active-session count), every registered
    observer/monitoring host (with the same hardware/network reading),
    client-reported and server-observed per-peer WebRTC quality metrics
    from Prometheus (dvconf_relay_peer_*/dvconf_rtc_*), and on-chain
    contract/wallet-pool state for `env`. Note the shapes differ from the
    old SSH probes': `registry_status` is a plain `bool | None` now (None
    until relay/signaling/cp-daemon/validator-daemon are redeployed with the
    gauge -- no data, not stale/wrong data), not a human-readable string;
    hardware/network has no raw `kernel` (uname) string, no per-interface IP
    addresses (node_exporter carries neither), disk is a `partitions[]` list
    of byte counts rather than a single human-readable `df` row, and
    network/CPU figures are rates/percentages rather than raw cumulative
    counters. Every section fails independently (an {"error": ...} dict in
    its place) rather than raising, matching this CLI's existing
    warn-and-continue convention (see apply.py's observer refresh/push
    helpers) -- this makes it safe to call repeatedly from a background
    sampler thread without extra guarding."""
    return {
        "captured_at": infra.timestamp(),
        "env": env,
        "lock": _lock_snapshot(),
        "workers": _workers_snapshot(env),
        "observer_hosts": _observer_hosts_snapshot(),
        "relay_quality": _relay_quality_snapshot(),
        "contract_state": _contract_state_snapshot(env),
    }
