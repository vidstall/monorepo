"""End-to-end quality readback for the evaluation harness.

Per the locked decision in the "Quality/capacity/failover evaluation
harness" plan, "quality" for the capacity-search scenarios is END-TO-END
latency = dvconf_relay_peer_latency_ms + dvconf_relay_peer_encode_latency_ms
+ dvconf_relay_peer_decode_latency_ms (network RTT + this bot's own
encode/decode cost), not network latency alone.

A `vidctl scenario run` already captures every active peer's per-tick
quality sample straight to local JSON under
logs/<scenario_name>/<run_timestamp>/user/<peer_id>.json (see
metrics_sampler.py's `_capture_user_entry`, which mirrors
apps/bot/src/stats-reporter.ts's/useConnectionStats.ts's client-pushed
`dvconf_relay_peer_*` fields -- see `_USER_SAMPLE_FIELDS` in report_data.py)
-- so this module reads that local log directly instead of re-querying
Prometheus live. This also means quality can be computed for a run that's
already finished (no live-window race), same as report.py's own read-only
post-run pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import context
from .report_data import (
    _aggregate,
    _detect_plateaus,
    _load_action_records,
    _load_user_entries,
    _parse_ts,
    _replay_concurrency,
    _step_label,
)

END_TO_END_FIELDS = ("latencyMs", "encodeLatencyMs", "decodeLatencyMs")


def latest_run_dir(scenario_name: str) -> Path | None:
    """Most recent logs/<scenario_name>/<run_timestamp>/ dir, or None if the
    scenario has never been run. Run-timestamp directory names are
    `%Y%m%dT%H%M%SZ` (see system_log.py), which sorts lexicographically in
    chronological order -- no datetime parsing needed."""
    scenario_dir = context.LOGS_ROOT / scenario_name
    if not scenario_dir.is_dir():
        return None
    run_dirs = sorted(p for p in scenario_dir.iterdir() if p.is_dir())
    return run_dirs[-1] if run_dirs else None


def _end_to_end_ms(sample: dict[str, Any]) -> float | None:
    total = 0.0
    for field in END_TO_END_FIELDS:
        value = sample.get(field)
        if not isinstance(value, (int, float)):
            return None
        total += float(value)
    return total


def end_to_end_samples(run_dir: Path) -> list[tuple[float, str, float]]:
    """[(tick_timestamp, step_label, end_to_end_ms), ...] for every user
    sample in the run that has all three END_TO_END_FIELDS present. Ticks
    missing any field (e.g. a sample taken before a peer's stats first
    populate) are skipped rather than partially summed, since a partial sum
    would silently understate true end-to-end latency."""
    action_records = _load_action_records(run_dir)
    concurrency_series = _replay_concurrency(action_records)
    plateaus = _detect_plateaus(concurrency_series, run_end_ts=None)

    rows: list[tuple[float, str, float]] = []
    for row in _load_user_entries(run_dir):
        entry = row["entry"]
        sample = entry.get("sample") or {}
        total = _end_to_end_ms(sample)
        if total is None:
            continue
        ts = _parse_ts(entry.get("timestamp"))
        if ts is None:
            continue
        rows.append((ts, _step_label(ts, plateaus), total))
    return rows


def end_to_end_by_step(run_dir: Path) -> dict[str, dict[str, float | int | None]]:
    """{step_label: aggregate(count/avg/p95/max/min)} across every step the
    run held long enough to plateau (see report_data.MIN_PLATEAU_SECONDS),
    plus a "transition" bucket for anything outside a plateau."""
    by_step: dict[str, list[float]] = {}
    for _ts, step, value in end_to_end_samples(run_dir):
        by_step.setdefault(step, []).append(value)
    return {step: _aggregate(values) for step, values in by_step.items()}


def max_end_to_end_ms(run_dir: Path) -> float | None:
    """The single highest end-to-end latency observed anywhere in the run --
    the number a capacity search's "does average latency, does it ever
    exceed 400ms" avg-vs-max decision reads (see find_max_capacity.py)."""
    values = [value for _ts, _step, value in end_to_end_samples(run_dir)]
    return max(values) if values else None


def avg_end_to_end_ms(run_dir: Path) -> float | None:
    """Mean end-to-end latency across every sample in the run (all steps
    combined) -- the "avg stays below 400ms" reading."""
    values = [value for _ts, _step, value in end_to_end_samples(run_dir)]
    return sum(values) / len(values) if values else None
