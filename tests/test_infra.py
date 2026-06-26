from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.infra import ansible_extra_vars, render_inventory


def terraform_outputs() -> dict[str, object]:
    return {
        "private_key_pem": {"value": "PRIVATE KEY"},
        "inventory": {
            "value": {
                "worker": [
                    {
                        "name": "testbed-worker-1",
                        "public_ip": "198.51.100.10",
                        "private_ip": "10.42.1.10",
                        "ssh_user": "ecs-user",
                        "role": "worker",
                    }
                ],
                "dist": [
                    {
                        "name": "testbed-dist-1",
                        "public_ip": "198.51.100.20",
                        "private_ip": "10.42.1.20",
                        "ssh_user": "ecs-user",
                        "role": "dist",
                    }
                ],
                "vclient": [],
                "coordinator": [
                    {
                        "name": "testbed-coordinator-1",
                        "public_ip": "198.51.100.30",
                        "private_ip": "10.42.1.30",
                        "ssh_user": "ecs-user",
                        "role": "coordinator",
                    }
                ],
            }
        },
    }


class InfraTests(unittest.TestCase):
    def test_render_inventory_writes_yaml_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inventory_path = render_inventory("alibaba-cloud", terraform_outputs(), Path(tmp))
            inventory = inventory_path.read_text(encoding="utf-8")

        self.assertTrue(inventory_path.name.endswith("-inventory.yml"))
        self.assertIn("worker:", inventory)
        self.assertIn("dist:", inventory)
        self.assertIn("vclient:", inventory)
        self.assertIn("coordinator:", inventory)
        self.assertIn('ansible_host: "198.51.100.10"', inventory)
        self.assertIn('private_ip: "10.42.1.30"', inventory)

    def test_ansible_extra_vars_derives_livekit_url_and_redis_address(self) -> None:
        env = {
            "XAISEN_CLIENT_IMAGE": "registry.example.com/client:latest",
            "XAISEN_ROUTES_IMAGE": "registry.example.com/routes:latest",
            "XAISEN_WORKER_IMAGE": "registry.example.com/worker:latest",
            "LIVEKIT_API_KEY": "devkey",
            "LIVEKIT_API_SECRET": "secret",
            "CONTRACT_NETWORK": "testnet",
            "CONTRACT_PACKAGE_ID": "package",
            "CONTRACT_REGISTRY_OBJECT_ID": "registry",
        }

        values = ansible_extra_vars(terraform_outputs(), env, "node-registry")

        self.assertEqual(values["LIVEKIT_URL"], "ws://198.51.100.10:7880")
        self.assertEqual(values["redis_address"], "10.42.1.30:6379")
        self.assertEqual(values["dist_url"], "http://198.51.100.20")
        self.assertEqual(values["XAISEN_COORDINATOR_IMAGE"], "redis:7.4-alpine")
        self.assertEqual(values["XAISEN_PROXY_IMAGE"], "caddy:2-alpine")
        self.assertEqual(values["node_registry_contract_id"], "node-registry")
        self.assertEqual(values["CONTRACT_PACKAGE_ID"], "package")

    def test_ansible_extra_vars_requires_runtime_images_and_livekit_secrets(self) -> None:
        with self.assertRaisesRegex(SystemExit, "XAISEN_CLIENT_IMAGE"):
            ansible_extra_vars(terraform_outputs(), {}, None)


if __name__ == "__main__":
    unittest.main()
