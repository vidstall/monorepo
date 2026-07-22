from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_digitalocean as digitalocean

    name = instance["name"]
    # `services` is set for colocated hosts (program.py's group-by-name
    # merge); fall back to the singular service/port pair for a
    # single-service instance so this function still works unchanged when
    # called directly (e.g. from other providers' equivalent, or tests).
    services = instance.get("services") or (
        [{"service": instance.get("service", ""), "port": int(instance.get("port") or 0)}]
        if instance.get("service")
        else []
    )
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
    seen_ports: set[int] = set()
    for svc in services:
        port = int(svc.get("port") or 0)
        if port and port not in seen_ports:
            seen_ports.add(port)
            inbound_rules.append(
                digitalocean.FirewallInboundRuleArgs(
                    protocol="tcp",
                    port_range=str(port),
                    source_addresses=["0.0.0.0/0", "::/0"],
                )
            )
    if any(svc.get("service") == "relay" for svc in services):
        # relay's mediasoup RTC/pipe transports -- see
        # services/worker/apps/relay/.env.example and the matching Ansible
        # port-publish change in docker_service/tasks/main.yml.
        for udp_range in ("10000-10100", "40000-40100"):
            inbound_rules.append(
                digitalocean.FirewallInboundRuleArgs(
                    protocol="udp", port_range=udp_range, source_addresses=["0.0.0.0/0", "::/0"]
                )
            )
    if any(svc.get("service") in ("relay", "signaling") for svc in services):
        # Each relay/signaling instance gets a Caddy TLS sidecar (see
        # docker_service/tasks/deploy_one_service.yml) that terminates HTTPS
        # via a free Let's Encrypt cert on an sslip.io hostname -- port 80
        # for the ACME HTTP-01 challenge, port 443 for the actual wss://
        # traffic clients connect to.
        for port in (80, 443):
            inbound_rules.append(
                digitalocean.FirewallInboundRuleArgs(
                    protocol="tcp", port_range=str(port), source_addresses=["0.0.0.0/0", "::/0"]
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
    region = provider_region("digitalocean", instance)
    instance["region"] = region
    droplet = digitalocean.Droplet(
        f"{name}-vm",
        name=f"xaisen-{name}",
        image=instance.get("image") or "ubuntu-22-04-x64",
        region=region,
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
    # Numeric droplet ID, as doctl's `--droplet-id`-style args expect (not
    # our internal `name`) -- persisted via persist_vm_resolution() so
    # image_bake.bake() can drive doctl against the right resource.
    instance["resource_id"] = droplet.id
    return {"address": droplet.ipv4_address, "user": "root"}
