from __future__ import annotations

import json
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
    logs/<scenario_name>/<run_timestamp>/ -- `run.json` for run-level
    events (run_start/run_end) and `actions/<index>-<type>.json` for one
    action's events (before_action/during_action x N/after_action), mirroring
    cli.scenario.metrics_sampler's per-entity file layout under
    context.METRICS_ROOT instead of a single ever-growing file per run.
    Reuses cli.observer.metrics_writer's atomic read-append-write primitive
    directly rather than re-implementing it."""

    def __init__(
        self, scenario_path: str, env: str, scenario_name: str, run_timestamp: str | None = None
    ) -> None:
        self.env = env
        started = datetime.now(timezone.utc)
        # run_timestamp is normally passed in by run() -- generated ONCE,
        # before either SystemLog or MetricsSampler is constructed -- so
        # both trees land under the exact same <run_timestamp> even though
        # they're keyed by different first-level names (scenario_name here,
        # provider for MetricsSampler). Falling back to generating our own
        # here only matters for the one direct-construction test call site;
        # every real `scenario run` invocation always passes one in.
        self.run_timestamp = run_timestamp if run_timestamp is not None else started.strftime("%Y%m%dT%H%M%SZ")
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
    a fresh LIVE system snapshot and records it as an event -- wrapped
    defensively even though capture_system_snapshot() shouldn't itself
    raise, so a logging failure can never abort a scenario run. Only used
    for the run_start/run_end events now (cli.scenario.run.py) -- 2 live
    calls per run, negligible. Per-action before/after/during markers use
    record_action_marker() instead (no live query at all -- see that
    function's doc and backfill_action_snapshots())."""
    if system_log is None:
        return
    try:
        snapshot = capture_system_snapshot(env)
    except Exception as exc:  # noqa: BLE001
        snapshot = {"error": str(exc)}
    system_log.record(phase, snapshot=snapshot, **fields)


def record_action_marker(system_log: SystemLog | None, phase: str, **fields: Any) -> None:
    """No-ops when system_log is None (logging disabled). Otherwise records
    a bare identity+timestamp event -- NO Prometheus query, unlike
    record_snapshot_event(). SystemLog.record() already stamps a timestamp
    on every event for free, so this is a pure local write with zero
    network I/O, meant for the before_action/after_action/during_action
    markers actions.py/DuringActionSampler fire throughout a run. The
    corresponding telemetry gets backfilled once, historically, at run end
    by backfill_action_snapshots() -- see that function's doc for why."""
    if system_log is None:
        return
    system_log.record(phase, **fields)


class DuringActionSampler:
    """Background thread started right before one action's blocking dispatch
    call, stopped right after it returns. Records a bare 'during_action'
    marker (identity + timestamp, no Prometheus query -- see
    record_action_marker()) every SAMPLE_INTERVAL_SECONDS; the corresponding
    telemetry gets backfilled historically at run end by
    backfill_action_snapshots(). Fast actions may produce zero samples --
    that's fine."""

    def __init__(
        self,
        system_log: SystemLog,
        env: str,
        action_index: int,
        action_id: str | None,
        action_type: str,
    ) -> None:
        self._system_log = system_log
        self._env = env  # vestigial: no longer read in _run() now that it records a bare marker, not a live snapshot; kept so callers' positional args stay unchanged
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
            record_action_marker(
                self._system_log,
                "during_action",
                action_index=self._action_index,
                action_id=self._action_id,
                action_type=self._action_type,
            )


_MARKER_PHASES = ("before_action", "after_action", "during_action")


def backfill_action_snapshots(system_log: SystemLog, env: str) -> int:
    """Run once at scenario-run end (cli.scenario.run.py's `finally` block,
    after the run_end event and before Grafana capture): for every
    before_action/after_action/during_action marker recorded live during
    the run (bare identity + timestamp, no Prometheus query -- see
    record_action_marker()), fetches Prometheus's historical view of the
    system AS OF that marker's own original timestamp and appends it as a
    companion f"{phase}_snapshot" event (e.g. "before_action_snapshot") in
    the same action file, carrying the same identity fields plus
    `for_timestamp` (the original marker's timestamp, for correlation) and
    `snapshot`. Purely additive -- appends new events via the existing
    SystemLog.record()/write_metrics_entry() machinery rather than mutating
    the original marker events in place (no in-place update primitive
    exists today, and none is needed here).

    This replaces the old design where capture_system_snapshot() queried
    Prometheus LIVE at every single action (2 blocking calls per action,
    plus a live call every 5s while the action was in flight), which was
    the dominant source of a real run's ~44-56s-per-action overhead on top
    of each action's own work.

    Markers are processed SEQUENTIALLY here, deliberately not through a
    second thread pool layered on top -- capture_system_snapshot() already
    fans out internally (its own ThreadPoolExecutor(16) over every worker,
    and another over every observer host) for a SINGLE marker's snapshot.
    Nesting an outer pool across markers as well multiplies that fan-out
    (e.g. 16 markers x 16 workers = up to 256 concurrent HTTPS connections
    to the one Caddy-fronted Prometheus route), which is exactly what
    overwhelmed a real observer host's TLS handshake capacity and turned
    into a wall of `_ssl.c:993: The handshake operation timed out` errors
    the first time this ran for real -- confirmed live. Sequential-over-
    markers keeps concurrency bounded at the existing per-snapshot fan-out
    level (already tuned via the `min(16, len(workers))` caps in
    system_status.py) without changing that -- correctness doesn't depend
    on marker ordering, and there's no live scripted timeline left to
    protect at this point (unlike during the run itself), so the extra
    wall-clock time of not parallelizing markers is an acceptable trade for
    not saturating the observer host. Best-effort per marker: a failed
    capture_system_snapshot() call for one marker becomes {"error": ...} in
    that one snapshot event rather than aborting the whole backfill,
    matching this module's existing warn-and-continue convention. Returns
    the number of markers backfilled (0 if `system_log` has no `actions/`
    directory at all, e.g. a `--fast` run, or a run with no actions), for
    run.py's progress line."""
    actions_dir = system_log.run_dir / "actions"
    if not actions_dir.is_dir():
        return 0

    # (identity, phase, original marker timestamp) -- one per marker found
    # across every action file, gathered up front so the batch below can
    # run through a single shared thread pool.
    markers: list[tuple[dict[str, Any], str, str]] = []
    for path in sorted(actions_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        identity = doc.get("identity") or {}
        for event in doc.get("events", []):
            phase = event.get("phase")
            timestamp = event.get("timestamp")
            if phase in _MARKER_PHASES and timestamp:
                markers.append((identity, phase, timestamp))

    if not markers:
        return 0

    for identity, phase, timestamp in markers:
        try:
            at_time = datetime.fromisoformat(timestamp).timestamp()
            snapshot = capture_system_snapshot(env, at_time=at_time)
        except Exception as exc:  # noqa: BLE001 - one marker's backfill must not sink the rest
            snapshot = {"error": str(exc)}
        system_log.record(
            f"{phase}_snapshot",
            action_index=identity.get("action_index"),
            action_id=identity.get("action_id"),
            action_type=identity.get("action_type"),
            for_timestamp=timestamp,
            snapshot=snapshot,
        )

    return len(markers)
