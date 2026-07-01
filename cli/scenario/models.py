from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Topology:
    media_nodes: int = 1
    routes_nodes: int = 1
    vclient_nodes: int = 0
    coordinator_nodes: int = 1
    contract_network: str = "devnet"
    provider: str = "alibaba-cloud"
    region: str = "cn-hangzhou"
    instance_type: Optional[str] = None
    deploy_contract: bool = True
    teardown: bool = True
    build_images: bool = False
    registry_init: bool = False
    registry_build: bool = False
    registry_namespace: str = "xaisen"
    registry_tag: str = "latest"
    registry_platform: str = "linux/amd64"
    session_duration_secs: int = 5
    benchmark_targets: Dict[str, int] = field(default_factory=dict)


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


@dataclass
class Scenario:
    name: str
    description: str
    topology: Topology
    run: Callable[[Any], None]
