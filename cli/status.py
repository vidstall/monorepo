from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Optional

from cli.config import (
    CONTRACT_ENV_DIR,
    CONTRACT_NETWORK_CHOICES,
    PROVIDER_CHOICES,
    SSH_CONFIG_DIR,
    TERRAFORM_ENV_DIR,
)
from cli.env import RUNTIME_ENV_FILE, load_env_file

_W = 16  # label column width

IMAGE_KEYS = {
    "worker": "XAISEN_WORKER_IMAGE",
    "routes": "XAISEN_ROUTES_IMAGE",
    "client": "XAISEN_CLIENT_IMAGE",
}


def _rule(char: str = "─", width: int = 45) -> str:
    return char * width


def _tick(ok: bool) -> str:
    return "✓" if ok else "─"


def _trunc(value: str, n: int = 20) -> str:
    if len(value) <= n:
        return value
    return value[:8] + "…" + value[-6:]


def _is_provider_deployed(provider: str) -> bool:
    tfstate = TERRAFORM_ENV_DIR / provider / "terraform.tfstate"
    return tfstate.exists() and tfstate.stat().st_size > 0


def _has_inventory(provider: str) -> bool:
    return (SSH_CONFIG_DIR / f"{provider}-inventory.yml").exists()


def _load_contract_state(network: str) -> Dict[str, str]:
    return load_env_file(CONTRACT_ENV_DIR / f"{network}.env")


def _load_runtime_images() -> Dict[str, Optional[str]]:
    env = load_env_file(RUNTIME_ENV_FILE)
    return {svc: env.get(key) or None for svc, key in IMAGE_KEYS.items()}


def _print_infra_section(providers: tuple[str, ...] = PROVIDER_CHOICES) -> None:
    print("INFRASTRUCTURE")
    for provider in providers:
        deployed = _is_provider_deployed(provider)
        inv = _has_inventory(provider)
        label = f"{provider:<{_W}}"
        suffix = "  [inventory cached]" if inv else ""
        if deployed:
            print(f"  {label} ✓  deployed{suffix}")
        else:
            print(f"  {label} ─  not deployed")
    print()


def _print_contract_section() -> None:
    print("CONTRACT")
    for network in CONTRACT_NETWORK_CHOICES:
        state = _load_contract_state(network)
        pkg = state.get("CONTRACT_PACKAGE_ID", "").strip()
        reg = state.get("CONTRACT_REGISTRY_OBJECT_ID", "").strip()
        deployed = bool(pkg)
        initialized = bool(reg)

        label = f"{network:<{_W}}"
        if deployed and initialized:
            print(f"  {label} ✓  deployed   pkg={_trunc(pkg)}  registry={_trunc(reg)}")
        elif deployed:
            print(f"  {label} ✓  published  pkg={_trunc(pkg)}  (registry not initialized)")
        else:
            print(f"  {label} ─  not deployed")
    print()


def _print_images_section() -> None:
    print("RUNTIME IMAGES")
    images = _load_runtime_images()
    any_set = any(v for v in images.values())
    if not any_set:
        print(f"  {'(none)':<{_W}} ─  no images built yet")
    else:
        for svc, url in images.items():
            label = f"{svc:<{_W}}"
            if url:
                print(f"  {label} ✓  {url}")
            else:
                print(f"  {label} ─  not set")
    print()


def cmd_infra_status(args: argparse.Namespace) -> None:
    raw = getattr(args, "provider", None)
    if raw:
        providers = tuple(p.strip() for p in raw.split(",") if p.strip())
        invalid = [p for p in providers if p not in PROVIDER_CHOICES]
        if invalid:
            raise SystemExit(f"Unknown provider(s): {', '.join(invalid)}. Choose from: {', '.join(PROVIDER_CHOICES)}")
    else:
        providers = PROVIDER_CHOICES
    print()
    _print_infra_section(providers)
    print(_rule())
    print('Run "python3 vidctl.py infra <subcommand> --help" for available actions.')
    print()


def cmd_status(args: argparse.Namespace) -> None:
    print()
    print("vidctl — xaisen testbed status")
    print(_rule())
    print()
    _print_infra_section()
    _print_contract_section()
    _print_images_section()
    print(_rule())
    print('Run "python3 vidctl.py --help" to see all commands.')
    print()
