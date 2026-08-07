"""Correlator for the Grafana "Liveness" table -- `vidctl observer
worker-liveness` (one-shot or --watch, mirrors contract_exporter.py's
export_contract_state() shape). Reads the local ground-truth stop/start
events `cli/worker_status.py` wrote to runtime/worker_liveness.toml, joins
them against the relay's client-awareness metrics
(dvconf_relay_down_hint_total / _last_at_seconds) and the validator-daemon's
worker-awareness metric (dvconf_worker_down_vote_total{target_miner_id}),
and pushes the derived per-event table rows to the observer Pushgateway as
xaisen_worker_liveness_*{event_id,worker}.

Column mapping (see the approved Liveness plan): every value from column 3
onward is pushed as SECONDS SINCE COLUMN 1 (the stop time), not an absolute
timestamp -- so the Grafana panel needs no further math, just field
renames.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

from .. import worker_status
from .query import query
from .pushgateway import push_samples

_JOB_NAME = "worker_liveness_derived"
_HELP_TEXT = (
    "Derived Liveness-experiment values, correlating vidctl utils worker stop/start "
    "against client (relay-down-hint) and worker (validator vote) awareness."
)


def _resolve_miner_id(ref: worker_status.WorkerRef, env: str) -> str | None:
    """This worker's on-chain miner_id (== its checked-out wallet's address),
    by matching WorkerRef's (host, service, provider, index) against the
    wallet pool's assigned_* fields -- the same tuple checkout_wallet() pins
    a wallet to (see cli/wallet/pool.py's _matches()). None if this worker
    was never wallet-assigned in this env (can't independently probe its
    voter count, same posture as an unresolvable target elsewhere in this
    codebase)."""
    from .. import wallet as wallet_cli

    entries = wallet_cli.pool_status(env).get(env, [])
    for entry in entries:
        if (
            entry.get("assigned_host") == ref.host
            and entry.get("assigned_service") == ref.service
            and entry.get("assigned_provider") == ref.provider
            and entry.get("assigned_worker_index", 1) == ref.index
        ):
            address = entry.get("address")
            return str(address) if address else None
    return None


def _numeric_values(result: list[dict] | None) -> list[float]:
    values: list[float] = []
    if not result:
        return values
    for entry in result:
        value = entry.get("value")
        if isinstance(value, list) and len(value) == 2:
            try:
                values.append(float(value[1]))
            except (TypeError, ValueError):
                continue
    return values


def _client_awareness_total() -> int:
    """Fleet-wide cumulative dvconf_relay_down_hint_total, summed across every
    relay instance's own counter series (each relay only counts hints it
    personally received -- there is no single global counter)."""
    return int(sum(_numeric_values(query("dvconf_relay_down_hint_total"))))


def _first_client_awareness_seconds(stopped_at_seconds: float) -> float | None:
    """Earliest dvconf_relay_down_hint_last_at_seconds sample (across every
    relay) that is at-or-after this event's stop time, offset from
    stopped_at_seconds -- i.e. how long after the kill the first client
    noticed. None if no relay has reported a hint since the stop."""
    candidates = [v for v in _numeric_values(query("dvconf_relay_down_hint_last_at_seconds")) if v >= stopped_at_seconds]
    if not candidates:
        return None
    return min(candidates) - stopped_at_seconds


def _worker_awareness_count(miner_id: str) -> int:
    """Distinct validator-daemon processes that have cast at least one
    down-vote against this miner_id -- one series per voting validator
    (prom-client's per-process registry), so len(result) IS the distinct
    count, not a value to sum."""
    result = query(f'dvconf_worker_down_vote_total{{target_miner_id="{miner_id}"}}')
    return len(result) if result else 0


def correlate_event(event: worker_status.LivenessEvent, env: str, host: str = "bourbon") -> int:
    """Compute and push one event's derived row. Returns 0 on a successful
    push, 1 if the push failed (best-effort, matches this CLI's other
    observer exporters)."""
    try:
        stopped_at_seconds = datetime.fromisoformat(event.stopped_at).timestamp()
    except ValueError:
        print(f"worker-liveness: event {event.event_id} has an unparseable stopped_at, skipping.", file=sys.stderr)
        return 1

    labels = {"event_id": event.event_id, "worker": event.worker}
    samples: list[tuple[str, dict[str, str], float]] = [
        ("xaisen_worker_liveness_stopped_at_seconds", labels, stopped_at_seconds),
    ]

    if event.resolved and event.started_at:
        try:
            started_at_seconds = datetime.fromisoformat(event.started_at).timestamp()
            samples.append(("xaisen_worker_liveness_downtime_seconds", labels, started_at_seconds - stopped_at_seconds))
        except ValueError:
            pass

    first_awareness = _first_client_awareness_seconds(stopped_at_seconds)
    if first_awareness is not None:
        samples.append(("xaisen_worker_liveness_first_client_awareness_seconds", labels, first_awareness))

    samples.append(("xaisen_worker_liveness_client_awareness_count", labels, float(_client_awareness_total())))

    ref = worker_status.parse_worker_hostname(event.worker)
    if ref is not None:
        miner_id = _resolve_miner_id(ref, env)
        if miner_id is not None:
            samples.append(("xaisen_worker_liveness_worker_awareness_count", labels, float(_worker_awareness_count(miner_id))))

    return push_samples(_JOB_NAME, event.event_id, samples, _HELP_TEXT, host=host)


def correlate_once(env: str, host: str = "bourbon") -> int:
    """CLI entrypoint for `vidctl observer worker-liveness`. Correlates every
    known event (open or resolved) each run -- experiment volume is low
    (manual, one operator, a handful of stop/start cycles at a time), so
    reprocessing the whole file every tick is simpler than tracking a
    separate "already-pushed" cursor, and it keeps every row's derived
    values fresh (e.g. client_awareness_count keeps climbing) rather than
    frozen at first-push."""
    events = worker_status._read_liveness_events()
    if not events:
        print("worker-liveness: no events on file yet -- nothing to correlate.")
        return 0

    failures = 0
    for event in events:
        if correlate_event(event, env, host) != 0:
            failures += 1
    print(f"worker-liveness: correlated {len(events)} event(s), {failures} push failure(s).")
    return 1 if failures else 0


def watch_worker_liveness(env: str, host: str = "bourbon", interval: int = 60) -> int:
    code = 0
    try:
        while True:
            code = correlate_once(env, host)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return code
