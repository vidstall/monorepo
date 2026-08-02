from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

# See metrics_worker.py's top-of-file comment: import the query function
# directly from its submodule to sidestep __init__.py's package-level
# shadowing of the `query` attribute.
from .query import query

# Standard node_exporter metric names (stable across versions, unlike this
# system's custom dvconf_* app metrics) -- scraped fleet-wide as job
# xaisen-node-exporter, one target per host (see
# IaC/ansible/roles/docker_service/templates/prometheus.yml.j2:97-105).
# Plain instant gauges: no rate() needed.
_GAUGE_NAMES = (
    "node_load1|node_load5|node_load15|"
    "node_memory_MemTotal_bytes|node_memory_MemAvailable_bytes|node_memory_MemFree_bytes|"
    "node_memory_Buffers_bytes|node_memory_Cached_bytes|"
    "node_memory_SwapTotal_bytes|node_memory_SwapFree_bytes|"
    "node_filesystem_size_bytes|node_filesystem_avail_bytes|node_filesystem_free_bytes|"
    "node_filefd_allocated|node_filefd_maximum|"
    "node_boot_time_seconds|"
    "node_nf_conntrack_entries|node_nf_conntrack_entries_limit|"
    "node_netstat_Tcp_CurrEstab"
)

# Monotonic counters: need rate() to become a per-second/percentage figure.
# One query per name, NOT a single combined `{__name__=~"a|b"}` regex --
# rate() (like every PromQL function) drops the __name__ label from its
# output, and several of these metrics carry no other labels besides
# instance/job (e.g. node_vmstat_oom_kill, node_pressure_*). Combined under
# one rate() call, those collapse to an identical labelset once __name__ is
# gone and Prometheus rejects the whole query with "vector cannot contain
# metrics with the same labelset" (HTTP 422) -- confirmed against a real
# deployment. Splitting into one rate() per name sidesteps this entirely.
_RATE_NAMES = (
    "node_cpu_seconds_total",
    "node_network_receive_bytes_total",
    "node_network_transmit_bytes_total",
    "node_network_receive_errs_total",
    "node_network_transmit_errs_total",
    "node_network_receive_drop_total",
    "node_network_transmit_drop_total",
    "node_disk_read_bytes_total",
    "node_disk_written_bytes_total",
    "node_vmstat_oom_kill",
    "node_pressure_cpu_waiting_seconds_total",
    "node_pressure_memory_waiting_seconds_total",
    "node_pressure_memory_stalled_seconds_total",
    "node_pressure_io_waiting_seconds_total",
)

_EXCLUDED_FSTYPES = {"tmpfs", "overlay", "squashfs"}


def _raw_series(result: list[dict] | None) -> list[tuple[str, dict[str, str], float]]:
    """[(metric_name, labels, value), ...] from a raw Prometheus vector,
    keeping every distinct label set -- unlike metrics_worker.py's
    _reshape(), infra metrics are inherently multi-series per name (one
    per core, per interface, per mountpoint), so collapsing to one value
    per metric name would lose data."""
    series: list[tuple[str, dict[str, str], float]] = []
    if not result:
        return series
    for entry in result:
        labels = dict(entry.get("metric") or {})
        name = labels.pop("__name__", "")
        value = entry.get("value")
        if not name or not isinstance(value, list) or len(value) != 2:
            continue
        try:
            numeric = float(value[1])
        except (TypeError, ValueError):
            continue
        series.append((name, labels, numeric))
    return series


def _rate_series(instance_filter: str, metric_name: str) -> tuple[list[tuple[str, dict[str, str], float]], bool]:
    """One metric's rate() series, tagged with `metric_name` directly rather
    than parsed from a `__name__` label -- rate() strips __name__ from its
    output, so there's nothing to parse. Returns (series, query_failed)."""
    result = query(f'rate({metric_name}{{{instance_filter}}}[1m])')
    if result is None:
        return [], True
    series: list[tuple[str, dict[str, str], float]] = []
    for entry in result:
        labels = dict(entry.get("metric") or {})
        labels.pop("__name__", None)
        value = entry.get("value")
        if not isinstance(value, list) or len(value) != 2:
            continue
        try:
            numeric = float(value[1])
        except (TypeError, ValueError):
            continue
        series.append((metric_name, labels, numeric))
    return series, False


