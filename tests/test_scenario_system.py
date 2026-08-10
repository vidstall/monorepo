from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from unittest.mock import patch

from cli import infra, observer
from cli.scenario import system_log, system_status

from tests.scenario_test_base import ScenarioTestCase


class SystemStatusTests(ScenarioTestCase):
    """Unit-tests cli.scenario.system_status.capture_system_snapshot()
    directly -- each subsystem it reads from is made to fail in isolation,
    confirming the snapshot always returns normally with {"error": ...} in
    the failed section instead of raising out of the function."""

    def test_capture_system_snapshot_survives_subsystem_failures(self) -> None:
        topology = infra.ensure_topology("devnet")
        topology["workers"].append(
            {
                "host": "002",
                "service": "bot",
                "provider": "akamai",
                "env": "devnet",
                "worker_index": 1,
                "desired_state": "started",
            }
        )
        infra.write_topology(topology)

        with (
            patch.object(
                system_status.metrics_worker, "registration_status", side_effect=Exception("registry prom boom")
            ),
            patch.object(system_status.metrics_infra, "collect_infra_evaluation", side_effect=Exception("prom boom")),
            patch.object(
                system_status.metrics_worker, "collect_worker_application", side_effect=Exception("bot prom boom")
            ),
            patch(
                "cli.observer.contract_exporter.collect_contract_state",
                side_effect=Exception("chain boom"),
            ),
        ):
            snapshot = system_status.capture_system_snapshot("devnet")

        self.assertEqual(snapshot["contract_state"], {"error": "chain boom"})
        bot_worker = next(w for w in snapshot["workers"] if w["service"] == "bot")
        self.assertEqual(bot_worker["registry_status"], {"error": "registry prom boom"})
        self.assertEqual(bot_worker["bot_sessions"], {"error": "bot prom boom"})
        self.assertEqual(bot_worker["hardware_network"], {"error": "prom boom"})

    def test_worker_snapshot_queries_prometheus_scoped_to_host(self) -> None:
        """_worker_snapshot() must route registry status, hardware/network,
        and bot-session data through cli.observer.metrics_worker/
        metrics_infra (the observation system) rather than SSH/HTTP, scoped
        to this worker's own address via an instance_filter -- not a
        fleet-wide query."""
        topology = infra.ensure_topology("devnet")
        topology["workers"].append(
            {
                "host": "002",
                "service": "bot",
                "provider": "akamai",
                "env": "devnet",
                "worker_index": 1,
                "desired_state": "started",
            }
        )
        infra.write_topology(topology)

        fake_hardware = {"cpu": {"usage_percent": 12.3}}
        fake_bot_application = {"sessions_active": 2.0}
        with (
            patch.object(
                system_status.metrics_worker, "registration_status", return_value=True
            ) as registration_status,
            patch.object(infra, "host_address", return_value="1.2.3.4"),
            patch.object(
                system_status.metrics_infra, "collect_infra_evaluation", return_value=fake_hardware
            ) as collect_infra,
            patch.object(
                system_status.metrics_worker, "collect_worker_application", return_value=fake_bot_application
            ) as collect_worker_app,
            patch(
                "cli.observer.contract_exporter.collect_contract_state",
                return_value=[],
            ),
        ):
            snapshot = system_status.capture_system_snapshot("devnet")

        bot_worker = next(w for w in snapshot["workers"] if w["service"] == "bot")
        self.assertEqual(bot_worker["registry_status"], True)
        self.assertEqual(bot_worker["hardware_network"], fake_hardware)
        self.assertEqual(bot_worker["bot_sessions"], fake_bot_application)
        registration_status.assert_called_with('instance=~".*1-2-3-4.*"', None)
        collect_infra.assert_called_with("1.2.3.4", system_status._SNAPSHOT_INTERVAL_SECONDS, None)
        collect_worker_app.assert_called_with("bot", 'instance=~".*1-2-3-4.*"', None)

    def test_workers_snapshot_includes_all_envs_and_states(self) -> None:
        topology = infra.ensure_topology("devnet")
        topology["workers"].append(
            {
                "host": "010",
                "service": "relay",
                "provider": "akamai",
                "env": "testnet",
                "worker_index": 1,
                "desired_state": "started",
            }
        )
        topology["workers"].append(
            {
                "host": "011",
                "service": "relay",
                "provider": "akamai",
                "env": "devnet",
                "worker_index": 1,
                "desired_state": "deleted",
            }
        )
        infra.write_topology(topology)

        with patch(
            "cli.observer.contract_exporter.collect_contract_state",
            return_value=[],
        ):
            snapshot = system_status.capture_system_snapshot("devnet")

        hosts = {w.get("host") for w in snapshot["workers"]}
        self.assertIn("010", hosts)  # a different env than "devnet"
        self.assertIn("011", hosts)  # desired_state == "deleted"

    def test_observer_hosts_included_in_snapshot(self) -> None:
        observer.add_host("bourbon", "203.0.113.9", "root", "/nonexistent/key")

        with (
            patch("cli.observer.contract_exporter.collect_contract_state", return_value=[]),
            patch.object(observer, "query", return_value=None),
        ):
            snapshot = system_status.capture_system_snapshot("devnet")

        self.assertEqual(len(snapshot["observer_hosts"]), 1)
        host_entry = snapshot["observer_hosts"][0]
        self.assertEqual(host_entry["name"], "bourbon")
        self.assertEqual(host_entry["address"], "203.0.113.9")
        self.assertIn("hardware_network", host_entry)

    def test_relay_quality_snapshot_parses_prometheus_result(self) -> None:
        fake_result = [
            {
                "metric": {"__name__": "dvconf_relay_peer_latency_ms", "roomId": "r1", "peerId": "p1"},
                "value": [1234.0, "42.5"],
            }
        ]
        with (
            patch.object(observer, "query", return_value=fake_result),
            patch("cli.observer.contract_exporter.collect_contract_state", return_value=[]),
        ):
            snapshot = system_status.capture_system_snapshot("devnet")

        self.assertEqual(len(snapshot["relay_quality"]), 1)
        sample = snapshot["relay_quality"][0]
        self.assertEqual(sample["metric"], "dvconf_relay_peer_latency_ms")
        self.assertEqual(sample["labels"], {"roomId": "r1", "peerId": "p1"})
        self.assertEqual(sample["value"], 42.5)

    def test_relay_quality_snapshot_survives_no_prometheus_host(self) -> None:
        with (
            patch.object(observer, "query", return_value=None),
            patch("cli.observer.contract_exporter.collect_contract_state", return_value=[]),
        ):
            snapshot = system_status.capture_system_snapshot("devnet")

        self.assertIn("error", snapshot["relay_quality"])


