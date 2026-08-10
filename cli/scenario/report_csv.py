from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .report_data import (
    _ROOM_QUALITY_FIELDS,
    _USER_SAMPLE_FIELDS,
    _aggregate,
    _detection_latency,
    _parse_ts,
    _room_field_value,
    _step_label,
)


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
        confirmed_at, observed_at, latency_seconds = _detection_latency(after)
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
                confirmed_at,
                observed_at,
                latency_seconds,
            ]
        )
    _write_csv(
        dest,
        [
            "action_index",
            "action_id",
            "action_type",
            "host",
            "timestamp",
            "duration_seconds",
            "status",
            "error",
            "container_action_confirmed_at",
            "health_observed_at",
            "detection_latency_seconds",
        ],
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
