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


config = pulumi.Config("xaisen")
hosts = config.get_object("hosts") or []
topology = load_topology()
topology_instances = topology.get("instances", [])

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
