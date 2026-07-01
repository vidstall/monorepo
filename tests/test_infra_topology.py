from __future__ import annotations

import argparse
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import infra
from cli.vidctl import build_parser


class InfraTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.topology = self.root / "runtime" / "topology.toml"
        self.history = self.root / "runtime" / "history.toml"
        self.contract = self.root / "runtime" / "contract" / "devnet.env"
        self.contract.parent.mkdir(parents=True, exist_ok=True)
        self.contract.write_text(
            "CONTRACT_PACKAGE_ID=0xpackage\nCONTRACT_REGISTRY_OBJECT_ID=0xregistry\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(infra, "RUNTIME_TOPOLOGY_TOML", self.topology),
            patch.object(infra, "RUNTIME_HISTORY_TOML", self.history),
            patch.object(infra, "contract_env_path", lambda _env: self.contract),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temp.cleanup()

    def read_topology(self) -> dict:
        return tomllib.loads(self.topology.read_text(encoding="utf-8"))

    def read_history(self) -> dict:
        return tomllib.loads(self.history.read_text(encoding="utf-8"))

    def test_init_creates_topology_and_history(self) -> None:
        with patch.object(infra, "select_or_create_stack", return_value=0):
            code = infra.init("devnet")

        self.assertEqual(code, 0)
        topology = self.read_topology()
        self.assertEqual(topology["active_env"], "devnet")
        self.assertEqual(topology["contract_env"], "runtime/contract/devnet.env")
        self.assertIn("aws", topology["providers"])
        self.assertIn("digitalocean", topology["providers"])
        self.assertEqual(self.read_history()["events"][0]["command"], "infra init")

    def test_start_updates_topology_runs_pulumi_and_records_history(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "node-1",
                        "service": "routes",
                        "provider": "digitalocean",
                        "resource_id": "droplet-1",
                        "address": "192.0.2.10",
                        "desired_state": "stopped",
                    }
                ],
            }
        )

        with (
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "configure", return_value=0),
        ):
            code = infra.control("start", "node-1", "routes", "digitalocean")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet")
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "running")
        self.assertEqual(instance["last_status"], "running")
        event = self.read_history()["events"][0]
        self.assertEqual(event["command"], "start")
        self.assertEqual(event["provider"], "digitalocean")

    def test_start_requires_contract_env(self) -> None:
        self.contract.unlink()
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [{"name": "node-1", "service": "routes", "provider": "aws"}],
            }
        )

        with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
            code = infra.control("start", "node-1", "routes", "aws")

        self.assertEqual(code, 1)
        pulumi_up.assert_not_called()
        self.assertEqual(self.read_history()["events"][0]["result"], "failure")

    def test_kill_requires_yes(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [{"name": "node-1", "service": "routes", "provider": "aws"}],
            }
        )

        with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
            code = infra.control("kill", "node-1", "routes", "aws", yes=False)

        self.assertEqual(code, 2)
        pulumi_up.assert_not_called()

    def test_parser_accepts_top_level_lifecycle_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["start", "--name", "node-1", "--service", "routes", "--provider", "digitalocean"])

        self.assertEqual(args.command, "start")
        self.assertEqual(args.name, "node-1")
        self.assertEqual(args.provider, "digitalocean")
        self.assertIsInstance(args, argparse.Namespace)


if __name__ == "__main__":
    unittest.main()
