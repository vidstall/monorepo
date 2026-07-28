from __future__ import annotations

import sys

from .config import read_hosts
from .inventory import write_inventory


def status(host: str | None = None) -> int:
    """SSH-reachability check for one (or every) registered observer host,
    via the same ping.yml playbook cli/infra/ansible.py's ping() uses --
    works unchanged since observer hosts join the same `xaisen` Ansible
    group (see inventory.py)."""
    # Deferred self-import: ansible_playbook is patched by tests as a flat
    # cli.infra attribute -- looking it up through the package at call time
    # is what makes that patch take effect here.
    from .. import infra

    hosts = read_hosts()
    if not hosts:
        print("No observer hosts registered. Run `vidctl observer add-host` first.", file=sys.stderr)
        return 1
    if host is not None and not any(h.get("name") == host for h in hosts):
        print(f"Unknown observer host: {host}", file=sys.stderr)
        return 1

    write_inventory()

    # See deploy.py's comment: --limit must never fall back to the whole
    # `xaisen` group (which also contains the Pulumi-managed fleet).
    host_limit = host if host is not None else ",".join(str(h["name"]) for h in hosts)
    return infra.ansible_playbook("ping.yml", host_limit=host_limit)
