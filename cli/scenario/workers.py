from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from cli.scenario.models import WorkerEntity

if TYPE_CHECKING:
    from cli.scenario.context import ScenarioContext


class _WorkersMixin:

    def add_worker(self: ScenarioContext, entity_id: str, address: str = "") -> WorkerEntity:
        worker = WorkerEntity(entity_id=entity_id, address=address)
        self.report.workers[entity_id] = worker
        self.log(f"add worker: {entity_id}" + (f" addr={address}" if address else ""))
        return worker

    @staticmethod
    def _ptb_bytes(value: str) -> str:
        if value.startswith("0x") or value.startswith("0X"):
            hex_str = value[2:]
            byte_ints = [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]
        else:
            byte_ints = list(value.encode("utf-8"))
        return "vector[" + ",".join(f"{b}u8" for b in byte_ints) + "]"

    def register_worker(
        self: ScenarioContext,
        entity_id: str,
        metadata_uri: str = "ipfs://xaisen-worker",
        metadata_hash: str = "0x" + "ab" * 32,
        price_per_rental: int = 500,
        stake: int = 1000,
    ) -> Optional[int]:
        worker = self.report.workers[entity_id]
        pkg = self._contract_package_id()
        registry = self._contract_registry_id()

        def _do() -> int:
            import json as _json
            output = self.sui_cli([
                "client", "ptb",
                "--split-coins", "gas", f"[{stake}]",
                "--assign", "stake_coin",
                "--move-call",
                f"{pkg}::node_registry::register_worker<0x2::sui::SUI>",
                f"@{registry}",
                self._ptb_bytes(metadata_uri),
                self._ptb_bytes(metadata_hash),
                f"{price_per_rental}u64",
                "stake_coin.0",
                "@0x6",
                "--gas-budget", "100000000",
                "--json",
            ], capture=True, as_address=worker.address)
            try:
                data = _json.loads(output or "{}")
                for event in data.get("events") or []:
                    pj = event.get("parsedJson") or {}
                    if "node_id" in pj:
                        return int(pj["node_id"])
            except Exception:
                pass
            return 0

        node_id = self.benchmark("register_worker", _do, entity_id=entity_id)
        worker.registered_at = time.time()
        worker.active = True
        worker.node_id = node_id or 0
        return node_id

    def deactivate_worker(self: ScenarioContext, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "set_worker_active",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(worker.node_id or 0), "false", "0x6",
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("deactivate_worker", _do, entity_id=entity_id)
        worker.active = False

    def activate_worker(self: ScenarioContext, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "set_worker_active",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(worker.node_id or 0), "true", "0x6",
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("activate_worker", _do, entity_id=entity_id)
        worker.active = True

    def unregister_worker(self: ScenarioContext, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "unregister_worker",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(worker.node_id or 0),
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("unregister_worker", _do, entity_id=entity_id)
        worker.unregistered_at = time.time()
        worker.active = False

    def update_worker_metadata(
        self: ScenarioContext,
        entity_id: str,
        metadata_uri: str = "ipfs://xaisen-worker",
        metadata_hash: str = "0x" + "ab" * 32,
    ) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "update_worker_metadata",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(worker.node_id or 0),
                f'"{metadata_uri}"', f'"{metadata_hash}"', "0x6",
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("update_worker_metadata", _do, entity_id=entity_id)

    def update_worker_price(self: ScenarioContext, entity_id: str, price_per_rental: int) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "update_worker_price",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(worker.node_id or 0), str(price_per_rental),
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("update_worker_price", _do, entity_id=entity_id, price_per_rental=price_per_rental)
