from __future__ import annotations

import sys

from .pool import gc_orphaned_assignments, pool_status, retire_wallet


def list_pool(env_name: str | None) -> int:
    status = pool_status(env_name)
    if not any(status.values()):
        print("No pooled wallets yet.")
        return 0
    for env, entries in status.items():
        retired = sum(1 for entry in entries if entry.get("retired"))
        free = sum(1 for entry in entries if not entry.get("assigned_host") and not entry.get("retired"))
        assigned = len(entries) - free - retired
        print(f"[{env}] {len(entries)} wallet(s), {free} free, {assigned} assigned, {retired} retired")
        for entry in entries:
            if entry.get("retired"):
                reason = entry.get("retired_reason") or "unspecified"
                state = f"RETIRED ({reason})"
            elif entry.get("assigned_host"):
                state = f"assigned -> {entry['assigned_host']}/{entry['assigned_service']}/{entry['assigned_provider']}"
            else:
                role = entry.get("registered_role", "")
                state = f"free (pinned: {role})" if role else "free (unpinned)"
            print(f"  {entry.get('alias', '(no alias)')}  {entry['address']}  {state}")
    return 0


def retire(identifier: str, env_name: str, reason: str) -> int:
    entry = retire_wallet(identifier, env_name, reason)
    if entry is None:
        print(f"No wallet matching '{identifier}' in [{env_name}].", file=sys.stderr)
        return 1
    print(f"Retired {entry.get('alias', '(no alias)')}  {entry['address']}")
    return 0


def gc() -> int:
    from ..context import RUNTIME_TOPOLOGY_TOML
    from ..infra import read_topology

    topology = read_topology() if RUNTIME_TOPOLOGY_TOML.exists() else {"workers": []}
    released = gc_orphaned_assignments(topology)
    for entry in released:
        print(f"Released {entry['address']}")
    print(f"{len(released)} wallet(s) released.")
    return 0
