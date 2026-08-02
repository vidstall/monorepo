from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from .. import context
from ..observer.metrics_writer import MetricsFileRegistry, write_metrics_entry
from .system_status import capture_system_snapshot

SAMPLE_INTERVAL_SECONDS = 5

_ACTION_IDENTITY_FIELDS = ("action_index", "action_id", "action_type")


class SystemLog:
    """Owns one `scenario run`'s event trail under
    data/logs/<scenario_name>/<run_timestamp>/ -- `run.json` for run-level
    events (run_start/run_end) and `actions/<index>-<type>.json` for one
    action's events (before_action/during_action x N/after_action), mirroring
    cli.scenario.metrics_sampler's per-entity file layout under
    context.METRICS_ROOT instead of a single ever-growing file per run.
    Reuses cli.observer.metrics_writer's atomic read-append-write primitive
    directly rather than re-implementing it."""

    def __init__(self, scenario_path: str, env: str, scenario_name: str) -> None:
        self.env = env
        started = datetime.now(timezone.utc)
        self.run_timestamp = started.strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = context.LOGS_ROOT / scenario_name / self.run_timestamp
        self._registry = MetricsFileRegistry()
        self._run_identity = {
            "scenario_path": scenario_path,
            "env": env,
            "run_started_at": started.isoformat(),
        }

    def record(self, phase: str, **fields: Any) -> None:
        action_index = fields.get("action_index")
        if action_index is None:
            event = {"phase": phase, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}
            write_metrics_entry(self._registry, self.run_dir / "run.json", self._run_identity, "events", event)
            return

        identity = {name: fields.get(name) for name in _ACTION_IDENTITY_FIELDS}
        remaining = {k: v for k, v in fields.items() if k not in _ACTION_IDENTITY_FIELDS}
        event = {"phase": phase, "timestamp": datetime.now(timezone.utc).isoformat(), **remaining}
        safe_type = str(identity["action_type"] or "unknown").replace(".", "-")
        path = self.run_dir / "actions" / f"{action_index:03d}-{safe_type}.json"
        write_metrics_entry(self._registry, path, identity, "events", event)


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
