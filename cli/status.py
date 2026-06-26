from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional

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


def _rule(char: str = "─", width: int = 50) -> str:
    return char * width


def _trunc(value: str, n: int = 20) -> str:
    if len(value) <= n:
        return value
    return value[:8] + "…" + value[-6:]


def _age(path: Path) -> str:
    delta = datetime.datetime.now() - datetime.datetime.fromtimestamp(path.stat().st_mtime)
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


# ── Infra helpers ─────────────────────────────────────────────────────────────

def _tfstate_path(provider: str) -> Path:
    return TERRAFORM_ENV_DIR / provider / "terraform.tfstate"


def _is_provider_deployed(provider: str) -> bool:
    p = _tfstate_path(provider)
    return p.exists() and p.stat().st_size > 0


def _inventory_path(provider: str) -> Path:
    return SSH_CONFIG_DIR / f"{provider}-inventory.yml"


def _parse_inventory_nodes(provider: str) -> Dict[str, List[str]]:
    """Return {role: [ip, ...]} from the cached Ansible inventory."""
    inv_path = _inventory_path(provider)
    if not inv_path.exists():
        return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(inv_path.read_text(encoding="utf-8"))
        children = data.get("all", {}).get("children", {})
        result: Dict[str, List[str]] = {}
        for role, group in children.items():
            hosts = group.get("hosts", {}) if isinstance(group, dict) else {}
            ips = [str(v.get("public_ip") or v.get("ansible_host") or "?")
                   for v in hosts.values() if isinstance(v, dict)]
            if ips:
                result[role] = ips
        return result
    except Exception:
        return {}


def _tfstate_node_counts(provider: str) -> Optional[Dict[str, int]]:
    """Read node counts from terraform.tfstate output block."""
    path = _tfstate_path(provider)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        outputs = state.get("outputs", {})
        inv_val = outputs.get("inventory", {}).get("value", {})
        if not isinstance(inv_val, dict):
            return None
        counts = {}
        for role in ("worker", "client", "coordinator"):
            nodes = inv_val.get(role, [])
            if isinstance(nodes, list) and nodes:
                counts[role] = len(nodes)
        return counts or None
    except Exception:
        return None


def _print_infra_section(providers: tuple[str, ...] = PROVIDER_CHOICES) -> None:
    print("INFRASTRUCTURE")
    for provider in providers:
        deployed = _is_provider_deployed(provider)
        label = f"{provider:<{_W}}"

        if not deployed:
            print(f"  {label} ─  not deployed")
            continue

        tfstate = _tfstate_path(provider)
        age = _age(tfstate)

        # Try inventory file for node IPs first, fall back to tfstate counts
        nodes = _parse_inventory_nodes(provider)
        counts = _tfstate_node_counts(provider)

        print(f"  {label} ✓  deployed  ({age})")

        if nodes:
            for role, ips in nodes.items():
                role_label = f"    {role:<{_W}}"
                print(f"{role_label} {', '.join(ips)}")
        elif counts:
            for role, n in counts.items():
                role_label = f"    {role:<{_W}}"
                print(f"{role_label} {n} node(s)")
        else:
            inv_path = _inventory_path(provider)
            if inv_path.exists():
                print(f"    {'inventory':<{_W}} {inv_path.name}")
            else:
                print(f"    {'inventory':<{_W}} not cached (run: vidctl infra inventory)")
    print()


# ── Contract helpers ──────────────────────────────────────────────────────────

def _load_contract_state(network: str) -> Dict[str, str]:
    return load_env_file(CONTRACT_ENV_DIR / f"{network}.env")


def _print_contract_section() -> None:
    print("CONTRACT")
    for network in CONTRACT_NETWORK_CHOICES:
        state = _load_contract_state(network)
        pkg     = state.get("CONTRACT_PACKAGE_ID", "").strip()
        reg     = state.get("CONTRACT_REGISTRY_OBJECT_ID", "").strip()
        cap     = state.get("CONTRACT_UPGRADE_CAP_ID", "").strip()
        deployer = state.get("CONTRACT_DEPLOYER_ADDRESS", "").strip()
        pub_tx  = state.get("CONTRACT_PUBLISH_TX_DIGEST", "").strip()
        upd_tx  = state.get("CONTRACT_UPDATE_TX_DIGEST", "").strip()

        label = f"{network:<{_W}}"
        if not pkg:
            print(f"  {label} ─  not deployed")
            continue

        status = "deployed + initialized" if reg else "published (registry not initialized)"
        print(f"  {label} ✓  {status}")
        print(f"    {'package':<{_W}} {_trunc(pkg)}")
        if reg:
            print(f"    {'registry':<{_W}} {_trunc(reg)}")
        if cap:
            print(f"    {'upgrade cap':<{_W}} {_trunc(cap)}")
        if deployer:
            print(f"    {'deployer':<{_W}} {_trunc(deployer)}")
        if pub_tx:
            print(f"    {'publish tx':<{_W}} {_trunc(pub_tx)}")
        if upd_tx:
            print(f"    {'last upgrade':<{_W}} {_trunc(upd_tx)}")
    print()


# ── Images helpers ────────────────────────────────────────────────────────────

def _load_runtime_images() -> Dict[str, Optional[str]]:
    env = load_env_file(RUNTIME_ENV_FILE)
    return {svc: env.get(key) or None for svc, key in IMAGE_KEYS.items()}


def _print_images_section() -> None:
    print("RUNTIME IMAGES")
    images = _load_runtime_images()
    any_set = any(v for v in images.values())
    if not any_set:
        print(f"  {'(none)':<{_W}} ─  run: vidctl infra build --provider <provider> --push")
    else:
        for svc, url in images.items():
            label = f"{svc:<{_W}}"
            if url:
                print(f"  {label} ✓  {url}")
            else:
                print(f"  {label} ─  not set")
    print()


# ── Commands ──────────────────────────────────────────────────────────────────

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
