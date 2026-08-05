from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Headless backend -- report generation runs at the tail end of a scripted
# `scenario run`, never in an environment with a display, and must never
# block on/require one.
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - backend must be set before this import

from .system_log import SystemLog

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


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _build_actions_csv(action_records: list[dict[str, Any]], dest: Path) -> None:
    rows = []
    for record in action_records:
        identity = record["identity"]
        after = record["after"]
        before = record["before"]
        action = (after or before or {}).get("action") or {}
        success = bool(after) and "error" not in after
        rows.append(
            [
                identity.get("action_index"),
                identity.get("action_id"),
                identity.get("action_type"),
                action.get("host"),
                (before or {}).get("timestamp"),
                after.get("duration_seconds") if after else None,
                "ok" if success else ("error" if after else "no_after_event"),
                after.get("error") if after else None,
            ]
        )
    _write_csv(
        dest,
        ["action_index", "action_id", "action_type", "host", "timestamp", "duration_seconds", "status", "error"],
        rows,
    )


def _build_room_csv(room_rows: list[dict[str, Any]], plateaus: list[dict[str, Any]], dest: Path) -> None:
    rows = []
    for row in room_rows:
        entry = row["entry"]
        ts = _parse_ts(entry.get("timestamp"))
        step = _step_label(ts, plateaus) if ts is not None else "unknown"
        peer_quality = entry.get("peer_quality") or {}
        rtc = entry.get("rtc_quality_server_observed") or {}
        audio = rtc.get("audio") or {}
        video = rtc.get("video") or {}
        rows.append(
            [
                entry.get("timestamp"),
                row["room_id"],
                step,
                *[peer_quality.get(field) for field in _ROOM_QUALITY_FIELDS],
                audio.get("avg_jitter_ms"),
                audio.get("avg_packet_loss_ratio"),
                audio.get("avg_bitrate_kbps"),
                audio.get("avg_rtt_ms"),
                video.get("avg_jitter_ms"),
                video.get("avg_packet_loss_ratio"),
                video.get("avg_bitrate_kbps"),
                video.get("avg_rtt_ms"),
            ]
        )
    header = [
        "timestamp",
        "room_id",
        "step",
        *_ROOM_QUALITY_FIELDS,
        "audio_avg_jitter_ms",
        "audio_avg_packet_loss_ratio",
        "audio_avg_bitrate_kbps",
        "audio_avg_rtt_ms",
        "video_avg_jitter_ms",
        "video_avg_packet_loss_ratio",
        "video_avg_bitrate_kbps",
        "video_avg_rtt_ms",
    ]
    _write_csv(dest, header, rows)


def _build_user_csv(user_rows: list[dict[str, Any]], plateaus: list[dict[str, Any]], dest: Path) -> None:
    rows = []
    for row in user_rows:
        entry = row["entry"]
        ts = _parse_ts(entry.get("timestamp"))
        step = _step_label(ts, plateaus) if ts is not None else "unknown"
        sample = entry.get("sample") or {}
        rows.append(
            [
                entry.get("timestamp"),
                row["peer_id"],
                row["room_id"],
                step,
                *[sample.get(field) for field in _USER_SAMPLE_FIELDS],
            ]
        )
    header = ["timestamp", "peer_id", "room_id", "step", *_USER_SAMPLE_FIELDS]
    _write_csv(dest, header, rows)


