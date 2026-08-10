from __future__ import annotations

import contextlib
import io
import unittest

from cli import scenario

from tests.scenario_test_base import SCENARIO_TOML, ScenarioTestCase


class LoadScenarioTests(ScenarioTestCase):
    def test_valid_scenario_parses(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        parsed = scenario.load_scenario(path)
        self.assertEqual(parsed["env"], "devnet")
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(parsed["workers"]), 3)

    def test_non_numeric_host_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n[[workers]]\nhost = "node-1"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_non_zero_padded_host_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n[[workers]]\nhost = "1"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_unknown_service_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n[[workers]]\nhost = "001"\nservice = "bogus"\nprovider = "digitalocean"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_unknown_provider_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n[[workers]]\nhost = "001"\nservice = "relay"\nprovider = "bogus"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_duplicate_worker_identity_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n'
            '[[workers]]\nhost = "001"\nservice = "relay"\nprovider = "digitalocean"\n'
            '[[workers]]\nhost = "001"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_empty_frontends_allowed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        parsed = scenario.load_scenario(path)
        self.assertEqual(parsed["frontends"], [])

    def test_frontends_parse(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        parsed = scenario.load_scenario(path)
        self.assertEqual(
            parsed["frontends"],
            [{"name": "site-2-bucket", "object": "frontend", "provider": "alibaba"}],
        )

    def test_frontend_unknown_object_type_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "n"\nobject = "bogus"\nprovider = "alibaba"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_frontend_unknown_provider_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "n"\nprovider = "bogus"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_registry_provider_optional(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        parsed = scenario.load_scenario(path)
        self.assertIsNone(parsed["registry"]["provider"])

        path2 = self.write_scenario("s2.toml", SCENARIO_TOML + '\n[registry]\nprovider = "digitalocean"\n')
        parsed2 = scenario.load_scenario(path2)
        self.assertEqual(parsed2["registry"]["provider"], "digitalocean")

    def test_empty_actions_allowed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        parsed = scenario.load_scenario(path)
        self.assertEqual(parsed["actions"], [])

    def test_actions_parse(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML
            + '\n[[actions]]\nid = "room1"\ntype = "bot.create_room"\ntimestamp = "+10s"\nhost = "001"\n'
            + '\n[[actions]]\ntype = "bot.delete_room"\ntimestamp = "+1m"\nhost = "001"\nbot_id = "$room1.botId"\n',
        )
        parsed = scenario.load_scenario(path)
        self.assertEqual(len(parsed["actions"]), 2)
        self.assertEqual(parsed["actions"][0]["offset_seconds"], 10)
        self.assertEqual(parsed["actions"][1]["offset_seconds"], 60)
        self.assertEqual(parsed["actions"][1]["bot_id"], "$room1.botId")

    def test_action_unknown_type_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[actions]]\ntype = "bogus"\ntimestamp = "+1s"\nhost = "001"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_action_bad_timestamp_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "10s"\nhost = "001"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_action_missing_required_field_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[actions]]\ntype = "bot.join_room"\ntimestamp = "+1s"\nhost = "001"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_duplicate_action_id_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML
            + '\n[[actions]]\nid = "a"\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n'
            + '\n[[actions]]\nid = "a"\ntype = "bot.create_room"\ntimestamp = "+2s"\nhost = "001"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_worker_join_leave_actions_parse(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML
            + '\n[[actions]]\ntype = "worker.leave"\ntimestamp = "+1s"\nhost = "001"\n'
            + 'service = "relay"\nprovider = "akamai"\n'
            + '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+2s"\n'
            + 'service = "relay"\nprovider = "akamai"\n',
        )
        parsed = scenario.load_scenario(path)
        self.assertEqual(parsed["actions"][0]["type"], "worker.leave")
        self.assertEqual(parsed["actions"][1]["type"], "worker.join")
        self.assertIsNone(parsed["actions"][1]["host"])

    def test_await_defaults_false(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        parsed = scenario.load_scenario(path)
        self.assertTrue(all(row["await"] is False for row in parsed["workers"]))

    def test_await_field_parses_and_flags_solo_node_exporter(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\n',
        )
        parsed = scenario.load_scenario(path)
        by_service = {row["service"]: row for row in parsed["workers"]}
        self.assertTrue(by_service["cp-daemon"]["await"])
        # Sole worker on host "002" is deferred, so its auto-injected
        # node_exporter is deferred too.
        self.assertTrue(by_service["node_exporter"]["await"])

    def test_await_node_exporter_stays_eager_with_eager_sibling(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\n'
            '[[workers]]\nhost = "002"\nservice = "relay"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        parsed = scenario.load_scenario(path)
        by_service = {row["service"]: row for row in parsed["workers"]}
        self.assertFalse(by_service["cp-daemon"]["await"])
        self.assertTrue(by_service["relay"]["await"])
        self.assertFalse(by_service["node_exporter"]["await"])

    def test_await_worker_without_matching_join_action_warns(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\nawait = true\n',
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            scenario.load_scenario(path)  # must not raise
        self.assertIn("await=true", buf.getvalue())

    def test_await_worker_with_explicit_host_join_action_no_warning(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\n',
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            scenario.load_scenario(path)
        # The declared cp-daemon worker itself has a matching join action,
        # so it must not be the one warned about (its co-located
        # node_exporter is a separate, expected warning of its own -- see
        # test_await_field_parses_and_flags_solo_node_exporter).
        self.assertNotIn("service=cp-daemon", buf.getvalue())

    def test_await_worker_auto_match_unambiguous_no_warning(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "cp-daemon"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'service = "cp-daemon"\nprovider = "digitalocean"\n',
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            scenario.load_scenario(path)
        self.assertNotIn("service=cp-daemon", buf.getvalue())

    def test_out_of_order_timestamps_warn_not_error(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML
            + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+10s"\nhost = "001"\n'
            + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n',
        )
        parsed = scenario.load_scenario(path)  # must not raise
        self.assertEqual(len(parsed["actions"]), 2)

