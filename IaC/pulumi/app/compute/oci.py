import os
from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance

_NETWORKS: dict[str, dict[str, Any]] = {}
_PROVIDER: Any = None


def _provider():
    # Unlike ARM_*/DIGITALOCEAN_TOKEN-style ambient credentials, pulumi_oci's
    # default provider config isn't reliably ambient-discovered from
    # secrets/cloud/oci.env's OCI_* names -- build it explicitly once and
    # pass it to every resource/data-source call below, so auth is never a
    # guess. OCI_PRIVATE_KEY stores the PEM inline with literal "\n" line
    # breaks (secrets/cloud/*.env is parsed one KEY=VALUE per line); unescape
    # back to real newlines before handing it to the provider.
    global _PROVIDER
    if _PROVIDER is None:
        import pulumi_oci as oci

        _PROVIDER = oci.Provider(
            "oci-provider",
            tenancy_ocid=os.environ["OCI_TENANCY_OCID"],
            user_ocid=os.environ["OCI_USER_OCID"],
            fingerprint=os.environ["OCI_FINGERPRINT"],
            private_key=os.environ["OCI_PRIVATE_KEY"].replace("\\n", "\n"),
            region=os.environ.get("OCI_REGION", "us-ashburn-1"),
        )
    return _PROVIDER


def _compartment_id() -> str:
    compartment_id = os.environ.get("OCI_COMPARTMENT_OCID")
    if not compartment_id:
        raise ValueError(
            "OCI_COMPARTMENT_OCID is required to provision OCI worker VMs -- set it in "
            "secrets/cloud/oci.env."
        )
    return compartment_id


