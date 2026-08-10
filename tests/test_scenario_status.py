from __future__ import annotations

from unittest.mock import patch

from cli import observer, scenario

from tests.scenario_test_base import SCENARIO_TOML, ScenarioTestCase


class StatusDestroyTests(ScenarioTestCase):
    def test_status_with_no_lock(self) -> None:
        self.assertEqual(scenario.status(None), 0)

    def test_destroy_with_no_lock_is_noop(self) -> None:
        self.assertEqual(scenario.destroy(None), 0)

    def test_destroy_kills_all_workers_and_clears_lock(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)

        code = scenario.destroy(None)
        self.assertEqual(code, 0)
        self.assertIsNone(scenario.read_lock())

        topology = self.read_topology()
        active = [i for i in topology["workers"] if i["desired_state"] != "deleted"]
        self.assertEqual(active, [])

    def test_status_reports_active_scenario(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        self.assertEqual(scenario.status(None), 0)

    def test_destroy_cleans_observer_stack_for_each_registered_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            self.assertEqual(scenario.apply(str(path), True), 0)

        with patch.object(observer, "clean", return_value=0) as observer_clean:
            code = scenario.destroy(None)
        self.assertEqual(code, 0)
        observer_clean.assert_called_once_with("bourbon")
        self.assertIsNone(scenario.read_lock())

    def test_destroy_skips_observer_cleanup_when_none_registered(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)

        with patch.object(observer, "clean") as observer_clean:
            code = scenario.destroy(None)
        self.assertEqual(code, 0)
        observer_clean.assert_not_called()

    def test_destroy_survives_observer_cleanup_failure(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            self.assertEqual(scenario.apply(str(path), True), 0)

        with patch.object(observer, "clean", side_effect=RuntimeError("unreachable")):
            code = scenario.destroy(None)
        self.assertEqual(code, 0)
        self.assertIsNone(scenario.read_lock())


class GuardManualInfraTests(ScenarioTestCase):
    def test_guard_allows_when_unlocked(self) -> None:
        self.assertIsNone(scenario.guard_manual_infra("start"))

    def test_guard_blocks_when_locked(self) -> None:
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "active")
        self.assertEqual(scenario.guard_manual_infra("start"), 3)

    def test_guard_ignores_failed_status(self) -> None:
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "failed")
        self.assertIsNone(scenario.guard_manual_infra("start"))

