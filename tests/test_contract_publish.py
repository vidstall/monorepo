from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import contract


def published_payload(package_id: str = "0xpackage", digest: str = "0xpublishdigest") -> dict:
    return {
        "objectChanges": [
            {"type": "published", "packageId": package_id},
            {
                "type": "created",
                "objectType": "0x2::package::UpgradeCap",
                "objectId": "0xupgradecap",
            },
        ],
        "input": {"sender": "0xdeployer"},
        "effects": {"transactionDigest": digest},
    }


def registry_payload(registry_id: str = "0xregistry") -> dict:
    return {
        "objectChanges": [
            {
                "type": "created",
                "objectType": "0xpackage::node_registry::Registry<0x2::sui::SUI>",
                "objectId": registry_id,
            }
        ]
    }


def upgrade_payload(package_id: str = "0xupgraded", digest: str = "0xupgradedigest") -> dict:
    return {
        "objectChanges": [{"type": "published", "packageId": package_id}],
        "effects": {"transactionDigest": digest},
    }


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


class ContractPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env_path = self.root / "devnet.env"
        self.published_toml = self.root / "Published.toml"
        self.runtime_dir = self.root / "runtime"
        self.commands: list[list[str]] = []

        self.path_patch = patch.object(contract, "contract_env_path", lambda _env: self.env_path)
        self.pubfile_patch = patch.object(contract, "PUBLISHED_TOML", self.published_toml)
        self.runtime_patch = patch.object(contract, "RUNTIME_DIR", self.runtime_dir)
        self.path_patch.start()
        self.pubfile_patch.start()
        self.runtime_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.pubfile_patch.stop)
        self.addCleanup(self.runtime_patch.stop)

    def fake_sui(self, args: list[object], cwd: Path | None = None) -> tuple[int, dict | None, str]:
        command = [str(arg) for arg in args]
        self.commands.append(command)
        action = command[2]
        if action == "test-publish":
            return 0, {"effects": {}}, ""
        if action == "publish":
            return 0, published_payload(), ""
        if action == "call":
            return 0, registry_payload(), ""
        if action == "test-upgrade":
            return 0, {"effects": {}}, ""
        if action == "upgrade":
            return 0, upgrade_payload(), ""
        self.fail(f"Unexpected Sui action: {action}")

    def write_env(self, values: dict[str, str]) -> None:
        self.env_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))

    def test_first_publish_creates_registry_and_writes_env(self) -> None:
        with patch.object(contract, "run_sui_json", self.fake_sui):
            code = contract.publish("devnet", dry_run=False, yes=True, gas_budget=None)

        self.assertEqual(code, 0)
        self.assertEqual([command[2] for command in self.commands], ["test-publish", "publish", "call"])
        values = parse_env(self.env_path)
        self.assertEqual(values["CONTRACT_PACKAGE_ID"], "0xpackage")
        self.assertEqual(values["CONTRACT_REGISTRY_OBJECT_ID"], "0xregistry")
        self.assertEqual(values["CONTRACT_UPGRADE_CAP_ID"], "0xupgradecap")
        self.assertEqual(values["CONTRACT_DEPLOYER_ADDRESS"], "0xdeployer")
        self.assertEqual(values["CONTRACT_PUBLISH_TX_DIGEST"], "0xpublishdigest")
        self.assertIn(str(self.runtime_dir / "Pub.devnet.toml"), self.commands[0])
        self.assertIn(str(self.runtime_dir / "Pub.devnet.toml"), self.commands[1])

    def test_existing_publish_upgrades_and_preserves_registry(self) -> None:
        self.write_env(
            {
                "CONTRACT_NETWORK": "devnet",
                "CONTRACT_PACKAGE_ID": "0xpackage",
                "CONTRACT_REGISTRY_OBJECT_ID": "0xregistry",
                "CONTRACT_UPGRADE_CAP_ID": "0xupgradecap",
                "CONTRACT_DEPLOYER_ADDRESS": "0xdeployer",
                "CONTRACT_PUBLISH_TX_DIGEST": "0xpublishdigest",
            }
        )

        with patch.object(contract, "run_sui_json", self.fake_sui):
            code = contract.publish("devnet", dry_run=False, yes=True, gas_budget="1000")

        self.assertEqual(code, 0)
        self.assertEqual([command[2] for command in self.commands], ["test-upgrade", "upgrade"])
        self.assertIn("--gas-budget", self.commands[0])
        values = parse_env(self.env_path)
        self.assertEqual(values["CONTRACT_PACKAGE_ID"], "0xupgraded")
        self.assertEqual(values["CONTRACT_REGISTRY_OBJECT_ID"], "0xregistry")
        self.assertEqual(values["CONTRACT_UPGRADE_CAP_ID"], "0xupgradecap")
        self.assertEqual(values["CONTRACT_PUBLISH_TX_DIGEST"], "0xpublishdigest")
        self.assertEqual(values["CONTRACT_UPGRADE_TX_DIGEST"], "0xupgradedigest")
        pubfile = self.runtime_dir / "Pub.devnet.toml"
        self.assertTrue(pubfile.exists())
        self.assertIn('source = { local = "', pubfile.read_text())

    def test_existing_publish_fails_when_registry_missing(self) -> None:
        self.write_env(
            {
                "CONTRACT_NETWORK": "devnet",
                "CONTRACT_PACKAGE_ID": "0xpackage",
                "CONTRACT_UPGRADE_CAP_ID": "0xupgradecap",
            }
        )

        with patch.object(contract, "run_sui_json", self.fake_sui):
            code = contract.publish("devnet", dry_run=False, yes=True, gas_budget=None)

        self.assertEqual(code, 1)
        self.assertEqual(self.commands, [])

    def test_existing_publish_can_create_missing_registry_with_flag(self) -> None:
        self.write_env(
            {
                "CONTRACT_NETWORK": "devnet",
                "CONTRACT_PACKAGE_ID": "0xpackage",
                "CONTRACT_UPGRADE_CAP_ID": "0xupgradecap",
            }
        )

        with patch.object(contract, "run_sui_json", self.fake_sui):
            code = contract.publish(
                "devnet",
                dry_run=False,
                yes=True,
                gas_budget=None,
                create_registry_if_missing=True,
            )

        self.assertEqual(code, 0)
        self.assertEqual([command[2] for command in self.commands], ["test-upgrade", "upgrade", "call"])
        values = parse_env(self.env_path)
        self.assertEqual(values["CONTRACT_PACKAGE_ID"], "0xupgraded")
        self.assertEqual(values["CONTRACT_REGISTRY_OBJECT_ID"], "0xregistry")

    def test_existing_dry_run_uses_test_upgrade_and_does_not_write(self) -> None:
        self.write_env(
            {
                "CONTRACT_NETWORK": "devnet",
                "CONTRACT_PACKAGE_ID": "0xpackage",
                "CONTRACT_REGISTRY_OBJECT_ID": "0xregistry",
                "CONTRACT_UPGRADE_CAP_ID": "0xupgradecap",
            }
        )
        before = self.env_path.read_text()

        with patch.object(contract, "run_sui_json", self.fake_sui):
            code = contract.publish("devnet", dry_run=True, yes=False, gas_budget=None)

        self.assertEqual(code, 0)
        self.assertEqual([command[2] for command in self.commands], ["test-upgrade"])
        self.assertEqual(self.env_path.read_text(), before)
        self.assertTrue((self.runtime_dir / "Pub.devnet.toml").exists())

    def fake_sui_fresh_devnet_publish(self, args: list[object], cwd: Path | None = None) -> tuple[int, dict | None, str]:
        # Unlike `fake_sui`, distinguishes devnet's preview vs real
        # "test-publish" call by `--dry-run` presence, since real_publish_command()
        # uses "test-publish" (not "publish") for BOTH on devnet. The real
        # response also needs to mint AdminCap/NetworkRegistry/MinerStore/
        # RoleVoteBox, which the shared published_payload() fixture omits.
        command = [str(arg) for arg in args]
        self.commands.append(command)
        action = command[2]
        if action == "test-publish":
            if "--dry-run" in command:
                return 0, {"effects": {}}, ""
            payload = published_payload()
            payload["objectChanges"].extend(
                [
                    {"type": "created", "objectType": "0xpackage::admin::AdminCap", "objectId": "0xadmincap"},
                    {"type": "created", "objectType": "0xpackage::node_registry::NetworkRegistry", "objectId": "0xnetworkregistry"},
                    {"type": "created", "objectType": "0xpackage::miner::MinerStore", "objectId": "0xminerstore"},
                    {"type": "created", "objectType": "0xpackage::role_voting::RoleVoteBox", "objectId": "0xrolevotebox"},
                ]
            )
            return 0, payload, ""
        if action == "call":
            return 0, registry_payload(), ""
        self.fail(f"Unexpected Sui action: {action}")

    def test_devnet_chain_reset_forces_fresh_publish_not_upgrade(self) -> None:
        # An existing (pre-reset) deployment record: package/upgrade-cap and
        # a CHAIN_ID that no longer matches the live devnet network.
        self.write_env(
            {
                "CONTRACT_NETWORK": "devnet",
                "CONTRACT_CHAIN_ID": "old-chain-id",
                "CONTRACT_PACKAGE_ID": "0xpackage",
                "CONTRACT_REGISTRY_OBJECT_ID": "0xregistry",
                "CONTRACT_UPGRADE_CAP_ID": "0xupgradecap",
            }
        )

        with (
            patch.object(contract, "run_sui_json", self.fake_sui_fresh_devnet_publish),
            patch.object(contract, "sync_devnet_chain_id", return_value="new-chain-id"),
            patch.object(contract, "upgrade_existing") as upgrade_existing,
            patch.object(
                contract,
                "create_registries",
                return_value={
                    "CP_REGISTRY_ID": "0xcp",
                    "RELAY_REGISTRY_ID": "0xrelay",
                    "SIGNALING_REGISTRY_ID": "0xsignaling",
                    "VALIDATOR_REGISTRY_ID": "0xvalidator",
                    "USER_REGISTRY_ID": "0xuser",
                    "ROOM_MANAGER_ID": "0xroom",
                    "QUORUM_CONFIG_ID": "0xquorum",
                },
            ),
        ):
            code = contract.publish("devnet", dry_run=False, yes=True, gas_budget=None)

        self.assertEqual(code, 0)
        # The chain-id mismatch must route to a fresh publish, never to the
        # upgrade path (which would fail on-chain against a wiped network).
        upgrade_existing.assert_not_called()
        self.assertEqual([command[2] for command in self.commands], ["test-publish", "test-publish"])
        values = parse_env(self.env_path)
        self.assertEqual(values["CONTRACT_PACKAGE_ID"], "0xpackage")
        # The record self-heals to the live chain-id, not the stale one.
        self.assertEqual(values["CONTRACT_CHAIN_ID"], "new-chain-id")

    def test_devnet_matching_chain_id_still_upgrades(self) -> None:
        self.write_env(
            {
                "CONTRACT_NETWORK": "devnet",
                "CONTRACT_CHAIN_ID": "same-chain-id",
                "CONTRACT_PACKAGE_ID": "0xpackage",
                "CONTRACT_REGISTRY_OBJECT_ID": "0xregistry",
                "CONTRACT_UPGRADE_CAP_ID": "0xupgradecap",
                "CP_REGISTRY_ID": "0xcp",
                "RELAY_REGISTRY_ID": "0xrelay",
                "SIGNALING_REGISTRY_ID": "0xsignaling",
                "VALIDATOR_REGISTRY_ID": "0xvalidator",
                "USER_REGISTRY_ID": "0xuser",
                "ROOM_MANAGER_ID": "0xroom",
                "QUORUM_CONFIG_ID": "0xquorum",
            }
        )

        with (
            patch.object(contract, "run_sui_json", self.fake_sui),
            patch.object(contract, "sync_devnet_chain_id", return_value="same-chain-id"),
        ):
            code = contract.publish("devnet", dry_run=False, yes=True, gas_budget="1000")

        self.assertEqual(code, 0)
        self.assertEqual([command[2] for command in self.commands], ["test-upgrade", "upgrade"])
        values = parse_env(self.env_path)
        self.assertEqual(values["CONTRACT_PACKAGE_ID"], "0xupgraded")


if __name__ == "__main__":
    unittest.main()
