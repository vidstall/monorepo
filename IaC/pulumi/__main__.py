from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any, Callable, TypedDict

import pulumi

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY_PATH = ROOT / "runtime" / "topology.toml"
FRONTEND_ARTIFACT_ROOT = ROOT / "services" / "frontend" / "out"
OBJECT_STORAGE_SERVICE = "frontend"


class HostConfig(TypedDict, total=False):
    name: str
    address: str
    user: str
    port: int
    groups: list[str]


class TopologyInstance(TypedDict, total=False):
    name: str
    service: str
    provider: str
    env: str
    backend: str
    address: str
    user: str
    port: int
    bucket: str
    desired_state: str
    last_status: str
    contract_env: str
    artifact_dir: str
    region: str
    ssh_key_dir: str
    size: str


def load_topology() -> dict[str, Any]:
    if not TOPOLOGY_PATH.exists():
        return {"active_env": "devnet", "contract_env": "runtime/contract/devnet.env", "instances": []}
    return tomllib.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))


def host_entry(host: HostConfig | TopologyInstance) -> dict[str, Any]:
    entry: dict[str, Any] = {"ansible_host": host["address"]}
    if host.get("user"):
        entry["ansible_user"] = host["user"]
    if host.get("port"):
        entry["ansible_port"] = host["port"]
    return entry


def topology_host_entry(instance: TopologyInstance) -> dict[str, Any]:
    entry = host_entry(instance)
    entry.update(
        {
            "xaisen_service": instance.get("service", ""),
            "xaisen_provider": instance.get("provider", ""),
            "xaisen_env": instance.get("env", topology.get("active_env", "devnet")),
            "xaisen_contract_env": instance.get("contract_env", topology.get("contract_env", "")),
            "xaisen_desired_state": instance.get("desired_state", ""),
        }
    )
    return entry


def should_include_ansible_host(instance: TopologyInstance) -> bool:
    if instance.get("backend") == "object_storage" or instance.get("service") == OBJECT_STORAGE_SERVICE:
        return False
    if instance.get("desired_state") in {"deleted", "stopped"}:
        return False
    if instance.get("backend") == "vm":
        # Real address comes from vm_resources (a freshly-created compute resource output),
        # not from this static topology.toml-sourced dict.
        return True
    return bool(instance.get("address"))


def frontend_instances() -> list[TopologyInstance]:
    return [
        instance
        for instance in topology_instances
        if instance.get("service") == OBJECT_STORAGE_SERVICE or instance.get("backend") == "object_storage"
    ]


def artifact_files(instance: TopologyInstance) -> list[Path]:
    root = ROOT / instance.get("artifact_dir", str(FRONTEND_ARTIFACT_ROOT))
    if not root.is_absolute():
        root = ROOT / root
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def object_key(instance: TopologyInstance, path: Path) -> str:
    root = ROOT / instance.get("artifact_dir", str(FRONTEND_ARTIFACT_ROOT))
    if not root.is_absolute():
        root = ROOT / root
    return path.relative_to(root).as_posix()


def content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def upload_artifacts(
    instance: TopologyInstance,
    upload: Callable[[str, Path, str], None],
) -> int:
    count = 0
    for path in artifact_files(instance):
        upload(object_key(instance, path), path, content_type(path))
        count += 1
    return count


def frontend_bucket_name(instance: TopologyInstance) -> str:
    return str(instance.get("bucket") or f"xaisen-{instance.get('env', 'devnet')}-{instance.get('provider', 'unknown')}-{instance.get('name', 'frontend')}")


def frontend_site_url(provider: str, bucket_name: str, instance: TopologyInstance | None = None) -> str:
    region = provider_region(provider, instance)
    if provider == "aws":
        return f"http://{bucket_name}.s3-website-{region}.amazonaws.com"
    if provider == "digitalocean":
        return f"https://{bucket_name}.{region}.digitaloceanspaces.com"
    if provider == "gcp":
        return f"https://storage.googleapis.com/{bucket_name}/index.html"
    if provider == "alibaba":
        return f"https://{bucket_name}.oss-website-{region}.aliyuncs.com"
    if provider == "cloudflare":
        return os.getenv("CLOUDFLARE_R2_PUBLIC_URL", "")
    if provider == "tencent":
        return os.getenv("TENCENT_COS_PUBLIC_URL", "")
    if provider == "azure":
        return os.getenv("AZURE_STATIC_WEBSITE_URL", "")
    return ""


