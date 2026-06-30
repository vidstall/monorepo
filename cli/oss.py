from __future__ import annotations

import argparse
import mimetypes
import os
import subprocess
import time
from pathlib import Path
from typing import Mapping

from cli.config import PROVIDER_ENV_FILES, REPO_ROOT
from cli.env import build_contract_env, build_env
from cli.infra import _update_env_file

_OSS_ENDPOINT = "https://oss-{region}.aliyuncs.com"
_OSS_PROVIDERS = {"alibaba-cloud"}


def _require_oss2():
    try:
        import oss2
        return oss2
    except ImportError:
        raise SystemExit("oss2 not installed. Run: pip install oss2")


def _require_acme_deps():
    try:
        import acme  # noqa: F401
        import josepy  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: F401
    except ImportError:
        raise SystemExit(
            "HTTPS cert dependencies not installed.\n"
            "Run: pip install acme josepy cryptography"
        )


def _bucket_client(env: Mapping[str, str], bucket_name: str):
    oss2 = _require_oss2()
    region = env.get("ALICLOUD_REGION", "cn-hangzhou")
    endpoint = _OSS_ENDPOINT.format(region=region)
    auth = oss2.Auth(env["ALICLOUD_ACCESS_KEY"], env["ALICLOUD_SECRET_KEY"])
    return oss2.Bucket(auth, endpoint, bucket_name), region


def _cloud_env_path(provider: str) -> Path:
    return REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider]


def _letsencrypt_https(bucket, domain: str) -> tuple[str, str]:
    """
    Obtain a Let's Encrypt cert for `domain` via HTTP-01 challenge.
    The challenge file is uploaded to the OSS bucket (which serves it via the CNAME).
    Returns (fullchain_pem, private_key_pem).
    """
    _require_acme_deps()

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from acme import client as acme_client_lib, challenges, messages, crypto_util
    import josepy as jose

    print(f"  generating account key ...")
    account_key_rsa = rsa.generate_private_key(65537, 2048, default_backend())
    account_key_pem = account_key_rsa.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    jwk = jose.JWKRSA(key=account_key_rsa)

    print(f"  connecting to Let's Encrypt ...")
    net = acme_client_lib.ClientNetwork(jwk, user_agent="vidctl/1.0")
    directory = acme_client_lib.ClientV2.get_directory(
        "https://acme-v02.api.letsencrypt.org/directory", net
    )
    acme = acme_client_lib.ClientV2(directory, net)
    acme.new_account(
        messages.NewRegistration.from_data(terms_of_service_agreed=True)
    )

    print(f"  generating domain key ...")
    domain_key_rsa = rsa.generate_private_key(65537, 2048, default_backend())
    domain_key_pem = domain_key_rsa.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )

    csr_pem = crypto_util.make_csr(domain_key_pem, [domain])
    orderr = acme.new_order(csr_pem)

    http_chall = None
    for authz in orderr.authorizations:
        for ch in authz.body.challenges:
            if isinstance(ch.chall, challenges.HTTP01):
                http_chall = ch
                break
        if http_chall:
            break

    if not http_chall:
        raise SystemExit("No HTTP-01 challenge available from Let's Encrypt for this domain.")

    chall_key = http_chall.chall.path.lstrip("/")  # .well-known/acme-challenge/TOKEN
    chall_response = http_chall.response(jwk)
    bucket.put_object(
        chall_key,
        chall_response.key_authorization.encode(),
        headers={"Content-Type": "text/plain"},
    )
    print(f"  uploaded challenge: /{chall_key}")

    acme.answer_challenge(http_chall, chall_response)
    print(f"  waiting for Let's Encrypt to validate {domain} ...")
    finalized = acme.poll_and_finalize(orderr)

    try:
        bucket.delete_object(chall_key)
    except Exception:
        pass

    print(f"  certificate issued")
    return finalized.fullchain_pem, domain_key_pem.decode()


def _bind_domain_https(bucket, oss2, domain: str, cert_pem: str, key_pem: str) -> None:
    cert_config = oss2.models.CertificateConfig(
        certificate=cert_pem,
        private_key=key_pem,
        force=True,
    )
    request = oss2.models.PutBucketCnameRequest(domain, cert_config)
    bucket.put_bucket_cname(request)


def cmd_oss_init(args: argparse.Namespace) -> None:
    if args.provider not in _OSS_PROVIDERS:
        raise SystemExit(f"OSS not supported for provider '{args.provider}'. Supported: {', '.join(_OSS_PROVIDERS)}")

    oss2 = _require_oss2()
    env = build_env(args.provider)
    bucket_name = args.oss_bucket

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
