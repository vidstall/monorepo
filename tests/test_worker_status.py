from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import context, infra, worker_status


class ParseWorkerHostnameTests(unittest.TestCase):
    def test_parses_full_sslip_hostname(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-003-signaling-1.96-126-106-95.sslip.io")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.provider, "akamai")
        self.assertEqual(ref.host, "003")
        self.assertEqual(ref.service, "signaling")
        self.assertEqual(ref.index, 1)
        self.assertEqual(ref.container_name, "xaisen-akamai-003-signaling-1")

    def test_parses_multi_word_service(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-001-validator-daemon-1.1-2-3-4.sslip.io")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.service, "validator-daemon")

    def test_rejects_unparseable_hostname(self) -> None:
        self.assertIsNone(worker_status.parse_worker_hostname("not-a-worker"))


class LivenessEventRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "worker_liveness.toml"
        self.patch = patch.object(context, "RUNTIME_WORKER_LIVENESS_TOML", self.toml_path)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(worker_status._read_liveness_events(), [])

    def test_round_trip_preserves_fields(self) -> None:
        event = worker_status.LivenessEvent(
            event_id="abc123",
            worker="akamai-003-relay-1",
            stopped_at="2026-08-07T08:00:00+00:00",
            started_at="2026-08-07T08:00:05+00:00",
            resolved=True,
        )
        worker_status._write_liveness_events([event])
        [loaded] = worker_status._read_liveness_events()
        self.assertEqual(loaded, event)

    def test_open_event_ignores_resolved_events(self) -> None:
        resolved = worker_status.LivenessEvent(
            event_id="old", worker="w1", stopped_at="t1", started_at="t2", resolved=True
        )
        open_event = worker_status.LivenessEvent(event_id="new", worker="w1", stopped_at="t3")
        events = [resolved, open_event]
        found = worker_status._open_liveness_event(events, "w1")
        self.assertEqual(found, open_event)

    def test_open_event_none_when_no_match(self) -> None:
        events = [worker_status.LivenessEvent(event_id="a", worker="other", stopped_at="t")]
        self.assertIsNone(worker_status._open_liveness_event(events, "w1"))


class RecordLivenessEventTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.toml_path = Path(self.temp.name) / "worker_liveness.toml"
        self.patch = patch.object(context, "RUNTIME_WORKER_LIVENESS_TOML", self.toml_path)
        self.patch.start()
        self.push_patch = patch("cli.observer.pushgateway.push_samples", return_value=0)
        self.push_mock = self.push_patch.start()

    def tearDown(self) -> None:
        self.push_patch.stop()
        self.patch.stop()
        self.temp.cleanup()

    def test_stop_opens_a_new_unresolved_event(self) -> None:
        at_iso = infra.timestamp()
        worker_status._record_liveness_event("akamai-003-relay-1", "stop", at_iso)
        events = worker_status._read_liveness_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].worker, "akamai-003-relay-1")
        self.assertFalse(events[0].resolved)
        self.assertEqual(events[0].stopped_at, at_iso)
        self.push_mock.assert_called_once()

    def test_start_resolves_the_matching_open_event(self) -> None:
        worker_status._record_liveness_event("akamai-003-relay-1", "stop", infra.timestamp())
        started_at_iso = infra.timestamp()
        worker_status._record_liveness_event("akamai-003-relay-1", "start", started_at_iso)
        [event] = worker_status._read_liveness_events()
        self.assertTrue(event.resolved)
        self.assertEqual(event.started_at, started_at_iso)
        self.assertEqual(self.push_mock.call_count, 2)

    def test_start_with_no_open_event_is_a_no_op(self) -> None:
        worker_status._record_liveness_event("akamai-003-relay-1", "start", infra.timestamp())
        self.assertEqual(worker_status._read_liveness_events(), [])
        self.push_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
