from __future__ import annotations

import unittest
from unittest.mock import patch

from cli import contract, wallet
from cli.observer.contract_exporter import collect_contract_state


class CollectContractStateTests(unittest.TestCase):
    def _wallet_pool_samples(self, samples: list[tuple[str, dict[str, str], float]]) -> dict[tuple[str, str], float]:
        return {
            (labels["role"], labels["status"]): value
            for name, labels, value in samples
            if name == "dvconf_wallet_pool_count"
        }

    def test_wallet_pool_emits_separate_role_and_status_labels(self) -> None:
        # One wallet in each of the four states _wallet_pool_role_and_status()
        # distinguishes -- covers the exact bug this test guards against:
        # dvconf_wallet_pool_count used to carry a single conflated "bucket"
        # label instead of independent role/status labels, silently breaking
        # every panel that reads it via legendFormat "{{role}} ({{status}})".
        entries = [
            {"assigned_host": "node-1", "registered_role": "relay", "retired": False},
            {"assigned_host": "", "registered_role": "signaling", "retired": False},
            {"assigned_host": "", "registered_role": "", "retired": False},
            {"assigned_host": "", "registered_role": "cp-daemon", "retired": True},
        ]
        with patch.object(wallet, "pool_status", return_value={"devnet": entries}), patch.object(
            contract, "load_deployment", return_value={}
        ):
            samples = collect_contract_state("devnet")

        pool = self._wallet_pool_samples(samples)
        self.assertEqual(pool[("relay", "assigned")], 1.0)
        self.assertEqual(pool[("signaling", "idle")], 1.0)
        self.assertEqual(pool[("unassigned", "free")], 1.0)
        self.assertEqual(pool[("cp-daemon", "retired")], 1.0)
        # No sample should carry the old conflated "bucket" label.
        self.assertTrue(all("bucket" not in labels for _, labels, _ in samples))

    def test_wallet_balance_mist_emitted_per_wallet(self) -> None:
        # Monitoring-redesign gap #3: one dvconf_wallet_balance_mist gauge sample
        # per pool entry, labeled by alias/address, reading the already-populated
        # last_balance_mist field (no new chain call).
        entries = [
            {"alias": "w1", "address": "0xaaa", "last_balance_mist": 500_000_000, "assigned_host": "", "registered_role": "", "retired": False},
            {"alias": "w2", "address": "0xbbb", "last_balance_mist": 0, "assigned_host": "", "registered_role": "", "retired": False},
        ]
        with patch.object(wallet, "pool_status", return_value={"devnet": entries}), patch.object(
            contract, "load_deployment", return_value={}
        ):
            samples = collect_contract_state("devnet")

        balances = {
            (labels["alias"], labels["address"]): value
            for name, labels, value in samples
            if name == "dvconf_wallet_balance_mist"
        }
        self.assertEqual(balances[("w1", "0xaaa")], 500_000_000.0)
        self.assertEqual(balances[("w2", "0xbbb")], 0.0)

    def test_contract_package_info_emitted_when_published(self) -> None:
        with patch.object(wallet, "pool_status", return_value={"devnet": []}), patch.object(
            contract,
            "load_deployment",
            return_value={"CONTRACT_PACKAGE_ID": "0xpkg", "CONTRACT_CHAIN_ID": "devnet-chain"},
        ), patch.object(contract, "fetch_object", return_value=None):
            samples = collect_contract_state("devnet")

        package_info = [
            (name, labels, value) for name, labels, value in samples if name == "dvconf_contract_package_info"
        ]
        self.assertEqual(len(package_info), 1)
        _, labels, value = package_info[0]
        self.assertEqual(labels, {"package_id": "0xpkg", "chain_id": "devnet-chain"})
        self.assertEqual(value, 1.0)

    def test_contract_published_false_when_no_package(self) -> None:
        with patch.object(wallet, "pool_status", return_value={"devnet": []}), patch.object(
            contract, "load_deployment", return_value={}
        ):
            samples = collect_contract_state("devnet")

        published = [(name, labels, value) for name, labels, value in samples if name == "dvconf_contract_published"]
        self.assertEqual(published, [("dvconf_contract_published", {}, 0.0)])


if __name__ == "__main__":
    unittest.main()
