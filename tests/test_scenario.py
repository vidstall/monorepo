from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import bot_client, contract, context, image_bake, infra, observer, registry, scenario
from cli import object as object_cmd
from cli.registry import RegistryState
from cli.scenario import system_log, system_status
from cli.vidctl import build_parser

FAKE_WALLET = {"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SCENARIO_TOML = """
name = "baseline-devnet"
env = "devnet"

[[workers]]
host = "001"
service = "signaling"
provider = "digitalocean"
size = "s-1vcpu-1gb"

[[workers]]
host = "001"
service = "relay"
provider = "digitalocean"
size = "s-1vcpu-1gb"
"""

SCENARIO_TOML_ONE_INSTANCE = """
name = "baseline-devnet-small"
env = "devnet"

[[workers]]
host = "001"
service = "signaling"
provider = "digitalocean"
size = "s-1vcpu-1gb"
"""


class ScenarioTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.topology = self.root / "runtime" / "topology.toml"
        self.history = self.root / "runtime" / "history.toml"
        self.lock = self.root / "runtime" / "scenario.lock"
        self.contract_env = self.root / "runtime" / "contract" / "devnet.env"
        _write(
            self.contract_env,
            "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
        )
        self.scenario_dir = self.root / "scenario"
        self.scenario_dir.mkdir(parents=True, exist_ok=True)

        self.patches = [
            patch.object(infra, "RUNTIME_TOPOLOGY_TOML", self.topology),
            patch.object(infra, "RUNTIME_HISTORY_TOML", self.history),
            patch.object(infra, "contract_env_path", lambda _env: self.contract_env),
            patch.object(scenario, "contract_env_path", lambda _env: self.contract_env),
            patch.object(scenario, "RUNTIME_SCENARIO_LOCK", self.lock),
            patch.object(infra, "command_env", return_value={"DIGITALOCEAN_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "configure", return_value=0),
            patch.object(infra, "persist_vm_resolution", return_value=None),
            patch.object(infra, "GENERATED_INVENTORY", self.root / "runtime" / "hosts.generated.yml"),
            # No observer host registered by default -- apply()/destroy()'s
            # best-effort observer refresh/cleanup should be a silent no-op
            # for every test in this file unless a test explicitly registers
            # one. Isolated from the real repo's runtime/observer.toml so
            # these tests never depend on (or corrupt) real operator state.
            patch.object(context, "RUNTIME_OBSERVER_TOML", self.root / "runtime" / "observer.toml"),
            # set_vm_defaults()'s ensure_ssh_keypair() does real ssh-keygen
            # file I/O against SSH_KEY_ROOT regardless of the pulumi_up/
            # inventory/configure mocks above -- these scenarios use worker
            # host "node-1", which collides with a real deployed worker
            # host. Without this, running this suite regenerates the REAL
            # runtime/ssh_key/node-1 keypair, orphaning SSH access to an
            # actually-running droplet.
            patch.object(infra, "SSH_KEY_ROOT", self.root / "runtime" / "ssh_key"),
            patch.object(image_bake, "ensure_image", return_value=(True, "")),
            # Best-effort contract-state push to whichever observer host runs
            # pushgateway (see apply()'s _push_contract_state()) -- stubbed
            # for every test in this file by default, same rationale as the
            # observer-deploy stub above: no registered host means it's never
            # actually called, and tests that DO register one shouldn't pay
            # for a real wallet-pool/on-chain read against this fake env.
            patch.object(observer, "export_contract_state", return_value=0),
            # Isolated from the real repo's logs/ dir so `scenario.run()`
            # tests never write files outside this test's tempdir; the
            # snapshot itself is stubbed too since capture_system_snapshot()
            # would otherwise make real SSH/HTTP/on-chain calls against this
            # fake env on every action -- tests exercising the real snapshot
            # behavior patch this back per-test.
            patch.object(context, "LOGS_ROOT", self.root / "logs"),
            patch.object(system_log, "capture_system_snapshot", return_value={"stub": True}),
            patch("cli.wallet.checkout_wallet", return_value=(dict(FAKE_WALLET), False)),
            patch("cli.wallet.release_wallet", return_value=None),
            patch.object(contract, "publish", return_value=0),
            patch.object(registry, "publish", return_value=0),
            patch.object(registry, "login", return_value=0),
            patch.object(object_cmd, "publish", return_value=0),
            patch.object(
                registry,
                "read_runtime_registry",
                return_value=RegistryState(
                    provider="digitalocean",
                    host="registry.digitalocean.com",
                    prefix="registry.digitalocean.com/xaisen",
                    images={s: f"registry.digitalocean.com/xaisen/{s}" for s in infra.DOCKER_SERVICES},
                    deployed={s: "abc1234" for s in infra.DOCKER_SERVICES},
                    digests={},
                ),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def read_topology(self) -> dict:
        return infra.read_topology()

    def write_scenario(self, name: str, content: str) -> Path:
        path = self.scenario_dir / name
        _write(path, content)
        return path


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
            '[[workers]]\nhost = "002"\nservice = "signaling"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "signaling"\nprovider = "digitalocean"\n',
        )
        parsed = scenario.load_scenario(path)
        by_service = {row["service"]: row for row in parsed["workers"]}
        self.assertTrue(by_service["signaling"]["await"])
        # Sole worker on host "002" is deferred, so its auto-injected
        # node_exporter is deferred too.
        self.assertTrue(by_service["node_exporter"]["await"])

    def test_await_node_exporter_stays_eager_with_eager_sibling(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "signaling"\nprovider = "digitalocean"\n'
            '[[workers]]\nhost = "002"\nservice = "relay"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        parsed = scenario.load_scenario(path)
        by_service = {row["service"]: row for row in parsed["workers"]}
        self.assertFalse(by_service["signaling"]["await"])
        self.assertTrue(by_service["relay"]["await"])
        self.assertFalse(by_service["node_exporter"]["await"])

    def test_await_worker_without_matching_join_action_warns(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "signaling"\nprovider = "digitalocean"\nawait = true\n',
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            scenario.load_scenario(path)  # must not raise
        self.assertIn("await=true", buf.getvalue())

    def test_await_worker_with_explicit_host_join_action_no_warning(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "signaling"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'host = "002"\nservice = "signaling"\nprovider = "digitalocean"\n',
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            scenario.load_scenario(path)
        # The declared signaling worker itself has a matching join action,
        # so it must not be the one warned about (its co-located
        # node_exporter is a separate, expected warning of its own -- see
        # test_await_field_parses_and_flags_solo_node_exporter).
        self.assertNotIn("service=signaling", buf.getvalue())

    def test_await_worker_auto_match_unambiguous_no_warning(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\nname = "await-test"\n'
            '[[workers]]\nhost = "002"\nservice = "signaling"\nprovider = "digitalocean"\nawait = true\n'
            '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            'service = "signaling"\nprovider = "digitalocean"\n',
        )
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            scenario.load_scenario(path)
        self.assertNotIn("service=signaling", buf.getvalue())

    def test_out_of_order_timestamps_warn_not_error(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML
            + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+10s"\nhost = "001"\n'
            + '\n[[actions]]\ntype = "bot.create_room"\ntimestamp = "+1s"\nhost = "001"\n',
        )
        parsed = scenario.load_scenario(path)  # must not raise
        self.assertEqual(len(parsed["actions"]), 2)


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
            ("node-1", "signaling", "digitalocean", "devnet", 1): {},
        }
        current = {
            ("node-1", "signaling", "digitalocean", "devnet", 1): {},
            ("node-2", "relay", "digitalocean", "devnet", 1): {},
        }
        to_kill, to_start = scenario.diff_workers(wanted, current)
        self.assertEqual(to_kill, [("node-2", "relay", "digitalocean", "devnet", 1)])
        self.assertEqual(to_start, [("node-1", "signaling", "digitalocean", "devnet", 1)])


class ApplyTests(ScenarioTestCase):
    def test_apply_ensures_image_before_starting_workers(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(image_bake, "ensure_image", return_value=(True, "")) as ensure_image:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        # SCENARIO_TOML has two digitalocean workers with no explicit
        # region -- ensure_image should be called once per unique
        # (provider, region) pair, not once per worker.
        ensure_image.assert_called_once_with("digitalocean", None, force=False)

    def test_apply_parser_rebake_flag_defaults_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["scenario", "apply", "s.toml", "--yes"])
        self.assertFalse(args.rebake)

    def test_apply_parser_rebake_flag_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["scenario", "apply", "s.toml", "--yes", "--rebake"])
        self.assertTrue(args.rebake)

    def test_apply_rebake_forces_ensure_image(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(image_bake, "ensure_image", return_value=(True, "")) as ensure_image:
            code = scenario.apply(str(path), True, rebake=True)
        self.assertEqual(code, 0)
        ensure_image.assert_called_once_with("digitalocean", None, force=True)

    def test_apply_fails_when_image_bake_fails(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(image_bake, "ensure_image", return_value=(False, "bake blew up")):
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "active")
        # The workers should still have been started despite bake failure (best-effort).
        topology = self.read_topology()
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(topology.get("workers", [])), 3)

    def test_apply_passes_explicit_region_through_to_control(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML.replace(
                '[[workers]]\nhost = "001"\nservice = "signaling"',
                '[[workers]]\nhost = "001"\nservice = "signaling"\nregion = "sfo3"',
            ),
        )
        with (
            patch.object(image_bake, "ensure_image", return_value=(True, "")) as ensure_image,
            patch.object(infra, "control_many_hosts", wraps=infra.control_many_hosts) as control_many_hosts_spy,
        ):
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        ensure_image.assert_any_call("digitalocean", "sfo3", force=False)
        # Both workers are colocated on node-1@digitalocean, so apply()
        # batches them through control_many_hosts() instead of calling control() once per service.
        call_args, _call_kwargs = control_many_hosts_spy.call_args
        groups = call_args[1]
        workers = groups[0][2]
        signaling_row = next(r for r in workers if r["service"] == "signaling")
        self.assertEqual(signaling_row.get("region"), "sfo3")


    def test_apply_excludes_await_worker_from_provisioning(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML_ONE_INSTANCE
            + '\n[[workers]]\nhost = "002"\nservice = "relay"\nprovider = "digitalocean"\nawait = true\n'
            + '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            + 'host = "002"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        topology = self.read_topology()
        hosts = {row["host"] for row in topology.get("workers", [])}
        self.assertNotIn("002", hosts)
        self.assertIn("001", hosts)

    def test_apply_does_not_kill_worker_previously_started_via_join(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML_ONE_INSTANCE)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        # Re-declare the already-running host "001" signaling worker as
        # await=true (simulating a scenario file edited after the worker
        # was separately brought up e.g. via worker.join) and re-apply --
        # it must not be treated as drift and killed.
        v2 = self.write_scenario(
            "s.toml",
            SCENARIO_TOML_ONE_INSTANCE.replace(
                '[[workers]]\nhost = "001"\nservice = "signaling"\nprovider = "digitalocean"\nsize = "s-1vcpu-1gb"\n',
                '[[workers]]\nhost = "001"\nservice = "signaling"\nprovider = "digitalocean"\n'
                'size = "s-1vcpu-1gb"\nawait = true\n',
            )
            + '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            + 'host = "001"\nservice = "signaling"\nprovider = "digitalocean"\n',
        )
        code = scenario.apply(str(v2), True)
        self.assertEqual(code, 0)
        topology = self.read_topology()
        hosts = {row["host"] for row in topology.get("workers", [])}
        self.assertIn("001", hosts)

    def test_apply_creates_workers_and_locks(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        topology = self.read_topology()
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(topology["workers"]), 3)
        self.assertTrue(all(i["desired_state"] == "running" for i in topology["workers"]))

        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "active")
        self.assertEqual(lock["scenario_hash"], scenario.scenario_hash_of(path))

    def test_apply_refreshes_observer_stack_in_one_combined_call(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0) as observer_deploy:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        # observer.deploy(host=None) already covers every registered host in
        # one combined Ansible run -- apply() calls it once, not once per
        # registered host, to avoid paying a full playbook startup per host.
        observer_deploy.assert_called_once_with(None)

    def test_apply_skips_observer_refresh_when_none_registered(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy") as observer_deploy:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        observer_deploy.assert_not_called()

    def test_apply_survives_observer_refresh_failure(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", side_effect=RuntimeError("unreachable")):
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "active")

    def test_apply_pushes_contract_state_to_pushgateway_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            with patch.object(observer, "export_contract_state", return_value=0) as export_state:
                code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        export_state.assert_called_once_with("devnet", "bourbon")

    def test_apply_skips_contract_state_push_when_no_pushgateway_host(self) -> None:
        observer.add_host("vermouth", "1.2.3.4", "deploy", "/tmp/key", services=["tempo", "loki"])
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            with patch.object(observer, "export_contract_state") as export_state:
                code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        export_state.assert_not_called()

    def test_apply_skips_contract_state_push_when_none_registered(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "export_contract_state") as export_state:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        export_state.assert_not_called()

    def test_apply_survives_contract_state_push_failure(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            with patch.object(observer, "export_contract_state", side_effect=RuntimeError("unreachable")):
                code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "active")

    def test_apply_publishes_frontends_before_registry(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        with patch.object(object_cmd, "publish", return_value=0) as publish_frontend:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        publish_frontend.assert_called_once_with("site-2-bucket", "frontend", "alibaba")

    def test_apply_frontend_failure_stops_before_registry_and_workers(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        with (
            patch.object(object_cmd, "publish", return_value=1),
            patch.object(registry, "publish") as registry_publish,
        ):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        registry_publish.assert_not_called()
        self.assertEqual(scenario.read_lock()["status"], "failed")
        # Instance reconcile never started -- topology.toml isn't even
        # created yet (only ensure_topology(), reached during reconcile,
        # would create it).
        self.assertFalse(self.topology.exists())

    def test_apply_never_calls_object_delete(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        with patch.object(object_cmd, "delete") as delete_frontend:
            self.assertEqual(scenario.apply(str(path), True), 0)
            self.assertEqual(scenario.destroy(None), 0)
        delete_frontend.assert_not_called()

    def test_apply_logs_into_registry_when_provider_set(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML + '\n[registry]\nprovider = "digitalocean"\n')
        with patch.object(registry, "login", return_value=0) as login:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        login.assert_called_once_with("digitalocean")

    def test_apply_skips_registry_login_when_provider_unset(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(registry, "login", return_value=0) as login:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        login.assert_not_called()

    def test_apply_registry_login_failure_leaves_lock_failed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML + '\n[registry]\nprovider = "digitalocean"\n')
        with patch.object(registry, "login", return_value=1):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "failed")

    def test_apply_without_yes_is_refused(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        code = scenario.apply(str(path), False)
        self.assertEqual(code, 2)
        self.assertIsNone(scenario.read_lock())

    def test_reapply_same_scenario_allowed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        self.assertEqual(scenario.apply(str(path), True), 0)

    def test_apply_different_scenario_while_locked_is_blocked(self) -> None:
        path_a = self.write_scenario("a.toml", SCENARIO_TOML)
        path_b = self.write_scenario("b.toml", SCENARIO_TOML_ONE_INSTANCE)
        self.assertEqual(scenario.apply(str(path_a), True), 0)
        lock_before = scenario.read_lock()

        code = scenario.apply(str(path_b), True)
        self.assertNotEqual(code, 0)
        lock_after = scenario.read_lock()
        self.assertEqual(lock_before, lock_after)

    def test_reconcile_kills_dropped_worker_and_never_touches_objects(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(self.read_topology()["workers"]), 3)

        # Seed an [[objects]] row (frontend/object-storage) that must survive
        # every scenario apply/destroy untouched.
        topology = infra.read_topology()
        topology.setdefault("objects", []).append(
            {
                "name": "site-1-bucket",
                "object": "frontend",
                "provider": "alibaba",
                "env": "devnet",
                "backend": "object_storage",
                "desired_state": "running",
            }
        )
        infra.write_topology(topology)

        # Edit the SAME scenario path in place (drop the relay worker) and
        # re-apply it -- this is the intended drift-reconcile flow, since the
        # lock's identity check is by content hash, not path.
        self.write_scenario("s.toml", SCENARIO_TOML_ONE_INSTANCE)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        topology = self.read_topology()
        active = [i for i in topology["workers"] if i["desired_state"] != "deleted"]
        # signaling (still declared) + its auto-injected node_exporter --
        # relay was dropped, along with relay's OWN auto-injected instance
        # (SCENARIO_TOML_ONE_INSTANCE only declares one host, so there's
        # only ever one node_exporter for it either way).
        self.assertEqual(len(active), 2)
        self.assertEqual({i["service"] for i in active}, {"signaling", "node_exporter"})
        self.assertEqual(len(topology["objects"]), 1)
        self.assertEqual(topology["objects"][0]["name"], "site-1-bucket")

    def test_failure_mid_reconcile_leaves_lock_failed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(infra, "pulumi_up", return_value=1):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "failed")

    def test_contract_publish_failure_leaves_lock_failed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(contract, "publish", return_value=1):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "failed")


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
            "start", "009", "relay", "akamai", yes=True, size=None, worker_index=1, region=None
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
        control.assert_called_once_with("pause", "001", "relay", "akamai", yes=True, worker_index=1)

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
            "start", "002", "cp-daemon", "akamai", yes=True, size="g6-standard-4", worker_index=1, region="us-east"
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
            "start", "003", "cp-daemon", "akamai", yes=True, size=None, worker_index=1, region=None
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
            "start", "009", "relay", "akamai", yes=True, size=None, worker_index=1, region=None
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
            "restart", "001", "relay", "akamai", yes=True, worker_index=1
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
        registration_status.assert_called_with('instance=~".*1-2-3-4.*"')
        collect_infra.assert_called_with("1.2.3.4", system_status._SNAPSHOT_INTERVAL_SECONDS)
        collect_worker_app.assert_called_with("bot", 'instance=~".*1-2-3-4.*"')

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


if __name__ == "__main__":
    unittest.main()
