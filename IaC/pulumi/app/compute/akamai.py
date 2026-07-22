from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_linode as linode

    name = instance["name"]
    # `services` is set for colocated hosts (program.py's group-by-name
    # merge); fall back to the singular service/port pair for a
    # single-service instance so this function still works unchanged when
    # called directly (mirrors digitalocean.py's create_vm).
    services = instance.get("services") or (
        [{"service": instance.get("service", ""), "port": int(instance.get("port") or 0)}]
        if instance.get("service")
        else []
    )
    inbounds = [
        linode.FirewallInboundArgs(action="ACCEPT", label="ssh", protocol="TCP", ports="22"),
    ]
    seen_ports: set[int] = set()
    for svc in services:
        port = int(svc.get("port") or 0)
        if port and port not in seen_ports:
            seen_ports.add(port)
            inbounds.append(
                linode.FirewallInboundArgs(
                    action="ACCEPT",
                    label=f"port-{port}",
                    protocol="TCP",
                    ports=str(port),
                )
            )
    if any(svc.get("service") == "relay" for svc in services):
        # relay's mediasoup RTC/pipe transports -- see
        # services/worker/apps/relay/.env.example and the matching Ansible
        # port-publish change in docker_service/tasks/main.yml.
        for label, ports in (("relay-rtc", "10000-10100"), ("relay-pipe", "40000-40100")):
            inbounds.append(
                linode.FirewallInboundArgs(action="ACCEPT", label=label, protocol="UDP", ports=ports)
            )
    if any(svc.get("service") in ("relay", "signaling") for svc in services):
        # Each relay/signaling instance gets a Caddy TLS sidecar (see
        # docker_service/tasks/deploy_one_service.yml) that terminates HTTPS
        # via a free Let's Encrypt cert on an sslip.io hostname -- port 80
        # for the ACME HTTP-01 challenge, port 443 for the actual wss://
        # traffic clients connect to.
        for label, port in (("http", 80), ("https", 443)):
            inbounds.append(
                linode.FirewallInboundArgs(action="ACCEPT", label=label, protocol="TCP", ports=str(port))
            )

    server = linode.Instance(
        f"{name}-vm",
        label=f"xaisen-{name}",
        region=provider_region("akamai", instance),
        type=instance.get("size") or "g6-nanode-1",
        image="linode/ubuntu22.04",
        authorized_keys=[public_key],
        # Pause/restart lifecycle: `booted` is Linode's in-place power-state
        # toggle (mirrors alicloud.ecs.Instance's `status` field in
        # alibaba.py) -- a plain `pulumi up` re-reads desired_state from
        # topology.toml and boots/shuts the instance down without recreating
        # it, so no targeted-apply machinery (like alibaba's
        # alibaba_vm_target_urns) is needed here.
        booted=instance.get("desired_state") != "stopped",
    )
    linode.Firewall(
        f"{name}-vm-fw",
        label=f"xaisen-{name}-fw",
        inbound_policy="DROP",
        outbound_policy="ACCEPT",
        inbounds=inbounds,
        linodes=[server.id.apply(lambda value: int(value))],
    )
    return {"address": server.ip_address, "user": "root"}
