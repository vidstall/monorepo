from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_digitalocean as digitalocean

    name = instance["name"]
    port = int(instance.get("port") or 0)
    key = digitalocean.SshKey(
        f"{name}-vm-key",
        name=f"xaisen-{name}",
        public_key=public_key,
    )
    inbound_rules = [
        digitalocean.FirewallInboundRuleArgs(
            protocol="tcp",
            port_range="22",
            source_addresses=["0.0.0.0/0", "::/0"],
        ),
    ]
    if port:
        inbound_rules.append(
            digitalocean.FirewallInboundRuleArgs(
                protocol="tcp",
                port_range=str(port),
                source_addresses=["0.0.0.0/0", "::/0"],
            )
        )
    if instance.get("service") == "media":
        inbound_rules.append(
            digitalocean.FirewallInboundRuleArgs(
                protocol="tcp", port_range="7890", source_addresses=["0.0.0.0/0", "::/0"]
            )
        )
    destinations = ["0.0.0.0/0", "::/0"]
    outbound_rules = [
        digitalocean.FirewallOutboundRuleArgs(
            protocol="tcp", destination_addresses=destinations, port_range="1-65535"
        ),
        digitalocean.FirewallOutboundRuleArgs(
            protocol="udp", destination_addresses=destinations, port_range="1-65535"
        ),
        digitalocean.FirewallOutboundRuleArgs(
            protocol="icmp", destination_addresses=destinations
        ),
    ]
    droplet = digitalocean.Droplet(
        f"{name}-vm",
        name=f"xaisen-{name}",
        image="ubuntu-22-04-x64",
        region=provider_region("digitalocean", instance),
        size=instance.get("size") or "s-1vcpu-1gb",
        ssh_keys=[key.fingerprint],
    )
    digitalocean.Firewall(
        f"{name}-vm-fw",
        name=f"xaisen-{name}",
        droplet_ids=[droplet.id.apply(lambda value: int(value))],
        inbound_rules=inbound_rules,
        outbound_rules=outbound_rules,
    )
    return {"address": droplet.ipv4_address, "user": "root"}