class SystemLogTests(ScenarioTestCase):
    """Unit-tests cli.scenario.system_log.DuringActionSampler in isolation,
    without going through a full scenario run."""

    def test_during_action_sampler_runs_and_stops(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "sampler-test")
        with patch.object(system_log, "SAMPLE_INTERVAL_SECONDS", 0.01):
            sampler = system_log.DuringActionSampler(log, "devnet", 0, "room1", "bot.create_room")
            sampler.start()
            time.sleep(0.05)
            sampler.stop()

        action_files = list((log.run_dir / "actions").glob("*.json"))
        self.assertEqual(len(action_files), 1)
        doc = json.loads(action_files[0].read_text())
        self.assertEqual(doc["identity"]["action_id"], "room1")

        during_events = [event for event in doc["events"] if event["phase"] == "during_action"]
        self.assertGreater(len(during_events), 0)
        for event in during_events:
            self.assertNotIn("snapshot", event)

    def test_record_action_marker_never_queries_prometheus(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "marker-test")
        with patch("cli.observer.query.query") as mock_query:
            system_log.record_action_marker(
                log, "before_action", action_index=0, action_id="a1", action_type="bot.create_room"
            )
            system_log.record_action_marker(
                log,
                "after_action",
                action_index=0,
                action_id="a1",
                action_type="bot.create_room",
                result={"botId": "b1"},
            )
        mock_query.assert_not_called()

        action_files = list((log.run_dir / "actions").glob("*.json"))
        self.assertEqual(len(action_files), 1)
        doc = json.loads(action_files[0].read_text())
        phases = [event["phase"] for event in doc["events"]]
        self.assertEqual(phases, ["before_action", "after_action"])
        for event in doc["events"]:
            self.assertNotIn("snapshot", event)

    def test_record_action_marker_noops_when_system_log_is_none(self) -> None:
        # Must not raise -- this is the --fast path (run_actions gets
        # system_log=None), exercised directly here rather than through a
        # full scenario run.
        system_log.record_action_marker(None, "before_action", action_index=0)

    def test_backfill_action_snapshots_queries_once_per_marker_at_recorded_time(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "backfill-test")
        system_log.record_action_marker(
            log, "before_action", action_index=0, action_id="a1", action_type="bot.create_room"
        )
        system_log.record_action_marker(
            log, "after_action", action_index=0, action_id="a1", action_type="bot.create_room", result={"ok": True}
        )

        action_files = list((log.run_dir / "actions").glob("*.json"))
        self.assertEqual(len(action_files), 1)
        doc_before = json.loads(action_files[0].read_text())
        recorded_timestamps = {event["phase"]: event["timestamp"] for event in doc_before["events"]}

        fake_snapshot = {"env": "devnet", "workers": []}
        with patch.object(system_log, "capture_system_snapshot", return_value=fake_snapshot) as mock_capture:
            backfilled = system_log.backfill_action_snapshots(log, "devnet")

        self.assertEqual(backfilled, 2)
        self.assertEqual(mock_capture.call_count, 2)
        called_at_times = sorted(call.kwargs["at_time"] for call in mock_capture.call_args_list)
        expected_at_times = sorted(datetime.fromisoformat(ts).timestamp() for ts in recorded_timestamps.values())
        self.assertEqual(called_at_times, expected_at_times)

        doc_after = json.loads(action_files[0].read_text())
        self.assertEqual(doc_after["identity"], {"action_index": 0, "action_id": "a1", "action_type": "bot.create_room"})
        snapshot_events = {
            event["phase"]: event for event in doc_after["events"] if event["phase"].endswith("_snapshot")
        }
        self.assertEqual(set(snapshot_events), {"before_action_snapshot", "after_action_snapshot"})
        for phase, marker_ts in recorded_timestamps.items():
            snap_event = snapshot_events[f"{phase}_snapshot"]
            self.assertEqual(snap_event["snapshot"], fake_snapshot)
            self.assertEqual(snap_event["for_timestamp"], marker_ts)

    def test_backfill_action_snapshots_is_noop_with_no_actions_dir(self) -> None:
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "empty-backfill-test")
        with patch.object(system_log, "capture_system_snapshot") as mock_capture:
            backfilled = system_log.backfill_action_snapshots(log, "devnet")
        self.assertEqual(backfilled, 0)
        mock_capture.assert_not_called()

    def test_backfill_action_snapshots_never_calls_capture_system_snapshot_concurrently(self) -> None:
        """Regression test for a real incident: backfill_action_snapshots()
        used to run its markers through its own ThreadPoolExecutor(16) on
        top of capture_system_snapshot()'s own internal 16-way fan-out per
        call, multiplying out to up to 256 concurrent Prometheus/Caddy
        connections and overwhelming a real observer host's TLS handshake
        capacity (a wall of `_ssl.c:993` timeout errors, confirmed live).
        Seeds many markers across many action files and asserts
        capture_system_snapshot is never entered while a previous call is
        still in flight -- i.e. markers are processed strictly
        sequentially, not through a second nested thread pool."""
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "concurrency-regression-test")
        marker_count = 40
        for index in range(marker_count):
            system_log.record_action_marker(
                log,
                "before_action",
                action_index=index,
                action_id=f"a{index}",
                action_type="bot.create_room",
            )

        in_flight = 0
        max_observed_in_flight = 0
        lock = threading.Lock()

        def fake_capture_system_snapshot(env: str, at_time: float | None = None) -> dict:
            nonlocal in_flight, max_observed_in_flight
            with lock:
                in_flight += 1
                max_observed_in_flight = max(max_observed_in_flight, in_flight)
            time.sleep(0.005)  # simulate real network latency, long enough to expose overlap
            with lock:
                in_flight -= 1
            return {"env": env}

        with patch.object(system_log, "capture_system_snapshot", side_effect=fake_capture_system_snapshot):
            backfilled = system_log.backfill_action_snapshots(log, "devnet")

        self.assertEqual(backfilled, marker_count)
        self.assertEqual(max_observed_in_flight, 1)

    def test_backfill_action_snapshots_survives_every_marker_erroring(self) -> None:
        """Simulates the exact failure mode from the log: every historical
        Prometheus query times out. Must not raise, and must still write a
        `{"error": ...}` snapshot event for each marker rather than losing
        it silently."""
        log = system_log.SystemLog("/tmp/fake.toml", "devnet", "all-errors-backfill-test")
        system_log.record_action_marker(
            log, "before_action", action_index=0, action_id="a1", action_type="bot.create_room"
        )
        system_log.record_action_marker(
            log, "after_action", action_index=0, action_id="a1", action_type="bot.create_room"
        )

        with patch.object(
            system_log,
            "capture_system_snapshot",
            side_effect=TimeoutError("_ssl.c:993: The handshake operation timed out"),
        ):
            backfilled = system_log.backfill_action_snapshots(log, "devnet")

        self.assertEqual(backfilled, 2)
        action_files = list((log.run_dir / "actions").glob("*.json"))
        doc = json.loads(action_files[0].read_text())
        snapshot_events = [event for event in doc["events"] if event["phase"].endswith("_snapshot")]
        self.assertEqual(len(snapshot_events), 2)
        for event in snapshot_events:
            self.assertIn("error", event["snapshot"])
            self.assertIn("handshake", event["snapshot"]["error"])

