from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Mapping

from cli.config import PROVIDER_CR_REGISTRY_KEY, PROVIDER_ENV_FILES, REPO_ROOT, TERRAFORM_REGISTRY_DIR
from cli.env import build_env
from cli.infra.inventory import _update_env_file
from cli.process import run_command
from cli.infra.terraform import purge_terraform_state


def cmd_setup_registry(args: argparse.Namespace) -> None:
    provider = args.provider
    if provider not in PROVIDER_CR_REGISTRY_KEY:
        raise SystemExit(f"registry init does not support provider '{provider}' yet")

    env = build_env(provider)
    tf_root = TERRAFORM_REGISTRY_DIR / provider
    if not tf_root.exists():
        raise SystemExit(f"No registry Terraform config found at {tf_root}")

    region = env.get("ALICLOUD_REGION", "cn-hangzhou")

    run_command(["terraform", "init", "-input=false"], cwd=tf_root, env=env)
    run_command(
        [
            "terraform", "apply", "-auto-approve", "-input=false",
            f"-var=namespace={args.namespace}",
            f"-var=region={region}",
        ],
        cwd=tf_root,
        env=env,
    )

    result = subprocess.run(
        ["terraform", "output", "-raw", "registry"],
        cwd=str(tf_root),
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
    )
    registry_url = result.stdout.strip()

    secrets_file = REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider]
    registry_key = PROVIDER_CR_REGISTRY_KEY[provider]
    _update_env_file(secrets_file, {registry_key: registry_url})

    print(f"\nRegistry ready: {registry_url}")
    print(f"  {registry_key} written to {secrets_file}")
    print(
        f"\nNext: add credentials to {secrets_file}:\n"
        f"  ALICLOUD_CR_USERNAME=<your-ram-username>\n"
        f"  ALICLOUD_CR_PASSWORD=<acr-fixed-password>\n"
        f"\nThen push images:\n"
        f"  python3 vidctl.py infra registry build --provider {provider}"
    )


def destroy_registry(provider: str, env: Mapping[str, str]) -> None:
    tf_root = TERRAFORM_REGISTRY_DIR / provider
    state_file = tf_root / "terraform.tfstate"
    if not state_file.exists():
        print(f"  no registry state found for {provider}, skipping")
        return
    run_command(["terraform", "init", "-input=false"], cwd=tf_root, env=env)
    run_command(["terraform", "destroy", "-auto-approve", "-input=false"], cwd=tf_root, env=env)
    purge_terraform_state(tf_root)


def cmd_registry_init(args: argparse.Namespace) -> None:
    provider = args.provider
    registry_key = PROVIDER_CR_REGISTRY_KEY.get(provider)
    if not registry_key:
        raise SystemExit(f"registry init does not support provider '{provider}' yet")

    env = build_env(provider)
    registry_url = env.get(registry_key, "").strip()
    if registry_url:
        print(f"Registry already configured for {provider}: {registry_url}")
        return

    cmd_setup_registry(args)


def cmd_registry_purge(args: argparse.Namespace) -> None:
    provider = args.provider
    if provider not in PROVIDER_CR_REGISTRY_KEY:
        raise SystemExit(f"registry purge does not support provider '{provider}' yet")

    env = build_env(provider)
    destroy_registry(provider, env)
    _update_env_file(
        REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider],
        {PROVIDER_CR_REGISTRY_KEY[provider]: ""},
    )
    print(f" registry purged for {provider}")


def cmd_registry_list(args: argparse.Namespace) -> None:
    provider = args.provider
    if provider not in PROVIDER_CR_REGISTRY_KEY:
        raise SystemExit(f"registry list does not support provider '{provider}' yet")

    env = build_env(provider)
    registry_key = PROVIDER_CR_REGISTRY_KEY[provider]
    saved_registry = env.get(registry_key, "").strip()
    tf_root = TERRAFORM_REGISTRY_DIR / provider
    state_file = tf_root / "terraform.tfstate"

    print(f"provider: {provider}")
    print(f"{registry_key}: {saved_registry or '<unset>'}")

    if not state_file.exists():
        print("terraform: <no registry state>")
        return

    run_command(["terraform", "init", "-input=false"], cwd=tf_root, env=env)
    result = subprocess.run(
        ["terraform", "output", "-raw", "registry"],
        cwd=str(tf_root),
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
    )
    print(f"terraform registry: {result.stdout.strip()}")
