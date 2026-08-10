from __future__ import annotations

from unittest.mock import patch

from cli import infra

from tests.infra_topology_test_base import InfraTopologyTestCase


class DockerAlibabaTests(InfraTopologyTestCase):
    def test_akamai_pause_powers_off_without_ansible(self) -> None:
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
                code = infra.control("pause", "node-1", "cp-daemon", "akamai")

            self.assertEqual(code, 0)
            # Unlike alibaba, akamai has no targeted-apply machinery -- pause
            # goes through the plain untargeted pulumi_up(env_name) call.
            pulumi_up.assert_called_once_with("devnet")
            inventory.assert_not_called()
            configure.assert_not_called()
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["desired_state"], "stopped")
            self.assertEqual(worker["last_status"], "stopped")

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
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "cp-daemon",
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
                code = infra.control("restart", "node-1", "cp-daemon", "akamai")

            self.assertEqual(code, 0)
            self.assertEqual(configure.call_args.kwargs["host_limit"], "node-1")
            self.assertEqual(configure.call_args.kwargs["container_state"], "restarted")
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "running")

    def test_detach_fires_configure_in_background_without_waiting(self) -> None:
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
                # configure() itself is mocked here (this test isn't about
                # ansible_playbook()'s Popen call -- see test_context.py's
                # run_detached test for that) -- it just asserts control()
                # threads detach=True and a log_path through, and treats
                # configure()'s immediate return as success without any extra
                # "did it actually finish" check.
                patch.object(infra, "configure", return_value=0) as configure,
            ):
                code = infra.control("restart", "node-1", "cp-daemon", "akamai", detach=True)

            self.assertEqual(code, 0)
            self.assertTrue(configure.call_args.kwargs["detach"])
            self.assertIsNotNone(configure.call_args.kwargs["log_path"])
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "running")

    def test_docker_only_restart_toggles_container_instead_of_full_configure(self) -> None:
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
                            "desired_state": "stopped",
                        }
                    ],
                }
            )

            with (
                patch("cli.wallet.checkout_wallet", return_value=({"secret_key": "k", "node_id": None, "x25519_secret": "x", "cap_id": None}, False)),
                patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
                patch.object(infra, "inventory") as inventory,
                patch.object(infra, "configure") as configure,
                patch.object(infra, "toggle_container", return_value=0) as toggle_container,
            ):
                code = infra.control("restart", "node-1", "cp-daemon", "akamai", detach=True, docker_only=True)

            self.assertEqual(code, 0)
            pulumi_up.assert_not_called()
            inventory.assert_not_called()
            configure.assert_not_called()
            toggle_container.assert_called_once_with(
                host_limit="node-1",
                container_name="xaisen-akamai-node-1-cp-daemon-1",
                action="start",
                detach=True,
                log_path=toggle_container.call_args.kwargs["log_path"],
            )
            self.assertIsNotNone(toggle_container.call_args.kwargs["log_path"])
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "running")

    def test_docker_only_pause_stops_container_when_sibling_still_running(self) -> None:
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
                            "desired_state": "running",
                        },
                        {
                            "host": "node-1",
                            "service": "relay",
                            "provider": "akamai",
                            "backend": "vm",
                            "desired_state": "running",
                            "worker_index": 1,
                        },
                    ],
                }
            )

            with (
                patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
                patch.object(infra, "toggle_container", return_value=0) as toggle_container,
            ):
                code = infra.control("pause", "node-1", "cp-daemon", "akamai", docker_only=True)

            self.assertEqual(code, 0)
            pulumi_up.assert_not_called()
            toggle_container.assert_called_once_with(
                host_limit="node-1",
                container_name="xaisen-akamai-node-1-cp-daemon-1",
                action="stop",
                detach=False,
                log_path=None,
            )
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "stopped")

    def test_docker_only_pause_stops_container_even_as_last_active_worker_on_host(self) -> None:
            # Pause is always a plain SSH `docker stop` against one container --
            # it never falls back to letting pulumi_up power off the whole VM,
            # even when this is the only worker left running on the host (see
            # cli/infra/control.py's `skip_pulumi` -- pulumi_up is skipped
            # entirely for docker_only pause/restart, so there's nothing for it
            # to fall back to).
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
                            "desired_state": "running",
                        }
                    ],
                }
            )

            with (
                patch.object(infra, "command_env", return_value={"LINODE_TOKEN": "token"}),
                patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
                patch.object(infra, "toggle_container", return_value=0) as toggle_container,
            ):
                code = infra.control("pause", "node-1", "cp-daemon", "akamai", docker_only=True)

            self.assertEqual(code, 0)
            pulumi_up.assert_not_called()
            toggle_container.assert_called_once_with(
                host_limit="node-1",
                container_name="xaisen-akamai-node-1-cp-daemon-1",
                action="stop",
                detach=False,
                log_path=None,
            )
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "stopped")

    def test_docker_only_pause_restart_works_for_non_alibaba_akamai_provider(self) -> None:
            # Regression test: docker_only pause/restart (scenario worker.leave/
            # worker.join churn) must work for ANY provider, since it's pure SSH
            # + a single docker command -- never routed through the per-provider
            # VM power-lifecycle guard that only applies outside docker_only.
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
                            "backend": "vm",
                            "desired_state": "running",
                            "worker_index": 1,
                        }
                    ],
                }
            )

            with (
                patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
                patch.object(infra, "toggle_container", return_value=0) as toggle_container,
            ):
                code = infra.control("pause", "node-1", "relay", "digitalocean", worker_index=1, docker_only=True)

            self.assertEqual(code, 0)
            pulumi_up.assert_not_called()
            toggle_container.assert_called_once_with(
                host_limit="node-1",
                container_name="xaisen-digitalocean-node-1-relay-1",
                action="stop",
                detach=False,
                log_path=None,
            )
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "stopped")

    def test_docker_only_ignored_for_fresh_start(self) -> None:
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
                patch.object(infra, "pulumi_up", return_value=0),
                patch.object(infra, "inventory", return_value=0),
                patch.object(infra, "configure", return_value=0) as configure,
                patch.object(infra, "toggle_container") as toggle_container,
            ):
                code = infra.control("start", "node-1", "cp-daemon", "akamai", docker_only=True)

            self.assertEqual(code, 0)
            configure.assert_called_once()
            toggle_container.assert_not_called()

    def test_alibaba_pause_powers_off_without_ansible(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "relay",
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
                code = infra.control("pause", "node-1", "relay", "alibaba")

            self.assertEqual(code, 0)
            pulumi_up.assert_called_once_with(
                "devnet",
                targets=infra.alibaba_vm_target_urns("devnet", "node-1", "relay", False),
            )
            inventory.assert_not_called()
            configure.assert_not_called()
            worker = self.read_topology()["workers"][0]
            self.assertEqual(worker["desired_state"], "stopped")
            self.assertEqual(worker["last_status"], "stopped")

    def test_alibaba_restart_reconfigures_and_restarts_container(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "relay",
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
                code = infra.control("restart", "node-1", "relay", "alibaba")

            self.assertEqual(code, 0)
            configure.assert_called_once_with(host_limit="node-1", container_state="restarted")
            self.assertEqual(self.read_topology()["workers"][0]["last_status"], "running")

    def test_pulumi_up_targets_only_selected_worker(self) -> None:
            with (
                patch.object(infra, "command_env", return_value={}),
                patch.object(infra, "run", return_value=0) as run,
            ):
                targets = infra.alibaba_vm_target_urns("devnet", "relay-1", "relay", True)
                code = infra.pulumi_up("devnet", targets=targets)

            self.assertEqual(code, 0)
            args = run.call_args.args[0]
            self.assertIn("--target", args)
            self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/instance:Instance::relay-1-vm", args)
            self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:vpc/switch:Switch::relay-1-vm-vswitch", args)
            self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::relay-1-vm-sg-http", args)
            self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::relay-1-vm-sg-https", args)
            self.assertNotIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::relay-1-vm-sg-port", args)


            with (
                patch.object(infra, "command_env", return_value={}),
                patch.object(infra, "run", return_value=0) as run,
            ):
                targets = infra.alibaba_vm_target_urns("devnet", "coordinator-1", "coordinator", True)
                code = infra.pulumi_up("devnet", targets=targets)

            self.assertEqual(code, 0)
            args = run.call_args.args[0]
            self.assertIn("urn:pulumi:devnet::xaisen-iac::alicloud:ecs/securityGroupRule:SecurityGroupRule::coordinator-1-vm-sg-port", args)

