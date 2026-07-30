from __future__ import annotations

from typing import Any

import pulumi

from .config import ROOT
from .models import HostConfig, TopologyInstance


def host_entry(host: HostConfig | TopologyInstance) -> dict[str, Any]:
    entry: dict[str, Any] = {"ansible_host": host["address"]}
    if host.get("user"):
        entry["ansible_user"] = host["user"]
    if host.get("port"):
        entry["ansible_port"] = host["port"]
    return entry


def topology_host_entry(
    instance: TopologyInstance,
    topology: dict[str, Any],
) -> dict[str, Any]:
    entry = host_entry(instance)
    entry.update(
        {
            "xaisen_service": instance.get("service", ""),
            "xaisen_provider": instance.get("provider", ""),
            "xaisen_env": instance.get("env", topology.get("active_env", "devnet")),
            "xaisen_contract_env": instance.get(
                "contract_env", topology.get("contract_env", "")
            ),
            "xaisen_desired_state": instance.get("desired_state", ""),
        }
    )
    return entry


def should_include_ansible_host(instance: TopologyInstance) -> bool:
    if instance.get("desired_state") in {"deleted", "stopped"}:
        return False
    if instance.get("backend") == "vm":
        return True
    return bool(instance.get("address"))


def vm_host_entry(
    instance: TopologyInstance,
    resource: dict[str, Any],
    topology: dict[str, Any],
) -> pulumi.Output[dict[str, Any]]:
    key_path = str(ROOT / instance.get("ssh_key_dir", "") / "id_ed25519")
    # `services` is set on the merged instance for colocated (digitalocean)
    # hosts (see program.py's _group_vm_workers). For a single-service
    # host it's absent, so fall back to the singular service/port pair --
    # xaisen_service/xaisen_port stay populated too either way, for any
    # Ansible task not yet converted to loop over xaisen_services.
    _fallback_service = instance.get("service", "")
    _fallback_index = instance.get("worker_index", 1)
    # node_exporter is auto-injected once per HOST, never colocated with a
    # same-typed sibling -- same host-level identity rationale as
    # program.py's _service_port() (<provider>-<host>, e.g.
    # "digitalocean-001"), instead of falling through to the bare literal
    # "node_exporter" (index is always 1 for it) that prometheus.yml.j2's
    # node_exporter scrape target hostname used to be built from.
    if _fallback_service == "node_exporter":
        _fallback_worker_key = f"{instance.get('provider', '')}-{instance.get('host', '')}"
    else:
        # <provider>-<host>-<service>-<index> -- MUST match program.py's
        # _service_port() and cli/infra/topology.py's worker_identifier()
        # exactly; see that function's comment for why a mismatch here
        # silently breaks wallet/keypair injection fleet-wide.
        _fallback_worker_key = f"{instance.get('provider', '')}-{instance.get('host', '')}-{_fallback_service}-{_fallback_index}"
    services = instance.get("services") or (
        [
            {
                "service": _fallback_service,
                "port": instance.get("port", 0),
                "desired_state": instance.get("desired_state", ""),
                "index": _fallback_index,
                "worker_key": _fallback_worker_key,
            }
        ]
        if instance.get("service")
        else []
    )
    return pulumi.Output.all(resource["address"]).apply(
        lambda values: {
            "ansible_host": values[0],
            "ansible_user": resource["user"],
            "ansible_ssh_private_key_file": key_path,
            "xaisen_service": instance.get("service", ""),
            "xaisen_services": services,
            "xaisen_provider": instance.get("provider", ""),
            "xaisen_env": instance.get(
                "env", topology.get("active_env", "devnet")
            ),
            "xaisen_contract_env": instance.get(
                "contract_env", topology.get("contract_env", "")
            ),
            "xaisen_desired_state": instance.get("desired_state", ""),
            "xaisen_port": instance.get("port", 0),
        }
    )


def build_inventory(
    hosts: list[HostConfig],
    workers: list[TopologyInstance],
    vm_resources: dict[str, dict[str, Any]],
    topology: dict[str, Any],
    merged_vm_workers: dict[str, TopologyInstance] | None = None,
) -> dict[str, Any]:
    inventory_hosts: dict[str, Any] = {}
    for host in hosts:
        host_name = host.get("name")
        if host_name:
            inventory_hosts[host_name] = host_entry(host)

    merged_vm_workers = merged_vm_workers or {}
    seen_vm_hosts: set[str] = set()
    for instance in workers:
        host_name = instance.get("host")
        if not host_name:
            continue
        # Golden-image bake VMs (cli/image_bake.py, service="__bake__") are
        # provisioned through the normal topology-driven pulumi up and DO
        # stay in this inventory -- image_bake.bake() needs their resolved
        # address from here (via infra.host_address()) to SSH in and
        # bootstrap them itself. They're still harmless if ever swept into a
        # real `vidctl infra configure` run: docker_service's first task
        # (`end_host` when xaisen_services is undefined/empty) no-ops for
        # them immediately, since a bake row never gets services assigned.
        if instance.get("backend") != "vm":
            if not should_include_ansible_host(instance):
                continue
            inventory_hosts[host_name] = topology_host_entry(instance, topology)
            continue
        # Colocated hosts have multiple raw rows sharing one host_name --
        # process each unique VM host once, and decide inclusion off the
        # MERGED worker's aggregate desired_state (e.g. one colocated
        # service paused while another still runs must keep the host in
        # inventory), not whichever raw row happens to be seen first.
        if host_name in seen_vm_hosts:
            continue
        seen_vm_hosts.add(host_name)
        vm_worker = merged_vm_workers.get(host_name, instance)
        if not should_include_ansible_host(vm_worker):
            continue
        resource = vm_resources.get(host_name)
        if resource is None or resource.get("address") is None:
            continue
        inventory_hosts[host_name] = vm_host_entry(vm_worker, resource, topology)
    return {
        "all": {
            "hosts": {},
            "children": {"xaisen": {"hosts": inventory_hosts}},
        }
    }
