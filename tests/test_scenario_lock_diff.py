from __future__ import annotations

import unittest

from cli import scenario

from tests.scenario_test_base import SCENARIO_TOML, ScenarioTestCase


class LockTests(ScenarioTestCase):
    def test_round_trip(self) -> None:
        self.assertIsNone(scenario.read_lock())
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "active")
        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "active")
        self.assertEqual(lock["scenario_hash"], "sha256:abc")
        scenario.clear_lock()
        self.assertIsNone(scenario.read_lock())

    def test_applied_at_preserved_on_same_hash_reapply(self) -> None:
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "active")
        first = scenario.read_lock()["applied_at"]
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "active")
        second = scenario.read_lock()["applied_at"]
        self.assertEqual(first, second)

    def test_applied_at_resets_on_different_path(self) -> None:
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "active")
        first = scenario.read_lock()["applied_at"]
        scenario.write_lock("scenario/other.toml", "sha256:def", "devnet", "applying")
        second = scenario.read_lock()["applied_at"]
        self.assertNotEqual(first, second)

    def test_hash_stable_and_content_sensitive(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        h1 = scenario.scenario_hash_of(path)
        h2 = scenario.scenario_hash_of(path)
        self.assertEqual(h1, h2)
        path.write_text(SCENARIO_TOML + "\n# comment\n", encoding="utf-8")
        h3 = scenario.scenario_hash_of(path)
        self.assertNotEqual(h1, h3)


class DiffWorkersTests(unittest.TestCase):
    def test_kill_and_start_sets(self) -> None:
        wanted = {
            ("node-1", "cp-daemon", "digitalocean", "devnet", 1): {},
        }
        current = {
            ("node-1", "cp-daemon", "digitalocean", "devnet", 1): {},
            ("node-2", "relay", "digitalocean", "devnet", 1): {},
        }
        to_kill, to_start = scenario.diff_workers(wanted, current)
        self.assertEqual(to_kill, [("node-2", "relay", "digitalocean", "devnet", 1)])
        self.assertEqual(to_start, [("node-1", "cp-daemon", "digitalocean", "devnet", 1)])
