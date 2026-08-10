from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from cli.scenario import report as scenario_report
from cli.scenario import system_log

from tests.scenario_test_base import ScenarioTestCase


def _iso(base: datetime, offset_seconds: float) -> str:
    from datetime import timedelta

    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _write_action_file(
    run_dir: Path,
    index: int,
    action_type: str,
    base: datetime,
    before_offset: float,
    after_offset: float,
    action_id: str | None = None,
    host: str = "001",
    error: str | None = None,
    result: dict | None = None,
) -> None:
    action_payload = {"type": action_type, "host": host, "id": action_id}
    after_event: dict = {
        "phase": "after_action",
        "timestamp": _iso(base, after_offset),
        "duration_seconds": after_offset - before_offset,
        "action": action_payload,
    }
    if error is not None:
        after_event["error"] = error
    else:
        after_event["result"] = result or {}

    doc = {
        "identity": {"action_index": index, "action_id": action_id, "action_type": action_type},
        "events": [
            {"phase": "before_action", "timestamp": _iso(base, before_offset), "action": action_payload},
            after_event,
        ],
    }
    path = run_dir / "actions" / f"{index:03d}-{action_type.replace('.', '-')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_room_file(
    run_dir: Path, room_id: str, entries: list[tuple[float, dict]], base: datetime
) -> None:
    doc = {
        "identity": {"room_id": room_id},
        "metrics": [
            {"timestamp": _iso(base, offset), "interval_seconds": 5, "peer_quality": peer_quality}
            for offset, peer_quality in entries
        ],
    }
    path = run_dir / "room" / f"{room_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_user_file(
    run_dir: Path, room_id: str, peer_id: str, entries: list[tuple[float, dict]], base: datetime
) -> None:
    doc = {
        "identity": {"room_id": room_id, "peer_id": peer_id},
        "metrics": [
            {"timestamp": _iso(base, offset), "interval_seconds": 5, "sample": sample} for offset, sample in entries
        ],
    }
    path = run_dir / "user" / f"{peer_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


