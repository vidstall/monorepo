from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from typing import Any

from .. import bot_client, infra
from .fast_health_poller import FastHealthPoller, worker_healthz_url
from .system_log import DuringActionSampler, SystemLog, record_action_marker

# How long to keep polling after the docker stop/start SSH call returns,
# looking for the /healthz transition -- bounds how long a worker.leave/
# worker.join action can block beyond its own dispatch time waiting for a
# fast_health_poller.FastHealthPoller sample to flip. 5s comfortably covers
# every existing fast-path detector this is meant to be compared against
# (the 1000ms relay-heartbeat.ts poll, the 200ms flap-gate probe) without
# meaningfully lengthening a scripted scenario timeline.
_HEALTH_POLL_GRACE_SECONDS = 5.0


def find_pooled_worker(
    env: str, service: str, provider: str, reserved: set[tuple[str, int]]
) -> dict[str, Any] | None:
    """Look for a paused (desired_state == "stopped") worker matching
    (env, service, provider) that isn't already claimed by an earlier
    action in this same run() -- the implicit "pool" a worker.leave action
    returns a worker to, and a worker.join action draws from before
    provisioning anything new. `reserved` holds (host, worker_index) pairs
    already handed out earlier in this run."""
    topology = infra.ensure_topology(env)
    for worker in topology.get("workers", []):
        if (
            worker.get("env", env) == env
            and worker.get("service") == service
            and worker.get("provider") == provider
            and worker.get("desired_state") == "stopped"
        ):
            key = (str(worker.get("host")), int(worker.get("worker_index", 1) or 1))
            if key not in reserved:
                return worker
    return None


