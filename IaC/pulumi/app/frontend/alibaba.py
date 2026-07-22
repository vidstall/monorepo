import base64
import hashlib
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
        # error_document -> index.html, not a real 404 page: this is a
        # client-side-routed SPA (React Router). A hard reload/direct link to
        # a deep route like /rooms/<id> is a real HTTP request the bucket has
        # no object for -- OSS static website hosting serves error_document
        # for ANY unmatched path, so it must be the app shell (letting the
        # router resolve the path client-side), not a dead-end 404 page.
        website={"index_document": "index.html", "error_document": "index.html"},
        opts=pulumi.ResourceOptions(
            provider=provider,
            delete_before_replace=True,
            replace_on_changes=["tags"],
            # oss.Bucket's own (deprecated) `acl` field defaults to "private" whenever
            # left unset, and the alicloud provider docs mandate ignore_changes here
            # when a standalone oss.BucketAcl manages the real ACL below — without it,
            # every subsequent `pulumi up` silently reconciles the bucket ACL back to
            # "private", breaking anonymous website/root access while individual
            # BucketObject reads (which carry their own ACL) keep working.
            ignore_changes=["acl"],
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
        # `source` is a plain path string for this provider (unlike the
        # pulumi.FileAsset-based S3/GCS/Spaces adapters, whose asset hash is
        # what drives diffing) - Pulumi won't notice a same-named file's
        # content changed across builds unless we also give it a property
        # that actually changes, so pass an explicit content hash.
        content_md5 = base64.b64encode(hashlib.md5(path.read_bytes()).digest()).decode()
        alicloud.oss.BucketObject(
            f"{instance['name']}-{key.replace('/', '-')}",
            bucket=bucket.bucket,
            key=key,
            source=str(path),
            content_md5=content_md5,
            content_type=mime,
            acl="public-read" if public else "private",
            opts=pulumi.ResourceOptions(provider=provider, depends_on=[bucket_acl]),
        )

    return upload_artifacts(instance, upload)
