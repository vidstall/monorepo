from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import contract, infra, registry, scenario
from cli.registry import RegistryState

FAKE_WALLET = {"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


SCENARIO_TOML = """
name = "baseline-devnet"
env = "devnet"

[[instances]]
name = "node-1"
service = "signaling"
provider = "digitalocean"
size = "s-1vcpu-1gb"

[[instances]]
name = "node-1"
service = "relay"
provider = "digitalocean"
size = "s-1vcpu-1gb"
"""

SCENARIO_TOML_ONE_INSTANCE = """
name = "baseline-devnet-small"
env = "devnet"

[[instances]]
name = "node-1"
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
            patch("cli.wallet.checkout_wallet", return_value=(dict(FAKE_WALLET), False)),
            patch("cli.wallet.release_wallet", return_value=None),
            patch.object(contract, "publish", return_value=0),
            patch.object(registry, "publish", return_value=0),
            patch.object(
                registry,
                "read_runtime_registry",
                return_value=RegistryState(
                    provider="digitalocean",
                    host="registry.digitalocean.com",
                    prefix="registry.digitalocean.com/xaisen",
                    images={s: f"registry.digitalocean.com/xaisen/{s}" for s in infra.DOCKER_SERVICES},
                    deployed={s: "abc1234" for s in infra.DOCKER_SERVICES},
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
        self.assertEqual(len(parsed["instances"]), 2)

    def test_unknown_service_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n[[instances]]\nname = "n"\nservice = "bogus"\nprovider = "digitalocean"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_unknown_provider_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n[[instances]]\nname = "n"\nservice = "relay"\nprovider = "bogus"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)

    def test_duplicate_instance_identity_rejected(self) -> None:
        path = self.write_scenario(
            "s.toml",
            'env = "devnet"\n'
            '[[instances]]\nname = "n"\nservice = "relay"\nprovider = "digitalocean"\n'
            '[[instances]]\nname = "n"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        with self.assertRaises(ValueError):
            scenario.load_scenario(path)


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


class DiffInstancesTests(unittest.TestCase):
    def test_kill_and_start_sets(self) -> None:
        wanted = {
            ("node-1", "signaling", "digitalocean", "devnet", 1): {},
        }
        current = {
            ("node-1", "signaling", "digitalocean", "devnet", 1): {},
            ("node-2", "relay", "digitalocean", "devnet", 1): {},
        }
        to_kill, to_start = scenario.diff_instances(wanted, current)
        self.assertEqual(to_kill, [("node-2", "relay", "digitalocean", "devnet", 1)])
        self.assertEqual(to_start, [("node-1", "signaling", "digitalocean", "devnet", 1)])


class ApplyTests(ScenarioTestCase):
    def test_apply_creates_instances_and_locks(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        topology = self.read_topology()
        self.assertEqual(len(topology["instances"]), 2)
        self.assertTrue(all(i["desired_state"] == "running" for i in topology["instances"]))

        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "active")
        self.assertEqual(lock["scenario_hash"], scenario.scenario_hash_of(path))

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

    def test_reconcile_kills_dropped_instance_and_never_touches_objects(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        self.assertEqual(len(self.read_topology()["instances"]), 2)

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

        # Edit the SAME scenario path in place (drop the relay instance) and
        # re-apply it -- this is the intended drift-reconcile flow, since the
        # lock's identity check is by content hash, not path.
        self.write_scenario("s.toml", SCENARIO_TOML_ONE_INSTANCE)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        topology = self.read_topology()
        active = [i for i in topology["instances"] if i["desired_state"] != "deleted"]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["service"], "signaling")
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

    def test_destroy_kills_all_instances_and_clears_lock(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)

        code = scenario.destroy(None)
        self.assertEqual(code, 0)
        self.assertIsNone(scenario.read_lock())

        topology = self.read_topology()
        active = [i for i in topology["instances"] if i["desired_state"] != "deleted"]
        self.assertEqual(active, [])

    def test_status_reports_active_scenario(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        self.assertEqual(scenario.status(None), 0)


class GuardManualInfraTests(ScenarioTestCase):
    def test_guard_allows_when_unlocked(self) -> None:
        self.assertIsNone(scenario.guard_manual_infra("start"))

    def test_guard_blocks_when_locked(self) -> None:
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "active")
        self.assertEqual(scenario.guard_manual_infra("start"), 3)

    def test_guard_ignores_failed_status(self) -> None:
        scenario.write_lock("scenario/s.toml", "sha256:abc", "devnet", "failed")
        self.assertIsNone(scenario.guard_manual_infra("start"))


if __name__ == "__main__":
    unittest.main()
