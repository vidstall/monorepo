from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cli.scenario import mini_report, system_log

from tests.scenario_test_base import ScenarioTestCase


def _iso(base: datetime, offset_seconds: float) -> str:
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _write_infra_file(run_dir: Path, instance_name: str, host: str, entries: list[tuple[float, float, float]], base: datetime) -> None:
    doc = {
        "identity": {"instance_name": instance_name, "host": host},
        "evaluation": [
            {
                "timestamp": _iso(base, offset),
                "interval_seconds": 5,
                "cpu": {"usage_percent": cpu},
                "memory": {"used_percent": mem},
            }
            for offset, cpu, mem in entries
        ],
    }
    path = run_dir / "infra" / f"{instance_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_worker_file(run_dir: Path, process_key: str, service: str, host: str) -> None:
    doc = {"identity": {"process_key": process_key, "service": service, "host": host}, "logging": []}
    path = run_dir / "worker" / f"{process_key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_user_file(run_dir: Path, room_id: str, peer_id: str, entries: list[tuple[float, dict]], base: datetime) -> None:
    doc = {
        "identity": {"room_id": room_id, "peer_id": peer_id},
        "metrics": [
            {"timestamp": _iso(base, offset), "interval_seconds": 5, "sample": sample} for offset, sample in entries
        ],
    }
    path = run_dir / "user" / f"{peer_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


class MiniReportTests(ScenarioTestCase):
    BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def test_generate_mini_log_aggregates_instances_roles_and_rooms(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "mini-test")
        run_dir = log.run_dir

        # Two colocated services (relay + cp-daemon) share host "001" --
        # their worker-role cpu/ram should both resolve to that one
        # instance's readings. relay-002 is a second, dedicated instance.
        _write_infra_file(run_dir, "digitalocean-001", "001", [(0, 20.0, 40.0), (5, 30.0, 50.0)], self.BASE)
        _write_infra_file(run_dir, "digitalocean-002", "002", [(0, 60.0, 70.0)], self.BASE)
        _write_worker_file(run_dir, "digitalocean-001-relay-1", "relay", "001")
        _write_worker_file(run_dir, "digitalocean-001-cp-daemon-1", "cp-daemon", "001")
        _write_worker_file(run_dir, "digitalocean-002-relay-1", "relay", "002")

        _write_user_file(
            run_dir,
            "r1",
            "peer1",
            [
                (0, {"latencyMs": 40.0, "packetLoss": 0.01, "jitterMs": 2.0, "bitrateUpKbps": 100.0, "bitrateDownKbps": 500.0, "framerate": 30.0, "resolutionWidth": 1280.0, "resolutionHeight": 720.0, "iceSuccess": 1.0, "reconnectMs": 250.0}),
                (5, {"latencyMs": 60.0, "packetLoss": 0.02, "jitterMs": 4.0, "bitrateUpKbps": 120.0, "bitrateDownKbps": 480.0, "framerate": 25.0, "resolutionWidth": 1280.0, "resolutionHeight": 720.0, "iceSuccess": 1.0}),
            ],
            self.BASE,
        )
        _write_user_file(
            run_dir,
            "r1",
            "peer2",
            [(0, {"latencyMs": 44.0})],
            self.BASE,
        )

        run_start_ms = int(self.BASE.timestamp() * 1000)
        run_end_ms = int((self.BASE.timestamp() + 10) * 1000)

        json_path = mini_report.generate_mini_log(log, "devnet", run_start_ms, run_end_ms)
        self.assertTrue(json_path.exists())
        self.assertTrue((run_dir / "mini_log.txt").exists())

        doc = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertAlmostEqual(doc["instances"]["digitalocean-001"]["cpu_percent"], 25.0)
        self.assertAlmostEqual(doc["instances"]["digitalocean-001"]["memory_percent"], 45.0)
        self.assertEqual(doc["instances"]["digitalocean-002"]["cpu_percent"], 60.0)

        # Both roles on host "001" share its (20,30) cpu readings -> avg 25.
        self.assertAlmostEqual(doc["worker_roles"]["cp-daemon"]["cpu_percent"], 25.0)
        # relay spans hosts 001 and 002 -> averaged across both instances' ticks.
        relay_cpu = doc["worker_roles"]["relay"]["cpu_percent"]
        self.assertAlmostEqual(relay_cpu, (20.0 + 30.0 + 60.0) / 3)

        room = doc["rooms"]["r1"]
        # latencyMs samples across both peers: 40, 60, 44 -> avg 48.
        self.assertAlmostEqual(room["avg_latency_ms"], 48.0)
        self.assertAlmostEqual(room["avg_frame_rate"], 27.5)
        self.assertAlmostEqual(room["avg_relay_failover_downtime_ms"], 250.0)
        # Bucket 0 (t=0s): peer1 + peer2 both present -> 2 participants.
        # Bucket 1 (t=5s): only peer1 -> 1 participant.
        buckets = {p["t_offset_seconds"]: p["participants"] for p in room["participants_by_time"]}
        self.assertEqual(buckets, {0: 2, 5: 1})

    def test_generate_mini_log_handles_empty_run_dir(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "mini-empty")
        run_start_ms = int(self.BASE.timestamp() * 1000)
        run_end_ms = int((self.BASE.timestamp() + 10) * 1000)
        json_path = mini_report.generate_mini_log(log, "devnet", run_start_ms, run_end_ms)
        doc = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["instances"], {})
        self.assertEqual(doc["worker_roles"], {})
        self.assertEqual(doc["rooms"], {})
