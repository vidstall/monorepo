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
        # error_document -> index.html, not a real 404 page: this is a
        # client-side-routed SPA (React Router). A hard reload/direct link to
        # a deep route like /rooms/<id> is a real HTTP request the bucket has
        # no object for -- S3 static website hosting serves error_document
        # for ANY unmatched path, so it must be the app shell (letting the
        # router resolve the path client-side), not a dead-end 404 page.
        website={"index_document": "index.html", "error_document": "index.html"},
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