def provider_region(provider: str, instance: TopologyInstance | None = None) -> str:
    defaults = {
        "aws": "us-east-1",
        "gcp": "US",
        "azure": "eastus",
        "alibaba": "cn-hangzhou",
        "digitalocean": "nyc3",
        "tencent": "ap-guangzhou",
        "cloudflare": "apac",
    }
    env_keys = {
        "aws": "AWS_REGION",
        "gcp": "GCP_REGION",
        "azure": "AZURE_LOCATION",
        "alibaba": "ALIBABA_CLOUD_REGION",
        "digitalocean": "DIGITALOCEAN_REGION",
        "tencent": "TENCENTCLOUD_REGION",
        "cloudflare": "CLOUDFLARE_R2_LOCATION",
    }
    if instance and instance.get("region"):
        return str(instance["region"])
    return os.getenv(env_keys[provider], defaults[provider])


def require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"{key} is required for this frontend object-storage provider")
    return value


def alibaba_scan_all_regions() -> bool:
    return os.getenv("ALIBABA_SCAN_ALL_REGIONS", "").lower() in ("1", "true", "yes")


def create_frontend_site(instance: TopologyInstance) -> dict[str, Any]:
    provider = str(instance.get("provider", ""))
    desired_state = str(instance.get("desired_state", ""))
    bucket_name = frontend_bucket_name(instance)
    if desired_state == "deleted":
        return {"provider": provider, "bucket": bucket_name, "desired_state": desired_state, "objects": 0, "site_url": ""}
    if provider == "aws":
        objects = create_aws_site(instance, bucket_name, desired_state)
    elif provider == "digitalocean":
        objects = create_digitalocean_site(instance, bucket_name, desired_state)
    elif provider == "gcp":
        objects = create_gcp_site(instance, bucket_name, desired_state)
    elif provider == "alibaba":
        objects = create_alibaba_site(instance, bucket_name, desired_state)
    elif provider == "cloudflare":
        objects = create_cloudflare_r2_site(instance, bucket_name, desired_state)
    else:
        objects = create_metadata_only_site(instance, bucket_name, desired_state)
    return {
        "provider": provider,
        "bucket": bucket_name,
        "desired_state": desired_state,
        "objects": objects,
        "site_url": frontend_site_url(provider, bucket_name, instance),
    }


def create_aws_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    import pulumi_aws as aws

    public = desired_state == "running"
    bucket = aws.s3.Bucket(
        f"{instance['name']}-frontend",
        bucket=bucket_name,
        acl="public-read" if public else "private",
        force_destroy=True,
        website={"index_document": "index.html", "error_document": "404.html"},
    )

    def upload(key: str, path: Path, mime: str) -> None:
        aws.s3.BucketObject(
            f"{instance['name']}-{key.replace('/', '-')}",
            bucket=bucket.id,
            key=key,
            source=pulumi.FileAsset(str(path)),
            content_type=mime,
            acl="public-read" if public else "private",
        )

    return upload_artifacts(instance, upload)


def create_digitalocean_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    import pulumi_digitalocean as digitalocean

    public = desired_state == "running"
    region = provider_region("digitalocean")
    bucket = digitalocean.SpacesBucket(
        f"{instance['name']}-frontend",
        name=bucket_name,
        region=region,
        acl="public-read" if public else "private",
    )

    def upload(key: str, path: Path, mime: str) -> None:
        digitalocean.SpacesBucketObject(
            f"{instance['name']}-{key.replace('/', '-')}",
            bucket=bucket.name,
            region=region,
            key=key,
            source=pulumi.FileAsset(str(path)),
            content_type=mime,
            acl="public-read" if public else "private",
        )

    return upload_artifacts(instance, upload)


