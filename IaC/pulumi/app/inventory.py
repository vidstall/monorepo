from __future__ import annotations

from typing import Any

import pulumi

from .config import OBJECT_STORAGE_SERVICE, ROOT
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
    if (
        instance.get("backend") == "object_storage"
        or instance.get("service") == OBJECT_STORAGE_SERVICE
    ):
        return False
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
    return pulumi.Output.all(resource["address"]).apply(
        lambda values: {
            "ansible_host": values[0],
            "ansible_user": resource["user"],
            "ansible_ssh_private_key_file": key_path,
            "xaisen_service": instance.get("service", ""),
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
) -> dict[str, Any]:
    inventory_hosts: dict[str, Any] = {}
    for host in hosts:
        host_name = host.get("name")
        if host_name:
            inventory_hosts[host_name] = host_entry(host)
    for instance in instances:
        host_name = instance.get("name")
        if not host_name or not should_include_ansible_host(instance):
            continue
        if instance.get("backend") != "vm":
            inventory_hosts[host_name] = topology_host_entry(instance, topology)
            continue
        resource = vm_resources.get(host_name)
        if resource is None or resource.get("address") is None:
            continue
        inventory_hosts[host_name] = vm_host_entry(instance, resource, topology)
    return {
        "all": {
            "hosts": {},
            "children": {"xaisen": {"hosts": inventory_hosts}},
        }
    }
