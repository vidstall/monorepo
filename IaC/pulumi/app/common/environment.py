import os


def require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"{key} is required for this frontend object-storage provider")
    return value


def alibaba_scan_all_regions() -> bool:
    return os.getenv("ALIBABA_SCAN_ALL_REGIONS", "").lower() in ("1", "true", "yes")


def cloud_credentials() -> dict[str, object]:
    return {
        "aws": bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")),
        "gcp": bool(os.getenv("GOOGLE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        "azure": bool(os.getenv("ARM_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")),
        "digitalOcean": bool(os.getenv("DIGITALOCEAN_TOKEN")),
        "upcloud": bool(os.getenv("UPCLOUD_TOKEN")),
        "akamai": bool(os.getenv("LINODE_TOKEN")),
        "alibabaCloud": bool(
            os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
            and os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        ),
        "alibabaRegion": os.getenv("ALIBABA_CLOUD_REGION", ""),
        "tencentCloud": bool(
            os.getenv("TENCENTCLOUD_SECRET_ID") and os.getenv("TENCENTCLOUD_SECRET_KEY")
        ),
        "cloudflare": bool(
            os.getenv("CLOUDFLARE_API_TOKEN") and os.getenv("CLOUDFLARE_ACCOUNT_ID")
        ),
    }
