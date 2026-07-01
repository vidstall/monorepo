from __future__ import annotations

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Mapping

from cli.config import IMAGE_SERVICES, PROVIDER_CR_REGISTRY_KEY, REPO_ROOT
from cli.env import build_env
from cli.infra.inventory import IMAGE_TAR_KEYS, _update_env_file


IMAGES_DIR = REPO_ROOT / "artifacts" / "images"

BASE_IMAGE_SERVICES = {
    "coordinator": ("redis:7.4-alpine", "xaisen-redis", "XAISEN_COORDINATOR_IMAGE"),
    "proxy": ("caddy:2-alpine", "xaisen-caddy", "XAISEN_PROXY_IMAGE"),
}


def mirror_base_images(registry: str, tag: str, platform: str) -> Dict[str, str]:
    mirrored: Dict[str, str] = {}
    for service, (source_image, repo_name, env_key) in BASE_IMAGE_SERVICES.items():
        target_image = f"{registry}/{repo_name}:{tag}"
        print(f"\n=== Mirroring {service} base image ===")
        print(f" source: {source_image}")
        print(f" target: {target_image}")
        print(f" platform: {platform}")
        subprocess.run(
            ["docker", "buildx", "imagetools", "create", "--platform", platform, "--tag", target_image, source_image],
            check=True,
        )
        mirrored[env_key] = target_image
    return mirrored


def cmd_build_images(args: argparse.Namespace) -> None:
    provider = getattr(args, "provider", None)
    explicit_registry = getattr(args, "registry", None)
    push = args.push
    tag = args.tag
    platform = args.platform

    registry: str | None = None
    env: Mapping[str, str] = {}

    if push:
        if provider and explicit_registry:
            raise SystemExit("--registry and --provider are mutually exclusive")
        if not provider and not explicit_registry:
            raise SystemExit("--push requires --registry or --provider")

        if provider:
            env = build_env(provider)
            registry_key = PROVIDER_CR_REGISTRY_KEY.get(provider)
            if not registry_key:
                raise SystemExit(f"No registry configured for provider '{provider}'")
            registry_url = env.get(registry_key, "").strip()
            if not registry_url:
                raise SystemExit(
                    f"{registry_key} is not set for {provider}. "
                    f"Run: python3 vidctl.py infra registry init --provider {provider}"
                )
            registry = registry_url.rstrip("/")
        else:
            registry = explicit_registry.rstrip("/")

        registry_host = registry.split("/")[0]
    username = env.get("ALICLOUD_CR_USERNAME", "").strip() if provider == "alibaba-cloud" else ""
    password = env.get("ALICLOUD_CR_PASSWORD", "").strip() if provider == "alibaba-cloud" else ""
    if username and password:
        print(f"\n=== Logging in to {registry_host} ===")
        subprocess.run(
            ["docker", "login", registry_host, "-u", username, "--password", password],
            check=True,
        )

    image_map: Dict[str, str] = {}
    tar_map: Dict[str, str] = {}

    def _build_one(service: str, src_dir: str) -> tuple[str, str]:
        image_name = f"{registry}/xaisen-{service}:{tag}" if registry else f"xaisen-{service}:{tag}"
        build_context = REPO_ROOT / src_dir
        if not build_context.exists():
            raise SystemExit(f"Build context not found: {build_context}")
        print(f"\n=== Building {service} ===")
        print(f"  image: {image_name}")
        print(f"  platform: {platform}")
        print(f"  context: {build_context}")
        if push:
            subprocess.run(
                ["docker", "buildx", "build", "--platform", platform, "-t", image_name, "--push", "."],
                cwd=str(build_context),
                check=True,
            )
        else:
            subprocess.run(
                ["docker", "buildx", "build", "--platform", platform, "-t", image_name, "--load", "."],
                cwd=str(build_context),
                check=True,
            )
            IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            tar_path = IMAGES_DIR / f"xaisen-{service}.tar"
            print(f"  saving: {tar_path}")
            subprocess.run(["docker", "save", "-o", str(tar_path), image_name], check=True)
            tar_map[service] = str(tar_path)
        return service, image_name

    with ThreadPoolExecutor(max_workers=len(IMAGE_SERVICES)) as pool:
        futures = {pool.submit(_build_one, svc, src): svc for svc, src in IMAGE_SERVICES.items()}
        for future in as_completed(futures):
            service, image_name = future.result()
            image_map[service] = image_name

    runtime_env_path = REPO_ROOT / "secrets" / "runtime.env"
    env_updates: Dict[str, str] = {
        "XAISEN_MEDIA_IMAGE": image_map["media"],
        "XAISEN_ROUTES_IMAGE": image_map["routes"],
        "XAISEN_CLIENT_IMAGE": image_map["client"],
        "XAISEN_VCLIENT_IMAGE": image_map["vclient"],
    }
    if tar_map:
        env_updates["XAISEN_MEDIA_IMAGE_TAR"] = tar_map.get("media", "")
        env_updates["XAISEN_ROUTES_IMAGE_TAR"] = tar_map.get("routes", "")
        env_updates["XAISEN_CLIENT_IMAGE_TAR"] = tar_map.get("client", "")
        env_updates["XAISEN_VCLIENT_IMAGE_TAR"] = tar_map.get("vclient", "")
    _update_env_file(runtime_env_path, env_updates)

    existing = {}
    for line in runtime_env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
    if "LIVEKIT_API_KEY" not in existing or not existing["LIVEKIT_API_KEY"]:
        import secrets as _secrets
        _update_env_file(runtime_env_path, {
            "LIVEKIT_API_KEY": f"devkey_{_secrets.token_hex(8)}",
            "LIVEKIT_API_SECRET": _secrets.token_hex(32),
        })
        print("\n  generated LIVEKIT_API_KEY and LIVEKIT_API_SECRET")

    print(f"\n  wrote {runtime_env_path}")
    if push:
        print("\nDone. Images pushed to registry.")
    else:
        print(f"\nDone. Images saved to {IMAGES_DIR}. Transfer via Ansible on next deploy.")


def cmd_registry_build(args: argparse.Namespace) -> None:
    env = build_env(args.provider)
    registry_key = PROVIDER_CR_REGISTRY_KEY.get(args.provider)
    if not registry_key:
        raise SystemExit(f"registry build does not support provider '{args.provider}' yet")
    registry = env.get(registry_key, "").strip().rstrip("/")
    if not registry:
        raise SystemExit(
            f"{registry_key} is not set for {args.provider}. "
            f"Run: python3 vidctl.py infra registry init --provider {args.provider}"
        )

    build_args = argparse.Namespace(
        provider=args.provider,
        registry=None,
        tag=args.tag,
        push=True,
        platform=args.platform,
    )
    cmd_build_images(build_args)
    env_updates = {key: "" for key in IMAGE_TAR_KEYS}
    env_updates.update(mirror_base_images(registry, args.tag, args.platform))
    _update_env_file(REPO_ROOT / "secrets" / "runtime.env", env_updates)
