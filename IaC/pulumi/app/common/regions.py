from __future__ import annotations

import os

from ..models import TopologyInstance

_DEFAULTS = {
    "aws": "us-east-1",
    "gcp": "US",
    "azure": "eastus",
    "alibaba": "cn-hangzhou",
    "digitalocean": "nyc3",
    "tencent": "ap-guangzhou",
    "cloudflare": "apac",
}
_ENV_KEYS = {
    "aws": "AWS_REGION",
    "gcp": "GCP_REGION",
    "azure": "AZURE_LOCATION",
    "alibaba": "ALIBABA_CLOUD_REGION",
    "digitalocean": "DIGITALOCEAN_REGION",
    "tencent": "TENCENTCLOUD_REGION",
    "cloudflare": "CLOUDFLARE_R2_LOCATION",
}


def provider_region(provider: str, instance: TopologyInstance | None = None) -> str:
    if instance and instance.get("region"):
        return str(instance["region"])
    return os.getenv(_ENV_KEYS[provider], _DEFAULTS[provider])


def provider_zone(instance: TopologyInstance | None = None) -> str:
    if instance and instance.get("zone"):
        return str(instance["zone"])
    return os.getenv("GCP_ZONE", "us-central1-a")
