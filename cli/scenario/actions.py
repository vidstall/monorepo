from __future__ import annotations

import sys
import time
from typing import Any

from .. import bot_client, infra
from .system_log import DuringActionSampler, SystemLog, record_snapshot_event


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


def _worker_join(action: dict[str, Any], env: str, reserved: set[tuple[str, int]]) -> dict[str, Any] | None:
    service = action["service"]
    provider = action["provider"]
    pooled = find_pooled_worker(env, service, provider, reserved)
    if pooled is not None:
        host = str(pooled.get("host"))
        worker_index = int(pooled.get("worker_index", 1) or 1)
        code = infra.control("restart", host, service, provider, yes=True, worker_index=worker_index)
        if code != 0:
            return None
        reserved.add((host, worker_index))
        return {"host": host, "worker_index": worker_index, "reused": True}

    host = action.get("host")
    if not host:
        print(
            f"worker.join (service={service}, provider={provider}): no paused worker available to reuse, "
            "and no 'host' given to provision a new one.",
            file=sys.stderr,
        )
        return None
    worker_index = int(action.get("worker_index") or 1)
    code = infra.control(
        "start",
        host,
        service,
        provider,
        yes=True,
        size=action.get("size"),
        worker_index=worker_index,
        region=action.get("region"),
    )
    if code != 0:
        return None
    reserved.add((host, worker_index))
    return {"host": host, "worker_index": worker_index, "reused": False}


def _worker_leave(action: dict[str, Any]) -> dict[str, Any] | None:
    host = action["host"]
    worker_index = int(action.get("worker_index") or 1)
    code = infra.control(
        "pause", host, action["service"], action["provider"], yes=True, worker_index=worker_index
    )
    if code != 0:
        return None
    return {"host": host, "worker_index": worker_index}


def run_actions(scenario: dict[str, Any], env: str, system_log: SystemLog | None = None) -> int:
    actions = scenario.get("actions", [])
    if not actions:
        print("Scenario has no [[actions]]; nothing to run.")
        return 0

    t0 = time.monotonic()
    results: dict[str, dict[str, Any]] = {}
    reserved: set[tuple[str, int]] = set()

    for index, action in enumerate(actions):
        resolved = _resolve_refs(action, results)
        if resolved is None:
            print(f"Scenario run failed resolving references for action #{index + 1}.", file=sys.stderr)
            return 1

        record_snapshot_event(
            system_log,
            env,
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
                result = _worker_join(resolved, env, reserved)
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
            record_snapshot_event(
                system_log,
                env,
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
        record_snapshot_event(
            system_log,
            env,
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
