from typing import Any

from ..common.regions import provider_region
from ..models import TopologyInstance

_NETWORK: dict[str, Any] = {}


def shared_network(location: str):
    if _NETWORK:
        return _NETWORK["resource_group"], _NETWORK["subnet"]
    from pulumi_azure_native import network, resources

    resource_group = resources.ResourceGroup("xaisen-rg", location=location)
    vnet = network.VirtualNetwork(
        "xaisen-vnet",
        resource_group_name=resource_group.name,
        location=location,
        address_space=network.AddressSpaceArgs(address_prefixes=["10.10.0.0/16"]),
    )
    subnet = network.Subnet(
        "xaisen-subnet",
        resource_group_name=resource_group.name,
        virtual_network_name=vnet.name,
        address_prefix="10.10.1.0/24",
    )
    _NETWORK.update(resource_group=resource_group, subnet=subnet)
    return resource_group, subnet


def create_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    from pulumi_azure_native import compute, network

    name = instance["name"]
    port = int(instance.get("port") or 0)
    location = provider_region("azure", instance)
    resource_group, subnet = shared_network(location)
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
    if port:
        security_rules.append(
            network.SecurityRuleArgs(
                name="allow-service-port",
                priority=110,
                direction="Inbound",
                access="Allow",
                protocol="Tcp",
                source_port_range="*",
                destination_port_range=str(port),
                source_address_prefix="*",
                destination_address_prefix="*",
            )
        )
    if instance.get("service") == "media":
        security_rules.append(
            network.SecurityRuleArgs(
                name="allow-media-broker",
                priority=120,
                direction="Inbound",
                access="Allow",
                protocol="Tcp",
                source_port_range="*",
                destination_port_range="7890",
                source_address_prefix="*",
                destination_address_prefix="*",
            )
        )
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
        public_ip_allocation_method=network.IPAllocationMethod.DYNAMIC,
        sku=network.PublicIPAddressSkuArgs(name=network.PublicIPAddressSkuName.BASIC),
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
    compute.VirtualMachine(
        f"{name}-vm",
        resource_group_name=resource_group.name,
        location=location,
        hardware_profile=compute.HardwareProfileArgs(
            vm_size=instance.get("size") or "Standard_B1s"
        ),
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
            image_reference=compute.ImageReferenceArgs(
                publisher="Canonical",
                offer="0001-com-ubuntu-server-jammy",
                sku="22_04-lts-gen2",
                version="latest",
            ),
        ),
        network_profile=compute.NetworkProfileArgs(
            network_interfaces=[
                compute.NetworkInterfaceReferenceArgs(id=nic.id, primary=True)
            ],
        ),
    )
    return {"address": public_ip.ip_address, "user": "azureuser"}
