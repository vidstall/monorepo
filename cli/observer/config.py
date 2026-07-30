from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ..infra import toml_value

# NOT 9090 (Prometheus's own well-known default) -- the port this host
# publishes it under externally. Picked arbitrarily away from both 9090 and
# other well-trafficked scanner targets; override per-host with
# `add-host --port`.
DEFAULT_HOST_PORT = 19917


def read_hosts() -> list[dict[str, Any]]:
    """Every static host registered via `vidctl observer add-host`, read
    from runtime/observer.toml. Empty list if the file doesn't exist yet --
    unlike topology.toml, there's no "ensure" bootstrap step; this module
    has nothing to default until a host is actually added."""
    from .. import context

    if not context.RUNTIME_OBSERVER_TOML.exists():
        return []
    data = tomllib.loads(context.RUNTIME_OBSERVER_TOML.read_text(encoding="utf-8"))
    return list(data.get("hosts", []))


def write_hosts(hosts: list[dict[str, Any]]) -> None:
    from .. import context

    context.RUNTIME_OBSERVER_TOML.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for entry in hosts:
        lines.append("[[hosts]]")
        for key, value in entry.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    context.RUNTIME_OBSERVER_TOML.write_text("\n".join(lines), encoding="utf-8")


def find_host(name: str) -> dict[str, Any] | None:
    for entry in read_hosts():
        if entry.get("name") == name:
            return entry
    return None


def add_host(
    name: str,
    address: str,
    ssh_user: str,
    ssh_key: str,
    port: int | None = None,
    services: list[str] | None = None,
) -> dict[str, Any]:
    """Add (or update, if `name` already exists) a static observer host.
    ssh_key is expanded and resolved to an absolute path at write time --
    Ansible's ansible_ssh_private_key_file needs a real filesystem path, not
    a shell-expandable `~/...` string it never expands itself. Re-adding an
    existing host preserves its current desired_state (start/stop/restart),
    published port, and services split unless explicitly passed.

    services: which of the 5 known monitoring services (prometheus/tempo/
    grafana/pushgateway/loki) this host should run -- lets two (or more)
    weak static hosts divide the stack between them instead of each running
    all 5 colocated. None (the default) means "all 5", today's implicit
    behavior, preserved for hosts registered before this option existed and
    for any caller that doesn't care about splitting the stack (see
    inventory.py's _host_entry(), which applies this same fallback). Only
    written into the persisted entry when actually set, so runtime/
    observer.toml stays unchanged for hosts that never use this."""
    key_path = str(Path(ssh_key).expanduser())
    existing = find_host(name)
    desired_state = existing.get("desired_state", "running") if existing else "running"
    if port is None:
        port = existing.get("port", DEFAULT_HOST_PORT) if existing else DEFAULT_HOST_PORT
    if services is None:
        services = existing.get("services") if existing else None
    entry = {
        "name": name,
        "address": address,
        "ssh_user": ssh_user,
        "ssh_key": key_path,
        "port": port,
        "desired_state": desired_state,
    }
    if services is not None:
        entry["services"] = list(services)
    hosts = [h for h in read_hosts() if h.get("name") != name]
    hosts.append(entry)
    write_hosts(hosts)
    return entry


def set_desired_state(name: str, desired_state: str) -> dict[str, Any] | None:
    """Flip a registered host's desired_state ("running"/"stopped") --
    consumed by inventory.py's xaisen_services entry, which is what
    docker_service/tasks/deploy_one_service.yml's docker_container `state:`
    is keyed off. Returns None if `name` isn't registered."""
    hosts = read_hosts()
    updated: dict[str, Any] | None = None
    for entry in hosts:
        if entry.get("name") == name:
            entry["desired_state"] = desired_state
            updated = entry
    if updated is not None:
        write_hosts(hosts)
    return updated


def remove_host(name: str) -> bool:
    """Forget a static host locally. Deliberately does NOT touch the remote
    box in any way -- no SSH, no container stop/remove -- only removes it
    from future `deploy`/`status` runs. Returns False if `name` wasn't
    registered."""
    hosts = read_hosts()
    remaining = [h for h in hosts if h.get("name") != name]
    if len(remaining) == len(hosts):
        return False
    write_hosts(remaining)
    return True
