from typing import Any

import pulumi

from ..models import TopologyInstance


def security_rules(instance: TopologyInstance) -> list[tuple[str, str, str]]:
    port = int(instance.get("port") or 0)
    if instance.get("service") in ("routes", "frontend"):
        return [("tcp", "80/80", "http"), ("tcp", "443/443", "https")]
    if instance.get("service") == "media":
        return [
            ("tcp", "7880/7880", "signal"),
            ("tcp", "7881/7881", "ice"),
            ("tcp", "7890/7890", "broker"),
            ("udp", "50000/60000", "rtc"),
        ]
    return [("tcp", f"{port}/{port}", "port")] if port else []


def create_network(name: str, zone: str, instance: TopologyInstance, provider: Any):
    import pulumi_alicloud as alicloud

    opts = pulumi.ResourceOptions(provider=provider)
    vpc = alicloud.vpc.Network(
        f"{name}-vm-vpc",
        cidr_block="172.16.0.0/16",
        vpc_name=f"xaisen-{name}",
        opts=opts,
    )
    vswitch = alicloud.vpc.Switch(
        f"{name}-vm-vswitch",
        vpc_id=vpc.id,
        cidr_block="172.16.0.0/24",
        zone_id=zone,
        opts=opts,
    )
    group = alicloud.ecs.SecurityGroup(f"{name}-vm-sg", vpc_id=vpc.id, opts=opts)
    alicloud.ecs.SecurityGroupRule(
        f"{name}-vm-sg-ssh",
        type="ingress",
        ip_protocol="tcp",
        port_range="22/22",
        cidr_ip="0.0.0.0/0",
        security_group_id=group.id,
        opts=opts,
    )
    for protocol, port_range, rule_name in security_rules(instance):
        alicloud.ecs.SecurityGroupRule(
            f"{name}-vm-sg-{rule_name}",
            type="ingress",
            ip_protocol=protocol,
            port_range=port_range,
            cidr_ip="0.0.0.0/0",
            security_group_id=group.id,
            opts=opts,
        )
    return vswitch, group, opts
