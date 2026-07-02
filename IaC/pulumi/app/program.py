from __future__ import annotations

from typing import cast

import pulumi

from .common.environment import cloud_credentials
from .compute.service import create_vm_instance, vm_instances
from .frontend.service import create_frontend_site, frontend_instances
from .inventory import build_inventory
from .models import HostConfig, TopologyInstance
from .topology import load_topology


def run() -> None:
    config = pulumi.Config("xaisen")
    hosts = cast(list[HostConfig], config.get_object("hosts") or [])
    topology = load_topology()
    instances = cast(list[TopologyInstance], topology.get("instances", []))
    objects = cast(list[TopologyInstance], topology.get("objects", []))
    vm_resources = {
        str(instance.get("name")): create_vm_instance(instance)
        for instance in vm_instances(instances)
    }
    inventory = build_inventory(hosts, instances, vm_resources, topology)
    frontend_sites = {
        str(obj.get("name", "frontend")): create_frontend_site(obj)
        for obj in frontend_instances(objects)
    }
    pulumi.export("cloudCredentials", cloud_credentials())
    pulumi.export("topology", topology)
    pulumi.export("frontendSites", frontend_sites)
    pulumi.export("ansibleInventory", inventory)
