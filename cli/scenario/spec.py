from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import tomllib

from .. import infra
from .. import object as object_cmd
from ..bot_client import MEDIA_MODES
from ..context import ROOT

SCENARIO_DIR = ROOT / "scenario"

WorkerKey = tuple[str, str, str, str, int]
FrontendKey = tuple[str, str, str]

ACTION_TYPES = (
    "bot.create_room",
    "bot.join_room",
    "bot.delete_room",
    "worker.join",
    "worker.leave",
)

# Required fields per action type, beyond the common `type`/`timestamp`/`id`.
# Checked for presence (non-empty) at load time; per-field format/enum
# validation (media_mode, service, provider, ...) happens separately below.
ACTION_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "bot.create_room": ("host",),
    "bot.join_room": ("host", "room_id"),
    "bot.delete_room": ("host", "bot_id"),
    "worker.join": ("service", "provider"),
    "worker.leave": ("host", "service", "provider"),
}

_TIMESTAMP_RE = re.compile(r"^\+(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


def parse_timestamp(value: str) -> int:
    """Parse a scenario action's `timestamp` field ("+10s", "+5m", "+1h30m")
    into a total-seconds offset from t0 (when `scenario run` starts) -- NOT
    chained off the previous action. Raises ValueError on anything that
    isn't `+` followed by at least one of h/m/s components."""
    match = _TIMESTAMP_RE.match(value)
    if not match or not any(match.groups()):
        raise ValueError(f"expected a duration like '+10s', '+5m', '+1h30m', got {value!r}")
    hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def load_scenario(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Scenario file not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    env = str(data.get("env", ""))
    if env not in infra.NETWORKS:
        raise ValueError(f"Scenario env must be one of {', '.join(infra.NETWORKS)}, got {env!r}.")

    raw_workers = data.get("workers", [])
    if not isinstance(raw_workers, list) or not raw_workers:
        raise ValueError("Scenario must declare at least one [[workers]] entry.")

    seen: set[WorkerKey] = set()
    workers: list[dict[str, Any]] = []
    for row in raw_workers:
        host = str(row.get("host", ""))
        service = str(row.get("service", ""))
        provider = str(row.get("provider", ""))
        worker_index = int(row.get("worker_index", 1) or 1)
        if not host:
            raise ValueError("Every scenario worker needs a 'host'.")
        if service not in infra.DOCKER_SERVICES and service not in infra.PINNED_IMAGES:
            raise ValueError(f"Unknown service '{service}' for worker on host '{host}'.")
        if provider not in infra.PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' for worker on host '{host}'.")
        key: WorkerKey = (host, service, provider, env, worker_index)
        if key in seen:
            raise ValueError(
                f"Duplicate scenario worker: host={host} service={service} "
                f"provider={provider} worker_index={worker_index}."
            )
        seen.add(key)
        workers.append(
            {
                "host": host,
                "service": service,
                "provider": provider,
                "worker_index": worker_index,
                "size": row.get("size") or None,
                "region": row.get("region") or None,
            }
        )

    raw_frontends = data.get("frontends", [])
    if not isinstance(raw_frontends, list):
        raise ValueError("Scenario 'frontends' must be an array of tables ([[frontends]]).")

    seen_frontends: set[FrontendKey] = set()
    frontends: list[dict[str, Any]] = []
    for row in raw_frontends:
        name = str(row.get("name", ""))
        object_type = str(row.get("object") or "frontend")
        provider = str(row.get("provider", ""))
        if not name:
            raise ValueError("Every scenario frontend needs a 'name'.")
        if object_type not in object_cmd.OBJECT_TYPES:
            raise ValueError(f"Unknown object type '{object_type}' for frontend '{name}'.")
        if provider not in object_cmd.PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' for frontend '{name}'.")
        key: FrontendKey = (name, object_type, provider)
        if key in seen_frontends:
            raise ValueError(f"Duplicate scenario frontend: name={name} object={object_type} provider={provider}.")
        seen_frontends.add(key)
        frontends.append({"name": name, "object": object_type, "provider": provider})

    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raise ValueError("Scenario 'actions' must be an array of tables ([[actions]]).")

    seen_ids: set[str] = set()
    actions: list[dict[str, Any]] = []
    previous_offset = 0
    for index, row in enumerate(raw_actions):
        action_type = str(row.get("type", ""))
        if action_type not in ACTION_TYPES:
            raise ValueError(
                f"Unknown action type {action_type!r} for action #{index + 1}; "
                f"expected one of {', '.join(ACTION_TYPES)}."
            )

        timestamp_raw = str(row.get("timestamp") or "+0s")
        try:
            offset_seconds = parse_timestamp(timestamp_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid 'timestamp' for action #{index + 1} (type={action_type}): {exc}") from None
        if offset_seconds < previous_offset:
            print(
                f"Warning: action #{index + 1} (type={action_type}) has timestamp {timestamp_raw!r} "
                f"earlier than an earlier action's -- actions run in file order, so this action won't "
                "actually wait as long as its position implies.",
                file=sys.stderr,
            )
        previous_offset = offset_seconds

        action_id = str(row.get("id") or "")
        if action_id:
            if action_id in seen_ids:
                raise ValueError(f"Duplicate scenario action id {action_id!r}.")
            seen_ids.add(action_id)

        for field in ACTION_REQUIRED_FIELDS[action_type]:
            if not row.get(field):
                raise ValueError(f"Action #{index + 1} (type={action_type}) needs a {field!r} field.")

        service = str(row.get("service", ""))
        if service and service not in infra.DOCKER_SERVICES:
            raise ValueError(f"Unknown service {service!r} for action #{index + 1} (type={action_type}).")
        provider = str(row.get("provider", ""))
        if provider and provider not in infra.PROVIDERS:
            raise ValueError(f"Unknown provider {provider!r} for action #{index + 1} (type={action_type}).")
        media_mode = str(row.get("media_mode") or "both")
        if action_type in ("bot.create_room", "bot.join_room") and media_mode not in MEDIA_MODES:
            raise ValueError(
                f"Unknown media_mode {media_mode!r} for action #{index + 1} (type={action_type}); "
                f"expected one of {', '.join(MEDIA_MODES)}."
            )

        actions.append(
            {
                "type": action_type,
                "id": action_id or None,
                "timestamp": timestamp_raw,
                "offset_seconds": offset_seconds,
                "host": str(row.get("host") or "") or None,
                "worker_index": int(row.get("worker_index", 1) or 1),
                "service": service or None,
                "provider": provider or None,
                "size": row.get("size") or None,
                "region": row.get("region") or None,
                "media_mode": media_mode,
                "mp4_path": row.get("mp4_path") or None,
                "room_id": row.get("room_id") or None,
                "bot_id": row.get("bot_id") or None,
            }
        )

    contract_opts = data.get("contract", {})
    contract_opts = contract_opts if isinstance(contract_opts, dict) else {}
    registry_opts = data.get("registry", {})
    registry_opts = registry_opts if isinstance(registry_opts, dict) else {}

    return {
        "name": str(data.get("name") or path.stem),
        "env": env,
        "contract": {
            "gas_budget": contract_opts.get("gas_budget") or None,
            "create_registry_if_missing": bool(contract_opts.get("create_registry_if_missing", False)),
            "force": bool(contract_opts.get("force", False)),
        },
        "registry": {
            "provider": registry_opts.get("provider") or None,
            "tag": registry_opts.get("tag") or None,
        },
        "frontends": frontends,
        "workers": workers,
        "actions": actions,
    }


def scenario_hash_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
