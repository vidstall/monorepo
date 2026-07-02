from __future__ import annotations

import os
from typing import Any

import pulumi

from ..common.regions import provider_region
from ..config import OBJECT_STORAGE_SERVICE
from ..models import TopologyInstance
from .artifacts import artifact_files


def frontend_instances(instances: list[TopologyInstance]) -> list[TopologyInstance]:
    return [
        instance
        for instance in instances
        if instance.get("service") == OBJECT_STORAGE_SERVICE
        or instance.get("backend") == "object_storage"
    ]


def frontend_bucket_name(instance: TopologyInstance) -> str:
    return str(
        instance.get("bucket")
        or f"xaisen-{instance.get('env', 'devnet')}-{instance.get('provider', 'unknown')}-{instance.get('name', 'frontend')}"
    )


def frontend_site_url(
    provider: str,
    bucket_name: str,
    instance: TopologyInstance | None = None,
) -> str:
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


def create_metadata_only_site(
    instance: TopologyInstance,
    bucket_name: str,
    desired_state: str,
) -> int:
    pulumi.warn(
        f"{instance.get('provider')} frontend object-storage resources are recorded in topology, "
        "but this provider adapter is metadata-only until provider-specific bucket/object resources are added."
    )
    return len(artifact_files(instance)) if desired_state in {"running", "stopped"} else 0


def create_frontend_site(instance: TopologyInstance) -> dict[str, Any]:
    provider = str(instance.get("provider", ""))
    desired_state = str(instance.get("desired_state", ""))
    bucket_name = frontend_bucket_name(instance)
    if desired_state == "deleted":
        objects = 0
    elif provider == "aws":
        from .aws import create_site
        objects = create_site(instance, bucket_name, desired_state)
    elif provider == "digitalocean":
        from .digitalocean import create_site
        objects = create_site(instance, bucket_name, desired_state)
    elif provider == "gcp":
        from .gcp import create_site
        objects = create_site(instance, bucket_name, desired_state)
    elif provider == "alibaba":
        from .alibaba import create_site
        objects = create_site(instance, bucket_name, desired_state)
    elif provider == "cloudflare":
        from .cloudflare import create_site
        objects = create_site(instance, bucket_name, desired_state)
    else:
        objects = create_metadata_only_site(instance, bucket_name, desired_state)
    return {
        "provider": provider,
        "bucket": bucket_name,
        "desired_state": desired_state,
        "objects": objects,
        "site_url": "" if desired_state == "deleted" else frontend_site_url(provider, bucket_name, instance),
    }
