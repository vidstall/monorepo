from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics_sampler import INTERVAL_SECONDS
from .report_data import (
    _aggregate,
    _load_infra_entries,
    _load_room_entries,
    _load_user_entries,
    _load_worker_entries,
    _parse_ts,
)
from .system_log import SystemLog

# Subset of metrics_user.py's _SAMPLE_FIELD_METRICS -- exactly the fields
# --mini-log was asked to report per room (latency/packet-loss/jitter/
# bitrate-up/bitrate-down/frame-rate/resolution/ICE-rate/relay-failover
# downtime). Sourced from user/*.json ticks (the client-self-reported
# dvconf_relay_peer_* gauges, see metrics_user.collect_user_sample()) rather
# than room/*.json's peer_quality block, since that block never carried
# resolution/framerate to begin with -- collect_user_sample() already has
# every field this needs.
_ROOM_QUALITY_SAMPLE_FIELDS = (
    "latencyMs",
    "packetLoss",
    "jitterMs",
    "bitrateUpKbps",
    "bitrateDownKbps",
    "framerate",
    "resolutionWidth",
    "resolutionHeight",
    "iceSuccess",
    # dvconf_relay_peer_reconnect_ms -- the client's own measured downtime
    # between losing its primary relay and completing a warm-standby
    # cutover (see relay-failover.md); this IS "Relay Failover Downtime",
    # just under the sample's own field name.
    "reconnectMs",
)


