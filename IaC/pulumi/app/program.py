from __future__ import annotations

from typing import cast

import pulumi

from .common.environment import cloud_credentials
from .compute.service import create_vm_instance, vm_instances
from .frontend.service import create_frontend_site, frontend_instances
from .inventory import build_inventory
from .models import HostConfig, TopologyInstance
from .topology import load_topology


def _group_vm_instances(
    instances: list[TopologyInstance],
) -> tuple[dict[str, TopologyInstance], dict[str, TopologyInstance]]:
    """Merge topology rows sharing a VM `name` into one instance per name.

    Colocation-capable providers only (currently digitalocean, upcloud, and
    akamai): multiple topology rows can share a `name` to colocate several
    services on one VM (each `vidctl infra start --name X --service Y` call writes its
    own row). Calling create_vm_instance() once per raw row would create
    duplicate Pulumi resource URNs (`{name}-vm`, `{name}-vm-key`,
    `{name}-vm-fw`) and crash -- this merges them into one synthetic instance
    carrying a `services` list before provisioning.

    Every other provider keeps the exact 1-row-per-VM behavior unchanged.

    Returns (name -> instance to pass to create_vm_instance, name -> merged
    instance for inventory/host_vars -- the same object for the merged case,
    but kept as two dicts since the non-merged case still needs
    create_vm_instance called once per raw row).
    """
    to_provision: dict[str, TopologyInstance] = {}
    merged_for_inventory: dict[str, TopologyInstance] = {}
    groups: dict[str, list[TopologyInstance]] = {}
    for instance in vm_instances(instances):
        groups.setdefault(str(instance.get("name")), []).append(instance)

    for name, rows in groups.items():
        if len(rows) == 1 or rows[0].get("provider") not in ("digitalocean", "upcloud", "akamai"):
            # Original behavior, preserved exactly: one create_vm_instance
            # call per row (out of scope for this fix to change).
            for index, row in enumerate(rows):
                key = name if index == 0 else f"{name}#{index}"
                to_provision[key] = row
                merged_for_inventory[key] = row
            continue

        active = [r for r in rows if r.get("desired_state") not in ("deleted", "unknown")]
        if not active:
            # Nothing on this host wants to run -- provision from any one
            # row so create_vm_instance's existing deleted/unknown
            # short-circuit (compute/service.py) returns the null result.
            to_provision[name] = rows[0]
            merged_for_inventory[name] = rows[0]
            continue

        sizes = {r["size"] for r in active if r.get("size")}
        if len(sizes) > 1:
            raise ValueError(
                f"Instance '{name}' has conflicting --size values across colocated "
                f"services ({sorted(sizes)}). Pass a matching --size on every "
                "`vidctl infra start`/`restart` call sharing this --name."
            )

        merged: TopologyInstance = dict(active[0])  # type: ignore[assignment]

        def _service_port(r: TopologyInstance) -> dict:
            service = str(r.get("service", ""))
            index = int(r.get("instance_index", 1) or 1)
            return {
                "service": service,
                "port": int(r.get("port", 0) or 0),
                # Per-service state, NOT the host-level aggregate below --
                # Ansible uses this to start/stop each container
                # independently of its colocated siblings.
                "desired_state": str(r.get("desired_state", "")),
                "index": index,
                # Namespacing key for Ansible (container name/state dir/wallet
                # file) -- index 1 stays un-suffixed for backward compat with
                # already-deployed single-instance hosts.
                "instance_key": service if index == 1 else f"{service}-{index}",
            }

        merged["services"] = sorted(
            (_service_port(r) for r in active),
            key=lambda sp: (sp["service"], sp["index"]),
        )
        if sizes:
            merged["size"] = next(iter(sizes))
        if any(r.get("desired_state") == "running" for r in active):
            merged["desired_state"] = "running"

        to_provision[name] = merged
        merged_for_inventory[name] = merged

    return to_provision, merged_for_inventory


def run() -> None:
    config = pulumi.Config("xaisen")
    hosts = cast(list[HostConfig], config.get_object("hosts") or [])
    topology = load_topology()
    instances = cast(list[TopologyInstance], topology.get("instances", []))
    objects = cast(list[TopologyInstance], topology.get("objects", []))
    to_provision, merged_vm_instances = _group_vm_instances(instances)
    vm_resources = {
        name: create_vm_instance(instance) for name, instance in to_provision.items()
    }
    inventory = build_inventory(hosts, instances, vm_resources, topology, merged_vm_instances)
    frontend_sites = {
        str(obj.get("name", "frontend")): create_frontend_site(obj)
        for obj in frontend_instances(objects)
    }
    pulumi.export("cloudCredentials", cloud_credentials())
    pulumi.export("topology", topology)
    pulumi.export("frontendSites", frontend_sites)
    pulumi.export("ansibleInventory", inventory)