def shared_network(region: str, compartment_id: str):
    # Keyed by region -- same rationale as azure.py's shared_network(): a
    # subnet must be in the same region as the VMs attached to it, so each
    # region provisioned into gets its own VCN/subnet, not one global
    # singleton.
    cached = _NETWORKS.get(region)
    if cached:
        return cached["subnet"], cached["nsg_base"]
    import pulumi
    import pulumi_oci as oci

    opts = pulumi.ResourceOptions(provider=_provider())
    suffix = region.replace(".", "-")
    vcn = oci.core.Vcn(
        f"xaisen-vcn-{suffix}",
        compartment_id=compartment_id,
        cidr_blocks=["10.10.0.0/16"],
        display_name=f"xaisen-vcn-{suffix}",
        opts=opts,
    )
    igw = oci.core.InternetGateway(
        f"xaisen-igw-{suffix}",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        enabled=True,
        display_name=f"xaisen-igw-{suffix}",
        opts=opts,
    )
    route_table = oci.core.RouteTable(
        f"xaisen-rt-{suffix}",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        route_rules=[
            oci.core.RouteTableRouteRuleArgs(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                network_entity_id=igw.id,
            ),
        ],
        opts=opts,
    )
    subnet = oci.core.Subnet(
        f"xaisen-subnet-{suffix}",
        compartment_id=compartment_id,
        vcn_id=vcn.id,
        cidr_block="10.10.1.0/24",
        route_table_id=route_table.id,
        display_name=f"xaisen-subnet-{suffix}",
        prohibit_public_ip_on_vnic=False,
        opts=opts,
    )
    _NETWORKS[region] = {"subnet": subnet, "nsg_base": vcn.id}
    return subnet, vcn.id


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi
    import pulumi_oci as oci

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

    compartment_id = _compartment_id()
    region = provider_region("oci", instance)
    instance["region"] = region
    provider = _provider()
    opts = pulumi.ResourceOptions(provider=provider)
    invoke_opts = pulumi.InvokeOptions(provider=provider)

    subnet, vcn_id = shared_network(region, compartment_id)

    nsg = oci.core.NetworkSecurityGroup(
        f"{name}-vm-nsg",
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=f"xaisen-{name}-nsg",
        opts=opts,
    )

    def _tcp_rule(label: str, port: int) -> None:
        oci.core.NetworkSecurityGroupSecurityRule(
            f"{name}-vm-nsg-{label}",
            network_security_group_id=nsg.id,
            direction="INGRESS",
            protocol="6",  # TCP
            source="0.0.0.0/0",
            source_type="CIDR_BLOCK",
            tcp_options=oci.core.NetworkSecurityGroupSecurityRuleTcpOptionsArgs(
                destination_port_range=oci.core.NetworkSecurityGroupSecurityRuleTcpOptionsDestinationPortRangeArgs(
                    min=port, max=port
                ),
            ),
            opts=opts,
        )

    def _udp_rule(label: str, port_min: int, port_max: int) -> None:
        oci.core.NetworkSecurityGroupSecurityRule(
            f"{name}-vm-nsg-{label}",
            network_security_group_id=nsg.id,
            direction="INGRESS",
            protocol="17",  # UDP
            source="0.0.0.0/0",
            source_type="CIDR_BLOCK",
            udp_options=oci.core.NetworkSecurityGroupSecurityRuleUdpOptionsArgs(
                destination_port_range=oci.core.NetworkSecurityGroupSecurityRuleUdpOptionsDestinationPortRangeArgs(
                    min=port_min, max=port_max
                ),
            ),
            opts=opts,
        )

    _tcp_rule("ssh", 22)
    seen_ports: set[int] = set()
    for svc in services:
        port = int(svc.get("port") or 0)
        if port and port not in seen_ports:
            seen_ports.add(port)
            _tcp_rule(f"port-{port}", port)
    if any(svc.get("service") == "relay" for svc in services):
        # relay's mediasoup RTC/pipe transports -- see
        # services/worker/apps/relay/.env.example and the matching Ansible
        # port-publish change in docker_service/tasks/main.yml.
        _udp_rule("relay-rtc", 10000, 10100)
        _udp_rule("relay-pipe", 40000, 40100)
    if any(svc.get("service") in ("relay", "bot", "cp-daemon", "validator-daemon") for svc in services):
        # Each relay/signaling/bot instance, plus cp-daemon/validator-daemon
        # (whose only surface is a metrics endpoint), gets a Caddy TLS
        # sidecar -- port 80 for the ACME HTTP-01 challenge, port 443 for
        # the actual traffic (wss:// for relay/signaling, plain HTTPS for
        # the others).
        _tcp_rule("http", 80)
        _tcp_rule("https", 443)

    shape = instance.get("size") or "VM.Standard.E2.1.Micro"
    if instance.get("image"):
        image_id = instance["image"]
    else:
        images = oci.core.get_images(
            compartment_id=compartment_id,
            operating_system="Canonical Ubuntu",
            operating_system_version="22.04",
            shape=shape,
            sort_by="TIMECREATED",
            sort_order="DESC",
            opts=invoke_opts,
        )
        image_id = images.images[0].id

    availability_domains = oci.identity.get_availability_domains(
        compartment_id=compartment_id, opts=invoke_opts
    )
    # Most OCI regions have 1-3 ADs; picking the first is a known
    # simplification -- doesn't spread workers across ADs within a region.
    availability_domain = availability_domains.availability_domains[0].name

    # Flex shapes (name ends in ".Flex", e.g. VM.Standard.E4.Flex) require an
    # explicit OCPU/memory shape_config -- fixed shapes (VM.Standard.E2.1.Micro)
    # reject it outright, so only pass it when the shape actually needs one.
    shape_config = (
        oci.core.InstanceShapeConfigArgs(
            ocpus=float(instance.get("ocpus") or 2),
            memory_in_gbs=float(instance.get("memory_gb") or 4),
        )
        if shape.endswith(".Flex")
        else None
    )

    server = oci.core.Instance(
        f"{name}-vm",
        availability_domain=availability_domain,
        compartment_id=compartment_id,
        shape=shape,
        shape_config=shape_config,
        display_name=f"xaisen-{name}",
        create_vnic_details=oci.core.InstanceCreateVnicDetailsArgs(
            subnet_id=subnet.id,
            nsg_ids=[nsg.id],
            assign_public_ip=True,
        ),
        metadata={"ssh_authorized_keys": public_key},
        source_details=oci.core.InstanceSourceDetailsArgs(
            source_type="image",
            source_id=image_id,
        ),
        state="RUNNING" if instance.get("desired_state") != "stopped" else "STOPPED",
        opts=opts,
    )
    # OCID string, as `oci compute instance ...` commands expect --
    # persisted via persist_vm_resolution() for image_bake.bake().
    instance["resource_id"] = server.id
    # Canonical Ubuntu cloud images on OCI use the "ubuntu" login user, not
    # root/opc.
    return {"address": server.public_ip, "user": "ubuntu"}