def _instance_cpu_mem(infra_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{instance_name: {host, cpu_percent, memory_percent}} -- one row per
    cloud instance (provider+host), averaged over every infra tick captured
    during the run."""
    by_instance: dict[str, list[dict[str, Any]]] = {}
    for row in infra_rows:
        by_instance.setdefault(row["instance_name"], []).append(row)

    result: dict[str, dict[str, Any]] = {}
    for instance_name, rows in sorted(by_instance.items()):
        cpu_values = [v for r in rows if (v := (r["entry"].get("cpu") or {}).get("usage_percent")) is not None]
        mem_values = [v for r in rows if (v := (r["entry"].get("memory") or {}).get("used_percent")) is not None]
        result[instance_name] = {
            "host": rows[0].get("host"),
            "cpu_percent": _aggregate(cpu_values)["avg"],
            "memory_percent": _aggregate(mem_values)["avg"],
            "samples": len(rows),
        }
    return result


def _worker_role_cpu_mem(
    worker_rows: list[dict[str, Any]], infra_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """{service: {hosts, cpu_percent, memory_percent}} -- a worker role has
    no cpu/memory of its own (worker/*.json's "logging" array never had a
    live process-level source, see metrics_sampler._capture_worker_entry's
    comment), so this is the average of the INFRA cpu/memory of every host
    that role runs on -- a colocated host (e.g. relay+cp-daemon sharing one
    droplet) contributes the same instance reading to both roles."""
    infra_by_host: dict[str, list[dict[str, Any]]] = {}
    for row in infra_rows:
        host = row.get("host")
        if host:
            infra_by_host.setdefault(str(host), []).append(row)

    hosts_by_service: dict[str, set[str]] = {}
    for row in worker_rows:
        service = str(row.get("service") or "unknown")
        host = row.get("host")
        if host:
            hosts_by_service.setdefault(service, set()).add(str(host))

    result: dict[str, dict[str, Any]] = {}
    for service, hosts in sorted(hosts_by_service.items()):
        cpu_values: list[float] = []
        mem_values: list[float] = []
        for host in hosts:
            for row in infra_by_host.get(host, []):
                cpu = (row["entry"].get("cpu") or {}).get("usage_percent")
                mem = (row["entry"].get("memory") or {}).get("used_percent")
                if cpu is not None:
                    cpu_values.append(cpu)
                if mem is not None:
                    mem_values.append(mem)
        result[service] = {
            "hosts": sorted(hosts),
            "cpu_percent": _aggregate(cpu_values)["avg"],
            "memory_percent": _aggregate(mem_values)["avg"],
        }
    return result


def _room_metrics(user_rows: list[dict[str, Any]], run_start_ts: float) -> dict[str, dict[str, Any]]:
    """{room_id: {avg_<field>..., participants_by_time}} -- averages every
    _ROOM_QUALITY_SAMPLE_FIELDS field across every user tick belonging to
    that room, plus a distinct-peer-count-per-tick-bucket series
    (participants_by_time) bucketed to the sampler's own INTERVAL_SECONDS
    so peers whose ticks land a few hundred ms apart within the same
    capture_metrics_tick() pass still count as the same moment."""
    by_room: dict[str, list[dict[str, Any]]] = {}
    for row in user_rows:
        room_id = row.get("room_id")
        if not room_id:
            continue
        by_room.setdefault(str(room_id), []).append(row)

    result: dict[str, dict[str, Any]] = {}
    for room_id, rows in sorted(by_room.items()):
        values_by_field: dict[str, list[float]] = {field: [] for field in _ROOM_QUALITY_SAMPLE_FIELDS}
        buckets: dict[int, set[str]] = {}
        for row in rows:
            entry = row["entry"]
            sample = entry.get("sample") or {}
            for field in _ROOM_QUALITY_SAMPLE_FIELDS:
                value = sample.get(field)
                if isinstance(value, (int, float)):
                    values_by_field[field].append(value)
            ts = _parse_ts(entry.get("timestamp"))
            if ts is not None:
                bucket = int((ts - run_start_ts) // INTERVAL_SECONDS)
                buckets.setdefault(bucket, set()).add(str(row["peer_id"]))

        participants_by_time = [
            {"t_offset_seconds": bucket * INTERVAL_SECONDS, "participants": len(peers)}
            for bucket, peers in sorted(buckets.items())
        ]
        result[room_id] = {
            "avg_latency_ms": _aggregate(values_by_field["latencyMs"])["avg"],
            "avg_packet_loss": _aggregate(values_by_field["packetLoss"])["avg"],
            "avg_jitter_ms": _aggregate(values_by_field["jitterMs"])["avg"],
            "avg_bitrate_up_kbps": _aggregate(values_by_field["bitrateUpKbps"])["avg"],
            "avg_bitrate_down_kbps": _aggregate(values_by_field["bitrateDownKbps"])["avg"],
            "avg_frame_rate": _aggregate(values_by_field["framerate"])["avg"],
            "avg_resolution_width": _aggregate(values_by_field["resolutionWidth"])["avg"],
            "avg_resolution_height": _aggregate(values_by_field["resolutionHeight"])["avg"],
            "avg_ice_success_rate": _aggregate(values_by_field["iceSuccess"])["avg"],
            "avg_relay_failover_downtime_ms": _aggregate(values_by_field["reconnectMs"])["avg"],
            "participants_by_time": participants_by_time,
        }
    return result


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _build_mini_text(
    scenario_name: str,
    env: str,
    run_timestamp: str,
    instances: dict[str, dict[str, Any]],
    worker_roles: dict[str, dict[str, Any]],
    rooms: dict[str, dict[str, Any]],
) -> str:
    lines = [f"Scenario:  {scenario_name}", f"Env:       {env}", f"Run:       {run_timestamp}", "", "Instances (avg cpu% / mem%):"]
    for instance_name, stats in instances.items():
        lines.append(f"  {instance_name:<24} cpu={_fmt(stats['cpu_percent'])}  mem={_fmt(stats['memory_percent'])}  ({stats['samples']} samples)")

    lines += ["", "Worker roles (avg cpu% / mem% across their host(s)):"]
    for service, stats in worker_roles.items():
        lines.append(f"  {service:<16} cpu={_fmt(stats['cpu_percent'])}  mem={_fmt(stats['memory_percent'])}  hosts={','.join(stats['hosts'])}")

    lines += ["", "Rooms (session averages):"]
    for room_id, stats in rooms.items():
        lines.append(f"  {room_id}")
        lines.append(
            f"    latency={_fmt(stats['avg_latency_ms'])}ms  jitter={_fmt(stats['avg_jitter_ms'])}ms  "
            f"packet_loss={_fmt(stats['avg_packet_loss'], 4)}  ice_success={_fmt(stats['avg_ice_success_rate'], 4)}"
        )
        lines.append(
            f"    bitrate_up={_fmt(stats['avg_bitrate_up_kbps'])}kbps  bitrate_down={_fmt(stats['avg_bitrate_down_kbps'])}kbps  "
            f"frame_rate={_fmt(stats['avg_frame_rate'])}fps  resolution={_fmt(stats['avg_resolution_width'], 0)}x{_fmt(stats['avg_resolution_height'], 0)}"
        )
        lines.append(f"    relay_failover_downtime={_fmt(stats['avg_relay_failover_downtime_ms'])}ms")
        peak = max((p["participants"] for p in stats["participants_by_time"]), default=0)
        lines.append(f"    participants_by_time: {len(stats['participants_by_time'])} bucket(s), peak={peak}")
    return "\n".join(lines) + "\n"


def generate_mini_log(system_log: SystemLog, env: str, run_start_ms: int, run_end_ms: int) -> Path:
    """--mini-log's lightweight counterpart to report.generate_report():
    skips the CSV export / matplotlib charts / full Markdown report
    entirely and instead writes one condensed summary (mini_log.json +
    mini_log.txt, directly under run_dir) covering per-instance cpu/ram,
    per-worker-role cpu/ram, and per-room session-average quality
    (including a participants-over-time series and relay-failover
    downtime) -- exactly the fields --mini-log was asked to capture, no
    more. Read-only over the JSON files a run already wrote, same
    convention as generate_report(): never talks to Prometheus/Grafana
    itself, and callers should wrap this in their own try/except."""
    run_dir = system_log.run_dir
    scenario_name = run_dir.parent.name
    run_timestamp = run_dir.name
    run_start_ts = run_start_ms / 1000

    infra_rows = _load_infra_entries(run_dir)
    worker_rows = _load_worker_entries(run_dir)
    user_rows = _load_user_entries(run_dir)

    instances = _instance_cpu_mem(infra_rows)
    worker_roles = _worker_role_cpu_mem(worker_rows, infra_rows)
    rooms = _room_metrics(user_rows, run_start_ts)

    doc = {
        "scenario": scenario_name,
        "env": env,
        "run_timestamp": run_timestamp,
        "started": datetime.fromtimestamp(run_start_ts, tz=timezone.utc).isoformat(),
        "ended": datetime.fromtimestamp(run_end_ms / 1000, tz=timezone.utc).isoformat(),
        "instances": instances,
        "worker_roles": worker_roles,
        "rooms": rooms,
    }

    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "mini_log.json"
    json_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")

    text = _build_mini_text(scenario_name, env, run_timestamp, instances, worker_roles, rooms)
    text_path = run_dir / "mini_log.txt"
    text_path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Mini log written to {json_path} / {text_path}", file=sys.stderr)
    return json_path
