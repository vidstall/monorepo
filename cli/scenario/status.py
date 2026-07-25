from __future__ import annotations

from typing import Any

from .. import infra
from .lock import read_lock
from .spec import WorkerKey


def diff_workers(
    wanted: dict[WorkerKey, dict[str, Any]],
    current: dict[WorkerKey, dict[str, Any]],
) -> tuple[list[WorkerKey], list[WorkerKey]]:
    to_kill = sorted(current.keys() - wanted.keys())
    to_start = list(wanted.keys())
    return to_kill, to_start


def _topology_worker_key(item: dict[str, Any], default_env: str) -> WorkerKey:
    return (
        str(item.get("host")),
        str(item.get("service")),
        str(item.get("provider")),
        str(item.get("env", default_env)),
        int(item.get("worker_index", 1) or 1),
    )


def _active_workers_for_env(env: str) -> list[dict[str, Any]]:
    # ensure_topology (not read_topology) since topology.toml may not exist
    # yet on a first-ever `scenario apply` (normally created by `vidctl infra
    # init`, which a scenario apply doesn't require running first).
    topology = infra.ensure_topology(env)
    return [
        item
        for item in topology.get("workers", [])
        if item.get("env", env) == env and item.get("desired_state") != "deleted"
    ]


def status(_args: Any) -> int:
    lock = read_lock()
    if lock is None:
        print("No scenario is currently active.")
        return 0

    print(f"Active scenario: {lock.get('scenario_path')}")
    print(f"  env:      {lock.get('env')}")
    print(f"  status:   {lock.get('status')}")
    print(f"  hash:     {lock.get('scenario_hash', '')}")
    print(f"  applied:  {lock.get('applied_at')}")
    print(f"  updated:  {lock.get('updated_at')}")

    env = str(lock.get("env", ""))
    rows = _active_workers_for_env(env)
    if not rows:
        print("No managed workers.")
        return 0

    print("Workers:")
    for item in sorted(rows, key=lambda r: (str(r.get("host")), str(r.get("service")), int(r.get("worker_index", 1) or 1))):
        worker_index = int(item.get("worker_index", 1) or 1)
        label = str(item.get("service")) if worker_index == 1 else f"{item.get('service')}-{worker_index}"
        state = item.get("last_status") or item.get("desired_state")
        error = f" ERROR: {item.get('last_error')}" if item.get("last_error") else ""
        print(f"  {item.get('host')}/{label}@{item.get('provider')}: {state}{error}")
    return 0
