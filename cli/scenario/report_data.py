from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

# Minimum sustained duration (seconds) for a constant concurrent-client
# count to count as a "step" in the report rather than a transient
# in-between value while a ramp burst is still landing (e.g. 3, 4 on the
# way to a held target of 5). Roughly half of this scenario family's
# intended ~120s step hold, but this module makes no assumption about any
# particular scenario's step timing -- it just needs SOME sustained-enough
# window to call a plateau real.
MIN_PLATEAU_SECONDS = 60.0

# (action_type -> concurrent-client delta) for the actions that actually
# change who's in the room. worker.join/worker.leave don't affect this
# count and are left out.
_ROOM_MEMBERSHIP_DELTA = {
    "bot.create_room": 1,
    "bot.join_room": 1,
    "bot.delete_room": -1,
}

_ROOM_QUALITY_FIELDS = (
    "avg_latency_ms",
    "avg_packet_loss",
    "avg_jitter_ms",
    "avg_bitrate_up_kbps",
    "avg_bitrate_down_kbps",
    "freeze_count_total",
    "pause_count_total",
    "avg_connection_setup_ms",
    "ice_success_rate",
    "avg_av_sync_drift_ms",
)

_USER_SAMPLE_FIELDS = (
    "latencyMs",
    "packetLoss",
    "jitterMs",
    "bitrateUpKbps",
    "bitrateDownKbps",
    "resolutionWidth",
    "resolutionHeight",
    "framerate",
    "packetReorderingRate",
    "encodeLatencyMs",
    "decodeLatencyMs",
    "freezeCount",
    "pauseCount",
    "connectionSetupMs",
    "iceSuccess",
    "reconnectMs",
    "avSyncDriftMs",
)

_WORKER_ACTION_TYPES = {"worker.leave", "worker.join"}


def _parse_ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_action_records(run_dir: Path) -> list[dict[str, Any]]:
    """One record per action file: identity fields plus its before_action/
    after_action events (raw, still carrying the full resolved `action`
    dict each marker was recorded with -- see actions.py's
    record_action_marker() calls) -- sorted by the action's own index."""
    actions_dir = run_dir / "actions"
    if not actions_dir.is_dir():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(actions_dir.glob("*.json")):
        doc = _load_json(path)
        if doc is None:
            continue
        identity = doc.get("identity") or {}
        events = doc.get("events") or []
        before = next((e for e in events if e.get("phase") == "before_action"), None)
        after = next((e for e in events if e.get("phase") == "after_action"), None)
        records.append({"identity": identity, "before": before, "after": after})

    records.sort(key=lambda r: (r["identity"].get("action_index") if r["identity"].get("action_index") is not None else 0))
    return records


def _replay_concurrency(action_records: list[dict[str, Any]]) -> list[tuple[float, int]]:
    """[(timestamp, concurrent_client_count_after_this_action), ...] sorted
    by timestamp, built by replaying every successful room-membership
    action (bot.create_room/bot.join_room/bot.delete_room) in the order it
    actually completed (its own after_action timestamp -- real completion
    time, not the scenario file's scripted offset, which drifts). Failed
    actions (an "error" key on the after_action event) don't change the
    count. worker.join/worker.leave and any action with no after_action
    event yet (run aborted mid-action) are skipped."""
    transitions: list[tuple[float, str]] = []
    for record in action_records:
        after = record["after"]
        if not after or "error" in after:
            continue
        action_type = record["identity"].get("action_type")
        delta = _ROOM_MEMBERSHIP_DELTA.get(action_type)
        if delta is None:
            continue
        ts = _parse_ts(after.get("timestamp"))
        if ts is None:
            continue
        transitions.append((ts, delta))

    transitions.sort(key=lambda pair: pair[0])
    count = 0
    series: list[tuple[float, int]] = []
    for ts, delta in transitions:
        count += delta
        series.append((ts, count))
    return series


def _detect_plateaus(
    series: list[tuple[float, int]], run_end_ts: float | None, min_seconds: float = MIN_PLATEAU_SECONDS
) -> list[dict[str, Any]]:
    """Maximal [start, end) windows where the concurrent-client count held
    steady for at least `min_seconds` -- see module docstring. Each
    transition in `series` starts a new candidate interval that runs until
    the next transition (or run_end_ts for the last one)."""
    if not series:
        return []

    plateaus: list[dict[str, Any]] = []
    for index, (start_ts, count) in enumerate(series):
        end_ts = series[index + 1][0] if index + 1 < len(series) else run_end_ts
        if end_ts is None:
            end_ts = start_ts
        duration = end_ts - start_ts
        if duration >= min_seconds:
            plateaus.append({"count": count, "start": start_ts, "end": end_ts, "duration_seconds": duration})

    # Re-index in chronological order AFTER filtering -- a plateau's
    # `step_index` is its position among plateaus that actually qualified,
    # not its position in the raw transition list. Kept distinct from
    # `count`: two different plateaus can land on the same concurrent-client
    # count (e.g. a ramp back down to a level visited earlier, or churn
    # scenarios revisiting a baseline), and `step_index` is what keeps them
    # from being merged together when bucketing raw ticks below.
    for index, plateau in enumerate(plateaus):
        plateau["step_index"] = index
    return plateaus


def _step_label(ts: float, plateaus: list[dict[str, Any]]) -> str:
    """A stable, unique label for whichever plateau `ts` falls inside --
    "<step_index>:<count> clients", e.g. "2:10 clients" -- or "transition"
    if it falls in a ramp window that never held long enough to qualify as
    a plateau. Deliberately NOT just `str(count)`: two plateaus can share
    the same concurrent-client count (see _detect_plateaus's doc), and a
    count-only label would silently merge their raw ticks together."""
    for plateau in plateaus:
        if plateau["start"] <= ts < plateau["end"]:
            return f"{plateau['step_index']}:{plateau['count']} clients"
    return "transition"


