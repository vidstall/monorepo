from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import tomllib
import unittest
from types import ModuleType, SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from cli import infra
from cli import context
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
            # persist_vm_resolution shells out to `pulumi stack output` for
            # every provider now (generalized from alibaba-only); no test
            # here exercises its real behavior, so mock it out uniformly.
            patch.object(infra, "persist_vm_resolution", return_value=None),
            # Isolate from any real generated inventory left on disk by a
            # manual `vidctl` run -- without this, instance_address()/
            # registry_status() can pick up a real stale IP and attempt a
            # real (slow, timing-out) SSH connection.
            patch.object(infra, "GENERATED_INVENTORY", self.root / "runtime" / "hosts.generated.yml"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
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
            patch.object(infra, "inventory", return_value=0) as inventory,
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("start", "node-1", "routes", "digitalocean")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet")
        inventory.assert_called_once()
        configure.assert_called_once_with(host_limit="node-1", container_state="started")
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["backend"], "vm")
        self.assertEqual(instance["desired_state"], "running")
        self.assertEqual(instance["last_status"], "running")

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
                "instances": [],
            }
        )

        with (
            patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
            patch.object(infra, "command_env", return_value={"UPCLOUD_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
            patch.object(infra, "inventory", return_value=0) as inventory,
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("start", "node-1", "signaling", "upcloud")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet")
        inventory.assert_called_once()
        self.assertEqual(configure.call_args.kwargs["host_limit"], "node-1")
        self.assertEqual(configure.call_args.kwargs["container_state"], "started")
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["backend"], "vm")
        self.assertEqual(instance["desired_state"], "running")

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
                "instances": [
                    {
                        "name": "node-1",
                        "service": "signaling",
                        "provider": "upcloud",
                        "backend": "vm",
                        "instance_index": 1,
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

        # A second, different service colocated on the same --name must be
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
                "instances": [],
            }
        )

        with (
            patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
            patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
            patch.object(infra, "inventory", return_value=0) as inventory,
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("start", "node-1", "signaling", "akamai")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet")
        inventory.assert_called_once()
        self.assertEqual(configure.call_args.kwargs["host_limit"], "node-1")
        self.assertEqual(configure.call_args.kwargs["container_state"], "started")
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["backend"], "vm")
        self.assertEqual(instance["desired_state"], "running")

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
                "instances": [
                    {
                        "name": "node-1",
                        "service": "signaling",
                        "provider": "akamai",
                        "backend": "vm",
                        "instance_index": 1,
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

        # A second, different service colocated on the same --name must be
        # accepted for akamai (mirrors digitalocean/upcloud), not rejected
        # with the "Colocating ... only supported for" error.
        self.assertEqual(code, 0)

    def test_akamai_pause_powers_off_without_ansible(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "node-1",
                        "service": "signaling",
                        "provider": "akamai",
                        "backend": "vm",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with (
            patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
            patch.object(infra, "inventory", return_value=0) as inventory,
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("pause", "node-1", "signaling", "akamai")

        self.assertEqual(code, 0)
        # Unlike alibaba, akamai has no targeted-apply machinery -- pause
        # goes through the plain untargeted pulumi_up(env_name) call.
        pulumi_up.assert_called_once_with("devnet")
        inventory.assert_not_called()
        configure.assert_not_called()
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "stopped")
        self.assertEqual(instance["last_status"], "stopped")

    def test_akamai_restart_reconfigures_and_restarts_container(self) -> None:
        self.contract.write_text(
            "CONTRACT_PACKAGE_ID=0xpackage\nNETWORK_REGISTRY_ID=0xregistry\n",
            encoding="utf-8",
        )
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "node-1",
                        "service": "signaling",
                        "provider": "akamai",
                        "backend": "vm",
                        "desired_state": "stopped",
                    }
                ],
            }
        )

        with (
            patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
            patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("restart", "node-1", "signaling", "akamai")

        self.assertEqual(code, 0)
        self.assertEqual(configure.call_args.kwargs["host_limit"], "node-1")
        self.assertEqual(configure.call_args.kwargs["container_state"], "restarted")
        self.assertEqual(self.read_topology()["instances"][0]["last_status"], "running")

    def test_alibaba_pause_powers_off_without_ansible(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "node-1",
                        "service": "routes",
                        "provider": "alibaba",
                        "backend": "vm",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with (
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
            patch.object(infra, "inventory", return_value=0) as inventory,
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("pause", "node-1", "routes", "alibaba")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with(
            "devnet",
            targets=infra.alibaba_vm_target_urns("devnet", "node-1", "routes", False),
        )
        inventory.assert_not_called()
        configure.assert_not_called()
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "stopped")
        self.assertEqual(instance["last_status"], "stopped")

    def test_alibaba_restart_reconfigures_and_restarts_container(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "node-1",
                        "service": "routes",
                        "provider": "alibaba",
                        "backend": "vm",
                        "desired_state": "stopped",
                    }
                ],
            }
        )

        with (
            patch.object(infra, "command_env", return_value={
                "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                "ALIBABA_CLOUD_REGION": "cn-hangzhou",
            }),
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("restart", "node-1", "routes", "alibaba")

        self.assertEqual(code, 0)
        configure.assert_called_once_with(host_limit="node-1", container_state="restarted")
        self.assertEqual(self.read_topology()["instances"][0]["last_status"], "running")

    def test_inventory_failure_is_returned_after_successful_pulumi(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
            }
        )

        with (
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=7),
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("start", "node-1", "routes", "digitalocean")

        self.assertEqual(code, 7)
        configure.assert_not_called()
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "running")
        self.assertIn("inventory failed", instance["last_error"])

    def test_configure_failure_is_returned_and_recorded(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
            }
        )

        with (
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "configure", return_value=8),
        ):
            code = infra.control("start", "node-1", "routes", "digitalocean")

        self.assertEqual(code, 8)
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "running")
        self.assertIn("configure failed", instance["last_error"])
        self.assertEqual(self.read_history()["events"][-1]["result"], "failure")

    def test_non_alibaba_pause_is_rejected_before_topology_change(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
            }
        )

        with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
            code = infra.control("pause", "node-1", "routes", "aws")

        self.assertEqual(code, 1)
        pulumi_up.assert_not_called()
        self.assertEqual(self.read_topology().get("instances", []), [])

    def test_pulumi_up_targets_only_selected_instance(self) -> None:
        with (
            patch.object(infra, "command_env", return_value={}),
            patch.object(infra, "run", return_value=0) as run,
        ):
            targets = infra.alibaba_vm_target_urns("devnet", "routes-1", "routes", True)
            code = infra.pulumi_up("devnet", targets=targets)

        self.assertEqual(code, 0)
        args = run.call_args.args[0]
        self.assertIn("--target", args)
        self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/instance:Instance::routes-1-vm", args)
        self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:vpc/switch:Switch::routes-1-vm-vswitch", args)
        self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::routes-1-vm-sg-http", args)
        self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::routes-1-vm-sg-https", args)
        self.assertNotIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::routes-1-vm-sg-port", args)

        with (
            patch.object(infra, "command_env", return_value={}),
            patch.object(infra, "run", return_value=0) as run,
        ):
            targets = infra.alibaba_vm_target_urns("devnet", "coordinator-1", "coordinator", True)
            code = infra.pulumi_up("devnet", targets=targets)

        self.assertEqual(code, 0)
        args = run.call_args.args[0]
        self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::coordinator-1-vm-sg-port", args)

    def test_frontend_start_builds_and_skips_ansible(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
            }
        )

        with (
            patch.object(
                infra,
                "command_env",
                return_value={
                    "CLOUDFLARE_API_TOKEN": "token",
                    "CLOUDFLARE_ACCOUNT_ID": "account",
                    "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                },
            ),
            patch.object(infra, "build_frontend_static", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
            patch.object(infra, "inventory", return_value=0) as inventory,
            patch.object(infra, "configure", return_value=0) as configure,
        ):
            code = infra.control("start", "site-1", "frontend", "cloudflare")

        self.assertEqual(code, 0)
        build.assert_called_once_with("devnet")
        pulumi_up.assert_called_once_with("devnet")
        inventory.assert_not_called()
        configure.assert_not_called()
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["backend"], "object_storage")
        self.assertEqual(instance["service"], "frontend")
        self.assertEqual(instance["provider"], "cloudflare")
        self.assertEqual(instance["desired_state"], "running")
        self.assertEqual(instance["last_status"], "running")
        self.assertEqual(instance["bucket"], "xaisen-devnet-cloudflare-site-1")
        self.assertEqual(instance["artifact_dir"], "services/frontend/out")

    def test_frontend_start_requires_provider_credentials_before_build(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
            }
        )

        with (
            patch.object(infra, "command_env", return_value={}),
            patch.object(infra, "build_frontend_static", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = infra.control("start", "site-1", "frontend", "cloudflare")

        self.assertEqual(code, 1)
        build.assert_not_called()
        pulumi_up.assert_not_called()
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", self.read_history()["events"][0]["error"])

    def test_frontend_start_failure_rolls_back_desired_state(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "site-1",
                        "service": "frontend",
                        "provider": "cloudflare",
                        "backend": "object_storage",
                        "bucket": "xaisen-devnet-cloudflare-site-1",
                        "desired_state": "deleted",
                    }
                ],
            }
        )

        with (
            patch.object(
                infra,
                "command_env",
                return_value={
                    "CLOUDFLARE_API_TOKEN": "token",
                    "CLOUDFLARE_ACCOUNT_ID": "account",
                    "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                },
            ),
            patch.object(infra, "build_frontend_static", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=1) as pulumi_up,
        ):
            code = infra.control("start", "site-1", "frontend", "cloudflare")

        self.assertEqual(code, 1)
        build.assert_called_once_with("devnet")
        pulumi_up.assert_called_once_with("devnet")
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "deleted")
        self.assertIn("pulumi failed with exit code 1", instance["last_error"])

    def test_command_env_loads_alibaba_admin_file(self) -> None:
        alibaba_env = self.root / "secrets" / "cloud" / "alibaba.env"
        alibaba_env.parent.mkdir(parents=True, exist_ok=True)
        alibaba_env.write_text(
            "ALICLOUD_ACCESS_KEY=admin-key\nALICLOUD_SECRET_KEY=admin-secret\nALICLOUD_REGION=cn-shanghai\n",
            encoding="utf-8",
        )

        with (
            patch.object(context, "ROOT", self.root),
            patch.object(context, "IAC_DIR", self.root / "IaC"),
            patch.object(context, "SECRETS_DIR", self.root / "secrets" / "cloud"),
            patch.object(context, "PULUMI_STATE_DIR", self.root / "secrets" / "pulumi-state"),
            patch.object(context, "PULUMI_PASSPHRASE_FILE", self.root / "secrets" / "pulumi-passphrase"),
            patch.object(context, "ANSIBLE_DIR", self.root / "IaC" / "ansible"),
        ):
            env = context.command_env()

        self.assertEqual(env["ALIBABA_CLOUD_ACCESS_KEY_ID"], "admin-key")
        self.assertEqual(env["ALIBABA_CLOUD_ACCESS_KEY_SECRET"], "admin-secret")
        self.assertEqual(env["ALIBABA_CLOUD_REGION"], "cn-shanghai")

    def test_cloudflare_r2_provider_skips_aws_account_lookup(self) -> None:
        captured: dict[str, dict] = {}

        class FakeProvider:
            def __init__(self, name: str, **kwargs: dict) -> None:
                captured["provider"] = {"name": name, **kwargs}

        class FakeR2Bucket:
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                self.name = kwargs.get("name", resource_name)
                captured["bucket"] = {"name": resource_name, **kwargs}

        fake_aws = SimpleNamespace(
            Provider=FakeProvider,
            s3=SimpleNamespace(BucketObjectv2=lambda *args, **kwargs: None),
        )
        fake_cloudflare = SimpleNamespace(R2Bucket=FakeR2Bucket)
        fake_pulumi = ModuleType("pulumi")
        fake_pulumi.Config = lambda _name: SimpleNamespace(get_object=lambda _key: None)
        fake_pulumi.warn = lambda _message: None
        fake_pulumi.export = lambda *_args, **_kwargs: None
        fake_pulumi.FileAsset = lambda path: path
        fake_pulumi.ResourceOptions = lambda **kwargs: kwargs
        fake_pulumi.InvokeOptions = lambda **kwargs: kwargs

        module_path = Path(__file__).resolve().parents[1] / "IaC" / "pulumi" / "__main__.py"
        topology_path = Path(__file__).resolve().parents[1] / "runtime" / "topology.toml"
        fake_topology = (
            'active_env = "devnet"\n'
            'contract_env = "runtime/contract/devnet.env"\n\n'
            '[[instances]]\n'
            'name = "site-1"\n'
            'service = "frontend"\n'
            'provider = "cloudflare"\n'
            'env = "devnet"\n'
            'backend = "object_storage"\n'
            'bucket = "xaisen-devnet-cloudflare-site-1"\n'
            'artifact_dir = "services/frontend/out"\n'
            'desired_state = "running"\n'
        )
        spec = importlib.util.spec_from_file_location("pulumi_main_for_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        with (
            patch.object(Path, "exists", lambda self: str(self) == str(topology_path)),
            patch.object(Path, "read_text", lambda self, encoding="utf-8": fake_topology if str(self) == str(topology_path) else ""),
            patch.dict(
                sys.modules,
                {
                    "pulumi": fake_pulumi,
                    "pulumi_aws": fake_aws,
                    "pulumi_cloudflare": fake_cloudflare,
                },
            ),
            patch.dict(
                "os.environ",
                {
                    "CLOUDFLARE_API_TOKEN": "token",
                    "CLOUDFLARE_ACCOUNT_ID": "account",
                    "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                },
                clear=False,
            ),
        ):
            spec.loader.exec_module(module)

        self.assertIn("provider", captured)
        self.assertTrue(captured["provider"]["skip_requesting_account_id"])
        self.assertTrue(captured["provider"]["skip_credentials_validation"])
        self.assertTrue(captured["provider"]["skip_metadata_api_check"])
        self.assertTrue(captured["provider"]["skip_region_validation"])
        self.assertEqual(captured["provider"]["region"], "auto")

    def test_alibaba_oss_upload_inherits_bucket_acl(self) -> None:
        captured: dict[str, dict] = {}

        class FakeProvider:
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                captured["provider"] = {"resource": self, "name": resource_name, **kwargs}

        class FakeBucket:
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                self.bucket = kwargs.get("bucket", resource_name)
                captured["bucket"] = {"name": resource_name, **kwargs}

        class FakeBucketObject:
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                captured["object"] = {"name": resource_name, **kwargs}

        class FakeBucketAcl:
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                captured["bucket_acl"] = {"name": resource_name, **kwargs}

        fake_alicloud = SimpleNamespace(
            Provider=FakeProvider,
            oss=SimpleNamespace(Bucket=FakeBucket, BucketAcl=FakeBucketAcl, BucketObject=FakeBucketObject),
        )
        fake_pulumi = ModuleType("pulumi")
        fake_pulumi.Config = lambda _name: SimpleNamespace(get_object=lambda _key: None)
        fake_pulumi.warn = lambda _message: None
        fake_pulumi.export = lambda *_args, **_kwargs: None
        fake_pulumi.FileAsset = lambda path: path
        fake_pulumi.ResourceOptions = lambda **kwargs: kwargs

        module_path = Path(__file__).resolve().parents[1] / "IaC" / "pulumi" / "__main__.py"
        topology_path = Path(__file__).resolve().parents[1] / "runtime" / "topology.toml"
        fake_topology = (
            'active_env = "devnet"\n'
            'contract_env = "runtime/contract/devnet.env"\n\n'
            '[[instances]]\n'
            'name = "site-1"\n'
            'service = "frontend"\n'
            'provider = "alibaba"\n'
            'env = "devnet"\n'
            'backend = "object_storage"\n'
            'bucket = "xaisen-devnet-alibaba-site-1"\n'
            'region = "ap-southeast-1"\n'
            'artifact_dir = "services/frontend/out"\n'
            'desired_state = "running"\n'
        )
        spec = importlib.util.spec_from_file_location("pulumi_main_alibaba_for_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        with (
            patch.object(Path, "exists", lambda self: str(self) == str(topology_path) or str(self).endswith("services/frontend/out") or str(self).startswith(str(Path("services/frontend/out")))),
            patch.object(Path, "read_text", lambda self, encoding="utf-8": fake_topology if str(self) == str(topology_path) else ""),
            patch.dict(
                sys.modules,
                {
                    "pulumi": fake_pulumi,
                    "pulumi_alicloud": fake_alicloud,
                },
            ),
            patch.dict(
                "os.environ",
                {
                    "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                    "ALIBABA_CLOUD_REGION": "cn-hangzhou",
                },
                clear=False,
            ),
        ):
            spec.loader.exec_module(module)

        self.assertIn("object", captured)
        self.assertEqual(captured["provider"]["region"], "ap-southeast-1")
        self.assertIsInstance(captured["object"]["source"], str)
        self.assertNotIn("FileAsset", captured["object"]["source"])
        self.assertNotIn("acl", captured["bucket"])
        self.assertEqual(captured["bucket"]["tags"], {"xaisen:region": "ap-southeast-1"})
        self.assertEqual(captured["bucket_acl"]["acl"], "public-read")
        self.assertNotIn("acl", captured["object"])
        self.assertTrue(captured["bucket"]["opts"]["delete_before_replace"])
        self.assertEqual(captured["bucket"]["opts"]["replace_on_changes"], ["tags"])
        self.assertIs(captured["bucket"]["opts"]["provider"], captured["provider"]["resource"])
        self.assertIs(captured["bucket_acl"]["opts"]["provider"], captured["provider"]["resource"])
        self.assertIs(captured["object"]["opts"]["provider"], captured["provider"]["resource"])
        self.assertEqual(len(captured["object"]["opts"]["depends_on"]), 1)
        self.assertIsInstance(captured["object"]["opts"]["depends_on"][0], FakeBucketAcl)
        self.assertEqual(
            module.frontend_site_url("alibaba", "xaisen-devnet-alibaba-site-1", {"region": "ap-southeast-1"}),
            "https://xaisen-devnet-alibaba-site-1.oss-website-ap-southeast-1.aliyuncs.com",
        )

    def test_alibaba_frontend_start_limits_pulumi_parallelism(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
            }
        )

        with (
            patch.object(
                infra,
                "command_env",
                return_value={
                    "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                    "ALIBABA_CLOUD_REGION": "cn-hangzhou",
                    "ALIBABA_FRONTEND_REGION": "ap-southeast-1",
                },
            ),
            patch.object(infra, "build_frontend_static", return_value=0),
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = infra.control("start", "site-1", "frontend", "alibaba")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet", parallel=4)
        self.assertEqual(self.read_topology()["instances"][0]["region"], "ap-southeast-1")

    def test_alibaba_vm_maps_stopped_topology_to_ecs_power_state(self) -> None:
        captured: dict[str, dict] = {}

        class FakeResource:
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                self.id = f"{resource_name}-id"
                self.key_pair_name = kwargs.get("key_pair_name", resource_name)
                self.public_ip = "192.0.2.10"

        class FakeInstance(FakeResource):
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                captured["instance"] = {"name": resource_name, **kwargs}
                super().__init__(resource_name, **kwargs)

        class FakeSecurityGroupRule(FakeResource):
            def __init__(self, resource_name: str, **kwargs: dict) -> None:
                captured.setdefault("security_group_rules", {})[resource_name] = kwargs
                super().__init__(resource_name, **kwargs)

        fake_alicloud = SimpleNamespace(
            Provider=FakeResource,
            get_zones=lambda **_kwargs: SimpleNamespace(ids=["cn-hangzhou-h"]),
            vpc=SimpleNamespace(Network=FakeResource, Switch=FakeResource),
            ecs=SimpleNamespace(
                KeyPair=FakeResource,
                SecurityGroup=FakeResource,
                SecurityGroupRule=FakeSecurityGroupRule,
                Instance=FakeInstance,
                get_images=lambda **_kwargs: SimpleNamespace(images=[SimpleNamespace(id="ubuntu-image")]),
            ),
        )
        fake_pulumi = ModuleType("pulumi")
        fake_pulumi.Config = lambda _name: SimpleNamespace(get_object=lambda _key: None)
        fake_pulumi.warn = lambda _message: None
        fake_pulumi.export = lambda *_args, **_kwargs: None
        fake_pulumi.ResourceOptions = lambda **kwargs: kwargs
        fake_pulumi.InvokeOptions = lambda **kwargs: kwargs

        module_path = Path(__file__).resolve().parents[1] / "IaC" / "pulumi" / "__main__.py"
        spec = importlib.util.spec_from_file_location("pulumi_main_alibaba_vm_for_test", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)

        with (
            patch.object(Path, "exists", return_value=False),
            patch.dict(sys.modules, {"pulumi": fake_pulumi, "pulumi_alicloud": fake_alicloud}),
            patch.dict(
                "os.environ",
                {
                    "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                    "ALIBABA_CLOUD_REGION": "cn-hangzhou",
                },
                clear=False,
            ),
        ):
            spec.loader.exec_module(module)
            module.create_alibaba_vm(
                {
                    "name": "node-1",
                    "service": "routes",
                    "provider": "alibaba",
                    "desired_state": "stopped",
                    "port": 3001,
                },
                "ssh-ed25519 test",
            )

        self.assertEqual(captured["instance"]["status"], "Stopped")
        self.assertEqual(captured["instance"]["stopped_mode"], "KeepCharging")
        self.assertEqual(captured["instance"]["availability_zone"], "cn-hangzhou-h")
        self.assertEqual(captured["security_group_rules"]["node-1-vm-sg-http"]["port_range"], "80/80")
        self.assertEqual(captured["security_group_rules"]["node-1-vm-sg-https"]["port_range"], "443/443")
        self.assertNotIn("node-1-vm-sg-port", captured["security_group_rules"])

    def test_frontend_pause_keeps_bucket_and_does_not_build(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "site-1",
                        "service": "frontend",
                        "provider": "aws",
                        "backend": "object_storage",
                        "bucket": "xaisen-devnet-aws-site-1",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with (
            patch.object(infra, "build_frontend_static", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = infra.control("pause", "site-1", "frontend", "aws")

        self.assertEqual(code, 0)
        build.assert_not_called()
        pulumi_up.assert_called_once_with("devnet")
        instance = self.read_topology()["instances"][0]
        self.assertEqual(instance["desired_state"], "stopped")
        self.assertEqual(instance["last_status"], "stopped")
        self.assertEqual(instance["bucket"], "xaisen-devnet-aws-site-1")

    def test_frontend_kill_removes_instance_from_topology(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "site-1",
                        "service": "frontend",
                        "provider": "cloudflare",
                        "backend": "object_storage",
                        "bucket": "xaisen-devnet-cloudflare-site-1",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
            code = infra.control("kill", "site-1", "frontend", "cloudflare", yes=True)

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet")
        topology = self.read_topology()
        self.assertEqual(topology.get("instances", []), [])
        self.assertEqual(self.read_history()["events"][0]["next_status"], "deleted")

    def test_apply_blocks_running_frontend_when_contract_env_missing(self) -> None:
        self.contract.write_text("", encoding="utf-8")
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [
                    {
                        "name": "site-1",
                        "service": "frontend",
                        "provider": "aws",
                        "backend": "object_storage",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with (
            patch.object(infra, "build_frontend_static", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = infra.apply(yes=True)

        self.assertEqual(code, 1)
        build.assert_not_called()
        pulumi_up.assert_not_called()

    def test_missing_contract_blocks_start(self) -> None:
        self.contract.write_text("", encoding="utf-8")
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "instances": [],
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

    def test_parser_accepts_nested_infra_lifecycle_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["infra", "start", "--name", "node-1", "--service", "routes", "--provider", "digitalocean"])

        self.assertEqual(args.command, "infra")
        self.assertEqual(args.action, "start")
        self.assertEqual(args.name, "node-1")
        self.assertEqual(args.provider, "digitalocean")
        self.assertIsInstance(args, argparse.Namespace)

    def test_parser_accepts_cloudflare_frontend_lifecycle_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["infra", "start", "--name", "site-1", "--service", "frontend", "--provider", "cloudflare"])

        self.assertEqual(args.command, "infra")
        self.assertEqual(args.action, "start")
        self.assertEqual(args.service, "frontend")
        self.assertEqual(args.provider, "cloudflare")

    def test_parser_rejects_top_level_lifecycle_command(self) -> None:
        parser = build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(["start", "--name", "node-1", "--service", "routes", "--provider", "digitalocean"])


if __name__ == "__main__":
    unittest.main()
