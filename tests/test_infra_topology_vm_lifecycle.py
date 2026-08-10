from __future__ import annotations

import argparse
from unittest.mock import patch

from cli import infra
from cli.vidctl import build_parser

from tests.infra_topology_test_base import InfraTopologyTestCase


class VmLifecycleTests(InfraTopologyTestCase):
    def test_init_creates_topology_and_history(self) -> None:
            with patch.object(infra, "select_or_create_stack", return_value=0):
                code = infra.init("devnet")

            self.assertEqual(code, 0)
            topology = self.read_topology()
            self.assertEqual(topology["active_env"], "devnet")
            self.assertIn("aws", topology["providers"])
            self.assertIn("digitalocean", topology["providers"])
            self.assertIn("cloudflare", topology["providers"])
            self.assertEqual(self.read_history()["events"][0]["command"], "infra init")

    def test_vm_start_runs_pulumi_inventory_and_configure(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "relay",
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
                patch.object(infra, "inventory", return_value=0) as inventory,
                patch.object(infra, "configure", return_value=0) as configure,
            ):
                code = infra.control("start", "node-1", "relay", "digitalocean")

            self.assertEqual(code, 0)
            pulumi_up.assert_called_once_with("devnet")
            inventory.assert_called_once()
            configure.assert_called_once()
            self.assertEqual(configure.call_args.kwargs.get("host_limit"), "node-1")
            self.assertEqual(configure.call_args.kwargs.get("container_state"), "started")
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["backend"], "vm")
            self.assertEqual(worker["desired_state"], "running")
            self.assertEqual(worker["last_status"], "running")

    def test_upcloud_vm_start_runs_pulumi_inventory_and_configure(self) -> None:
            self.contract.write_text(
                "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
                encoding="utf-8",
            )
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [],
                }
            )

            with (
                patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
                patch.object(infra, "command_env", return_value={"UPCLOUD_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
                patch.object(infra, "inventory", return_value=0) as inventory,
                patch.object(infra, "configure", return_value=0) as configure,
            ):
                code = infra.control("start", "node-1", "cp-daemon", "upcloud")

            self.assertEqual(code, 0)
            pulumi_up.assert_called_once_with("devnet")
            inventory.assert_called_once()
            self.assertEqual(configure.call_args.kwargs["host_limit"], "node-1")
            self.assertEqual(configure.call_args.kwargs["container_state"], "started")
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["backend"], "vm")
            self.assertEqual(worker["desired_state"], "running")

    def test_upcloud_colocation_is_accepted_like_digitalocean(self) -> None:
            self.contract.write_text(
                "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
                encoding="utf-8",
            )
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "cp-daemon",
                            "provider": "upcloud",
                            "backend": "vm",
                            "worker_index": 1,
                            "desired_state": "running",
                        }
                    ],
                }
            )

            with (
                patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
                patch.object(infra, "command_env", return_value={"UPCLOUD_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0),
                patch.object(infra, "inventory", return_value=0),
                patch.object(infra, "configure", return_value=0),
            ):
                code = infra.control("start", "node-1", "relay", "upcloud")

            # A second, different service colocated on the same --host must be
            # accepted for upcloud (mirrors digitalocean), not rejected with the
            # "Colocating ... only supported for --provider digitalocean" error.
            self.assertEqual(code, 0)

    def test_akamai_vm_start_runs_pulumi_inventory_and_configure(self) -> None:
            self.contract.write_text(
                "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
                encoding="utf-8",
            )
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [],
                }
            )

            with (
                patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
                patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
                patch.object(infra, "inventory", return_value=0) as inventory,
                patch.object(infra, "configure", return_value=0) as configure,
            ):
                code = infra.control("start", "node-1", "cp-daemon", "akamai")

            self.assertEqual(code, 0)
            pulumi_up.assert_called_once_with("devnet")
            inventory.assert_called_once()
            self.assertEqual(configure.call_args.kwargs["host_limit"], "node-1")
            self.assertEqual(configure.call_args.kwargs["container_state"], "started")
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["backend"], "vm")
            self.assertEqual(worker["desired_state"], "running")

    def test_akamai_colocation_is_accepted_like_digitalocean(self) -> None:
            self.contract.write_text(
                "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
                encoding="utf-8",
            )
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "cp-daemon",
                            "provider": "akamai",
                            "backend": "vm",
                            "worker_index": 1,
                            "desired_state": "running",
                        }
                    ],
                }
            )

            with (
                patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
                patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0),
                patch.object(infra, "inventory", return_value=0),
                patch.object(infra, "configure", return_value=0),
            ):
                code = infra.control("start", "node-1", "relay", "akamai")

            # A second, different service colocated on the same --host must be
            # accepted for akamai (mirrors digitalocean/upcloud), not rejected
            # with the "Colocating ... only supported for" error.
            self.assertEqual(code, 0)

    def test_non_alibaba_pause_is_rejected_before_topology_change(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [],
                }
            )

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("pause", "node-1", "relay", "aws")

            self.assertEqual(code, 1)
            pulumi_up.assert_not_called()
            self.assertEqual(self.read_topology().get("workers", []), [])

    def test_inventory_failure_is_returned_after_successful_pulumi(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [],
                }
            )

            with (
                patch.object(infra, "pulumi_up", return_value=0),
                patch.object(infra, "inventory", return_value=7),
                patch.object(infra, "configure", return_value=0) as configure,
            ):
                code = infra.control("start", "node-1", "relay", "digitalocean")

            self.assertEqual(code, 7)
            configure.assert_not_called()
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["desired_state"], "running")
            self.assertIn("inventory failed", worker["last_error"])

    def test_configure_failure_is_returned_and_recorded(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [],
                }
            )

            with (
                patch.object(infra, "pulumi_up", return_value=0),
                patch.object(infra, "inventory", return_value=0),
                patch.object(infra, "configure", return_value=8),
            ):
                code = infra.control("start", "node-1", "relay", "digitalocean")

            self.assertEqual(code, 8)
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["desired_state"], "running")
            self.assertIn("configure failed", worker["last_error"])
            self.assertEqual(self.read_history()["events"][-1]["result"], "failure")

    def test_missing_contract_blocks_start(self) -> None:
            self.contract.write_text("", encoding="utf-8")
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [],
                }
            )

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("start", "node-1", "relay", "aws")

            self.assertEqual(code, 1)
            pulumi_up.assert_not_called()
            self.assertEqual(self.read_history()["events"][0]["result"], "failure")

    def test_kill_requires_yes(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [{"host": "node-1", "service": "relay", "provider": "aws"}],
                }
            )

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("kill", "node-1", "relay", "aws", yes=False)

            self.assertEqual(code, 2)
            pulumi_up.assert_not_called()

    def test_parser_accepts_nested_infra_lifecycle_command(self) -> None:
            parser = build_parser()
            args = parser.parse_args(["infra", "start", "--host", "node-1", "--service", "relay", "--provider", "digitalocean"])

            self.assertEqual(args.command, "infra")
            self.assertEqual(args.action, "start")
            self.assertEqual(args.host, "node-1")
            self.assertEqual(args.provider, "digitalocean")
            self.assertIsInstance(args, argparse.Namespace)

    def test_parser_rejects_top_level_lifecycle_command(self) -> None:
            parser = build_parser()

            with self.assertRaises(SystemExit):
                parser.parse_args(["start", "--host", "node-1", "--service", "relay", "--provider", "digitalocean"])

