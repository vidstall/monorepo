from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Topology:
    worker_nodes: int = 1
    client_nodes: int = 1
    coordinator_nodes: int = 1
    contract_network: str = "testnet"
    provider: str = "alibaba-cloud"


@dataclass
class BenchmarkSample:
    name: str
    duration_ms: float
    entity_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerEntity:
    entity_id: str
    node_id: Optional[int] = None
    address: str = ""
    samples: List[BenchmarkSample] = field(default_factory=list)
    registered_at: Optional[float] = None
    unregistered_at: Optional[float] = None
    active: bool = False

    def summary_line(self) -> str:
        parts = [self.entity_id]
        by_name = {}
        for s in self.samples:
            by_name[s.name] = s.duration_ms
        for name, ms in by_name.items():
            parts.append(f"{name}={ms:.0f}ms")
        if self.registered_at and self.unregistered_at:
            uptime = (self.unregistered_at - self.registered_at) * 1000
            parts.append(f"uptime={uptime:.0f}ms")
        elif self.registered_at:
            parts.append("active" if self.active else "inactive")
        return "  ".join(parts)


@dataclass
class ClientEntity:
    entity_id: str
    address: str = ""
    samples: List[BenchmarkSample] = field(default_factory=list)

    def summary_line(self) -> str:
        parts = [self.entity_id]
        for s in self.samples:
            parts.append(f"{s.name}={s.duration_ms:.0f}ms")
        return "  ".join(parts)


@dataclass
class UserEntity:
    entity_id: str
    room_name: str = ""
    samples: List[BenchmarkSample] = field(default_factory=list)
    joined_at: Optional[float] = None
    left_at: Optional[float] = None
    session_duration_ms: Optional[float] = None
    rejected: bool = False

    def summary_line(self) -> str:
        parts = [self.entity_id]
        if self.room_name:
            parts.append(f"room={self.room_name}")
        for s in self.samples:
            parts.append(f"{s.name}={s.duration_ms:.0f}ms")
        if self.session_duration_ms is not None:
            parts.append(f"session={self.session_duration_ms:.0f}ms")
        if self.rejected:
            parts.append("rejected")
        elif self.left_at:
            parts.append("left")
        elif self.joined_at:
            parts.append("connected")
        return "  ".join(parts)


