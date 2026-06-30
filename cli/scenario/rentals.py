from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from cli.scenario.models import ClientEntity

if TYPE_CHECKING:
    from cli.scenario.context import ScenarioContext


class _RentalsMixin:

    def add_client(self: ScenarioContext, entity_id: str, address: str = "") -> ClientEntity:
        client = ClientEntity(entity_id=entity_id, address=address)
        self.report.clients[entity_id] = client
        self.log(f"add client: {entity_id}" + (f" addr={address}" if address else ""))
        return client

    def worker_vote_room(
        self: ScenarioContext,
        entity_id: str,
        voter_node_id: int,
        rental_id: int,
        nominee_node_id: int,
    ) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cast_room_vote",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(voter_node_id), str(rental_id), str(nominee_node_id), "0x6",
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("cast_room_vote", _do, entity_id=entity_id,
                        rental_id=rental_id, nominee_node_id=nominee_node_id)

    def worker_vote_role(
        self: ScenarioContext,
        entity_id: str,
        voter_node_id: int,
        proposal_id: int,
    ) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cast_role_vote",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(voter_node_id), str(proposal_id), "0x6",
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("cast_role_vote", _do, entity_id=entity_id, proposal_id=proposal_id)

    def hire_worker(
        self: ScenarioContext,
        entity_id: str,
        worker_node_id: int,
        room_name: str,
        capacity: int,
        payment: int = 500,
    ) -> Optional[int]:
        pkg = self._contract_package_id()
        registry = self._contract_registry_id()

        def _do() -> int:
            self.sui_cli([
                "client", "ptb",
                "--split-coins", "gas", f"[{payment}]",
                "--assign", "payment_coin",
                "--move-call",
                f"{pkg}::node_registry::hire_worker<0x2::sui::SUI>",
                f"@{registry}",
                f"{worker_node_id}u64",
                self._ptb_bytes(room_name),
                f"{capacity}u64",
                "payment_coin.0",
                "@0x6",
                "--gas-budget", "100000000",
            ])
            return 0

        return self.benchmark("hire_worker", _do, entity_id=entity_id,
                              room_name=room_name, capacity=capacity,
                              worker_node_id=worker_node_id)

    def withdraw_worker_stake(self: ScenarioContext, entity_id: str) -> None:
        import time
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "withdraw_worker_stake",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(worker.node_id or 0),
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("withdraw_worker_stake", _do, entity_id=entity_id)
        worker.unregistered_at = time.time()
        worker.active = False

    def cancel_expired_order(self: ScenarioContext, entity_id: str, rental_id: int) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cancel_expired_order",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(rental_id), "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("cancel_expired_order", _do, entity_id=entity_id, rental_id=rental_id)

    def order_room(
        self: ScenarioContext,
        entity_id: str,
        room_name: str,
        capacity: int,
        payment: int = 500,
    ) -> Optional[int]:
        pkg = self._contract_package_id()
        registry = self._contract_registry_id()

        def _do() -> int:
            import json as _json
            output = self.sui_cli([
                "client", "ptb",
                "--split-coins", "gas", f"[{payment}]",
                "--assign", "payment_coin",
                "--move-call",
                f"{pkg}::node_registry::order_room<0x2::sui::SUI>",
                f"@{registry}",
                self._ptb_bytes(room_name),
                f"{capacity}u64",
                "payment_coin.0",
                "@0x6",
                "--gas-budget", "100000000",
                "--json",
            ], capture=True)
            try:
                data = _json.loads(output or "{}")
                for event in data.get("events") or []:
                    pj = event.get("parsedJson") or {}
                    if "rental_id" in pj:
                        return int(pj["rental_id"])
            except Exception:
                pass
            return 0

        return self.benchmark("order_room", _do, entity_id=entity_id,
                              room_name=room_name, capacity=capacity)

    def complete_rental(self: ScenarioContext, entity_id: str, rental_id: int) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "complete_rental",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(rental_id), "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("complete_rental", _do, entity_id=entity_id, rental_id=rental_id)

    def cancel_rental(self: ScenarioContext, entity_id: str, rental_id: int) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cancel_rental",
                "--type-args", "0x2::sui::SUI",
                "--args", self._contract_registry_id(), str(rental_id),
                "--gas-budget", "100000000",
            ])

        self.benchmark("cancel_rental", _do, entity_id=entity_id, rental_id=rental_id)