def create_gcp_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    import pulumi_gcp as gcp

    public = desired_state == "running"
    bucket = gcp.storage.Bucket(
        f"{instance['name']}-frontend",
        name=bucket_name,
        location=provider_region("gcp"),
        force_destroy=True,
        uniform_bucket_level_access=True,
        website={"main_page_suffix": "index.html", "not_found_page": "404.html"},
    )
    if public:
        gcp.storage.BucketIAMBinding(
            f"{instance['name']}-frontend-public",
            bucket=bucket.name,
            role="roles/storage.objectViewer",
            members=["allUsers"],
        )

    def upload(key: str, path: Path, mime: str) -> None:
        gcp.storage.BucketObject(
            f"{instance['name']}-{key.replace('/', '-')}",
            bucket=bucket.name,
            name=key,
            source=pulumi.FileAsset(str(path)),
            content_type=mime,
        )

    return upload_artifacts(instance, upload)


def create_alibaba_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    import pulumi_alicloud as alicloud

    public = desired_state == "running"
    provider = alicloud.Provider(
        f"{instance['name']}-oss-provider",
        access_key=require_env("ALIBABA_CLOUD_ACCESS_KEY_ID"),
        secret_key=require_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
        region=provider_region("alibaba", instance),
    )
    bucket = alicloud.oss.Bucket(
        f"{instance['name']}-frontend",
        bucket=bucket_name,
        tags={"xaisen:region": provider_region("alibaba", instance)},
        website={"index_document": "index.html", "error_document": "404.html"},
        opts=pulumi.ResourceOptions(
            provider=provider,
            delete_before_replace=True,
            replace_on_changes=["tags"],
        ),
    )
    bucket_acl = alicloud.oss.BucketAcl(
        f"{instance['name']}-frontend-acl",
        bucket=bucket.bucket,
        acl="public-read" if public else "private",
        opts=pulumi.ResourceOptions(provider=provider),
    )

    def upload(key: str, path: Path, mime: str) -> None:
        alicloud.oss.BucketObject(
            f"{instance['name']}-{key.replace('/', '-')}",
            bucket=bucket.bucket,
            key=key,
            source=str(path),
            content_type=mime,
            acl="public-read" if public else "private",
            opts=pulumi.ResourceOptions(provider=provider, depends_on=[bucket_acl]),
        )

    return upload_artifacts(instance, upload)


def create_cloudflare_r2_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    import pulumi_aws as aws
    import pulumi_cloudflare as cloudflare

    account_id = require_env("CLOUDFLARE_ACCOUNT_ID")
    bucket = cloudflare.R2Bucket(
        f"{instance['name']}-frontend",
        account_id=account_id,
        name=bucket_name,
        location=provider_region("cloudflare"),
        storage_class=os.getenv("CLOUDFLARE_R2_STORAGE_CLASS", "Standard"),
    )
    endpoint = os.getenv("CLOUDFLARE_R2_ENDPOINT", f"https://{account_id}.r2.cloudflarestorage.com")
    provider = aws.Provider(
        f"{instance['name']}-r2-s3",
        access_key=require_env("CLOUDFLARE_R2_ACCESS_KEY_ID"),
        secret_key=require_env("CLOUDFLARE_R2_SECRET_ACCESS_KEY"),
        region="auto",
        s3_use_path_style=True,
        skip_credentials_validation=True,
        skip_metadata_api_check=True,
        skip_region_validation=True,
        skip_requesting_account_id=True,
        endpoints=[{"s3": endpoint}],
    )

    def upload(key: str, path: Path, mime: str) -> None:
        aws.s3.BucketObjectv2(
            f"{instance['name']}-{key.replace('/', '-')}",
            bucket=bucket.name,
            key=key,
            source=pulumi.FileAsset(str(path)),
            content_type=mime,
            opts=pulumi.ResourceOptions(provider=provider),
        )

    return upload_artifacts(instance, upload)


def create_metadata_only_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    pulumi.warn(
        f"{instance.get('provider')} frontend object-storage resources are recorded in topology, "
        "but this provider adapter is metadata-only until provider-specific bucket/object resources are added."
    )
    return len(artifact_files(instance)) if desired_state in {"running", "stopped"} else 0


