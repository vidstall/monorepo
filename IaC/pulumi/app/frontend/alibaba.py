from pathlib import Path

import pulumi

from ..common.environment import require_env
from ..common.regions import provider_region
from ..models import TopologyInstance
from .artifacts import upload_artifacts


def create_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
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
    public_access_block = alicloud.oss.BucketPublicAccessBlock(
        f"{instance['name']}-frontend-public-access-block",
        bucket=bucket.bucket,
        block_public_access=not public,
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[bucket]),
    )
    bucket_acl = alicloud.oss.BucketAcl(
        f"{instance['name']}-frontend-acl",
        bucket=bucket.bucket,
        acl="public-read" if public else "private",
        opts=pulumi.ResourceOptions(provider=provider, depends_on=[public_access_block]),
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
