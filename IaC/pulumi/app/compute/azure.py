from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance

_NETWORKS: dict[str, dict[str, Any]] = {}

# "eastus2" already has LIVE resources under these exact bare (unsuffixed)
# Pulumi logical names -- azure-node-1 was deployed before this module
# supported multiple regions. Renaming its ResourceGroup's logical name would
# make Pulumi delete-then-recreate it, cascading a real, currently-running
# VM's destruction. Every OTHER region gets a location-suffixed name (see
# below) since there's no legacy resource to stay compatible with.
_LEGACY_LOCATION = "eastus2"


def shared_network(location: str):
    # Keyed by location -- NOT a single global singleton. Azure's per-region
    # LowPriorityCores quota (verified live: a 4-host scenario hit
    # "OperationNotAllowed ... Current Limit: 3" on its 2nd host in the same
    # region) means hosts get spread across regions, and a VM's NIC must be
    # in the same region as its VNet -- reusing one region's network for a
    # different-region VM would hard-fail (or worse, silently misplace it).
    cached = _NETWORKS.get(location)
    if cached:
        return cached["resource_group"], cached["subnet"]
    from pulumi_azure_native import network, resources

    if location == _LEGACY_LOCATION:
        rg_name, vnet_name, subnet_name = "xaisen-rg", "xaisen-vnet", "xaisen-subnet"
    else:
        rg_name = f"xaisen-rg-{location}"
        vnet_name = f"xaisen-vnet-{location}"
        subnet_name = f"xaisen-subnet-{location}"
    resource_group = resources.ResourceGroup(rg_name, resource_group_name=rg_name, location=location)
    vnet = network.VirtualNetwork(
        vnet_name,
        resource_group_name=resource_group.name,
        location=location,
        address_space=network.AddressSpaceArgs(address_prefixes=["10.10.0.0/16"]),
    )
    subnet = network.Subnet(
        subnet_name,
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        address_prefix="10.10.1.0/24",
    )
    _NETWORKS[location] = {"resource_group": resource_group, "subnet": subnet}
    return resource_group, subnet


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    from pulumi_azure_native import compute, network

    name = instance["host"]
    # `services` is set for colocated hosts (program.py's group-by-name merge, same
    # convention as digitalocean.py/akamai.py/upcloud.py) -- fall back to the singular
    # service/port pair for a single-service instance.
    services = instance.get("services") or (
        [{"service": instance.get("service", ""), "port": int(instance.get("port") or 0)}]
        if instance.get("service")
        else []
    )
    location = provider_region("azure", instance)
    instance["region"] = location
    resource_group, subnet = shared_network(location)
    # NSG rules need a unique name + strictly increasing priority (100-4096) each --
    # unlike DO's flat inbound-rule list, so priorities are assigned in increments of
    # 10 starting after the SSH rule to leave room.
    security_rules = [
        network.SecurityRuleArgs(
            name="allow-ssh",
            priority=100,
            direction="Inbound",
            access="Allow",
            protocol="Tcp",
            source_port_range="*",
            destination_port_range="22",
            source_address_prefix="*",
            destination_address_prefix="*",
        ),
    ]
    next_priority = 110
    seen_ports: set[int] = set()
    for svc in services:
        port = int(svc.get("port") or 0)
        if port and port not in seen_ports:
            seen_ports.add(port)
            security_rules.append(
                network.SecurityRuleArgs(
                    name=f"allow-port-{port}",
                    priority=next_priority,
                    direction="Inbound",
                    access="Allow",
                    protocol="Tcp",
                    source_port_range="*",
                    destination_port_range=str(port),
                    source_address_prefix="*",
                    destination_address_prefix="*",
                )
            )
            next_priority += 10
    # relay's mediasoup RTC/pipe transports -- see digitalocean.py's create_vm() for
    # the shared rationale (per-worker_index 100-port-wide UDP window). NSG supports
    # a port RANGE natively via destination_port_range, no per-port expansion needed.
    for svc in services:
        if svc.get("service") != "relay":
            continue
        offset = (int(svc.get("index") or 1) - 1) * 100
        for base in (10000, 40000):
            security_rules.append(
                network.SecurityRuleArgs(
                    name=f"allow-relay-udp-{base + offset}",
                    priority=next_priority,
                    direction="Inbound",
                    access="Allow",
                    protocol="Udp",
                    source_port_range="*",
                    destination_port_range=f"{base + offset}-{base + offset + 99}",
                    source_address_prefix="*",
                    destination_address_prefix="*",
                )
            )
            next_priority += 10
    if any(svc.get("service") in ("relay", "signaling") for svc in services):
        # Each relay/signaling instance gets a Caddy TLS sidecar -- port 80 for the
        # ACME HTTP-01 challenge, port 443 for the actual wss:// traffic.
        for tls_port in (80, 443):
            security_rules.append(
                network.SecurityRuleArgs(
                    name=f"allow-tls-{tls_port}",
                    priority=next_priority,
                    direction="Inbound",
                    access="Allow",
                    protocol="Tcp",
                    source_port_range="*",
                    destination_port_range=str(tls_port),
                    source_address_prefix="*",
                    destination_address_prefix="*",
                )
            )
            next_priority += 10
    nsg = network.NetworkSecurityGroup(
        f"{name}-vm-nsg",
        resource_group_name=resource_group.name,
        location=location,
        security_rules=security_rules,
    )
    public_ip = network.PublicIPAddress(
        f"{name}-vm-ip",
        resource_group_name=resource_group.name,
        location=location,
        # Basic SKU public IPs were retired by Azure (Sept 2025) -- quota is
        # now 0 on every subscription. Standard SKU requires Static (not
        # Dynamic) allocation.
        public_ip_allocation_method=network.IPAllocationMethod.STATIC,
        sku=network.PublicIPAddressSkuArgs(name=network.PublicIPAddressSkuName.STANDARD),
    )
    nic = network.NetworkInterface(
        f"{name}-vm-nic",
        resource_group_name=resource_group.name,
        location=location,
        network_security_group=network.NetworkSecurityGroupArgs(id=nsg.id),
        ip_configurations=[
            network.NetworkInterfaceIPConfigurationArgs(
                name="ipconfig1",
                subnet=network.SubnetArgs(id=subnet.id),
                public_ip_address=network.PublicIPAddressArgs(id=public_ip.id),
                private_ip_allocation_method=network.IPAllocationMethod.DYNAMIC,
            ),
        ],
    )
    # Deterministic name so `az vm ...` commands (image_bake.bake()) can
    # address this VM without needing to query Pulumi state for the
    # provider-autogenerated name -- resource group is the shared
    # "xaisen-rg" every azure VM lands in (see shared_network() above).
    instance["resource_id"] = f"{name}-vm"
    compute.VirtualMachine(
        f"{name}-vm",
        vm_name=f"{name}-vm",
        resource_group_name=resource_group.name,
        location=location,
        hardware_profile=compute.HardwareProfileArgs(
            vm_size=instance.get("size") or "Standard_D2als_v7"
        ),
        priority=compute.VirtualMachinePriorityTypes.SPOT,
        eviction_policy=compute.VirtualMachineEvictionPolicyTypes.DEALLOCATE,
        # -1 = pay up to on-demand price, i.e. never evicted purely for price
        # -- still gets the spot discount, only capacity-based eviction risk.
        billing_profile=compute.BillingProfileArgs(max_price=-1),
        os_profile=compute.OSProfileArgs(
            computer_name=name,
            admin_username="azureuser",
            linux_configuration=compute.LinuxConfigurationArgs(
                disable_password_authentication=True,
                ssh=compute.SshConfigurationArgs(
                    public_keys=[
                        compute.SshPublicKeyArgs(
                            path="/home/azureuser/.ssh/authorized_keys",
                            key_data=public_key,
                        ),
                    ],
                ),
            ),
        ),
        storage_profile=compute.StorageProfileArgs(
            image_reference=(
                compute.ImageReferenceArgs(id=instance["image"])
                if instance.get("image")
                else compute.ImageReferenceArgs(
                    publisher="Canonical",
                    offer="0001-com-ubuntu-server-jammy",
                    sku="22_04-lts-gen2",
                    version="latest",
                )
            ),
            # Explicit, not left to Azure's auto-selection -- confirmed live:
            # azure-node-4 (westeurope) failed VM creation outright with
            # "Standard_D2als_v7 cannot boot with OS image or disk ... disk
            # controller types" even though the marketplace image supports
            # both SCSI and NVMe and the SKU supports NVMe (confirmed via
            # `az vm list-skus`/`az vm image show`) -- auto-selection is
            # apparently not reliable across every region. NVMe is the only
            # type every region checked (eastus2/westus2/centralus/
            # westeurope) supports for this SKU, and the marketplace image
            # supports it everywhere too, so pinning it removes the
            # ambiguity without narrowing what actually works.
            disk_controller_type=compute.DiskControllerTypes.NV_ME,
        ),
        network_profile=compute.NetworkProfileArgs(
            network_interfaces=[
                compute.NetworkInterfaceReferenceArgs(id=nic.id, primary=True)
            ],
        ),
    )
    return {"address": public_ip.ip_address, "user": "azureuser"}