def _build_step_summary(
    room_rows: list[dict[str, Any]], plateaus: list[dict[str, Any]], dest: Path
) -> list[dict[str, Any]]:
    """One row per detected plateau plus a trailing whole-run row --
    avg/p95/max per room quality field, aggregated across every room-metric
    tick that fell inside that plateau's time window."""
    summaries: list[dict[str, Any]] = []
    for plateau in plateaus:
        in_window = [
            row["entry"]
            for row in room_rows
            if (ts := _parse_ts(row["entry"].get("timestamp"))) is not None and plateau["start"] <= ts < plateau["end"]
        ]
        field_stats = {
            field: _aggregate([_room_field_value(entry, field) for entry in in_window]) for field in _ROOM_QUALITY_FIELDS
        }
        summaries.append(
            {
                "step_index": plateau["step_index"],
                "concurrency": plateau["count"],
                "duration_seconds": plateau["duration_seconds"],
                "sample_ticks": len(in_window),
                "fields": field_stats,
            }
        )

    all_entries = [row["entry"] for row in room_rows]
    whole_run_stats = {
        field: _aggregate([_room_field_value(entry, field) for entry in all_entries]) for field in _ROOM_QUALITY_FIELDS
    }
    summaries.append(
        {
            "step_index": "whole_run",
            "concurrency": None,
            "duration_seconds": None,
            "sample_ticks": len(all_entries),
            "fields": whole_run_stats,
        }
    )

    rows = []
    for summary in summaries:
        for field in _ROOM_QUALITY_FIELDS:
            stats = summary["fields"][field]
            rows.append(
                [
                    summary["step_index"],
                    summary["concurrency"],
                    summary["duration_seconds"],
                    summary["sample_ticks"],
                    field,
                    stats["avg"],
                    stats["p95"],
                    stats["min"],
                    stats["max"],
                    stats["count"],
                ]
            )
    _write_csv(
        dest,
        ["step_index", "concurrency", "duration_seconds", "sample_ticks", "field", "avg", "p95", "min", "max", "sample_count"],
        rows,
    )
    return summaries


def _chart_concurrency(series: list[tuple[float, int]], plateaus: list[dict[str, Any]], run_start_ts: float, dest: Path) -> None:
    if not series:
        return
    xs = [(ts - run_start_ts) for ts, _count in series]
    ys = [count for _ts, count in series]
    # Turn the sparse transition list into a step curve for plotting.
    step_xs: list[float] = [0.0]
    step_ys: list[int] = [0]
    for x, y in zip(xs, ys):
        step_xs.append(x)
        step_ys.append(step_ys[-1])
        step_xs.append(x)
        step_ys.append(y)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(step_xs, step_ys, color="#1f77b4")
    for plateau in plateaus:
        ax.axvspan(plateau["start"] - run_start_ts, plateau["end"] - run_start_ts, color="#1f77b4", alpha=0.08)
        ax.text(
            (plateau["start"] + plateau["end"]) / 2 - run_start_ts,
            plateau["count"] + 0.5,
            str(plateau["count"]),
            ha="center",
            fontsize=8,
        )
    ax.set_xlabel("seconds since run start")
    ax.set_ylabel("concurrent clients")
    ax.set_title("Concurrent client count over time")
    fig.tight_layout()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest)
    plt.close(fig)


def _chart_quality_over_time(room_rows: list[dict[str, Any]], plateaus: list[dict[str, Any]], run_start_ts: float, dest: Path) -> None:
    points = []
    for row in room_rows:
        ts = _parse_ts(row["entry"].get("timestamp"))
        if ts is None:
            continue
        points.append((ts, row["entry"]))
    if not points:
        return
    points.sort(key=lambda pair: pair[0])

    fig, axes = plt.subplots(4, 1, figsize=(10, 12), sharex=True)
    metrics = [
        ("avg_latency_ms", "Latency (ms)"),
        ("avg_jitter_ms", "Jitter (ms)"),
        ("avg_packet_loss", "Packet loss (ratio)"),
        ("avg_bitrate_down_kbps", "Downlink bitrate (kbps)"),
    ]
    for ax, (field, label) in zip(axes, metrics):
        xs = [ts - run_start_ts for ts, _entry in points]
        ys = [_room_field_value(entry, field) for _ts, entry in points]
        ax.plot(xs, ys, color="#d62728", marker=".", linewidth=1)
        for plateau in plateaus:
            ax.axvline(plateau["start"] - run_start_ts, color="gray", linestyle="--", linewidth=0.5)
        ax.set_ylabel(label)
    axes[-1].set_xlabel("seconds since run start")
    fig.suptitle("Room call quality over time")
    fig.tight_layout()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest)
    plt.close(fig)


