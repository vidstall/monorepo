from pathlib import Path

import pulumi

from ..models import TopologyInstance
from .artifacts import upload_artifacts


def create_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
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
