from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import tomllib

from .. import infra
from .. import object as object_cmd
from ..context import ROOT

SCENARIO_DIR = ROOT / "scenario"

WorkerKey = tuple[str, str, str, str, int]
FrontendKey = tuple[str, str, str]


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
    }


def scenario_hash_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
