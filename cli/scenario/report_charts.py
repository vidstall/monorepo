from __future__ import annotations

from pathlib import Path
from typing import Any

# Headless backend -- report generation runs at the tail end of a scripted
# `scenario run`, never in an environment with a display, and must never
# block on/require one.
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 - backend must be set before this import

from .report_data import _parse_ts, _room_field_value


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
