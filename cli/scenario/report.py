from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .report_charts import _chart_concurrency, _chart_quality_by_step, _chart_quality_over_time
from .report_csv import _build_actions_csv, _build_room_csv, _build_step_summary, _build_user_csv
from .report_data import (
    MIN_PLATEAU_SECONDS,
    _action_outcome_counts,
    _detect_plateaus,
    _detection_latency_rows,
    _load_action_records,
    _load_room_entries,
    _load_user_entries,
    _replay_concurrency,
    _step_label,
)
from .system_log import SystemLog


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
    latency_rows: list[dict[str, Any]],
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

    if latency_rows:
        lines.append("")
        lines.append("Detection latency (worker down/up, /healthz first observed transition):")
        for row in latency_rows:
            latency = _fmt(row["latency_seconds"], 3) if row["latency_seconds"] is not None else "n/a"
            lines.append(
                f"  {row['action_type']:<12} id={row['action_id']!s:<10} host={row['host']!s:<6} "
                f"latency={latency}s"
            )

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
    latency_rows: list[dict[str, Any]],
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

    lines += ["", "Full detail: [csv/actions.csv](csv/actions.csv)", ""]

    if latency_rows:
        lines += [
            "## Detection latency",
            "",
            "Ground truth is `container_action_confirmed_at` -- the control node's own "
            "SSH-bracketed timestamp for when `docker stop`/`docker start` actually finished "
            "(see actions.py). Observed is the fast `/healthz` poller's first sampled state "
            "transition (relay only today -- see fast_health_poller.py). Only meaningful when "
            "both are present.",
            "",
            "| action | id | host | confirmed_at | observed_at | latency (s) |",
            "|---|---|---|---|---|---|",
        ]
        for row in latency_rows:
            latency = _fmt(row["latency_seconds"], 3) if row["latency_seconds"] is not None else "-"
            lines.append(
                f"| {row['action_type']} | {row['action_id']} | {row['host']} | "
                f"{row['confirmed_at'] or '-'} | {row['observed_at'] or '-'} | {latency} |"
            )
        lines.append("")

    lines += ["## Steps", ""]
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
    latency_rows = _detection_latency_rows(action_records)

    summary_text = _build_summary_text(
        scenario_name, env, run_timestamp, run_start_ts, run_end_ts, action_outcomes, step_summaries, latency_rows
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
        latency_rows,
        [concurrency_chart, quality_over_time_chart, quality_by_step_chart],
        grafana_images,
        report_dir,
    )
    report_path = report_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")

    print(f"Report written to {report_path}", file=sys.stderr)
    return report_path