# ── VM provisioning (routes/media/coordinator/vclient) ──────────────────────


def vm_instances() -> list[TopologyInstance]:
    return [
        instance
        for instance in topology_instances
        if instance.get("backend") == "vm" and instance.get("service") != OBJECT_STORAGE_SERVICE
    ]


def read_ssh_public_key(instance: TopologyInstance) -> str:
    key_dir = instance.get("ssh_key_dir")
    if not key_dir:
        raise ValueError(
            f"Instance {instance.get('name')} has no ssh_key_dir; the CLI should generate one before pulumi up."
        )
    path = ROOT / key_dir / "id_ed25519.pub"
    return path.read_text(encoding="utf-8").strip()


def provider_zone(instance: TopologyInstance | None = None) -> str:
    if instance and instance.get("zone"):
        return str(instance["zone"])
    return os.getenv("GCP_ZONE", "us-central1-a")


def create_vm_instance(instance: TopologyInstance) -> dict[str, Any]:
    provider = str(instance.get("provider", ""))
    desired_state = str(instance.get("desired_state", ""))
    if desired_state == "deleted":
        return {"provider": provider, "desired_state": desired_state, "address": None, "user": None}

    public_key = read_ssh_public_key(instance)
    if provider == "digitalocean":
        result = create_digitalocean_vm(instance, public_key)
    elif provider == "aws":
        result = create_aws_vm(instance, public_key)
    elif provider == "gcp":
        result = create_gcp_vm(instance, public_key)
    elif provider == "azure":
        result = create_azure_vm(instance, public_key)
    elif provider == "alibaba":
        result = create_alibaba_vm(instance, public_key)
    elif provider == "tencent":
        raise ValueError(
            "tencent VM provisioning is not yet supported (no working Pulumi Python SDK path was "
            "found for Tencent compute/VPC resources) - choose another --provider for now."
        )
    else:
        raise ValueError(f"No VM provisioning adapter for provider: {provider}")
    result["provider"] = provider
    result["desired_state"] = desired_state
    return result


def create_digitalocean_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_digitalocean as digitalocean

    name = instance["name"]
    port = int(instance.get("port") or 0)

    key = digitalocean.SshKey(f"{name}-vm-key", name=f"xaisen-{name}", public_key=public_key)

    inbound_rules = [
        digitalocean.FirewallInboundRuleArgs(
            protocol="tcp", port_range="22", source_addresses=["0.0.0.0/0", "::/0"]
        ),
    ]
    if port:
        inbound_rules.append(
            digitalocean.FirewallInboundRuleArgs(
                protocol="tcp", port_range=str(port), source_addresses=["0.0.0.0/0", "::/0"]
            )
        )
    outbound_rules = [
        digitalocean.FirewallOutboundRuleArgs(protocol="tcp", destination_addresses=["0.0.0.0/0", "::/0"], port_range="1-65535"),
        digitalocean.FirewallOutboundRuleArgs(protocol="udp", destination_addresses=["0.0.0.0/0", "::/0"], port_range="1-65535"),
        digitalocean.FirewallOutboundRuleArgs(protocol="icmp", destination_addresses=["0.0.0.0/0", "::/0"]),
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
        droplet_ids=[droplet.id.apply(lambda i: int(i))],
        inbound_rules=inbound_rules,
        outbound_rules=outbound_rules,
    )

    return {"address": droplet.ipv4_address, "user": "root"}