def _scalar(series: list[tuple[str, dict[str, str], float]]) -> dict[str, float]:
    """Metric-name -> value for series with no other distinguishing label
    (load average, memory totals, boot time, ...)."""
    return {name: value for name, labels, value in series if not labels}


def _cpu_usage_percent(rate_series: list[tuple[str, dict[str, str], float]]) -> float | None:
    """100 * (1 - average idle-mode rate across cores) -- the standard
    node_exporter CPU usage-percent derivation."""
    idle_rates = [
        value
        for name, labels, value in rate_series
        if name == "node_cpu_seconds_total" and labels.get("mode") == "idle"
    ]
    if not idle_rates:
        return None
    return round(100.0 * (1.0 - (sum(idle_rates) / len(idle_rates))), 2)


def _memory_block(gauges: dict[str, float]) -> dict[str, Any]:
    total = gauges.get("node_memory_MemTotal_bytes")
    available = gauges.get("node_memory_MemAvailable_bytes")
    free = gauges.get("node_memory_MemFree_bytes")
    used = (total - free) if total is not None and free is not None else None
    return {
        "total_bytes": total,
        "used_bytes": used,
        "used_percent": round(100.0 * used / total, 2) if used is not None and total else None,
        "free_bytes": free,
        "available_bytes": available,
        "available_percent": round(100.0 * available / total, 2) if available is not None and total else None,
        "cached_bytes": gauges.get("node_memory_Cached_bytes"),
        "buffered_bytes": gauges.get("node_memory_Buffers_bytes"),
        "swap_total_bytes": gauges.get("node_memory_SwapTotal_bytes"),
        "swap_free_bytes": gauges.get("node_memory_SwapFree_bytes"),
    }


def _disk_partitions(gauge_series: list[tuple[str, dict[str, str], float]]) -> list[dict[str, Any]]:
    by_mount: dict[str, dict[str, float]] = {}
    for name, labels, value in gauge_series:
        if name not in (
            "node_filesystem_size_bytes",
            "node_filesystem_avail_bytes",
            "node_filesystem_free_bytes",
        ):
            continue
        mount = labels.get("mountpoint")
        if not mount or labels.get("fstype") in _EXCLUDED_FSTYPES:
            continue
        by_mount.setdefault(mount, {})[name] = value

    partitions = []
    for mount, fields in sorted(by_mount.items()):
        size = fields.get("node_filesystem_size_bytes")
        avail = fields.get("node_filesystem_avail_bytes")
        free = fields.get("node_filesystem_free_bytes")
        used = (size - free) if size is not None and free is not None else None
        partitions.append(
            {
                "mount_point": mount,
                "total_bytes": size,
                "used_bytes": used,
                "used_percent": round(100.0 * used / size, 2) if used is not None and size else None,
                "free_bytes": avail,
            }
        )
    return partitions


def _network_interfaces(rate_series: list[tuple[str, dict[str, str], float]]) -> list[dict[str, Any]]:
    by_iface: dict[str, dict[str, float]] = {}
    for name, labels, value in rate_series:
        iface = labels.get("device")
        if not iface or iface == "lo":
            continue
        by_iface.setdefault(iface, {})[name] = value

    interfaces = []
    for iface, fields in sorted(by_iface.items()):
        interfaces.append(
            {
                "name": iface,
                "rx_bytes_per_sec": fields.get("node_network_receive_bytes_total"),
                "tx_bytes_per_sec": fields.get("node_network_transmit_bytes_total"),
                "rx_errors_per_sec": fields.get("node_network_receive_errs_total"),
                "tx_errors_per_sec": fields.get("node_network_transmit_errs_total"),
                "rx_dropped_per_sec": fields.get("node_network_receive_drop_total"),
                "tx_dropped_per_sec": fields.get("node_network_transmit_drop_total"),
                # link_utilization_percent/peak_bandwidth: node_exporter
                # doesn't reliably expose interface speed on this fleet
                # (unverified) -- omitted rather than guessed.
            }
        )
    return interfaces


