from __future__ import annotations

from unittest.mock import patch

from cli import infra

from tests.infra_topology_test_base import InfraTopologyTestCase


class ObservabilityCliTests(InfraTopologyTestCase):
    def test_prometheus_start_is_rejected_in_favor_of_vidctl_observer(self) -> None:
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

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("start", "node-1", "prometheus", "digitalocean")

            self.assertEqual(code, 1)
            pulumi_up.assert_not_called()
            self.assertIn("vidctl observer", self.read_history()["events"][0]["error"])

    def test_tempo_start_is_rejected_in_favor_of_vidctl_observer(self) -> None:
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

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("start", "node-1", "tempo", "digitalocean")

            self.assertEqual(code, 1)
            pulumi_up.assert_not_called()
            self.assertIn("vidctl observer", self.read_history()["events"][0]["error"])

    def test_grafana_start_is_rejected_in_favor_of_vidctl_observer(self) -> None:
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

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("start", "node-1", "grafana", "digitalocean")

            self.assertEqual(code, 1)
            pulumi_up.assert_not_called()
            self.assertIn("vidctl observer", self.read_history()["events"][0]["error"])

    def test_loki_start_is_rejected_in_favor_of_vidctl_observer(self) -> None:
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

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("start", "node-1", "loki", "digitalocean")

            self.assertEqual(code, 1)
            pulumi_up.assert_not_called()
            self.assertIn("vidctl observer", self.read_history()["events"][0]["error"])

    def test_prometheus_kill_is_still_allowed(self) -> None:
            infra.write_topology(
                {
                    "active_env": "devnet",
                    "contract_env": "runtime/contract/devnet.env",
                    "providers": {},
                    "workers": [
                        {
                            "host": "node-1",
                            "service": "prometheus",
                            "provider": "digitalocean",
                            "env": "devnet",
                            "backend": "vm",
                            "desired_state": "running",
                            "worker_index": 1,
                        }
                    ],
                }
            )

            with patch.object(infra, "pulumi_up", return_value=0) as pulumi_up:
                code = infra.control("kill", "node-1", "prometheus", "digitalocean", yes=True)

            self.assertEqual(code, 0)
            pulumi_up.assert_called_once()

