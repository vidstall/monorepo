from __future__ import annotations

from typing import cast

import pulumi

from .common.environment import cloud_credentials
from .compute.service import create_vm_instance, vm_workers
from .frontend.service import create_frontend_site, frontend_instances
from .inventory import build_inventory
from .models import HostConfig, TopologyInstance
from .topology import load_topology


def _group_vm_workers(
    workers: list[TopologyInstance],
) -> tuple[dict[str, TopologyInstance], dict[str, TopologyInstance]]:
    """Merge topology rows sharing a VM `host` into one instance per host.

    Colocation-capable providers only (currently digitalocean, upcloud,
    akamai, azure, and oci): multiple topology rows can share a `host` to colocate several
    worker services on one VM (each `vidctl infra start --host X --service Y` call
    writes its own row). Calling create_vm_instance() once per raw row would
    create duplicate Pulumi resource URNs (`{host}-vm`, `{host}-vm-key`,
    `{host}-vm-fw`) and crash -- this merges them into one synthetic instance
    carrying a `services` list before provisioning.

    Every other provider keeps the exact 1-row-per-VM behavior unchanged.

    Returns (host -> instance to pass to create_vm_instance, host -> merged
    instance for inventory/host_vars -- the same object for the merged case,
    but kept as two dicts since the non-merged case still needs
    create_vm_instance called once per raw row).
    """
    to_provision: dict[str, TopologyInstance] = {}
    merged_for_inventory: dict[str, TopologyInstance] = {}
    groups: dict[str, list[TopologyInstance]] = {}
    for worker in vm_workers(workers):
        groups.setdefault(str(worker.get("host")), []).append(worker)

    for host, rows in groups.items():
        if len(rows) == 1 or rows[0].get("provider") not in ("digitalocean", "upcloud", "akamai", "azure", "oci"):
            # Original behavior, preserved exactly: one create_vm_instance
            # call per row (out of scope for this fix to change).
            for index, row in enumerate(rows):
                key = host if index == 0 else f"{host}#{index}"
                to_provision[key] = row
                merged_for_inventory[key] = row
            continue

        active = [r for r in rows if r.get("desired_state") not in ("deleted", "unknown")]
        if not active:
            # Nothing on this host wants to run -- provision from any one
            # row so create_vm_instance's existing deleted/unknown
            # short-circuit (compute/service.py) returns the null result.
            to_provision[host] = rows[0]
            merged_for_inventory[host] = rows[0]
            continue

        sizes = {r["size"] for r in active if r.get("size")}
        if len(sizes) > 1:
            raise ValueError(
                f"Host '{host}' has conflicting --size values across colocated "
                f"worker services ({sorted(sizes)}). Pass a matching --size on every "
                "`vidctl infra start`/`restart` call sharing this --host."
            )

        merged: TopologyInstance = dict(active[0])  # type: ignore[assignment]

        def _service_port(r: TopologyInstance) -> dict:
            service = str(r.get("service", ""))
            index = int(r.get("worker_index", 1) or 1)
            # node_exporter is auto-injected once per HOST, never colocated
            # with a same-typed sibling (cli/scenario/spec.py) -- it reports
            # on the whole machine, so it gets a host-level identity
            # (<provider>-<host>, e.g. "digitalocean-001") instead of the
            # generic per-service worker_key below. This is what
            # prometheus.yml.j2's node_exporter scrape target hostname is
            # built from -- without this it fell through to the bare
            # literal "node_exporter" (index is always 1 for it), which is
            # what showed up as the opaque instance label on the
            # Infrastructure dashboard.
            if service == "node_exporter":
                worker_key = f"{r.get('provider', '')}-{r.get('host', '')}"
            else:
                # <provider>-<host>-<service>-<index> -- MUST match
                # cli/infra/topology.py's worker_identifier() exactly:
                # cli/infra/control_fleet.py/control_batch.py/control.py key
                # xaisen_operator_wallets by this exact string, and
                # deploy_one_service.yml's "Write operator wallet
                # credentials" task looks up
                # xaisen_operator_wallets[host][worker_key] -- a mismatch
                # here means that lookup silently misses, no wallet file
                # ever gets written, and every daemon crashes on boot with
                # "Missing keypair env var" (confirmed the hard way: this
                # used to be the un-suffixed-index-1 scheme here while
                # cli/infra had already moved to worker_identifier()'s
                # always-4-part format, breaking every colocated fleet
                # deploy since). Reimplemented inline (not imported) since
                # this Pulumi program is a separate Python project from
                # cli/ -- same reasoning as contract_exporter.py's own
                # not-imported-from-cli/gui note.
                worker_key = f"{r.get('provider', '')}-{r.get('host', '')}-{service}-{index}"
            return {
                "service": service,
                "port": int(r.get("port", 0) or 0),
                # Per-service state, NOT the host-level aggregate below --
                # Ansible uses this to start/stop each container
                # independently of its colocated siblings.
                "desired_state": str(r.get("desired_state", "")),
                "index": index,
                "worker_key": worker_key,
            }

        merged["services"] = sorted(
            (_service_port(r) for r in active),
            key=lambda sp: (sp["service"], sp["index"]),
        )
        if sizes:
            merged["size"] = next(iter(sizes))
        if any(r.get("desired_state") == "running" for r in active):
            merged["desired_state"] = "running"

        to_provision[host] = merged
        merged_for_inventory[host] = merged

    return to_provision, merged_for_inventory


def run() -> None:
    config = pulumi.Config("xaisen")
    hosts = cast(list[HostConfig], config.get_object("hosts") or [])
    topology = load_topology()
    workers = cast(list[TopologyInstance], topology.get("workers", []))
    objects = cast(list[TopologyInstance], topology.get("objects", []))
    to_provision, merged_vm_workers = _group_vm_workers(workers)
    vm_resources = {
        host: create_vm_instance(instance) for host, instance in to_provision.items()
    }
    inventory = build_inventory(hosts, workers, vm_resources, topology, merged_vm_workers)
    frontend_sites = {
        str(obj.get("name", "frontend")): create_frontend_site(obj)
        for obj in frontend_instances(objects)
    }
    pulumi.export("cloudCredentials", cloud_credentials())
    pulumi.export("topology", topology)
    pulumi.export("frontendSites", frontend_sites)
    pulumi.export("ansibleInventory", inventory)
