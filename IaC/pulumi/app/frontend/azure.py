import hashlib
from pathlib import Path

import pulumi

from ..common.regions import provider_region
from ..models import TopologyInstance
from .artifacts import upload_artifacts


def _storage_account_name(bucket_name: str) -> str:
    """Azure storage account names must be 3-24 chars, lowercase alphanumeric
    only (no hyphens) -- frontend_bucket_name()'s "xaisen-<env>-<provider>-
    <name>" format isn't valid as-is. Derive a compliant name: strip
    non-alphanumerics, lowercase, and if that's still too long, truncate and
    append a short hash of the original so distinct bucket_names (e.g. two
    scenarios differing only past character 20) don't collide."""
    cleaned = "".join(ch for ch in bucket_name.lower() if ch.isalnum())
    if len(cleaned) <= 24:
        return cleaned or "xaisenfrontend"
    digest = hashlib.sha1(bucket_name.encode()).hexdigest()[:6]
    return f"{cleaned[:18]}{digest}"


def create_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
    from pulumi_azure_native import storage

    from ..compute.azure import shared_network

    public = desired_state == "running"
    location = provider_region("azure", instance)
    resource_group, _subnet = shared_network(location)
    account_name = _storage_account_name(bucket_name)

    account = storage.StorageAccount(
        f"{instance['name']}-frontend",
        account_name=account_name,
        resource_group_name=resource_group.name,
        location=location,
        kind=storage.Kind.STORAGE_V2,
        sku=storage.SkuArgs(name=storage.SkuName.STANDARD_LRS),
    )

    if public:
        storage.StorageAccountStaticWebsite(
            f"{instance['name']}-frontend-static-site",
            account_name=account.name,
            resource_group_name=resource_group.name,
            index_document="index.html",
            error404_document="index.html",
        )
        # StorageAccountStaticWebsite exposes no URL output of its own (only
        # container_name/index_document echoes) -- the real endpoint lives on
        # the StorageAccount resource itself, populated once the static-website
        # feature is enabled.
        pulumi.export(
            f"{instance['name']}_azure_static_url",
            account.primary_endpoints.apply(lambda endpoints: endpoints.web),
        )

    def upload(key: str, path: Path, mime: str) -> None:
        storage.Blob(
            f"{instance['name']}-{key.replace('/', '-')}",
            account_name=account.name,
            resource_group_name=resource_group.name,
            # Azure's static-website feature serves exclusively from this
            # fixed, special container name -- not configurable.
            container_name="$web",
            blob_name=key,
            source=pulumi.FileAsset(str(path)),
            content_type=mime,
        )

    return upload_artifacts(instance, upload) if public else 0
