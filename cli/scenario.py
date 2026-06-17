from __future__ import annotations

import argparse
import importlib.util
import json
import time
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

    def summary_line(self) -> str:
        parts = [self.entity_id]
        if self.room_name:
            parts.append(f"room={self.room_name}")
        for s in self.samples:
            parts.append(f"{s.name}={s.duration_ms:.0f}ms")
        if self.session_duration_ms is not None:
            parts.append(f"session={self.session_duration_ms:.0f}ms")
        if self.left_at:
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


class ScenarioContext:
    """Runtime context passed to scenario scripts."""

    def __init__(self, topology: Topology, report: BenchmarkReport, dry_run: bool = False) -> None:
        self.topology = topology
        self.report = report
        self.dry_run = dry_run
        self._step = 0
        self._env: Dict[str, str] = {}

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

        def _do() -> None:
            import urllib.request
            url = f"{routes_url}/connection-details?roomName={user.room_name}&participantName={entity_id}"
            if rental_id is not None:
                url += f"&rentalId={rental_id}"
            urllib.request.urlopen(url, timeout=10)

        self.benchmark("join_room", _do, entity_id=entity_id, room_name=user.room_name)
        user.joined_at = time.time()

    def leave_room(self, entity_id: str) -> None:
        user = self.report.users[entity_id]
        user.left_at = time.time()
        if user.joined_at:
            user.session_duration_ms = (user.left_at - user.joined_at) * 1000
        sample = BenchmarkSample(
            name="leave_room",
            duration_ms=0.0,
            entity_id=entity_id,
            metadata={"session_duration_ms": user.session_duration_ms or 0},
        )
        self.report.samples.append(sample)
        user.samples.append(sample)
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


def cmd_run_scenario(args: argparse.Namespace) -> None:
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise SystemExit(f"Scenario file not found: {scenario_path}")

    scenario = load_scenario(scenario_path)
    dry_run = getattr(args, "dry_run", False)

    print(f"scenario: {scenario.name}")
    print(f"  {scenario.description}")
    print(f"  topology: {scenario.topology.worker_nodes} workers, {scenario.topology.client_nodes} clients, {scenario.topology.coordinator_nodes} coordinators")
    print(f"  network: {scenario.topology.contract_network}")
    if dry_run:
        print("  mode: DRY RUN")

    report = BenchmarkReport(
        scenario_name=scenario.name,
        topology=scenario.topology,
    )
    ctx = ScenarioContext(topology=scenario.topology, report=report, dry_run=dry_run)

    report.started_at = time.time()
    try:
        scenario.run(ctx)
    except KeyboardInterrupt:
        print("\n\nscenario interrupted by user")
    finally:
        report.finished_at = time.time()
        print_report(report)

        output_path = getattr(args, "output", None)
        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps({
                    "scenario": scenario.name,
                    "topology": {
                        "worker_nodes": scenario.topology.worker_nodes,
                        "client_nodes": scenario.topology.client_nodes,
                        "coordinator_nodes": scenario.topology.coordinator_nodes,
                        "contract_network": scenario.topology.contract_network,
                        "provider": scenario.topology.provider,
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