def _chart_quality_by_step(step_summaries: list[dict[str, Any]], dest: Path) -> None:
    # Already in chronological plateau order (see _build_step_summary) --
    # deliberately not re-sorted by concurrency value, since a non-monotonic
    # timeline (churn scenarios revisiting a lower count) should still read
    # left-to-right as "what happened over time", not "sorted by load".
    steps = [s for s in step_summaries if s["step_index"] != "whole_run"]
    if not steps:
        return

    fields = [
        ("avg_latency_ms", "Latency (ms)"),
        ("avg_jitter_ms", "Jitter (ms)"),
        ("avg_packet_loss", "Packet loss (ratio)"),
    ]
    fig, axes = plt.subplots(1, len(fields), figsize=(14, 4))
    labels = [f"{s['concurrency']}" for s in steps]
    for ax, (field, title) in zip(axes, fields):
        values = [s["fields"][field]["avg"] or 0 for s in steps]
        ax.bar(labels, values, color="#2ca02c")
        ax.set_title(title)
        ax.set_xlabel("concurrent clients")
    fig.suptitle("Average call quality by concurrency step")
    fig.tight_layout()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dest)
    plt.close(fig)


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


def _fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def _build_summary_text(
    scenario_name: str,
    env: str,
    run_timestamp: str,
    run_start_ts: float,
    run_end_ts: float,
    action_outcomes: dict[str, dict[str, int]],
    step_summaries: list[dict[str, Any]],
) -> str:
    lines = [
        f"Scenario:  {scenario_name}",
        f"Env:       {env}",
        f"Run:       {run_timestamp}",
        f"Started:   {datetime.fromtimestamp(run_start_ts, tz=timezone.utc).isoformat()}",
        f"Ended:     {datetime.fromtimestamp(run_end_ts, tz=timezone.utc).isoformat()}",
        f"Duration:  {run_end_ts - run_start_ts:.0f}s",
        "",
        "Actions:",
    ]
    for action_type, bucket in sorted(action_outcomes.items()):
        lines.append(f"  {action_type}: ok={bucket['ok']} error={bucket['error']} no_after_event={bucket['no_after_event']}")

    lines.append("")
    lines.append("Steps (concurrent clients -> room quality avg/p95/max):")
    for summary in step_summaries:
        step_desc = (
            "whole_run"
            if summary["step_index"] == "whole_run"
            else f"#{summary['step_index']} ({summary['concurrency']} clients)"
        )
        header = f"  step={step_desc:>18}  duration={_fmt(summary['duration_seconds'], 0)}s  ticks={summary['sample_ticks']}"
        lines.append(header)
        for field in ("avg_latency_ms", "avg_jitter_ms", "avg_packet_loss", "avg_bitrate_down_kbps"):
            stats = summary["fields"][field]
            lines.append(
                f"    {field:<24} avg={_fmt(stats['avg'])} p95={_fmt(stats['p95'])} max={_fmt(stats['max'])}"
            )
    return "\n".join(lines) + "\n"


