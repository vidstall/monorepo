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
        # not_found_page -> index.html, not a real 404 page: this is a
        # client-side-routed SPA (React Router). A hard reload/direct link to
        # a deep route like /rooms/<id> is a real HTTP request the bucket has
        # no object for -- GCS static website hosting serves not_found_page
        # for ANY unmatched path, so it must be the app shell (letting the
        # router resolve the path client-side), not a dead-end 404 page.
        website={"main_page_suffix": "index.html", "not_found_page": "index.html"},
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
