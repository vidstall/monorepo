from typing import Any

import pulumi

from ..common.environment import require_env
from ..common.regions import provider_region
from ..models import TopologyInstance
from .alibaba_network import create_network
from .alibaba_types import find_spot_type


def select_size(instance: TopologyInstance, provider: Any, region: str):
    import pulumi_alicloud as alicloud

    pinned_size = str(instance.get("size") or "")
    if not pinned_size:
        return find_spot_type(instance["host"], provider, region)
    types = alicloud.ecs.get_instance_types(
        instance_type=pinned_size,
        spot_strategy="SpotAsPriceGo",
        network_type="Vpc",
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if not types.instance_types:
        raise ValueError(
            f"Pinned instance type {pinned_size} has no spot capacity in {region}; "
            "rerun with --find-instance-type."
        )
    return region, pinned_size, types.instance_types[0], provider


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_alicloud as alicloud

    name = instance["host"]
    region = provider_region("alibaba", instance)
    provider = alicloud.Provider(
        f"{name}-vm-provider",
        access_key=require_env("ALIBABA_CLOUD_ACCESS_KEY_ID"),
        secret_key=require_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
        region=region,
    )
    region, size, matched, provider = select_size(instance, provider, region)
    instance["region"] = region
    instance["size"] = size
    zone = str(instance.get("zone") or matched.availability_zones[0])
    vswitch, security_group, opts = create_network(name, zone, instance, provider)
    key = alicloud.ecs.KeyPair(
        f"{name}-vm-key",
        key_pair_name=f"xaisen-{name}",
        public_key=public_key,
        opts=opts,
    )
    baked_image = instance.get("image")
    if baked_image:
        image_id = baked_image
    else:
        images = alicloud.ecs.get_images(
            name_regex="^ubuntu_22_04_x64.*",
            most_recent=True,
            owners="system",
            opts=pulumi.InvokeOptions(provider=provider),
        )
        image_id = images.images[0].id
    vm = alicloud.ecs.Instance(
        f"{name}-vm",
        instance_name=f"xaisen-{name}",
        instance_type=size,
        instance_charge_type="PostPaid",
        spot_strategy="SpotAsPriceGo",
        availability_zone=zone,
        image_id=image_id,
        vswitch_id=vswitch.id,
        security_groups=[security_group.id],
        key_name=key.key_pair_name,
        internet_max_bandwidth_out=5,
        system_disk_size=20,
        status="Stopped" if instance.get("desired_state") == "stopped" else "Running",
        stopped_mode="KeepCharging",
        opts=opts,
    )
    # ECS instance ID, as `aliyun ecs ...` commands expect -- persisted via
    # persist_vm_resolution() for image_bake.bake().
    instance["resource_id"] = vm.id
    return {"address": vm.public_ip, "user": "root"}