@dataclass
class BenchmarkReport:
    scenario_name: str
    topology: Topology
    samples: List[BenchmarkSample] = field(default_factory=list)
    workers: Dict[str, WorkerEntity] = field(default_factory=dict)
    clients: Dict[str, ClientEntity] = field(default_factory=dict)
    users: Dict[str, UserEntity] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def total_duration_ms(self) -> float:
        return (self.finished_at - self.started_at) * 1000

    def summary(self) -> Dict[str, Any]:
        grouped: Dict[str, List[float]] = {}
        for s in self.samples:
            grouped.setdefault(s.name, []).append(s.duration_ms)

        stats = {}
        for name, durations in grouped.items():
            durations.sort()
            n = len(durations)
            stats[name] = {
                "count": n,
                "min_ms": round(durations[0], 2),
                "max_ms": round(durations[-1], 2),
                "avg_ms": round(sum(durations) / n, 2),
                "p50_ms": round(durations[n // 2], 2),
                "p95_ms": round(durations[int(n * 0.95)], 2) if n >= 2 else round(durations[-1], 2),
            }
        return stats

    def entity_summary(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if self.workers:
            result["workers"] = {
                eid: {
                    "node_id": w.node_id,
                    "active": w.active,
                    "samples": [{"name": s.name, "duration_ms": round(s.duration_ms, 2)} for s in w.samples],
                }
                for eid, w in self.workers.items()
            }
        if self.clients:
            result["clients"] = {
                eid: {
                    "samples": [{"name": s.name, "duration_ms": round(s.duration_ms, 2)} for s in c.samples],
                }
                for eid, c in self.clients.items()
            }
        if self.users:
            result["users"] = {
                eid: {
                    "room": u.room_name,
                    "session_duration_ms": round(u.session_duration_ms, 2) if u.session_duration_ms else None,
                    "samples": [{"name": s.name, "duration_ms": round(s.duration_ms, 2)} for s in u.samples],
                }
                for eid, u in self.users.items()
            }
        return result


class _AsyncBridge:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def shutdown(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


class ScenarioContext:
    """Runtime context passed to scenario scripts."""

    def __init__(self, topology: Topology, report: BenchmarkReport, dry_run: bool = False) -> None:
        self.topology = topology
        self.report = report
        self.dry_run = dry_run
        self._step = 0
        self._env: Dict[str, str] = {}
        self._async_bridge = _AsyncBridge()
        self._rooms: Dict[str, Any] = {}
        self._deployment: Any = None

    def set_deployment(self, info: Any) -> None:
        self._deployment = info

    def cleanup(self) -> None:
        for entity_id in list(self._rooms.keys()):
            try:
                room = self._rooms.pop(entity_id)
                async def _disconnect(r: Any = room) -> None:
                    await r.disconnect()
                self._async_bridge.run(_disconnect())
            except Exception:
                pass
        self._async_bridge.shutdown()

    # --- logging ---

    def log(self, message: str) -> None:
        print(f"  [{self._step}] {message}", flush=True)

    def step(self, description: str) -> None:
        self._step += 1
        print(f"\n--- step {self._step}: {description}", flush=True)

    # --- low-level benchmark ---

    def benchmark(self, name: str, fn: Callable[[], Any], entity_id: str = "", **metadata: Any) -> Any:
        self.log(f"benchmark: {name}" + (f" ({entity_id})" if entity_id else ""))
        if self.dry_run:
            self.log("  (dry-run, skipped)")
            return None
        start = time.perf_counter()
        result = fn()
        elapsed_ms = (time.perf_counter() - start) * 1000
        sample = BenchmarkSample(name=name, duration_ms=elapsed_ms, entity_id=entity_id, metadata=metadata)
        self.report.samples.append(sample)
        self._attach_sample_to_entity(entity_id, sample)
        self.log(f"  {elapsed_ms:.1f}ms")
        return result

    def _attach_sample_to_entity(self, entity_id: str, sample: BenchmarkSample) -> None:
        if not entity_id:
            return
        if entity_id in self.report.workers:
            self.report.workers[entity_id].samples.append(sample)
        elif entity_id in self.report.clients:
            self.report.clients[entity_id].samples.append(sample)
        elif entity_id in self.report.users:
            self.report.users[entity_id].samples.append(sample)

    # --- worker lifecycle ---

    def add_worker(self, entity_id: str, address: str = "") -> WorkerEntity:
        worker = WorkerEntity(entity_id=entity_id, address=address)
        self.report.workers[entity_id] = worker
        self.log(f"add worker: {entity_id}" + (f" addr={address}" if address else ""))
        return worker

    def register_worker(
        self,
        entity_id: str,
        metadata_uri: str = "ipfs://xaisen-worker",
        metadata_hash: str = "0x" + "ab" * 32,
        price_per_rental: int = 500,
        stake: int = 1000,
    ) -> Optional[int]:
        worker = self.report.workers[entity_id]

        def _do() -> int:
            output = self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "register_worker",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                f'"{metadata_uri}"',
                f'"{metadata_hash}"',
                str(price_per_rental),
                str(stake),
                "0x6",
                "--gas-budget", "100000000",
            ], capture=True)
            return 0

        result = self.benchmark("register_worker", _do, entity_id=entity_id)
        worker.registered_at = time.time()
        worker.active = True
        return result

    def deactivate_worker(self, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "set_worker_active",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(worker.node_id or 0),
                "false",
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("deactivate_worker", _do, entity_id=entity_id)
        worker.active = False

    def activate_worker(self, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "set_worker_active",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(worker.node_id or 0),
                "true",
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("activate_worker", _do, entity_id=entity_id)
        worker.active = True

    def unregister_worker(self, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "unregister_worker",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(worker.node_id or 0),
                "--gas-budget", "100000000",
            ])

        self.benchmark("unregister_worker", _do, entity_id=entity_id)
        worker.unregistered_at = time.time()
        worker.active = False

    def worker_vote_room(
        self,
        entity_id: str,
        voter_node_id: int,
        rental_id: int,
        nominee_node_id: int,
    ) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cast_room_vote",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(voter_node_id),
                str(rental_id),
                str(nominee_node_id),
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("cast_room_vote", _do, entity_id=entity_id,
                        rental_id=rental_id, nominee_node_id=nominee_node_id)

    def worker_vote_role(
        self,
        entity_id: str,
        voter_node_id: int,
        proposal_id: int,
    ) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cast_role_vote",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(voter_node_id),
                str(proposal_id),
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("cast_role_vote", _do, entity_id=entity_id, proposal_id=proposal_id)

    def hire_worker(
        self,
        entity_id: str,
        worker_node_id: int,
        room_name: str,
        capacity: int,
        payment: int = 500,
    ) -> Optional[int]:
        def _do() -> int:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "hire_worker",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(worker_node_id),
                f'"{room_name}"',
                str(capacity),
                str(payment),
                "0x6",
                "--gas-budget", "100000000",
            ])
            return 0

        return self.benchmark("hire_worker", _do, entity_id=entity_id,
                              room_name=room_name, capacity=capacity,
                              worker_node_id=worker_node_id)

    def withdraw_worker_stake(self, entity_id: str) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "withdraw_worker_stake",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(worker.node_id or 0),
                "--gas-budget", "100000000",
            ])

        self.benchmark("withdraw_worker_stake", _do, entity_id=entity_id)
        worker.unregistered_at = time.time()
        worker.active = False

    def update_worker_metadata(
        self,
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
                "--args",
                self._contract_registry_id(),
                str(worker.node_id or 0),
                f'"{metadata_uri}"',
                f'"{metadata_hash}"',
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("update_worker_metadata", _do, entity_id=entity_id)

    def update_worker_price(self, entity_id: str, price_per_rental: int) -> None:
        worker = self.report.workers[entity_id]

        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "update_worker_price",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(worker.node_id or 0),
                str(price_per_rental),
                "--gas-budget", "100000000",
            ])

        self.benchmark("update_worker_price", _do, entity_id=entity_id,
                        price_per_rental=price_per_rental)

    def cancel_expired_order(self, entity_id: str, rental_id: int) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cancel_expired_order",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(rental_id),
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("cancel_expired_order", _do, entity_id=entity_id,
                        rental_id=rental_id)

    # --- client lifecycle ---

    def add_client(self, entity_id: str, address: str = "") -> ClientEntity:
        client = ClientEntity(entity_id=entity_id, address=address)
        self.report.clients[entity_id] = client
        self.log(f"add client: {entity_id}" + (f" addr={address}" if address else ""))
        return client

    def order_room(
        self,
        entity_id: str,
        room_name: str,
        capacity: int,
        payment: int = 500,
    ) -> Optional[int]:
        def _do() -> int:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "order_room",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                f'"{room_name}"',
                str(capacity),
                str(payment),
                "0x6",
                "--gas-budget", "100000000",
            ])
            return 0

        return self.benchmark("order_room", _do, entity_id=entity_id,
                              room_name=room_name, capacity=capacity)

    def complete_rental(self, entity_id: str, rental_id: int) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "complete_rental",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(rental_id),
                "0x6",
                "--gas-budget", "100000000",
            ])

        self.benchmark("complete_rental", _do, entity_id=entity_id, rental_id=rental_id)

    def cancel_rental(self, entity_id: str, rental_id: int) -> None:
        def _do() -> None:
            self.sui_cli([
                "client", "call",
                "--package", self._contract_package_id(),
                "--module", "node_registry",
                "--function", "cancel_rental",
                "--type-args", "0x2::sui::SUI",
                "--args",
                self._contract_registry_id(),
                str(rental_id),
                "--gas-budget", "100000000",
            ])

        self.benchmark("cancel_rental", _do, entity_id=entity_id, rental_id=rental_id)

    # --- user lifecycle ---

    def add_user(self, entity_id: str, room_name: str) -> UserEntity:
        user = UserEntity(entity_id=entity_id, room_name=room_name)
        self.report.users[entity_id] = user
        self.log(f"add user: {entity_id} room={room_name}")
        return user

    def join_room(self, entity_id: str, routes_url: str = "", rental_id: Optional[int] = None) -> None:
        user = self.report.users[entity_id]
        effective_url = routes_url or (self._deployment.routes_url if self._deployment else "")

        def _do() -> None:
            url = f"{effective_url}/api/connection-details?roomName={user.room_name}&participantName={entity_id}"
            if rental_id is not None:
                url += f"&rentalId={rental_id}"
            try:
                resp = urllib.request.urlopen(url, timeout=10)
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    user.rejected = True
                    return
                raise
            details = json.loads(resp.read())

            from livekit.rtc import Room, RoomOptions
            room = Room()

            async def _connect() -> None:
                await room.connect(
                    details["serverUrl"],
                    details["participantToken"],
                    options=RoomOptions(auto_subscribe=True),
                )

            self._async_bridge.run(_connect())
            self._rooms[entity_id] = room

        self.benchmark("join_room", _do, entity_id=entity_id, room_name=user.room_name)
        if not user.rejected:
            user.joined_at = time.time()

    def leave_room(self, entity_id: str) -> None:
        user = self.report.users[entity_id]

        def _do() -> None:
            room = self._rooms.pop(entity_id, None)
            if room:
                async def _disconnect() -> None:
                    await room.disconnect()
                self._async_bridge.run(_disconnect())

        self.benchmark("leave_room", _do, entity_id=entity_id)
        user.left_at = time.time()
        if user.joined_at:
            user.session_duration_ms = (user.left_at - user.joined_at) * 1000
        self.log(f"user left: {entity_id} session={user.session_duration_ms:.0f}ms" if user.session_duration_ms else f"user left: {entity_id}")

    # --- helpers ---

    def sleep(self, seconds: float, reason: str = "") -> None:
        label = f"wait {seconds}s" + (f" ({reason})" if reason else "")
        self.log(label)
        if not self.dry_run:
            time.sleep(seconds)

    def sui_cli(self, args: List[str], capture: bool = False) -> Optional[str]:
        import shlex
        import subprocess

        from cli.env import build_contract_env

        if not self._env:
            self._env = build_contract_env(self.topology.contract_network)

        cmd = ["sui"] + args
        self.log(f"$ {shlex.join(cmd)}")
        if self.dry_run:
            return None
        result = subprocess.run(
            cmd,
            env=self._env,
            capture_output=capture,
            text=True,
            check=True,
        )
        return result.stdout if capture else None

    def contract_env(self) -> Dict[str, str]:
        if not self._env:
            from cli.env import build_contract_env
            self._env = build_contract_env(self.topology.contract_network)
        return dict(self._env)

    def _contract_package_id(self) -> str:
        return self.contract_env().get("CONTRACT_PACKAGE_ID", "0x0")

    def _contract_registry_id(self) -> str:
        return self.contract_env().get("CONTRACT_REGISTRY_OBJECT_ID", "0x0")