def _build_markdown_report(
    scenario_name: str,
    env: str,
    run_timestamp: str,
    run_start_ts: float,
    run_end_ts: float,
    action_outcomes: dict[str, dict[str, int]],
    step_summaries: list[dict[str, Any]],
    chart_paths: list[Path],
    grafana_images: list[Path],
    report_dir: Path,
) -> str:
    lines = [
        f"# Scenario report: {scenario_name}",
        "",
        f"- Env: `{env}`",
        f"- Run: `{run_timestamp}`",
        f"- Started: {datetime.fromtimestamp(run_start_ts, tz=timezone.utc).isoformat()}",
        f"- Ended: {datetime.fromtimestamp(run_end_ts, tz=timezone.utc).isoformat()}",
        f"- Duration: {run_end_ts - run_start_ts:.0f}s",
        "",
        "## Actions",
        "",
        "| type | ok | error | no_after_event |",
        "|---|---|---|---|",
    ]
    for action_type, bucket in sorted(action_outcomes.items()):
        lines.append(f"| {action_type} | {bucket['ok']} | {bucket['error']} | {bucket['no_after_event']} |")

    lines += ["", "Full detail: [csv/actions.csv](csv/actions.csv)", "", "## Steps", ""]
    lines.append(
        "| step | concurrency | duration (s) | ticks | avg latency (ms) | avg jitter (ms) | avg packet loss | avg down bitrate (kbps) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for summary in step_summaries:
        f = summary["fields"]
        lines.append(
            "| {step} | {conc} | {dur} | {ticks} | {lat} | {jit} | {loss} | {bw} |".format(
                step=summary["step_index"],
                conc=summary["concurrency"] if summary["concurrency"] is not None else "-",
                dur=_fmt(summary["duration_seconds"], 0),
                ticks=summary["sample_ticks"],
                lat=_fmt(f["avg_latency_ms"]["avg"]),
                jit=_fmt(f["avg_jitter_ms"]["avg"]),
                loss=_fmt(f["avg_packet_loss"]["avg"], 4),
                bw=_fmt(f["avg_bitrate_down_kbps"]["avg"]),
            )
        )

    lines += [
        "",
        "Full detail: [csv/step_summary.csv](csv/step_summary.csv), "
        "[csv/room_metrics.csv](csv/room_metrics.csv), [csv/user_metrics.csv](csv/user_metrics.csv)",
        "",
        "## Charts",
        "",
    ]
    for chart_path in chart_paths:
        if chart_path.exists():
            lines.append(f"![{chart_path.stem}](charts/{chart_path.name})")
            lines.append("")

    if grafana_images:
        lines.append("## Grafana panels")
        lines.append("")
        for image_path in grafana_images:
            try:
                rel = image_path.relative_to(report_dir.parent)
            except ValueError:
                continue
            lines.append(f"![{image_path.stem}](../{rel.as_posix()})")
            lines.append("")

    return "\n".join(lines) + "\n"


def generate_report(
    system_log: SystemLog,
    env: str,
    run_start_ms: int,
    run_end_ms: int,
    grafana_img_dir: Path,
) -> Path:
    """Post-run report: console summary (also written to summary.txt), CSV
    export, matplotlib diagrams, and a Markdown report tying everything
    together (including the Grafana panel PNGs already captured under
    grafana_img_dir) -- all under system_log.run_dir/report/. Read-only over
    the JSON files a run already wrote (system_log.py's action markers,
    metrics_sampler.py's room/user/infra/worker ticks); this function never
    talks to Prometheus/Grafana/chain itself. Callers should wrap this in
    their own try/except (see run.py) -- a report-generation bug must never
    fail a scenario run that otherwise succeeded."""
    run_dir = system_log.run_dir
    scenario_name = run_dir.parent.name
    run_timestamp = run_dir.name
    run_start_ts = run_start_ms / 1000
    run_end_ts = run_end_ms / 1000

    report_dir = run_dir / "report"
    csv_dir = report_dir / "csv"
    charts_dir = report_dir / "charts"

    action_records = _load_action_records(run_dir)
    concurrency_series = _replay_concurrency(action_records)
    plateaus = _detect_plateaus(concurrency_series, run_end_ts)

    room_rows = _load_room_entries(run_dir)
    user_rows = _load_user_entries(run_dir)

    _build_actions_csv(action_records, csv_dir / "actions.csv")
    _build_room_csv(room_rows, plateaus, csv_dir / "room_metrics.csv")
    _build_user_csv(user_rows, plateaus, csv_dir / "user_metrics.csv")
    step_summaries = _build_step_summary(room_rows, plateaus, csv_dir / "step_summary.csv")

    concurrency_chart = charts_dir / "concurrency.png"
    quality_over_time_chart = charts_dir / "quality_over_time.png"
    quality_by_step_chart = charts_dir / "quality_by_step.png"
    _chart_concurrency(concurrency_series, plateaus, run_start_ts, concurrency_chart)
    _chart_quality_over_time(room_rows, plateaus, run_start_ts, quality_over_time_chart)
    _chart_quality_by_step(step_summaries, quality_by_step_chart)

    action_outcomes = _action_outcome_counts(action_records)

    summary_text = _build_summary_text(
        scenario_name, env, run_timestamp, run_start_ts, run_end_ts, action_outcomes, step_summaries
    )
    print(summary_text)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.txt").write_text(summary_text, encoding="utf-8")

    grafana_images = sorted(grafana_img_dir.rglob("*.png")) if grafana_img_dir.is_dir() else []

    markdown = _build_markdown_report(
        scenario_name,
        env,
        run_timestamp,
        run_start_ts,
        run_end_ts,
        action_outcomes,
        step_summaries,
        [concurrency_chart, quality_over_time_chart, quality_by_step_chart],
        grafana_images,
        report_dir,
    )
    report_path = report_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")

    print(f"Report written to {report_path}", file=sys.stderr)
    return report_path
