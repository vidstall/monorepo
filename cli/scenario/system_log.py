from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from .. import context
from .system_status import capture_system_snapshot

LOGS_ROOT = context.ROOT / "logs"
SAMPLE_INTERVAL_SECONDS = 5


class SystemLog:
    """Owns one `scenario run`'s logs/<scenario-name>/<timestamp>.json file:
    an in-memory event list plus atomic incremental persistence (write to a
    sibling temp file, then os.replace) after every event, so a crash
    mid-run leaves a valid, complete-so-far JSON file rather than a
    truncated one or nothing at all."""

    def __init__(self, scenario_path: str, env: str, scenario_name: str) -> None:
        self.env = env
        started = datetime.now(timezone.utc)
        run_dir = LOGS_ROOT / scenario_name
        run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / f"{started.strftime('%Y%m%dT%H%M%SZ')}.json"
        self._file_lock = threading.Lock()
        self._doc: dict[str, Any] = {
            "scenario_path": scenario_path,
            "env": env,
            "run_started_at": started.isoformat(),
            "run_finished_at": None,
            "events": [],
        }
        self._flush()

    def record(self, phase: str, **fields: Any) -> None:
        event = {"phase": phase, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}
        with self._file_lock:
            self._doc["events"].append(event)
            self._flush()

    def finish(self) -> None:
        with self._file_lock:
            self._doc["run_finished_at"] = datetime.now(timezone.utc).isoformat()
            self._flush()

    def _flush(self) -> None:
        # Caller already holds self._file_lock.
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._doc, indent=2, default=str), encoding="utf-8")
        os.replace(tmp_path, self.path)


def record_snapshot_event(system_log: SystemLog | None, env: str, phase: str, **fields: Any) -> None:
    """No-ops when system_log is None (logging disabled). Otherwise captures
    a fresh system snapshot and records it as an event -- wrapped
    defensively even though capture_system_snapshot() shouldn't itself
    raise, so a logging failure can never abort a scenario run."""
    if system_log is None:
        return
    try:
        snapshot = capture_system_snapshot(env)
    except Exception as exc:  # noqa: BLE001
        snapshot = {"error": str(exc)}
    system_log.record(phase, snapshot=snapshot, **fields)


class DuringActionSampler:
    """Background thread started right before one action's blocking dispatch
    call, stopped right after it returns. Samples capture_system_snapshot()
    every SAMPLE_INTERVAL_SECONDS and records each as a 'during_action'
    event. Fast actions may produce zero samples -- that's fine."""

    def __init__(
        self,
        system_log: SystemLog,
        env: str,
        action_index: int,
        action_id: str | None,
        action_type: str,
    ) -> None:
        self._system_log = system_log
        self._env = env
        self._action_index = action_index
        self._action_id = action_id
        self._action_type = action_type
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(SAMPLE_INTERVAL_SECONDS):
            try:
                snapshot = capture_system_snapshot(self._env)
            except Exception as exc:  # noqa: BLE001 - a sampler crash must never kill the run
                snapshot = {"error": str(exc)}
            self._system_log.record(
                "during_action",
                action_index=self._action_index,
                action_id=self._action_id,
                action_type=self._action_type,
                snapshot=snapshot,
            )
