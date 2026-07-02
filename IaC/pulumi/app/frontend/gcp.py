from pathlib import Path

import pulumi

from ..common.regions import provider_region
from ..models import TopologyInstance
from .artifacts import upload_artifacts


def create_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
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
