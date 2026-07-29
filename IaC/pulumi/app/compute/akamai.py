import hashlib
from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance


def _firewall_label(name: str) -> str:
    """Linode Firewall labels are capped at 32 chars -- unlike the Instance
    label (64 chars), "xaisen-{name}-fw" overflows for longer host names
    (e.g. image_bake.py's auto-generated "bake-akamai-<region>-<timestamp>"
    names). Truncate + hash-suffix to stay under the limit while keeping
    distinct names from colliding."""
    label = f"xaisen-{name}-fw"
    if len(label) <= 32:
        return label
    digest = hashlib.sha1(name.encode()).hexdigest()[:6]
    # Linode also rejects consecutive separators ("--", "__", ".."), so a
    # truncation landing right after a hyphen (e.g. "...us-" + "-<digest>")
    # must have its trailing separator stripped before rejoining.
    truncated = name[:15].rstrip("-_.")
    return f"xaisen-{truncated}-{digest}-fw"


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_linode as linode

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
    # Linode's Firewall API now rejects an inbound rule with no explicit
    # `addresses` ("[400] rules.inbound[0].addresses] Must be one of: ipv4,
    # ipv6") -- it no longer defaults to allow-all, so every rule below must
    # set ipv4s/ipv6s explicitly (open to the world, matching this fleet's
    # other providers which rely on the app-level auth instead of network
    # ACLs for these ports).
    open_v4, open_v6 = ["0.0.0.0/0"], ["::/0"]
    inbounds = [
        linode.FirewallInboundArgs(
            action="ACCEPT", label="ssh", protocol="TCP", ports="22", ipv4s=open_v4, ipv6s=open_v6
        ),
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
                    ipv4s=open_v4,
                    ipv6s=open_v6,
                )
            )
    if any(svc.get("service") == "relay" for svc in services):
        # relay's mediasoup RTC/pipe transports -- see
        # services/worker/apps/relay/.env.example and the matching Ansible
        # port-publish change in docker_service/tasks/main.yml.
        for label, ports in (("relay-rtc", "10000-10100"), ("relay-pipe", "40000-40100")):
            inbounds.append(
                linode.FirewallInboundArgs(
                    action="ACCEPT", label=label, protocol="UDP", ports=ports, ipv4s=open_v4, ipv6s=open_v6
                )
            )
    if any(svc.get("service") in ("relay", "signaling", "bot", "cp-daemon", "validator-daemon") for svc in services):
        # Each relay/signaling/bot instance, plus cp-daemon/validator-daemon (whose
        # only surface is a metrics endpoint), gets a Caddy TLS sidecar (see
        # docker_service/tasks/deploy_one_service.yml) that terminates HTTPS via a
        # free Let's Encrypt cert on an sslip.io hostname -- port 80 for the ACME
        # HTTP-01 challenge, port 443 for the actual traffic (wss:// for relay/
        # signaling, plain HTTPS for the others)
        # traffic clients connect to.
        for label, port in (("http", 80), ("https", 443)):
            inbounds.append(
                linode.FirewallInboundArgs(
                    action="ACCEPT", label=label, protocol="TCP", ports=str(port), ipv4s=open_v4, ipv6s=open_v6
                )
            )

    region = provider_region("akamai", instance)
    instance["region"] = region
    server = linode.Instance(
        f"{name}-vm",
        label=f"xaisen-{name}",
        region=region,
        type=instance.get("size") or "g6-nanode-1",
        image=instance.get("image") or "linode/ubuntu22.04",
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
        label=_firewall_label(name),
        inbound_policy="DROP",
        outbound_policy="ACCEPT",
        inbounds=inbounds,
        linodes=[server.id.apply(lambda value: int(value))],
    )
    # Numeric Linode ID, as `linode-cli linodes ...` commands expect --
    # persisted via persist_vm_resolution() for image_bake.bake().
    instance["resource_id"] = server.id
    return {"address": server.ip_address, "user": "root"}
