from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import math
import struct
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
    dist_nodes: int = 1
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


def _generate_audio_frame(sample_rate: int = 48000, num_channels: int = 1, duration_ms: int = 20) -> Any:
    from livekit.rtc import AudioFrame
    num_samples = sample_rate * duration_ms // 1000
    samples = [int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
               for i in range(num_samples)]
    data = struct.pack(f"<{num_samples}h", *samples)
    return AudioFrame(data=data, sample_rate=sample_rate,
                      num_channels=num_channels, samples_per_channel=num_samples)


def _generate_video_frame(width: int = 640, height: int = 480) -> Any:
    from livekit.rtc import VideoFrame
    pixel = struct.pack("BBBB", 0, 180, 0, 255)
    return VideoFrame(width, height, 0, pixel * (width * height))


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


_WALLET_MEMO_PATH = Path(__file__).resolve().parents[1] / "memo" / "wallets.json"


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
        self._track_stops: Dict[str, threading.Event] = {}
        self._track_threads: Dict[str, threading.Thread] = {}
        self._deployment: Any = None
        self._wallet_memo: Optional[Dict[str, Any]] = None

    def _load_wallet_memo(self) -> Dict[str, Any]:
        if self._wallet_memo is None:
            if _WALLET_MEMO_PATH.exists():
                try:
                    self._wallet_memo = json.loads(_WALLET_MEMO_PATH.read_text())
                except Exception:
                    self._wallet_memo = {}
            else:
                self._wallet_memo = {}
        return self._wallet_memo

    def _save_wallet_memo(self) -> None:
        if self._wallet_memo is None:
            return
        _WALLET_MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WALLET_MEMO_PATH.write_text(json.dumps(self._wallet_memo, indent=2))

    def set_deployment(self, info: Any) -> None:
        self._deployment = info

    def cleanup(self) -> None:
        for entity_id, stop_event in self._track_stops.items():
            stop_event.set()
        for entity_id, thread in self._track_threads.items():
            thread.join(timeout=2)
        self._track_stops.clear()
        self._track_threads.clear()
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

    @staticmethod
    def _ptb_bytes(value: str) -> str:
        """Convert a string or 0x-prefixed hex to a PTB vector<u8> literal.

        Uses vector[Nu8,...] notation to avoid re-tokenisation issues with
        b"..." / x"..." when the Sui CLI joins argv before parsing.
        """
        if value.startswith("0x") or value.startswith("0X"):
            hex_str = value[2:]
            byte_ints = [int(hex_str[i:i+2], 16) for i in range(0, len(hex_str), 2)]
        else:
            byte_ints = list(value.encode("utf-8"))
        return "vector[" + ",".join(f"{b}u8" for b in byte_ints) + "]"

    def register_worker(
        self,
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
            ], as_address=worker.address)

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
            ], as_address=worker.address)

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
            ], as_address=worker.address)

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
        worker = self.report.workers[entity_id]

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
            ], as_address=worker.address)

        self.benchmark("cast_room_vote", _do, entity_id=entity_id,
                        rental_id=rental_id, nominee_node_id=nominee_node_id)

    def worker_vote_role(
        self,
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
                "--args",
                self._contract_registry_id(),
                str(voter_node_id),
                str(proposal_id),
                "0x6",
                "--gas-budget", "100000000",
            ], as_address=worker.address)

        self.benchmark("cast_role_vote", _do, entity_id=entity_id, proposal_id=proposal_id)

    def hire_worker(
        self,
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
            ], as_address=worker.address)

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
            ], as_address=worker.address)

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
            ], as_address=worker.address)

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

    def join_room(self, entity_id: str, routes_url: str = "", rental_id: Optional[int] = None,
                  video_file: Optional[str] = None) -> None:
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

            from livekit.rtc import (
                AudioSource, LocalAudioTrack, LocalVideoTrack,
                Room, RoomOptions, TrackPublishOptions, VideoSource,
            )

            # Probe video file dimensions if streaming a file
            vw, vh, vfps = 640, 480, 30.0
            if video_file:
                import cv2 as _cv2
                _cap = _cv2.VideoCapture(video_file)
                raw_w = int(_cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
                raw_h = int(_cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
                vfps = _cap.get(_cv2.CAP_PROP_FPS) or 30.0
                _cap.release()
                if raw_w > 1280:
                    scale = 1280.0 / raw_w
                    vw, vh = 1280, int(raw_h * scale)
                else:
                    vw, vh = raw_w, raw_h

            room = Room()

            async def _connect() -> None:
                await room.connect(
                    details["serverUrl"],
                    details["participantToken"],
                    options=RoomOptions(auto_subscribe=True),
                )

            self._async_bridge.run(_connect())
            self._rooms[entity_id] = room

            audio_source = AudioSource(sample_rate=48000, num_channels=1)
            audio_track = LocalAudioTrack.create_audio_track("mock-audio", audio_source)
            video_source = VideoSource(vw, vh)
            video_track = LocalVideoTrack.create_video_track(
                "file-video" if video_file else "mock-video", video_source
            )

            async def _publish() -> None:
                lp = room.local_participant
                await lp.publish_track(audio_track, TrackPublishOptions())
                await lp.publish_track(video_track, TrackPublishOptions())

            self._async_bridge.run(_publish())

            stop_event = threading.Event()
            self._track_stops[entity_id] = stop_event

            def _push_frames() -> None:
                audio_frame = _generate_audio_frame()
                if video_file:
                    import cv2 as _cv2
                    from livekit.rtc import VideoFrame
                    cap = _cv2.VideoCapture(video_file)
                    frame_interval = 1.0 / vfps
                    while not stop_event.is_set():
                        ret, bgr = cap.read()
                        if not ret:
                            cap.set(_cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        if bgr.shape[1] != vw or bgr.shape[0] != vh:
                            bgr = _cv2.resize(bgr, (vw, vh))
                        rgba = _cv2.cvtColor(bgr, _cv2.COLOR_BGR2RGBA)
                        vf = VideoFrame(vw, vh, 0, rgba.tobytes())
                        try:
                            video_source.capture_frame(vf)
                            asyncio.run_coroutine_threadsafe(
                                audio_source.capture_frame(audio_frame),
                                self._async_bridge._loop,
                            ).result(timeout=1)
                        except Exception:
                            break
                        stop_event.wait(frame_interval)
                    cap.release()
                else:
                    video_frame = _generate_video_frame()
                    while not stop_event.is_set():
                        try:
                            video_source.capture_frame(video_frame)
                            asyncio.run_coroutine_threadsafe(
                                audio_source.capture_frame(audio_frame),
                                self._async_bridge._loop,
                            ).result(timeout=1)
                        except Exception:
                            break
                        stop_event.wait(0.02)

            thread = threading.Thread(target=_push_frames, daemon=True)
            thread.start()
            self._track_threads[entity_id] = thread

        self.benchmark("join_room", _do, entity_id=entity_id, room_name=user.room_name)
        if not user.rejected:
            user.joined_at = time.time()

    def leave_room(self, entity_id: str) -> None:
        user = self.report.users[entity_id]

        def _do() -> None:
            stop_event = self._track_stops.pop(entity_id, None)
            if stop_event:
                stop_event.set()
            thread = self._track_threads.pop(entity_id, None)
            if thread:
                thread.join(timeout=2)

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

    def ensure_wallet(self, entity_id: str) -> tuple:
        """Return (address, is_new) for entity_id, creating the wallet only on first use.

        Persists addresses in memo/wallets.json keyed by scenario/network/entity_id so
        wallets are isolated per network. Use is_new to gate fund_wallet calls.
        """
        if self.dry_run:
            return ("0x" + "00" * 32, True)

        scenario_key = f"{self.report.scenario_name}/{self.topology.contract_network}"
        memo = self._load_wallet_memo()
        existing = memo.get(scenario_key, {}).get(entity_id, "")
        if existing:
            self.log(f"wallet reused: {existing} ({entity_id})")
            return (existing, False)

        addr = self._create_new_wallet(entity_id)
        memo.setdefault(scenario_key, {})[entity_id] = addr
        self._save_wallet_memo()
        return (addr, True)

    def create_wallet(self, entity_id: str = "") -> str:
        """Return a persisted Ed25519 address for entity_id, creating one only on first use.

        Addresses are stored in memo/wallets.json keyed by scenario/network/entity_id so
        wallets are isolated per network and subsequent runs skip unnecessary funding.
        Use ensure_wallet() instead if you need to know whether the wallet is newly created.
        """
        if self.dry_run:
            return "0x" + "00" * 32

        if entity_id:
            addr, _ = self.ensure_wallet(entity_id)
            return addr

        return self._create_new_wallet(entity_id)

    def _create_new_wallet(self, entity_id: str = "") -> str:
        # sui client new-address registers the key in both the keystore and client.yaml,
        # so sui client switch --address works immediately afterward.
        output = self.sui_cli(["client", "new-address", "ed25519", "--json"], capture=True)
        try:
            data = json.loads(output or "{}")
            addr = data.get("address") or data.get("suiAddress") or ""
            if addr:
                self.log(f"wallet created: {addr}" + (f" ({entity_id})" if entity_id else ""))
                return addr
        except Exception:
            pass
        raise SystemExit("Could not parse address from sui client new-address output")

    def fund_wallet(self, address: str, amount_mist: int) -> None:
        """Split coins from the active (deployer) address and transfer to target address."""
        self.sui_cli([
            "client", "ptb",
            "--split-coins", "gas", f"[{amount_mist}]",
            "--assign", "fund_coin",
            "--transfer-objects", "[fund_coin.0]", f"@{address}",
            "--gas-budget", "10000000",
        ])

    def wallet_balance(self, address: str) -> int:
        """Return the total MIST balance for an address."""
        if self.dry_run:
            return 0
        output = self.sui_cli(["client", "gas", "--json", address], capture=True)
        try:
            coins = json.loads(output or "[]")
        except json.JSONDecodeError:
            return 0
        return sum(int(coin.get("mistBalance", 0)) for coin in coins)

    def ensure_wallet_funded(
        self,
        address: str,
        min_balance_mist: int,
        top_up_mist: int,
        label: str = "",
    ) -> None:
        """Top up an address when it cannot cover scenario PTB gas budgets."""
        balance = self.wallet_balance(address)
        if balance >= min_balance_mist:
            suffix = f" ({label})" if label else ""
            self.log(f"wallet funded: {address[:12]}... balance={balance} MIST{suffix}")
            return

        amount = max(top_up_mist, min_balance_mist - balance)
        self.fund_wallet(address, amount)
        suffix = f" ({label})" if label else ""
        self.log(f"funded: {address[:12]}... +{amount} MIST{suffix}")

    def sui_cli(self, args: List[str], capture: bool = False, as_address: str = "") -> Optional[str]:
        import shlex
        import subprocess
        import sys

        from cli.env import build_contract_env

        if not self._env:
            self._env = build_contract_env(self.topology.contract_network)

        deployer = self._env.get("CONTRACT_DEPLOYER_ADDRESS", "")

        if as_address and not self.dry_run:
            self.log(f"$ sui client switch --address {as_address}")
            subprocess.run(
                ["sui", "client", "switch", "--address", as_address],
                env=self._env,
                check=True,
                capture_output=True,
                text=True,
            )

        cmd = ["sui"] + args
        self.log(f"$ {shlex.join(cmd)}")
        if self.dry_run:
            return None

        stdout: Optional[str] = None
        try:
            result = subprocess.run(
                cmd,
                env=self._env,
                capture_output=capture,
                text=True,
                check=True,
            )
            stdout = result.stdout if capture else None
        except subprocess.CalledProcessError as exc:
            if exc.stdout:
                print(exc.stdout, end="", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr, end="", file=sys.stderr)
            raise
        finally:
            if as_address and deployer and not self.dry_run:
                subprocess.run(
                    ["sui", "client", "switch", "--address", deployer],
                    env=self._env,
                    check=False,
                    capture_output=True,
                    text=True,
                )
        return stdout

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
    topo = report.topology
    vc_str = f" / {topo.vclient_nodes}vc" if topo.vclient_nodes else ""
    print(f"topology: {topo.worker_nodes}w / {topo.dist_nodes}d{vc_str} / {topo.coordinator_nodes}coord")
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
                "provider": report.topology.provider,
                "region": report.topology.region,
                "instance_type": report.topology.instance_type,
                "worker_nodes": report.topology.worker_nodes,
                "dist_nodes": report.topology.dist_nodes,
                "vclient_nodes": report.topology.vclient_nodes,
                "coordinator_nodes": report.topology.coordinator_nodes,
                "contract_network": report.topology.contract_network,
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
    if getattr(args, "dist_nodes", None) is not None:
        topology.dist_nodes = args.dist_nodes
    if getattr(args, "coordinator_nodes", None) is not None:
        topology.coordinator_nodes = args.coordinator_nodes
    topology.provider = provider
    topology.contract_network = getattr(args, "contract_network", "devnet")

    print(f"scenario: {scenario.name}")
    print(f"  {scenario.description}")
    print(f"  topology: {topology.worker_nodes} workers, {topology.dist_nodes} dist, {topology.coordinator_nodes} coordinators")
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
                dist_nodes=topology.dist_nodes,
                vclient_nodes=topology.vclient_nodes,
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
            dist_nodes=topology.dist_nodes,
            vclient_nodes=topology.vclient_nodes,
            coordinator_nodes=topology.coordinator_nodes,
            auto_approve=True,
        )
        cmd_destroy(destroy_args)


# ── launch command ────────────────────────────────────────────────────────────

def _list_scenarios() -> None:
    from cli.config import REPO_ROOT
    scenario_dir = REPO_ROOT / "scenario"

    # Collect groups: named subdirectories first, then top-level files
    groups: Dict[str, List[Path]] = {}
    for subdir in sorted(scenario_dir.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("_") and not subdir.name.startswith("."):
            scripts = sorted(subdir.glob("*.py"))
            if scripts:
                groups[subdir.name] = scripts
    top_level = sorted(scenario_dir.glob("*.py"))
    if top_level:
        groups["(root)"] = top_level

    if not groups:
        print("No scenario scripts found in scenario/")
        return

    print()
    for group_name, scripts in groups.items():
        print(f"  [{group_name.upper()}]")
        for path in scripts:
            try:
                s = load_scenario(path)
                t = s.topology
                teardown_flag = "teardown" if t.teardown else "persistent"
                vc_part = f"/{t.vclient_nodes}vc" if t.vclient_nodes else ""
                topo_str = (
                    f"{t.provider} | {t.worker_nodes}w/{t.dist_nodes}d{vc_part}/{t.coordinator_nodes}coord"
                    f" | {t.contract_network} | {teardown_flag}"
                )
                print(f"    {path.name:<32} {s.name:<25} {topo_str}")
                print(f"    {'':32} {s.description}")
            except Exception as e:
                print(f"    {path.name:<32} (load error: {e})")
        print()
    print(f"  Run: python3 vidctl.py launch scenario/<category>/<file>.py")


def _terraform_apply_with_topology(topo: Topology, env: Any) -> None:
    """Run terraform apply passing region/instance_type from topology."""
    from cli.infra import provider_terraform_root, terraform_init
    from cli.process import run_command

    root = provider_terraform_root(topo.provider)
    terraform_init(topo.provider, env)

    vars = [
        "-input=false",
        "-var=testbed_name=depin-testbed",
        f"-var=worker_count={topo.worker_nodes}",
        f"-var=dist_count={topo.dist_nodes}",
        f"-var=vclient_count={topo.vclient_nodes}",
        f"-var=coordinator_count={topo.coordinator_nodes}",
    ]
    if topo.provider == "alibaba-cloud":
        vars.append(f"-var=alicloud_region={topo.region}")
        if topo.instance_type:
            vars.append(f"-var=alicloud_instance_type={topo.instance_type}")

    run_command(["terraform", "apply", "-auto-approve", *vars], cwd=root, env=env)


def _apply_registry_overrides(topo: Topology, args: argparse.Namespace) -> None:
    if getattr(args, "skip_build", False):
        topo.registry_init = False
        topo.registry_build = False
        return
    registry_init = getattr(args, "registry_init", None)
    registry_build = getattr(args, "registry_build", None)
    if registry_init is not None:
        topo.registry_init = registry_init
    if registry_build is not None:
        topo.registry_build = registry_build
    if getattr(args, "registry_namespace", None):
        topo.registry_namespace = args.registry_namespace
    if getattr(args, "registry_tag", None):
        topo.registry_tag = args.registry_tag
    if getattr(args, "registry_platform", None):
        topo.registry_platform = args.registry_platform


def _setup_registry(topo: Topology) -> None:
    from cli.infra import cmd_registry_build, cmd_registry_init

    if topo.registry_init:
        init_args = argparse.Namespace(provider=topo.provider, namespace=topo.registry_namespace)
        cmd_registry_init(init_args)

    if topo.registry_build:
        build_args = argparse.Namespace(
            provider=topo.provider,
            tag=topo.registry_tag,
            platform=topo.registry_platform,
        )
        cmd_registry_build(build_args)


def _setup_and_push_images(topo: Topology, env: Any) -> None:
    from cli.infra import cmd_build_images

    build_args = argparse.Namespace(
        provider=None,
        registry=None,
        tag="latest",
        push=False,
        platform="linux/amd64",
    )
    cmd_build_images(build_args)


def _print_launch_banner(scenario: "Scenario", topo: Topology, dry_run: bool = False) -> None:
    print(f"\n{'='*60}")
    print(f"LAUNCH: {scenario.name}")
    print(f"  {scenario.description}")
    print(f"  provider:    {topo.provider}  ({topo.region})")
    if topo.instance_type:
        print(f"  instance:    {topo.instance_type}")
    vc_nodes_str = f" / {topo.vclient_nodes} vclient" if topo.vclient_nodes else ""
    print(f"  nodes:       {topo.worker_nodes} workers / {topo.dist_nodes} dist{vc_nodes_str} / {topo.coordinator_nodes} coordinators")
    print(f"  network:     {topo.contract_network}")
    print(f"  contract:    {'deploy+init' if topo.deploy_contract else 'use existing'}")
    print(f"  registry:    init={topo.registry_init} build={topo.registry_build} tag={topo.registry_tag}")
    print(f"  teardown:    {topo.teardown}")
    if topo.benchmark_targets:
        targets = "  ".join(f"{k}<{v}ms" for k, v in topo.benchmark_targets.items())
        print(f"  targets:     {targets}")
    if dry_run:
        print("  mode:        DRY RUN")
    print(f"{'='*60}\n")


def cmd_launch(args: argparse.Namespace) -> None:
    if getattr(args, "list", False) or not getattr(args, "scenario", None):
        _list_scenarios()
        return

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise SystemExit(f"Scenario file not found: {scenario_path}")

    scenario = load_scenario(scenario_path)
    topo = scenario.topology
    dry_run = getattr(args, "dry_run", False)
    no_teardown = getattr(args, "no_teardown", False)
    _apply_registry_overrides(topo, args)

    _print_launch_banner(scenario, topo, dry_run)

    deployment = None
    if not dry_run:
        from cli.contract import cmd_deploy_contract, cmd_update_contract
        from cli.discovery import discover, is_deployed, wait_for_routes
        from cli.env import build_env
        from cli.infra import (
            ansible_playbook,
            render_ansible_vars,
            render_inventory,
            require_runtime_env,
            terraform_output,
        )

        env = build_env(topo.provider)
        if topo.registry_init or topo.registry_build:
            print("\nSetting up container registry...")
            _setup_registry(topo)
            env = build_env(topo.provider)
        if not topo.build_images:
            require_runtime_env(env)

        infra_provisioned_here = False
        _purge_args = argparse.Namespace(
            provider=topo.provider,
            auto_approve=True,
            testbed_name="depin-testbed",
            worker_nodes=topo.worker_nodes,
            dist_nodes=topo.dist_nodes,
            vclient_nodes=topo.vclient_nodes,
            coordinator_nodes=topo.coordinator_nodes,
            node_registry_contract_id=None,
        )

        if not is_deployed(topo.provider):
            print("Provisioning infrastructure from topology spec...")
            _terraform_apply_with_topology(topo, env)
            infra_provisioned_here = True

            if topo.build_images:
                print("\nSetting up container registry and building images...")
                _setup_and_push_images(topo, env)
                env = build_env(topo.provider)
                require_runtime_env(env)

            try:
                if topo.deploy_contract:
                    from cli.config import CONTRACT_PACKAGE_PATH
                    contract_args = argparse.Namespace(
                        network=topo.contract_network,
                        package_path=CONTRACT_PACKAGE_PATH,
                        gas_budget=1_000_000_000,
                    gas_coins=[],
                )
                cmd_deploy_contract(contract_args)
                env = build_env(topo.provider)

                outputs = terraform_output(topo.provider, env)
                inventory_path = render_inventory(topo.provider, outputs)
                vars_path = render_ansible_vars(topo.provider, outputs, env)
                ansible_playbook(inventory_path, vars_path, env)
            except Exception as exc:
                print(f"\n[atomic] step failed — purging infrastructure to avoid partial state...")
                try:
                    from cli.infra import cmd_purge
                    cmd_purge(_purge_args)
                except Exception as purge_exc:
                    print(f"[atomic] purge also failed: {purge_exc}")
                raise SystemExit(f"Launch aborted and infrastructure purged. Original error: {exc}")
        else:
            print(f"Infrastructure already deployed for {topo.provider} — skipping provisioning.")
            if getattr(args, "update_contract", False):
                print("\nUpgrading on-chain contract...")
                from cli.config import CONTRACT_PACKAGE_PATH
                update_args = argparse.Namespace(
                    network=topo.contract_network,
                    package_path=CONTRACT_PACKAGE_PATH,
                    gas_budget=1_000_000_000,
                    gas_coins=[],
                    skip_verify_compatibility=False,
                )
                cmd_update_contract(update_args)
                env = build_env(topo.provider)

        deployment = discover(topo.provider)
        print(f"  routes:   {deployment.routes_url}")
        print(f"  livekit:  {deployment.livekit_url}")
        print("\nWaiting for routes service...")
        try:
            wait_for_routes(deployment)
        except Exception as exc:
            if infra_provisioned_here:
                print(f"\n[atomic] routes service unreachable — purging infrastructure...")
                try:
                    from cli.infra import cmd_purge
                    cmd_purge(_purge_args)
                except Exception as purge_exc:
                    print(f"[atomic] purge also failed: {purge_exc}")
            raise SystemExit(f"Routes service did not become ready: {exc}")
        print("  routes service ready\n")

    report = BenchmarkReport(scenario_name=scenario.name, topology=topo)
    ctx = ScenarioContext(topology=topo, report=report, dry_run=dry_run)
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

    should_teardown = topo.teardown and not no_teardown
    if should_teardown and not dry_run:
        print("\nTearing down infrastructure (topology.teardown=True)...")
        from cli.infra import cmd_purge
        purge_args = argparse.Namespace(
            provider=topo.provider,
            auto_approve=True,
            testbed_name="depin-testbed",
            worker_nodes=topo.worker_nodes,
            dist_nodes=topo.dist_nodes,
            vclient_nodes=topo.vclient_nodes,
            coordinator_nodes=topo.coordinator_nodes,
            node_registry_contract_id=None,
        )
        cmd_purge(purge_args)