def _resolve_refs(action: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Replace any "$id.key" string field value with the recorded result of
    an earlier action with that `id`. Returns None (caller aborts) if a
    reference points at an id that hasn't run yet or has no such key --
    almost always means the action ordering/timestamps are wrong."""
    resolved = dict(action)
    for field, value in action.items():
        if not isinstance(value, str) or not value.startswith("$"):
            continue
        ref_id, _, ref_key = value[1:].partition(".")
        if ref_id not in results or ref_key not in results[ref_id]:
            print(
                f"Scenario action {action.get('type')!r} references unresolved '{value}' "
                f"(action id {ref_id!r} hasn't produced a {ref_key!r} result yet).",
                file=sys.stderr,
            )
            return None
        resolved[field] = results[ref_id][ref_key]
    return resolved


def _bot_create_room(action: dict[str, Any]) -> dict[str, Any] | None:
    return bot_client.create_room(action["host"], action["media_mode"], action.get("mp4_path"))


def _bot_join_room(action: dict[str, Any]) -> dict[str, Any] | None:
    return bot_client.join_room(action["host"], action["room_id"], action["media_mode"])


def _bot_delete_room(action: dict[str, Any]) -> dict[str, Any] | None:
    return bot_client.delete_room(action["host"], action["bot_id"])


def _find_declared_await_worker(
    action: dict[str, Any],
    service: str,
    provider: str,
    reserved: set[tuple[str, int]],
    deferred_by_key: dict[tuple[str, str, str, int], dict[str, Any]],
) -> dict[str, Any] | None:
    """Match a worker.join action to a declared `await = true` [[workers]]
    row (see spec.py::load_scenario) -- either directly by (host, service,
    provider, worker_index) when the action gives a host, or, when it
    doesn't, by (service, provider) alone as long as exactly one still-
    unreserved await worker qualifies (ambiguous otherwise, left to the
    caller to report)."""
    host = action.get("host")
    if host:
        worker_index = int(action.get("worker_index") or 1)
        return deferred_by_key.get((str(host), service, provider, worker_index))

    candidates = [
        row
        for (row_host, row_service, row_provider, row_worker_index), row in deferred_by_key.items()
        if row_service == service
        and row_provider == provider
        and (row_host, row_worker_index) not in reserved
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _worker_join(
    action: dict[str, Any],
    env: str,
    reserved: set[tuple[str, int]],
    deferred_by_key: dict[tuple[str, str, str, int], dict[str, Any]],
) -> dict[str, Any] | None:
    """The pooled-reuse ("restart") call below passes docker_only=True: a
    pooled worker was already fully provisioned once (by `vidctl scenario
    apply`) and is only ever paused/resumed by churn, never reconfigured --
    so control() skips the whole Ansible reconcile entirely and just fires
    a bare `docker start <container>` (see control.py's `docker_only`
    param, and IaC/ansible/playbooks/toggle_container.yml). It also passes
    detach=False (blocking) -- that one-command playbook is fast, and
    running it synchronously lets this function bracket a real
    "container_action_confirmed_at" ground-truth timestamp around it (see
    fast_health_poller.py / run_actions()'s detection-latency measurement),
    which a detached/backgrounded dispatch could never give an accurate
    value for. The fresh-provision ("start") call just below still passes
    detach=True: that path pays the full Ansible reconcile (SSH-reconnect
    wait plus every OTHER colocated service on the host, see
    docker_service/tasks/main.yml) -- minutes of overhead a scripted
    scenario timeline shouldn't have to block on, and it isn't the churn
    path this latency measurement targets anyway."""
    service = action["service"]
    provider = action["provider"]
    pooled = find_pooled_worker(env, service, provider, reserved)
    if pooled is not None:
        host = str(pooled.get("host"))
        worker_index = int(pooled.get("worker_index", 1) or 1)
        health_url = worker_healthz_url(host, service, provider, worker_index)
        poller = FastHealthPoller(health_url) if health_url else None
        if poller is not None:
            poller.start()
        dispatched_at = time.time()
        code = infra.control(
            "restart",
            host,
            service,
            provider,
            yes=True,
            worker_index=worker_index,
            detach=False,
            docker_only=True,
        )
        confirmed_at = time.time()
        health_poll = None
        if poller is not None:
            poller.wait_for_transition(_HEALTH_POLL_GRACE_SECONDS)
            poller.stop()
            health_poll = poller.result()
        if code != 0:
            return None
        reserved.add((host, worker_index))
        return {
            "host": host,
            "worker_index": worker_index,
            "reused": True,
            "container_action_dispatched_at": datetime.fromtimestamp(dispatched_at, tz=timezone.utc).isoformat(),
            "container_action_confirmed_at": datetime.fromtimestamp(confirmed_at, tz=timezone.utc).isoformat(),
            "health_poll": health_poll,
        }

    declared = _find_declared_await_worker(action, service, provider, reserved, deferred_by_key)
    if declared is None and not action.get("host"):
        ambiguous = [
            row
            for (row_host, row_service, row_provider, row_worker_index), row in deferred_by_key.items()
            if row_service == service and row_provider == provider and (row_host, row_worker_index) not in reserved
        ]
        if len(ambiguous) > 1:
            print(
                f"worker.join (service={service}, provider={provider}): multiple declared await=true workers "
                f"match and no 'host' was given to disambiguate: "
                f"{sorted(row['host'] for row in ambiguous)}.",
                file=sys.stderr,
            )
            return None

    host = action.get("host") or (declared["host"] if declared else None)
    if not host:
        print(
            f"worker.join (service={service}, provider={provider}): no paused worker available to reuse, "
            "no declared await=true worker matches, and no 'host' given to provision a new one.",
            file=sys.stderr,
        )
        return None
    worker_index = int(action.get("worker_index") or (declared["worker_index"] if declared else 1))
    size = action.get("size") or (declared.get("size") if declared else None)
    region = action.get("region") or (declared.get("region") if declared else None)
    code = infra.control(
        "start",
        host,
        service,
        provider,
        yes=True,
        size=size,
        worker_index=worker_index,
        region=region,
        detach=True,
    )
    if code != 0:
        return None
    reserved.add((host, worker_index))
    return {"host": host, "worker_index": worker_index, "reused": False}


def _worker_leave(action: dict[str, Any]) -> dict[str, Any] | None:
    """docker_only=True: pause alone runs no Ansible by default (just a
    VM-power-state check) -- see control.py's docker_only pause branch for
    why this action now also fires a targeted `docker stop <container>`
    (skipped when this is the last active worker on the host, since the
    whole VM is powering off anyway, via IaC/ansible/playbooks/
    toggle_container.yml's single `docker stop` task). detach=False
    (blocking) rather than the fire-and-forget dispatch _worker_join's
    fresh-provision path uses: that one-command playbook is fast, and
    running it synchronously lets this function bracket a real
    "container_action_confirmed_at" ground-truth timestamp (time.time()
    immediately before/after the blocking infra.control() call) for the
    scenario's detection-latency measurement -- an async/detached dispatch
    would only tell us when the SSH command was *launched*, not when
    `docker stop` actually finished on the host.

    A fast_health_poller.FastHealthPoller is started (relay only -- see
    SUPPORTED_SERVICES) right before dispatch and kept running for
    _HEALTH_POLL_GRACE_SECONDS after confirmed_at, so its first observed
    /healthz transition ("health_poll"["observed_at"] in the returned
    dict) can be diffed against container_action_confirmed_at to get a
    real detection-latency number (see report.py)."""
    host = action["host"]
    service = action["service"]
    provider = action["provider"]
    worker_index = int(action.get("worker_index") or 1)
    health_url = worker_healthz_url(host, service, provider, worker_index)
    poller = FastHealthPoller(health_url) if health_url else None
    if poller is not None:
        poller.start()
    dispatched_at = time.time()
    code = infra.control(
        "pause",
        host,
        service,
        provider,
        yes=True,
        worker_index=worker_index,
        detach=False,
        docker_only=True,
    )
    confirmed_at = time.time()
    health_poll = None
    if poller is not None:
        poller.wait_for_transition(_HEALTH_POLL_GRACE_SECONDS)
        poller.stop()
        health_poll = poller.result()
    if code != 0:
        return None
    return {
        "host": host,
        "worker_index": worker_index,
        "container_action_dispatched_at": datetime.fromtimestamp(dispatched_at, tz=timezone.utc).isoformat(),
        "container_action_confirmed_at": datetime.fromtimestamp(confirmed_at, tz=timezone.utc).isoformat(),
        "health_poll": health_poll,
    }


def run_actions(scenario: dict[str, Any], env: str, system_log: SystemLog | None = None) -> int:
    actions = scenario.get("actions", [])
    if not actions:
        print("Scenario has no [[actions]]; nothing to run.")
        return 0

    t0 = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    reserved: set[tuple[str, int]] = set()
    deferred_by_key: dict[tuple[str, str, str, int], dict[str, Any]] = {
        (row["host"], row["service"], row["provider"], row["worker_index"]): row
        for row in scenario.get("workers", [])
        if row.get("await")
    }

    for index, action in enumerate(actions):
        resolved = _resolve_refs(action, results)
        if resolved is None:
            print(f"Scenario run failed resolving references for action #{index + 1}.", file=sys.stderr)
            return 1

        record_action_marker(
            system_log,
            "before_action",
            action_index=index,
            action_id=resolved.get("id"),
            action_type=resolved.get("type"),
            action=resolved,
        )

        wait_seconds = t0 + resolved["offset_seconds"] - time.monotonic()
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        action_type = resolved["type"]
        action_started = time.monotonic()
        sampler = (
            DuringActionSampler(system_log, env, index, resolved.get("id"), action_type)
            if system_log is not None
            else None
        )
        if sampler is not None:
            sampler.start()
        try:
            if action_type == "bot.create_room":
                result = _bot_create_room(resolved)
            elif action_type == "bot.join_room":
                result = _bot_join_room(resolved)
            elif action_type == "bot.delete_room":
                result = _bot_delete_room(resolved)
            elif action_type == "worker.join":
                result = _worker_join(resolved, env, reserved, deferred_by_key)
            elif action_type == "worker.leave":
                result = _worker_leave(resolved)
            else:  # pragma: no cover - load_scenario() already rejects unknown types
                print(f"Scenario run failed at action #{index + 1}: unknown type {action_type!r}.", file=sys.stderr)
                return 1
        finally:
            if sampler is not None:
                sampler.stop()
        duration_seconds = time.monotonic() - action_started

        if result is None:
            record_action_marker(
                system_log,
                "after_action",
                action_index=index,
                action_id=resolved.get("id"),
                action_type=action_type,
                action=resolved,
                duration_seconds=duration_seconds,
                error="action returned None",
            )
            print(
                f"Scenario run failed at action #{index + 1} (type={action_type}, id={resolved.get('id')}).",
                file=sys.stderr,
            )
            return 1

        if resolved.get("id"):
            results[resolved["id"]] = result
        record_action_marker(
            system_log,
            "after_action",
            action_index=index,
            action_id=resolved.get("id"),
            action_type=action_type,
            action=resolved,
            duration_seconds=duration_seconds,
            result=result,
        )
        print(f"Action #{index + 1} (type={action_type}) succeeded: {result}")

    print(f"Scenario actions complete: {len(actions)} ran.")
    return 0
