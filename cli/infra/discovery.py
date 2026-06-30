from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from cli.config import SSH_CONFIG_DIR


@dataclass
class DeploymentInfo:
    routes_url: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    worker_ips: List[str] = field(default_factory=list)
    dist_ips: List[str] = field(default_factory=list)
    coordinator_ips: List[str] = field(default_factory=list)
    provider: str = "alibaba-cloud"


def _inventory_path(provider: str) -> Path:
    return SSH_CONFIG_DIR / f"{provider}-inventory.yml"


def _vars_path(provider: str) -> Path:
    return SSH_CONFIG_DIR / f"{provider}-vars.json"


def is_deployed(provider: str) -> bool:
    return _inventory_path(provider).exists()


def _parse_inventory_ips(inventory: dict, role: str) -> List[str]:
    children = inventory.get("all", {}).get("children", {})
    hosts = children.get(role, {}).get("hosts", {})
    ips: List[str] = []
    for _name, attrs in hosts.items():
        ip = attrs.get("public_ip") or attrs.get("ansible_host", "")
        if ip:
            ips.append(ip)
    return ips


def discover(provider: str) -> DeploymentInfo:
    inv_path = _inventory_path(provider)
    vars_path = _vars_path(provider)

    if not inv_path.exists():
        raise SystemExit(f"No inventory found at {inv_path}. Run deploy first.")
    if not vars_path.exists():
        raise SystemExit(f"No vars found at {vars_path}. Run deploy first.")

    import yaml
    inventory = yaml.safe_load(inv_path.read_text(encoding="utf-8"))
    vars_data = json.loads(vars_path.read_text(encoding="utf-8"))

    worker_ips = _parse_inventory_ips(inventory, "worker")
    dist_ips = _parse_inventory_ips(inventory, "dist")
    coordinator_ips = _parse_inventory_ips(inventory, "coordinator")

    if not dist_ips:
        raise SystemExit("No dist nodes found in inventory.")
    if not worker_ips:
        raise SystemExit("No worker nodes found in inventory.")

    routes_url = f"http://{dist_ips[0]}"
    livekit_url = vars_data.get("LIVEKIT_URL", f"ws://{worker_ips[0]}:7880")
    livekit_api_key = vars_data.get("LIVEKIT_API_KEY", "")
    livekit_api_secret = vars_data.get("LIVEKIT_API_SECRET", "")

    return DeploymentInfo(
        routes_url=routes_url,
        livekit_url=livekit_url,
        livekit_api_key=livekit_api_key,
        livekit_api_secret=livekit_api_secret,
        worker_ips=worker_ips,
        dist_ips=dist_ips,
        coordinator_ips=coordinator_ips,
        provider=provider,
    )


def wait_for_routes(info: DeploymentInfo, timeout: float = 60) -> None:
    url = f"{info.routes_url}/api/connection-details?roomName=health&participantName=probe"
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=5)
            return
        except urllib.error.HTTPError:
            return
        except Exception as e:
            last_error = str(e)
            time.sleep(3)
    raise SystemExit(f"Routes service not responding at {info.routes_url} after {timeout}s: {last_error}")