class ReportTests(ScenarioTestCase):
    """Unit-tests cli.scenario.report.generate_report() against hand-built
    logs/<scenario>/<run_timestamp>/ fixtures -- same style as
    SystemLogTests, but for the post-run report step (never exercised via a
    real `scenario run`, since that needs live actions/metrics timing)."""

    BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_generate_report_creates_expected_outputs_and_detects_plateaus(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "report-test")
        run_dir = log.run_dir

        # Replayed concurrency timeline: create @5s (+1 -> count 1, held
        # 65s), join @70s (+1 -> count 2, held 70s), delete @140s (-1 ->
        # count 1 again, held 60s until run end @200s). All three windows
        # clear MIN_PLATEAU_SECONDS (60s) -- 3 plateaus expected, the last
        # one revisiting a count (1) already seen earlier.
        _write_action_file(
            run_dir, 0, "bot.create_room", self.BASE, 0, 5, action_id="room1", result={"roomId": "r1", "botId": "b0"}
        )
        _write_action_file(run_dir, 1, "bot.join_room", self.BASE, 65, 70, action_id="j1", result={"botId": "b1"})
        _write_action_file(run_dir, 2, "bot.delete_room", self.BASE, 135, 140, action_id=None, result={})
        # A failed action must not perturb the replayed count.
        _write_action_file(
            run_dir, 3, "bot.join_room", self.BASE, 150, 155, action_id="j2", error="join failed"
        )

        _write_room_file(
            run_dir,
            "r1",
            [
                (30, {"avg_latency_ms": 40.0, "avg_jitter_ms": 2.0, "avg_packet_loss": 0.01, "avg_bitrate_down_kbps": 500.0}),
                (100, {"avg_latency_ms": 60.0, "avg_jitter_ms": 4.0, "avg_packet_loss": 0.02, "avg_bitrate_down_kbps": 480.0}),
                (170, {"avg_latency_ms": 50.0, "avg_jitter_ms": 3.0, "avg_packet_loss": 0.015, "avg_bitrate_down_kbps": 490.0}),
            ],
            self.BASE,
        )
        _write_user_file(
            run_dir,
            "r1",
            "peer1",
            [(30, {"latencyMs": 42.0, "jitterMs": 2.1})],
            self.BASE,
        )

        run_start_ms = int(self.BASE.timestamp() * 1000)
        run_end_ms = int((self.BASE.timestamp() + 200) * 1000)

        report_path = scenario_report.generate_report(
            log, "devnet", run_start_ms, run_end_ms, self.root / "logs" / "no-grafana-host"
        )

        self.assertTrue(report_path.exists())
        report_dir = run_dir / "report"
        self.assertTrue((report_dir / "summary.txt").exists())
        self.assertTrue((report_dir / "csv" / "actions.csv").exists())
        self.assertTrue((report_dir / "csv" / "room_metrics.csv").exists())
        self.assertTrue((report_dir / "csv" / "user_metrics.csv").exists())
        self.assertTrue((report_dir / "csv" / "step_summary.csv").exists())
        self.assertTrue((report_dir / "charts" / "concurrency.png").exists())
        self.assertTrue((report_dir / "charts" / "quality_over_time.png").exists())
        self.assertTrue((report_dir / "charts" / "quality_by_step.png").exists())

        with (report_dir / "csv" / "step_summary.csv").open(encoding="utf-8") as handle:
            step_rows = list(csv.DictReader(handle))
        step_indices = sorted({row["step_index"] for row in step_rows})
        self.assertEqual(step_indices, ["0", "1", "2", "whole_run"])
        concurrency_by_index = {row["step_index"]: row["concurrency"] for row in step_rows}
        self.assertEqual(concurrency_by_index["0"], "1")
        self.assertEqual(concurrency_by_index["1"], "2")
        self.assertEqual(concurrency_by_index["2"], "1")

        with (report_dir / "csv" / "actions.csv").open(encoding="utf-8") as handle:
            action_rows = list(csv.DictReader(handle))
        self.assertEqual(len(action_rows), 4)
        statuses = {row["action_id"] or row["action_index"]: row["status"] for row in action_rows}
        self.assertEqual(statuses["room1"], "ok")
        self.assertEqual(statuses["j2"], "error")

        markdown = (report_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("## Steps", markdown)
        self.assertIn("concurrency.png", markdown)

    def test_generate_report_degrades_gracefully_with_no_actions_dir(self) -> None:
        """--fast run: no actions/ directory at all. Must not raise, and
        must fall back to a whole-run-only summary instead of crashing on
        missing plateau/step data."""
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "fast-report-test")
        run_dir = log.run_dir
        _write_room_file(
            run_dir,
            "r1",
            [(10, {"avg_latency_ms": 30.0, "avg_jitter_ms": 1.0, "avg_packet_loss": 0.0, "avg_bitrate_down_kbps": 400.0})],
            self.BASE,
        )

        run_start_ms = int(self.BASE.timestamp() * 1000)
        run_end_ms = int((self.BASE.timestamp() + 60) * 1000)

        report_path = scenario_report.generate_report(
            log, "devnet", run_start_ms, run_end_ms, self.root / "logs" / "no-grafana-host"
        )
        self.assertTrue(report_path.exists())

        with ((run_dir / "report" / "csv" / "step_summary.csv")).open(encoding="utf-8") as handle:
            step_rows = list(csv.DictReader(handle))
        self.assertTrue(all(row["step_index"] == "whole_run" for row in step_rows))
        # No plateaus at all -- the concurrency chart has nothing to plot.
        self.assertFalse((run_dir / "report" / "charts" / "concurrency.png").exists())

    def test_step_label_disambiguates_repeated_concurrency(self) -> None:
        """Two plateaus landing on the SAME concurrent-client count must not
        collapse into one label -- see _step_label's docstring for the
        real-world scenario this guards against (a ramp back down to a
        level visited earlier)."""
        series = [(0.0, 5), (100.0, 10), (200.0, 5)]
        plateaus = scenario_report._detect_plateaus(series, run_end_ts=300.0, min_seconds=50.0)
        self.assertEqual(len(plateaus), 3)
        self.assertEqual([p["count"] for p in plateaus], [5, 10, 5])

        label_first = scenario_report._step_label(50.0, plateaus)
        label_second = scenario_report._step_label(250.0, plateaus)
        self.assertNotEqual(label_first, label_second)
        self.assertIn("5 clients", label_first)
        self.assertIn("5 clients", label_second)



if __name__ == "__main__":
    import unittest

    unittest.main()