def _load_room_entries(run_dir: Path) -> list[dict[str, Any]]:
    room_dir = run_dir / "room"
    if not room_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(room_dir.glob("*.json")):
        doc = _load_json(path)
        if doc is None:
            continue
        room_id = (doc.get("identity") or {}).get("room_id") or path.stem
        for entry in doc.get("metrics") or []:
            rows.append({"room_id": room_id, "entry": entry})
    return rows


def _load_user_entries(run_dir: Path) -> list[dict[str, Any]]:
    user_dir = run_dir / "user"
    if not user_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(user_dir.glob("*.json")):
        doc = _load_json(path)
        if doc is None:
            continue
        identity = doc.get("identity") or {}
        peer_id = identity.get("peer_id") or path.stem
        room_id = identity.get("room_id")
        for entry in doc.get("metrics") or []:
            rows.append({"peer_id": peer_id, "room_id": room_id, "entry": entry})
    return rows


def _load_infra_entries(run_dir: Path) -> list[dict[str, Any]]:
    """One row per infra/<instance>.json tick -- see
    metrics_sampler._capture_infra_entry()'s "evaluation" array (cpu/memory
    node_exporter block, keyed by instance_name = "<provider>-<host>")."""
    infra_dir = run_dir / "infra"
    if not infra_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(infra_dir.glob("*.json")):
        doc = _load_json(path)
        if doc is None:
            continue
        identity = doc.get("identity") or {}
        instance_name = identity.get("instance_name") or path.stem
        host = identity.get("host")
        for entry in doc.get("evaluation") or []:
            rows.append({"instance_name": instance_name, "host": host, "entry": entry})
    return rows


def _load_worker_entries(run_dir: Path) -> list[dict[str, Any]]:
    """One row per worker/<process_key>.json tick's identity -- only the
    identity is needed (service/host, to map a worker role onto the infra
    host(s) that actually run it); worker/*.json's own "logging" array has
    no live cpu/memory source today (see metrics_sampler._capture_worker_entry's
    comment), so callers get cpu/memory from infra rows keyed by `host`
    instead."""
    worker_dir = run_dir / "worker"
    if not worker_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(worker_dir.glob("*.json")):
        doc = _load_json(path)
        if doc is None:
            continue
        identity = doc.get("identity") or {}
        rows.append(
            {
                "process_key": identity.get("process_key") or path.stem,
                "service": identity.get("service"),
                "host": identity.get("host"),
            }
        )
    return rows


def _aggregate(values: list[float]) -> dict[str, float | int | None]:
    clean = [v for v in values if isinstance(v, (int, float))]
    if not clean:
        return {"count": 0, "avg": None, "p95": None, "max": None, "min": None}
    ordered = sorted(clean)
    p95_index = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
    return {
        "count": len(ordered),
        "avg": statistics.fmean(ordered),
        "p95": ordered[p95_index],
        "max": ordered[-1],
        "min": ordered[0],
    }


def _room_field_value(entry: dict[str, Any], field: str) -> float | None:
    return (entry.get("peer_quality") or {}).get(field)


def _detection_latency(after: dict[str, Any] | None) -> tuple[str | None, str | None, float | None]:
    """(container_action_confirmed_at, health_observed_at, latency_seconds)
    for a worker.leave/worker.join after_action event -- see actions.py's
    FastHealthPoller wiring. confirmed_at is the ground-truth SSH-bracketed
    "docker stop/start finished" timestamp; observed_at is the fast
    /healthz poller's first observed state transition. Either or both can
    be None (e.g. the target service isn't relay -- fast_health_poller
    only supports that today -- or the transition never landed within the
    poller's grace window), in which case latency_seconds is None too."""
    result = (after or {}).get("result") or {}
    confirmed_at = result.get("container_action_confirmed_at")
    observed_at = (result.get("health_poll") or {}).get("observed_at")
    latency_seconds = None
    confirmed_ts = _parse_ts(confirmed_at)
    observed_ts = _parse_ts(observed_at)
    if confirmed_ts is not None and observed_ts is not None:
        latency_seconds = observed_ts - confirmed_ts
    return confirmed_at, observed_at, latency_seconds


def _detection_latency_rows(action_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per worker.leave/worker.join action that has an after_action
    event, regardless of whether a latency value could be computed (a
    missing confirmed_at/observed_at is itself worth surfacing, not hidden
    -- e.g. a non-relay target, or the /healthz transition never landing
    within the poller's grace window)."""
    rows = []
    for record in action_records:
        identity = record["identity"]
        if identity.get("action_type") not in _WORKER_ACTION_TYPES:
            continue
        after = record["after"]
        if not after:
            continue
        action = after.get("action") or {}
        confirmed_at, observed_at, latency_seconds = _detection_latency(after)
        rows.append(
            {
                "action_id": identity.get("action_id"),
                "action_type": identity.get("action_type"),
                "host": action.get("host"),
                "confirmed_at": confirmed_at,
                "observed_at": observed_at,
                "latency_seconds": latency_seconds,
            }
        )
    return rows


def _action_outcome_counts(action_records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for record in action_records:
        action_type = str(record["identity"].get("action_type") or "unknown")
        bucket = counts.setdefault(action_type, {"ok": 0, "error": 0, "no_after_event": 0})
        after = record["after"]
        if not after:
            bucket["no_after_event"] += 1
        elif "error" in after:
            bucket["error"] += 1
        else:
            bucket["ok"] += 1
    return counts
