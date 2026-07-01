from __future__ import annotations

import argparse
import mimetypes
import os
import subprocess
from pathlib import Path
from typing import Mapping

from cli.config import PROVIDER_ENV_FILES, REPO_ROOT
from cli.env import build_contract_env, build_env
from cli.infra.inventory import _update_env_file
from cli.oss.cert import _bind_domain_https, _letsencrypt_https

_OSS_ENDPOINT = "https://oss-{region}.aliyuncs.com"
_OSS_PROVIDERS = {"alibaba-cloud"}


def _require_oss2():
    try:
        import oss2
        return oss2
    except ImportError:
        raise SystemExit("oss2 not installed. Run: pip install oss2")


def _bucket_client(env: Mapping[str, str], bucket_name: str):
    oss2 = _require_oss2()
    region = env.get("ALICLOUD_REGION", "cn-hangzhou")
    endpoint = _OSS_ENDPOINT.format(region=region)
    auth = oss2.Auth(env["ALICLOUD_ACCESS_KEY"], env["ALICLOUD_SECRET_KEY"])
    return oss2.Bucket(auth, endpoint, bucket_name), region


def _cloud_env_path(provider: str) -> Path:
    return REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider]


def cmd_oss_init(args: argparse.Namespace) -> None:
    if args.provider not in _OSS_PROVIDERS:
        raise SystemExit(f"OSS not supported for provider '{args.provider}'. Supported: {', '.join(_OSS_PROVIDERS)}")

    oss2 = _require_oss2()
    env = build_env(args.provider)
    bucket_name = getattr(args, "oss_bucket", None) or env.get("ALICLOUD_OSS_BUCKET", "") or "xaisen-client"

    bucket, region = _bucket_client(env, bucket_name)

    try:
        bucket.create_bucket(oss2.models.BucketCreateConfig(oss2.BUCKET_ACL_PUBLIC_READ))
        print(f"Created OSS bucket: {bucket_name}")
    except oss2.exceptions.BucketAlreadyExists:
        print(f"OSS bucket already exists: {bucket_name}")

    bucket.put_bucket_website(oss2.models.BucketWebsite(
        index_file="index.html",
        error_file="index.html",
    ))
    print("Enabled static website hosting")

    rule = oss2.models.CorsRule(
        allowed_origins=["*"],
        allowed_methods=["GET", "HEAD"],
        allowed_headers=["*"],
        max_age_seconds=3600,
    )
    bucket.put_bucket_cors(oss2.models.BucketCors([rule]))
    print("Configured CORS rules")

    endpoint = _OSS_ENDPOINT.format(region=region)
    website_host = f"{bucket_name}.oss-{region}.aliyuncs.com"

    env_updates = {
        "ALICLOUD_OSS_BUCKET": bucket_name,
        "ALICLOUD_OSS_ENDPOINT": endpoint,
    }

    domain = getattr(args, "oss_domain", None)
    if domain:
        print(f"\nBinding custom domain: {domain}")
        bucket.put_bucket_cname(domain)
        print(f"  CNAME bound (HTTP)")

        print(f"  Requesting Let's Encrypt certificate for {domain} ...")
        print(f"  (the CNAME {domain} → {website_host} must already be active in DNS)")
        cert_pem, key_pem = _letsencrypt_https(bucket, domain)

        _bind_domain_https(bucket, oss2, domain, cert_pem, key_pem)
        print(f"  HTTPS enabled: https://{domain}")

        env_updates["ALICLOUD_OSS_DOMAIN"] = domain
    else:
        print(f"\nCNAME target: {website_host}")
        print(
            "\nNote: set COOP/COEP headers in OSS console → bucket → Basic Settings → HTTP Response Headers:\n"
            "  Cross-Origin-Opener-Policy: same-origin-allow-popups\n"
            "  Cross-Origin-Embedder-Policy: credentialless"
        )

    _update_env_file(_cloud_env_path(args.provider), env_updates)