def _psi_percent(rates: dict[str, float], name: str) -> float | None:
    value = rates.get(name)
    return round(value * 100.0, 2) if value is not None else None


def collect_infra_evaluation(public_ip: str, interval_seconds: int) -> dict[str, Any]:
    """One infra/<provider>-<instance>.json `evaluation[]` entry, sourced
    entirely from node_exporter via Prometheus (job xaisen-node-exporter) --
    no SSH. Matches `instance=~".*<dashed-ip>.*"` on the host's dashed
    public IP rather than the exact scrape target string, since the
    node_exporter worker_key prefix is auto-injected at deploy time and
    not independently known to the caller (not part of topology.toml).
    Fields with no confirmed node_exporter source on this fleet (exact
    per-interface link_utilization_percent/peak bandwidth, gateway_probe)
    are omitted, not fabricated. Never raises -- a failed query yields
    empty gauge/rate maps, so every derived field below naturally becomes
    None rather than propagating an exception."""
    dashed_ip = public_ip.replace(".", "-")
    instance_filter = f'instance=~".*{dashed_ip}.*"'

    gauge_result = query(f'{{__name__=~"{_GAUGE_NAMES}", {instance_filter}}}')
    gauge_series = _raw_series(gauge_result)

    rate_series: list[tuple[str, dict[str, str], float]] = []
    all_rate_queries_failed = True
    for metric_name in _RATE_NAMES:
        series, failed = _rate_series(instance_filter, metric_name)
        rate_series.extend(series)
        all_rate_queries_failed = all_rate_queries_failed and failed

    gauges = _scalar(gauge_series)
    rates = _scalar(rate_series)

    boot_time = gauges.get("node_boot_time_seconds")
    uptime_seconds = (time.time() - boot_time) if boot_time is not None else None

    errors = None
    if gauge_result is None and all_rate_queries_failed:
        errors = "prometheus query failed or no observer host runs prometheus"
    elif not gauge_series and not rate_series:
        errors = f"no node_exporter series matched instance filter for {public_ip}"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": interval_seconds,
        "cpu": {
            "usage_percent": _cpu_usage_percent(rate_series),
            "load_avg_1m": gauges.get("node_load1"),
            "load_avg_5m": gauges.get("node_load5"),
            "load_avg_15m": gauges.get("node_load15"),
            "psi_some_percent": _psi_percent(rates, "node_pressure_cpu_waiting_seconds_total"),
        },
        "memory": {
            **_memory_block(gauges),
            "psi_some_percent": _psi_percent(rates, "node_pressure_memory_waiting_seconds_total"),
            "psi_full_percent": _psi_percent(rates, "node_pressure_memory_stalled_seconds_total"),
            "oom_kill_count": rates.get("node_vmstat_oom_kill"),
        },
        "disk": {
            "partitions": _disk_partitions(gauge_series),
            "psi_some_percent": _psi_percent(rates, "node_pressure_io_waiting_seconds_total"),
        },
        "network": {
            "interfaces": _network_interfaces(rate_series),
            "tcp": {"established_connections": gauges.get("node_netstat_Tcp_CurrEstab")},
            "conntrack": {
                "current_entries": gauges.get("node_nf_conntrack_entries"),
                "max_entries": gauges.get("node_nf_conntrack_entries_limit"),
            },
            # gateway_probe (RTT/jitter to a reference target): no
            # node_exporter equivalent -- omitted, would need a
            # blackbox_exporter probe, out of scope for this pass.
        },
        "uptime_seconds": uptime_seconds,
        "file_descriptors": {
            "allocated": gauges.get("node_filefd_allocated"),
            "max": gauges.get("node_filefd_maximum"),
        },
        "status": {"errors": errors},
    }
