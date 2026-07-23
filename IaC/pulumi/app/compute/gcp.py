from typing import Any

from ..common.regions import provider_zone
from ..models import TopologyInstance


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_gcp as gcp

    name = instance["host"]
    port = int(instance.get("port") or 0)
    zone = provider_zone(instance)
    instance["zone"] = zone
    tag = f"xaisen-{name}"
    # gcloud commands identify instances by name (not a separate numeric
    # ID), and `tag` here already *is* that name -- persisted via
    # persist_vm_resolution() for image_bake.bake().
    instance["resource_id"] = tag
    allows = [gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["22"])]
    if port:
        allows.append(gcp.compute.FirewallAllowArgs(protocol="tcp", ports=[str(port)]))
    if instance.get("service") == "media":
        allows.append(gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["7890"]))
    gcp.compute.Firewall(
        f"{name}-vm-fw",
        network="default",
        allows=allows,
        source_ranges=["0.0.0.0/0"],
        target_tags=[tag],
    )
    vm = gcp.compute.Instance(
        f"{name}-vm",
        name=tag,
        machine_type=instance.get("size") or "e2-micro",
        zone=zone,
        tags=[tag],
        boot_disk=gcp.compute.InstanceBootDiskArgs(
            initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(
                image=instance.get("image") or "ubuntu-os-cloud/ubuntu-2204-lts",
            ),
        ),
        network_interfaces=[
            gcp.compute.InstanceNetworkInterfaceArgs(
                network="default",
                access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()],
            ),
        ],
        metadata={"ssh-keys": f"ubuntu:{public_key}"},
    )
    address = vm.network_interfaces[0].access_configs[0].nat_ip
    return {"address": address, "user": "ubuntu"}