def cmd_oss_deploy(args: argparse.Namespace) -> None:
    if args.provider not in _OSS_PROVIDERS:
        raise SystemExit(f"OSS not supported for provider '{args.provider}'.")

    env = build_env(args.provider)
    bucket_name = args.oss_bucket or env.get("ALICLOUD_OSS_BUCKET", "")
    if not bucket_name:
        raise SystemExit("--oss-bucket is required for OSS deploy.")

    contract_network = getattr(args, "contract_network", "devnet")
    contract_env = build_contract_env(contract_network)
    registry_object_id = contract_env.get("CONTRACT_REGISTRY_OBJECT_ID", "")
    package_id = contract_env.get("CONTRACT_PACKAGE_ID", "")
    if not registry_object_id:
        raise SystemExit("CONTRACT_REGISTRY_OBJECT_ID not set — run contract deploy first.")

    client_dir = REPO_ROOT / "src" / "client"
    build_environ = {
        **os.environ,
        "NEXT_PUBLIC_REGISTRY_OBJECT_ID": registry_object_id,
        "NEXT_PUBLIC_SUI_NETWORK": contract_network,
        "NEXT_PUBLIC_PACKAGE_ID": package_id,
    }
    print(f"Building static client (NEXT_PUBLIC_REGISTRY_OBJECT_ID={registry_object_id}, network={contract_network}) ...")
    subprocess.run(["pnpm", "build"], cwd=str(client_dir), env=build_environ, check=True)

    out_dir = client_dir / "out"
    if not out_dir.exists():
        raise SystemExit(f"Build output not found at {out_dir}. Ensure next.config.js has output: 'export'.")

    bucket, region = _bucket_client(env, bucket_name)
    print(f"Uploading to {bucket_name} ...")

    uploaded = 0
    for file_path in sorted(out_dir.rglob("*")):
        if not file_path.is_file():
            continue

        key = file_path.relative_to(out_dir).as_posix()
        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or "application/octet-stream"

        if "/_next/static/" in f"/{key}":
            cache_control = "public, max-age=31536000, immutable"
        elif key.endswith(".html"):
            cache_control = "no-cache, no-store, must-revalidate"
        else:
            cache_control = "public, max-age=3600"

        bucket.put_object_from_file(key, str(file_path), headers={
            "Content-Type": content_type,
            "Cache-Control": cache_control,
        })
        uploaded += 1
        if uploaded % 50 == 0:
            print(f"  {uploaded} files uploaded...")

    print(f"Uploaded {uploaded} files to {bucket_name}")

    domain = getattr(args, "oss_domain", None) or env.get("ALICLOUD_OSS_DOMAIN", "")
    if domain:
        print(f"Public URL: https://{domain}")
    else:
        print(f"Public URL: http://{bucket_name}.oss-{region}.aliyuncs.com")


def cmd_oss_purge(args: argparse.Namespace) -> None:
    if args.provider not in _OSS_PROVIDERS:
        return

    oss2 = _require_oss2()
    env = build_env(args.provider)
    bucket_name = getattr(args, "oss_bucket", None) or env.get("ALICLOUD_OSS_BUCKET", "")
    if not bucket_name:
        return

    bucket, _ = _bucket_client(env, bucket_name)

    try:
        deleted = 0
        for obj in oss2.ObjectIterator(bucket):
            bucket.delete_object(obj.key)
            deleted += 1
        print(f"Deleted {deleted} objects from OSS bucket {bucket_name}")
        bucket.delete_bucket()
        print(f"Deleted OSS bucket: {bucket_name}")
    except Exception as exc:
        print(f"OSS purge warning: {exc}")

    _update_env_file(_cloud_env_path(args.provider), {
        "ALICLOUD_OSS_BUCKET": "",
        "ALICLOUD_OSS_ENDPOINT": "",
        "ALICLOUD_OSS_DOMAIN": "",
    })
