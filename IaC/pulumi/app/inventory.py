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
    # hosts (see program.py's _group_vm_instances). For a single-service
    # host it's absent, so fall back to the singular service/port pair --
    # xaisen_service/xaisen_port stay populated too either way, for any
    # Ansible task not yet converted to loop over xaisen_services.
    services = instance.get("services") or (
        [
            {
                "service": instance.get("service", ""),
                "port": instance.get("port", 0),
                "desired_state": instance.get("desired_state", ""),
                "index": instance.get("instance_index", 1),
                "instance_key": instance.get("service", "")
                if instance.get("instance_index", 1) == 1
                else f"{instance.get('service', '')}-{instance.get('instance_index', 1)}",
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
    instances: list[TopologyInstance],
    vm_resources: dict[str, dict[str, Any]],
    topology: dict[str, Any],
    merged_vm_instances: dict[str, TopologyInstance] | None = None,
) -> dict[str, Any]:
    inventory_hosts: dict[str, Any] = {}
    for host in hosts:
        host_name = host.get("name")
        if host_name:
            inventory_hosts[host_name] = host_entry(host)

    merged_vm_instances = merged_vm_instances or {}
    seen_vm_hosts: set[str] = set()
    for instance in instances:
        host_name = instance.get("name")
        if not host_name:
            continue
        if instance.get("backend") != "vm":
            if not should_include_ansible_host(instance):
                continue
            inventory_hosts[host_name] = topology_host_entry(instance, topology)
            continue
        # Colocated hosts have multiple raw rows sharing one host_name --
        # process each unique VM host once, and decide inclusion off the
        # MERGED instance's aggregate desired_state (e.g. one colocated
        # service paused while another still runs must keep the host in
        # inventory), not whichever raw row happens to be seen first.
        if host_name in seen_vm_hosts:
            continue
        seen_vm_hosts.add(host_name)
        vm_instance = merged_vm_instances.get(host_name, instance)
        if not should_include_ansible_host(vm_instance):
            continue
        resource = vm_resources.get(host_name)
        if resource is None or resource.get("address") is None:
            continue
        inventory_hosts[host_name] = vm_host_entry(vm_instance, resource, topology)
    return {
        "all": {
            "hosts": {},
            "children": {"xaisen": {"hosts": inventory_hosts}},
        }
    }