def create_aws_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_aws as aws

    name = instance["name"]
    port = int(instance.get("port") or 0)
    region = provider_region("aws", instance)

    ami = aws.ec2.get_ami(
        most_recent=True,
        owners=["099720109477"],
        filters=[
            aws.ec2.GetAmiFilterArgs(name="name", values=["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]),
        ],
        region=region,
    )

    key = aws.ec2.KeyPair(f"{name}-vm-key", key_name=f"xaisen-{name}", public_key=public_key, region=region)

    ingress = [
        aws.ec2.SecurityGroupIngressArgs(protocol="tcp", from_port=22, to_port=22, cidr_blocks=["0.0.0.0/0"]),
    ]
    if port:
        ingress.append(
            aws.ec2.SecurityGroupIngressArgs(protocol="tcp", from_port=port, to_port=port, cidr_blocks=["0.0.0.0/0"])
        )
    sg = aws.ec2.SecurityGroup(
        f"{name}-vm-sg",
        region=region,
        ingress=ingress,
        egress=[aws.ec2.SecurityGroupEgressArgs(protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"])],
    )

    vm = aws.ec2.Instance(
        f"{name}-vm",
        ami=ami.id,
        instance_type=instance.get("size") or "t3.micro",
        key_name=key.key_name,
        vpc_security_group_ids=[sg.id],
        associate_public_ip_address=True,
        region=region,
        tags={"Name": f"xaisen-{name}"},
    )

    return {"address": vm.public_ip, "user": "ubuntu"}


def create_gcp_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_gcp as gcp

    name = instance["name"]
    port = int(instance.get("port") or 0)
    zone = provider_zone(instance)
    tag = f"xaisen-{name}"

    allows = [gcp.compute.FirewallAllowArgs(protocol="tcp", ports=["22"])]
    if port:
        allows.append(gcp.compute.FirewallAllowArgs(protocol="tcp", ports=[str(port)]))
    gcp.compute.Firewall(
        f"{name}-vm-fw",
        network="default",
        allows=allows,
        source_ranges=["0.0.0.0/0"],
        target_tags=[tag],
    )

    vm = gcp.compute.Instance(
        f"{name}-vm",
        name=tag,
        machine_type=instance.get("size") or "e2-micro",
        zone=zone,
        tags=[tag],
        boot_disk=gcp.compute.InstanceBootDiskArgs(
            initialize_params=gcp.compute.InstanceBootDiskInitializeParamsArgs(
                image="ubuntu-os-cloud/ubuntu-2204-lts",
            ),
        ),
        network_interfaces=[
            gcp.compute.InstanceNetworkInterfaceArgs(
                network="default",
                access_configs=[gcp.compute.InstanceNetworkInterfaceAccessConfigArgs()],
            ),
        ],
        metadata={"ssh-keys": f"ubuntu:{public_key}"},
    )

    address = vm.network_interfaces[0].access_configs[0].nat_ip
    return {"address": address, "user": "ubuntu"}


_azure_network: dict[str, Any] = {}


def azure_shared_network(location: str):
    if _azure_network:
        return _azure_network["resource_group"], _azure_network["subnet"]

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
    _azure_network["resource_group"] = resource_group
    _azure_network["subnet"] = subnet
    return resource_group, subnet


def create_azure_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    from pulumi_azure_native import compute, network

    name = instance["name"]
    port = int(instance.get("port") or 0)
    location = provider_region("azure", instance)
    resource_group, subnet = azure_shared_network(location)

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
        hardware_profile=compute.HardwareProfileArgs(vm_size=instance.get("size") or "Standard_B1s"),
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
            network_interfaces=[compute.NetworkInterfaceReferenceArgs(id=nic.id, primary=True)],
        ),
    )

    return {"address": public_ip.ip_address, "user": "azureuser"}


def find_alibaba_spot_type(name: str, provider: Any, region: str) -> tuple[str, str, Any, Any]:
    """Search for a 1 vCPU / 1 GiB spot-capable Alibaba instance type.

    Tries `region` (via the already-constructed `provider`) first. If nothing
    matches there and ALIBABA_SCAN_ALL_REGIONS is set, probes every other account
    region with ad-hoc providers, stopping at the first region with any match.
    Note: sorting by price (sorted_by="Price") would require BSS OpenAPI billing
    permissions this account's RAM user doesn't have, so this just takes the
    first spec match instead.
    """
    import pulumi_alicloud as alicloud

    result = alicloud.ecs.get_instance_types(
        cpu_core_count=1,
        memory_size=1,
        spot_strategy="SpotAsPriceGo",
        network_type="Vpc",
        opts=pulumi.InvokeOptions(provider=provider),
    )
    if result.instance_types:
        matched = result.instance_types[0]
        return region, str(matched.id), matched, provider

    if not alibaba_scan_all_regions():
        raise ValueError(f"No 1 vCPU / 1 GiB spot-capable Alibaba instance type found in region {region}.")

    access_key = require_env("ALIBABA_CLOUD_ACCESS_KEY_ID")
    secret_key = require_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    regions = alicloud.get_regions(opts=pulumi.InvokeOptions(provider=provider))
    for idx, candidate_region in enumerate(r for r in regions.ids if r != region):
        candidate_provider = alicloud.Provider(
            f"{name}-vm-provider-{idx}",
            access_key=access_key,
            secret_key=secret_key,
            region=candidate_region,
        )
        result = alicloud.ecs.get_instance_types(
            cpu_core_count=1,
            memory_size=1,
            spot_strategy="SpotAsPriceGo",
            network_type="Vpc",
            opts=pulumi.InvokeOptions(provider=candidate_provider),
        )
        if result.instance_types:
            matched = result.instance_types[0]
            return candidate_region, str(matched.id), matched, candidate_provider

    raise ValueError("No 1 vCPU / 1 GiB spot-capable Alibaba instance type found in any Alibaba region.")


def create_alibaba_vm(instance: TopologyInstance, public_key: str) -> dict[str, Any]:
    import pulumi_alicloud as alicloud

    name = instance["name"]
    port = int(instance.get("port") or 0)
    spot_strategy = "SpotAsPriceGo"

    region = provider_region("alibaba", instance)
    provider = alicloud.Provider(
        f"{name}-vm-provider",
        access_key=require_env("ALIBABA_CLOUD_ACCESS_KEY_ID"),
        secret_key=require_env("ALIBABA_CLOUD_ACCESS_KEY_SECRET"),
        region=region,
    )

    pinned_size = str(instance.get("size") or "")
    if pinned_size:
        spot_capable_types = alicloud.ecs.get_instance_types(
            instance_type=pinned_size,
            spot_strategy=spot_strategy,
            network_type="Vpc",
            opts=pulumi.InvokeOptions(provider=provider),
        )
        if not spot_capable_types.instance_types:
            raise ValueError(
                f"Pinned instance type {pinned_size} has no spot capacity in {region}; "
                "rerun with --find-instance-type."
            )
        size = pinned_size
        matched = spot_capable_types.instance_types[0]
    else:
        region, size, matched, provider = find_alibaba_spot_type(name, provider, region)

    instance["region"] = region
    instance["size"] = size

    opts = pulumi.ResourceOptions(provider=provider)
    zone = str(instance.get("zone") or matched.availability_zones[0])

    vpc = alicloud.vpc.Network(f"{name}-vm-vpc", cidr_block="172.16.0.0/16", vpc_name=f"xaisen-{name}", opts=opts)
    vswitch = alicloud.vpc.Switch(
        f"{name}-vm-vswitch",
        vpc_id=vpc.id,
        cidr_block="172.16.0.0/24",
        zone_id=zone,
        opts=opts,
    )

    key = alicloud.ecs.KeyPair(f"{name}-vm-key", key_pair_name=f"xaisen-{name}", public_key=public_key, opts=opts)

    sg = alicloud.ecs.SecurityGroup(f"{name}-vm-sg", vpc_id=vpc.id, opts=opts)
    alicloud.ecs.SecurityGroupRule(
        f"{name}-vm-sg-ssh",
        type="ingress",
        ip_protocol="tcp",
        port_range="22/22",
        cidr_ip="0.0.0.0/0",
        security_group_id=sg.id,
        opts=opts,
    )
    service = instance.get("service")
    if service == "routes":
        security_rules = [("tcp", "80/80", "http"), ("tcp", "443/443", "https")]
    elif service == "media":
        security_rules = [
            ("tcp", "7880/7880", "signal"),
            ("tcp", "7881/7881", "ice"),
            ("udp", "50000/60000", "rtc"),
        ]
    elif port:
        security_rules = [("tcp", f"{port}/{port}", "port")]
    else:
        security_rules = []

    for ip_protocol, port_range, rule_name in security_rules:
        alicloud.ecs.SecurityGroupRule(
            f"{name}-vm-sg-{rule_name}",
            type="ingress",
            ip_protocol=ip_protocol,
            port_range=port_range,
            cidr_ip="0.0.0.0/0",
            security_group_id=sg.id,
            opts=opts,
        )

    images = alicloud.ecs.get_images(
        name_regex="^ubuntu_22_04_x64.*",
        most_recent=True,
        owners="system",
        opts=pulumi.InvokeOptions(provider=provider),
    )

    vm = alicloud.ecs.Instance(
        f"{name}-vm",
        instance_name=f"xaisen-{name}",
        instance_type=size,
        instance_charge_type="PostPaid",
        spot_strategy=spot_strategy,
        availability_zone=zone,
        image_id=images.images[0].id,
        vswitch_id=vswitch.id,
        security_groups=[sg.id],
        key_name=key.key_pair_name,
        internet_max_bandwidth_out=5,
        system_disk_size=20,
        status="Stopped" if instance.get("desired_state") == "stopped" else "Running",
        stopped_mode="KeepCharging",
        opts=opts,
    )

    return {"address": vm.public_ip, "user": "root"}


config = pulumi.Config("xaisen")
hosts = config.get_object("hosts") or []
topology = load_topology()
topology_instances = topology.get("instances", [])

vm_resources: dict[str, dict[str, Any]] = {
    str(instance.get("name")): create_vm_instance(instance) for instance in vm_instances()
}

inventory_hosts: dict[str, Any] = {}
for host in hosts:
    host_name = host.get("name")
    if not host_name:
        continue
    inventory_hosts[host_name] = host_entry(host)

for instance in topology_instances:
    if not should_include_ansible_host(instance):
        continue
    host_name = instance.get("name")
    if not host_name:
        continue
    if instance.get("backend") == "vm":
        resource = vm_resources.get(host_name)
        if resource is None or resource.get("address") is None:
            continue
        ssh_key_path = str(ROOT / instance.get("ssh_key_dir", "") / "id_ed25519")
        inventory_hosts[host_name] = pulumi.Output.all(resource["address"]).apply(
            lambda vals, inst=instance, user=resource["user"], key_path=ssh_key_path: {
                "ansible_host": vals[0],
                "ansible_user": user,
                "ansible_ssh_private_key_file": key_path,
                "xaisen_service": inst.get("service", ""),
                "xaisen_provider": inst.get("provider", ""),
                "xaisen_env": inst.get("env", topology.get("active_env", "devnet")),
                "xaisen_contract_env": inst.get("contract_env", topology.get("contract_env", "")),
                "xaisen_desired_state": inst.get("desired_state", ""),
                "xaisen_port": inst.get("port", 0),
            }
        )
    else:
        inventory_hosts[host_name] = topology_host_entry(instance)

inventory = {
    "all": {
        "hosts": {},
        "children": {
            "xaisen": {
                "hosts": inventory_hosts,
            }
        },
    }
}

frontend_sites = {
    str(instance.get("name", "frontend")): create_frontend_site(instance)
    for instance in frontend_instances()
}

pulumi.export(
    "cloudCredentials",
    {
        "aws": bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")),
        "gcp": bool(os.getenv("GOOGLE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        "azure": bool(os.getenv("ARM_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")),
        "digitalOcean": bool(os.getenv("DIGITALOCEAN_TOKEN")),
        "alibabaCloud": bool(os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID") and os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")),
        "alibabaRegion": os.getenv("ALIBABA_CLOUD_REGION", ""),
        "tencentCloud": bool(os.getenv("TENCENTCLOUD_SECRET_ID") and os.getenv("TENCENTCLOUD_SECRET_KEY")),
        "cloudflare": bool(os.getenv("CLOUDFLARE_API_TOKEN") and os.getenv("CLOUDFLARE_ACCOUNT_ID")),
    },
)
pulumi.export("topology", topology)
pulumi.export("frontendSites", frontend_sites)
pulumi.export("ansibleInventory", inventory)
