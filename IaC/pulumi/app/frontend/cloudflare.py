import os
from pathlib import Path

import pulumi

from ..common.environment import require_env
from ..common.regions import provider_region
from ..models import TopologyInstance
from .artifacts import upload_artifacts


def create_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
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
    endpoint = os.getenv(
        "CLOUDFLARE_R2_ENDPOINT",
        f"https://{account_id}.r2.cloudflarestorage.com",
    )
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
