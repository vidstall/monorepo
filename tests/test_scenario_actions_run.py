from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cli import bot_client, infra, scenario

from tests.scenario_test_base import SCENARIO_TOML, SCENARIO_TOML_ONE_INSTANCE, ScenarioTestCase


class ActionsExecutionTests(ScenarioTestCase):
    """Unit-tests cli.scenario.actions.run_actions() directly, patching
    time.sleep/time.monotonic so tests don't actually wait, and bot_client/
    infra.control so no real HTTP/pulumi/ansible calls happen -- same
    "mock the boundary, assert the dispatch" style as ApplyTests above."""

    def setUp(self) -> None:
        super().setUp()
        self.sleep_patch = patch("cli.scenario.actions.time.sleep", return_value=None)
        self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    def _scenario(self, actions_toml: str) -> dict:
        path = self.write_scenario("s.toml", SCENARIO_TOML + "\n" + actions_toml)
        return scenario.load_scenario(path)

    def test_bot_create_room_dispatches(self) -> None:
        parsed = self._scenario(
            '[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        with patch.object(bot_client, "create_room", return_value={"botId": "b1", "roomId": "r1"}) as create_room:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        create_room.assert_called_once_with("001", "both", None)

    def test_bot_delete_room_resolves_id_reference(self) -> None:
        parsed = self._scenario(
            '[[actions]]\nid = "room1"\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
            '\n[[actions]]\ntype = "bot.delete_room"\ntimestamp = "+2s"\nhost = "001"\nbot_id = "$room1.botId"\n'
        )
        with (
            patch.object(bot_client, "create_room", return_value={"botId": "b1", "roomId": "r1"}),
            patch.object(bot_client, "delete_room", return_value={}) as delete_room,
        ):
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        delete_room.assert_called_once_with("001", "b1")

    def test_unresolved_reference_fails_cleanly(self) -> None:
        parsed = self._scenario(
            '[[actions]]\ntype = "bot.delete_room"\ntimestamp = "+1s"\nhost = "001"\nbot_id = "$missing.botId"\n'
        )
        code = scenario.run_actions(parsed, "devnet")
        self.assertNotEqual(code, 0)

    def test_bot_action_failure_stops_run(self) -> None:
        parsed = self._scenario(
            '[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
            '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+2s"\nhost = "001"\n'
        )
        with patch.object(bot_client, "create_room", return_value=None) as create_room:
            code = scenario.run_actions(parsed, "devnet")
        self.assertNotEqual(code, 0)
        create_room.assert_called_once()

    def test_worker_join_provisions_fresh_when_pool_empty(self) -> None:
        parsed = self._scenario(
            '[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'service = "relay"\nprovider = "akamai"\nhost = "009"\n'
        )
        with patch.object(infra, "control", return_value=0) as control:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        control.assert_called_once_with(
            "start", "009", "relay", "akamai", yes=True, size=None, worker_index=1, region=None, detach=True
        )

    def test_worker_join_without_host_and_empty_pool_fails(self) -> None:
        parsed = self._scenario(
            '[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\nservice = "relay"\nprovider = "akamai"\n'
        )
        code = scenario.run_actions(parsed, "devnet")
        self.assertNotEqual(code, 0)

    def test_worker_leave_pauses_worker(self) -> None:
        parsed = self._scenario(
            '[[actions]]\ntype = "worker.leave"\ntimestamp = "+1s"\n'
            'host = "001"\nservice = "relay"\nprovider = "akamai"\n'
        )
        with patch.object(infra, "control", return_value=0) as control:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        control.assert_called_once_with(
            "pause", "001", "relay", "akamai", yes=True, worker_index=1, detach=False, docker_only=True
        )

    def test_worker_join_matches_declared_await_worker_and_inherits_size_region(self) -> None:
        parsed = self._scenario(
            '[[workers]]\nhost = "002"\nservice = "cp-daemon"\nprovider = "akamai"\n'
            'size = "g6-standard-4"\nregion = "us-east"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "cp-daemon"\nprovider = "akamai"\n'
        )
        with patch.object(infra, "control", return_value=0) as control:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        control.assert_called_once_with(
            "start",
            "002",
            "cp-daemon",
            "akamai",
            yes=True,
            size="g6-standard-4",
            worker_index=1,
            region="us-east",
            detach=True,
        )

    def test_worker_join_auto_matches_declared_await_worker_when_unambiguous(self) -> None:
        parsed = self._scenario(
            '[[workers]]\nhost = "003"\nservice = "cp-daemon"\nprovider = "akamai"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'service = "cp-daemon"\nprovider = "akamai"\n'
        )
        with patch.object(infra, "control", return_value=0) as control:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        control.assert_called_once_with(
            "start", "003", "cp-daemon", "akamai", yes=True, size=None, worker_index=1, region=None, detach=True
        )

    def test_worker_join_ambiguous_declared_await_workers_fails_without_host(self) -> None:
        parsed = self._scenario(
            '[[workers]]\nhost = "003"\nservice = "cp-daemon"\nprovider = "akamai"\nawait = true\n'
            '[[workers]]\nhost = "004"\nservice = "cp-daemon"\nprovider = "akamai"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'service = "cp-daemon"\nprovider = "akamai"\n'
        )
        code = scenario.run_actions(parsed, "devnet")
        self.assertNotEqual(code, 0)

    def test_worker_join_ad_hoc_host_unmatched_by_any_declared_worker_still_works(self) -> None:
        # Backward-compat: a host given directly on the action that matches
        # no declared await=true worker behaves exactly as it did before
        # this feature -- a plain fresh provision with whatever the action
        # itself specifies.
        parsed = self._scenario(
            '[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'service = "relay"\nprovider = "akamai"\nhost = "009"\n'
        )
        with patch.object(infra, "control", return_value=0) as control:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        control.assert_called_once_with(
            "start", "009", "relay", "akamai", yes=True, size=None, worker_index=1, region=None, detach=True
        )

    def test_worker_join_reuses_pooled_worker_over_provisioning(self) -> None:
        topology = infra.ensure_topology("devnet")
        topology["workers"].append(
            {
                "host": "001",
                "service": "relay",
                "provider": "akamai",
                "env": "devnet",
                "worker_index": 1,
                "desired_state": "stopped",
            }
        )
        infra.write_topology(topology)

        parsed = self._scenario(
            '[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\nservice = "relay"\nprovider = "akamai"\n'
        )
        with patch.object(infra, "control", return_value=0) as control:
            code = scenario.run_actions(parsed, "devnet")
        self.assertEqual(code, 0)
        control.assert_called_once_with(
            "restart", "001", "relay", "akamai", yes=True, worker_index=1, detach=False, docker_only=True
        )


class RunTests(ScenarioTestCase):
    def test_run_without_yes_is_refused(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        code = scenario.run(str(path), False)
        self.assertEqual(code, 2)

    def test_run_without_active_lock_is_refused(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        code = scenario.run(str(path), True)
        self.assertEqual(code, 1)

    def test_run_against_different_locked_scenario_is_refused(self) -> None:
        actions_toml = '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        path_a = self.write_scenario("a.toml", SCENARIO_TOML + actions_toml)
        path_b = self.write_scenario("b.toml", SCENARIO_TOML_ONE_INSTANCE + actions_toml)
        self.assertEqual(scenario.apply(str(path_a), True), 0)

        code = scenario.run(str(path_b), True)
        self.assertEqual(code, 1)

    def test_run_executes_actions_against_active_scenario(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value={"botId": "b1"}) as create_room,
        ):
            code = scenario.run(str(path), True)
        self.assertEqual(code, 0)
        create_room.assert_called_once()

    def test_run_with_no_actions_is_a_noop(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        self.assertEqual(scenario.run(str(path), True), 0)

    def test_run_writes_system_log_with_expected_phases(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value={"botId": "b1"}),
        ):
            code = scenario.run(str(path), True)
        self.assertEqual(code, 0)

        run_dirs = list((self.root / "logs" / "s").glob("*"))
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]

        run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(run_doc["identity"]["run_started_at"])
        run_phases = [event["phase"] for event in run_doc["events"]]
        self.assertEqual(run_phases[0], "run_start")
        self.assertEqual(run_phases[-1], "run_end")

        action_files = list((run_dir / "actions").glob("*.json"))
        self.assertEqual(len(action_files), 1)
        action_doc = json.loads(action_files[0].read_text(encoding="utf-8"))
        action_phases = [event["phase"] for event in action_doc["events"]]
        self.assertIn("before_action", action_phases)
        self.assertIn("after_action", action_phases)
        after_action = next(event for event in action_doc["events"] if event["phase"] == "after_action")
        self.assertEqual(after_action["result"], {"botId": "b1"})
        self.assertGreaterEqual(after_action["duration_seconds"], 0)
        # Live markers carry no snapshot -- record_action_marker() never
        # queries Prometheus.
        self.assertNotIn("snapshot", after_action)

        # backfill_action_snapshots() (run.py's finally block) appends a
        # companion "<phase>_snapshot" event per live marker at run end.
        self.assertIn("before_action_snapshot", action_phases)
        self.assertIn("after_action_snapshot", action_phases)
        after_action_snapshot = next(
            event for event in action_doc["events"] if event["phase"] == "after_action_snapshot"
        )
        self.assertIn("snapshot", after_action_snapshot)
        self.assertIn("for_timestamp", after_action_snapshot)

    def test_run_fast_skips_per_action_snapshots(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value={"botId": "b1"}),
        ):
            code = scenario.run(str(path), True, True)
        self.assertEqual(code, 0)

        run_dirs = list((self.root / "logs" / "s").glob("*"))
        self.assertEqual(len(run_dirs), 1)
        run_dir = run_dirs[0]

        # run_start/run_end are still recorded (cheap, twice per run)...
        run_doc = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        run_phases = [event["phase"] for event in run_doc["events"]]
        self.assertEqual(run_phases, ["run_start", "run_end"])

        # ...but no per-action before_action/after_action snapshot ever gets
        # written, since run_actions() was handed system_log=None.
        action_files = list((run_dir / "actions").glob("*.json"))
        self.assertEqual(action_files, [])

    def test_run_mini_log_uses_reduced_resolution_and_skips_full_report(self) -> None:
        import importlib

        from cli.observer import grafana_render

        # cli.scenario/__init__.py does `from .run import run`, rebinding
        # cli.scenario.run to the FUNCTION -- importlib.import_module gets
        # the actual submodule object (run.py's own top-level names) so
        # patch.object can target the names run() actually calls.
        run_module = importlib.import_module("cli.scenario.run")

        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(run_module.time, "sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value={"botId": "b1"}),
            patch.object(run_module, "capture_dashboard_images", return_value=0) as capture,
            patch.object(run_module, "generate_mini_log", return_value=None) as gen_mini,
            patch.object(run_module, "generate_report") as gen_full,
        ):
            code = scenario.run(str(path), True, mini_log=True)
        self.assertEqual(code, 0)

        capture.assert_called_once()
        # width/height are the 4th/5th positional args to capture_dashboard_images.
        self.assertEqual(capture.call_args[0][3], grafana_render.MINI_PANEL_WIDTH)
        self.assertEqual(capture.call_args[0][4], grafana_render.MINI_PANEL_HEIGHT)
        gen_mini.assert_called_once()
        gen_full.assert_not_called()

    def test_run_without_mini_log_uses_full_resolution_and_report(self) -> None:
        import importlib

        from cli.observer import grafana_render

        # cli.scenario/__init__.py does `from .run import run`, rebinding
        # cli.scenario.run to the FUNCTION -- importlib.import_module gets
        # the actual submodule object (run.py's own top-level names) so
        # patch.object can target the names run() actually calls.
        run_module = importlib.import_module("cli.scenario.run")

        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(run_module.time, "sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value={"botId": "b1"}),
            patch.object(run_module, "capture_dashboard_images", return_value=0) as capture,
            patch.object(run_module, "generate_mini_log") as gen_mini,
            patch.object(run_module, "generate_report", return_value=Path("/tmp/report.md")) as gen_full,
        ):
            code = scenario.run(str(path), True)
        self.assertEqual(code, 0)

        self.assertEqual(capture.call_args[0][3], grafana_render.PANEL_WIDTH)
        self.assertEqual(capture.call_args[0][4], grafana_render.PANEL_HEIGHT)
        gen_full.assert_called_once()
        gen_mini.assert_not_called()

    def test_system_log_atomic_write_leaves_no_tmp_file(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value={"botId": "b1"}),
        ):
            scenario.run(str(path), True)

        tmp_files = list((self.root / "logs" / "s").rglob("*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_run_records_run_end_even_when_action_fails(self) -> None:
        path = self.write_scenario(
            "s.toml", SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
        )
        self.assertEqual(scenario.apply(str(path), True), 0)

        with (
            patch("cli.scenario.actions.time.sleep", return_value=None),
            patch.object(bot_client, "create_room", return_value=None),
        ):
            code = scenario.run(str(path), True)
        self.assertNotEqual(code, 0)

        run_dirs = list((self.root / "logs" / "s").glob("*"))
        self.assertEqual(len(run_dirs), 1)
        run_doc = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
        phases = [event["phase"] for event in run_doc["events"]]
        self.assertEqual(phases[-1], "run_end")

