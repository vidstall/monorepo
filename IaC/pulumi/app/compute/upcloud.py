from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_upcloud as upcloud

    name = instance["host"]
    # `services` is set for colocated hosts (program.py's group-by-name
    # merge); fall back to the singular service/port pair for a
    # single-service instance so this function still works unchanged when
    # called directly (mirrors digitalocean.py's create_vm).
    services = instance.get("services") or (
        [{"service": instance.get("service", ""), "port": int(instance.get("port") or 0)}]
        if instance.get("service")
        else []
    )
    rules = [
        upcloud.FirewallRulesetRuleArgs(
            action="accept",
            direction="in",
            family="IPv4",
            protocol="tcp",
            destination_port_start=22,
            destination_port_end=22,
            source_address_cidr="0.0.0.0/0",
        ),
    ]
    seen_ports: set[int] = set()
    for svc in services:
        port = int(svc.get("port") or 0)
        if port and port not in seen_ports:
            seen_ports.add(port)
            rules.append(
                upcloud.FirewallRulesetRuleArgs(
                    action="accept",
                    direction="in",
                    family="IPv4",
                    protocol="tcp",
                    destination_port_start=port,
                    destination_port_end=port,
                    source_address_cidr="0.0.0.0/0",
                )
            )
    if any(svc.get("service") == "relay" for svc in services):
        # relay's mediasoup RTC/pipe transports -- see
        # services/worker/apps/relay/.env.example and the matching Ansible
        # port-publish change in docker_service/tasks/main.yml.
        for start, end in ((10000, 10100), (40000, 40100)):
            rules.append(
                upcloud.FirewallRulesetRuleArgs(
                    action="accept",
                    direction="in",
                    family="IPv4",
                    protocol="udp",
                    destination_port_start=start,
                    destination_port_end=end,
                    source_address_cidr="0.0.0.0/0",
                )
            )
    if any(svc.get("service") in ("relay", "signaling") for svc in services):
        # Each relay/signaling instance gets a Caddy TLS sidecar (see
        # docker_service/tasks/deploy_one_service.yml) that terminates HTTPS
        # via a free Let's Encrypt cert on an sslip.io hostname -- port 80
        # for the ACME HTTP-01 challenge, port 443 for the actual wss://
        # traffic clients connect to.
        for port in (80, 443):
            rules.append(
                upcloud.FirewallRulesetRuleArgs(
                    action="accept",
                    direction="in",
                    family="IPv4",
                    protocol="tcp",
                    destination_port_start=port,
                    destination_port_end=port,
                    source_address_cidr="0.0.0.0/0",
                )
            )

    zone = provider_region("upcloud", instance)
    instance["region"] = zone
    server = upcloud.Server(
        f"{name}-vm",
        hostname=f"xaisen-{name}",
        zone=zone,
        plan=instance.get("size") or "1xCPU-1GB",
        login=upcloud.ServerLoginArgs(user="root", keys=[public_key], create_password=False),
        network_interfaces=[upcloud.ServerNetworkInterfaceArgs(type="public")],
        template=upcloud.ServerTemplateArgs(storage=instance.get("image") or "Ubuntu Server 22.04 LTS", size=25),
    )
    # FirewallRuleset is per-server (server_uuid), unlike DigitalOcean's
    # shared Firewall+droplet_ids resource -- still exactly one resource per
    # VM, so the colocation merge in program.py's _group_vm_instances (one
    # create_vm() call per merged host) works unchanged.
    upcloud.FirewallRuleset(
        f"{name}-vm-fw",
        name=f"xaisen-{name}-fw",
        server_uuid=server.id,
        rules=rules,
    )
    address = server.network_interfaces.apply(
        lambda nics: nics[0].ip_address if nics else None
    )
    # Server UUID, as `upctl server ...` commands expect -- persisted via
    # persist_vm_resolution() for image_bake.bake().
    instance["resource_id"] = server.id
    return {"address": address, "user": "root"}