@dataclass
class Scenario:
    name: str
    description: str
    topology: Topology
    run: Callable[[ScenarioContext], None]


def load_scenario(path: Path) -> Scenario:
    spec = importlib.util.spec_from_file_location("scenario_module", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load scenario from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr in ("NAME", "DESCRIPTION", "TOPOLOGY", "run"):
        if not hasattr(module, attr):
            raise SystemExit(f"Scenario {path} missing required attribute: {attr}")

    return Scenario(
        name=module.NAME,
        description=module.DESCRIPTION,
        topology=module.TOPOLOGY,
        run=module.run,
    )


def print_report(report: BenchmarkReport) -> None:
    print("\n" + "=" * 60)
    print(f"BENCHMARK REPORT: {report.scenario_name}")
    print(f"topology: {report.topology.worker_nodes}w / {report.topology.client_nodes}c / {report.topology.coordinator_nodes}coord")
    print(f"network: {report.topology.contract_network}")
    print(f"total duration: {report.total_duration_ms:.0f}ms")
    print("-" * 60)

    stats = report.summary()
    if not stats:
        print("(no benchmark samples recorded)")
    else:
        print("\nAGGREGATE METRICS:")
        for name, s in stats.items():
            print(f"  {name}:")
            print(f"    count={s['count']}  min={s['min_ms']}ms  avg={s['avg_ms']}ms  max={s['max_ms']}ms  p50={s['p50_ms']}ms  p95={s['p95_ms']}ms")

    if report.workers or report.clients or report.users:
        print("\nPER-ENTITY METRICS:")
        for w in report.workers.values():
            print(f"  {w.summary_line()}")
        for c in report.clients.values():
            print(f"  {c.summary_line()}")
        for u in report.users.values():
            print(f"  {u.summary_line()}")

    print("=" * 60)


def _write_report(report: BenchmarkReport, output_path: Optional[str]) -> None:
    if not output_path:
        return
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({
            "scenario": report.scenario_name,
            "topology": {
                "worker_nodes": report.topology.worker_nodes,
                "client_nodes": report.topology.client_nodes,
                "coordinator_nodes": report.topology.coordinator_nodes,
                "contract_network": report.topology.contract_network,
                "provider": report.topology.provider,
            },
            "total_duration_ms": report.total_duration_ms,
            "samples": [
                {
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 2),
                    "entity_id": s.entity_id,
                    "metadata": s.metadata,
                }
                for s in report.samples
            ],
            "summary": report.summary(),
            "entities": report.entity_summary(),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nreport written to {out}")


def cmd_run_scenario(args: argparse.Namespace) -> None:
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise SystemExit(f"Scenario file not found: {scenario_path}")

    scenario = load_scenario(scenario_path)
    dry_run = getattr(args, "dry_run", False)
    provider = getattr(args, "provider", "alibaba-cloud")
    teardown = getattr(args, "teardown", False)

    topology = scenario.topology
    if getattr(args, "worker_nodes", None) is not None:
        topology.worker_nodes = args.worker_nodes
    if getattr(args, "client_nodes", None) is not None:
        topology.client_nodes = args.client_nodes
    if getattr(args, "coordinator_nodes", None) is not None:
        topology.coordinator_nodes = args.coordinator_nodes
    topology.provider = provider
    topology.contract_network = getattr(args, "contract_network", "testnet")

    print(f"scenario: {scenario.name}")
    print(f"  {scenario.description}")
    print(f"  topology: {topology.worker_nodes} workers, {topology.client_nodes} clients, {topology.coordinator_nodes} coordinators")
    print(f"  network: {topology.contract_network}")
    print(f"  provider: {topology.provider}")
    if dry_run:
        print("  mode: DRY RUN")

    deployment = None
    if not dry_run:
        from cli.discovery import is_deployed, discover, wait_for_routes

        if not is_deployed(provider):
            print("\nInfrastructure not deployed. Running deploy...")
            from cli.infra import cmd_deploy

            deploy_args = argparse.Namespace(
                provider=provider,
                deploy_contract=getattr(args, "deploy_contract", False),
                contract_network=topology.contract_network,
                testbed_name=getattr(args, "testbed_name", "depin-testbed"),
                node_registry_contract_id=getattr(args, "node_registry_contract_id", None),
                worker_nodes=topology.worker_nodes,
                client_nodes=topology.client_nodes,
                coordinator_nodes=topology.coordinator_nodes,
            )
            try:
                cmd_deploy(deploy_args)
            except Exception as e:
                raise SystemExit(f"Deploy failed: {e}")

        deployment = discover(provider)
        print(f"  routes: {deployment.routes_url}")
        print(f"  livekit: {deployment.livekit_url}")

        print("\nWaiting for routes service...")
        wait_for_routes(deployment)
        print("  routes service ready")

    report = BenchmarkReport(scenario_name=scenario.name, topology=topology)
    ctx = ScenarioContext(topology=topology, report=report, dry_run=dry_run)
    if deployment:
        ctx.set_deployment(deployment)

    report.started_at = time.time()
    try:
        scenario.run(ctx)
    except KeyboardInterrupt:
        print("\n\nscenario interrupted by user")
    finally:
        ctx.cleanup()
        report.finished_at = time.time()
        print_report(report)
        _write_report(report, getattr(args, "output", None))

    if teardown and not dry_run:
        print("\nTearing down infrastructure...")
        from cli.infra import cmd_destroy

        destroy_args = argparse.Namespace(
            provider=provider,
            testbed_name=getattr(args, "testbed_name", "depin-testbed"),
            node_registry_contract_id=getattr(args, "node_registry_contract_id", None),
            worker_nodes=topology.worker_nodes,
            client_nodes=topology.client_nodes,
            coordinator_nodes=topology.coordinator_nodes,
            auto_approve=True,
        )
        cmd_destroy(destroy_args)
