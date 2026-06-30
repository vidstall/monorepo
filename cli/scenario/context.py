from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from cli.scenario.media import _AsyncBridge
from cli.scenario.models import BenchmarkReport, BenchmarkSample, Topology
from cli.scenario.rentals import _RentalsMixin
from cli.scenario.users import _UsersMixin
from cli.scenario.wallets import _WalletsMixin
from cli.scenario.workers import _WorkersMixin

_WALLET_MEMO_PATH = Path(__file__).resolve().parents[1] / "memo" / "wallets.json"


class ScenarioContext(_WorkersMixin, _RentalsMixin, _UsersMixin, _WalletsMixin):
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

    def log(self, message: str) -> None:
        print(f"  [{self._step}] {message}", flush=True)

    def step(self, description: str) -> None:
        self._step += 1
        print(f"\n--- step {self._step}: {description}", flush=True)

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

