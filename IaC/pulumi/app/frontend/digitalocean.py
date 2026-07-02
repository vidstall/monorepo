from pathlib import Path

import pulumi

from ..common.regions import provider_region
from ..models import TopologyInstance
from .artifacts import upload_artifacts


def create_site(instance: TopologyInstance, bucket_name: str, desired_state: str) -> int:
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
