from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypedDict

import pulumi

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY_PATH = ROOT / "runtime" / "topology.toml"


class HostConfig(TypedDict, total=False):
    name: str
    address: str
    user: str
    port: int
    groups: list[str]
    vars: dict[str, str | int | bool]


class TopologyInstance(TypedDict, total=False):
    name: str
    service: str
    provider: str
    env: str
    address: str
    user: str
    port: int
    desired_state: str
    last_status: str
    contract_env: str


def load_topology() -> dict[str, Any]:
    if not TOPOLOGY_PATH.exists():
        return {"active_env": "devnet", "contract_env": "runtime/contract/devnet.env", "instances": []}
    return tomllib.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))


config = pulumi.Config("xaisen")
hosts = config.get_object("hosts") or []
topology = load_topology()
topology_instances = topology.get("instances", [])


def host_entry(host: HostConfig | TopologyInstance) -> dict[str, Any]:
    entry: dict[str, Any] = {"ansible_host": host["address"]}
    if host.get("user"):
        entry["ansible_user"] = host["user"]
    if host.get("port"):
        entry["ansible_port"] = host["port"]
    entry.update(host.get("vars", {}))
    return entry


def topology_host_entry(instance: TopologyInstance) -> dict[str, Any]:
    entry = host_entry(instance)
    entry.update(
        {
            "xaisen_service": instance.get("service", ""),
            "xaisen_provider": instance.get("provider", ""),
            "xaisen_env": instance.get("env", topology.get("active_env", "devnet")),
            "xaisen_contract_env": instance.get("contract_env", topology.get("contract_env", "")),
            "xaisen_desired_state": instance.get("desired_state", ""),
        }
    )
    return entry


inventory_hosts: dict[str, dict[str, Any]] = {
    host["name"]: host_entry(host)
    for host in hosts
    if host.get("name") and host.get("address")
}

for instance in topology_instances:
    if not instance.get("name") or not instance.get("address"):
        continue
    if instance.get("desired_state") in {"deleted", "stopped"}:
        continue
    inventory_hosts[instance["name"]] = topology_host_entry(instance)

inventory: dict[str, Any] = {
    "all": {
        "hosts": inventory_hosts,
        "children": {
            "xaisen": {"hosts": {}},
        },
    }
}

for host in hosts:
    host_name = host.get("name")
    if not host_name:
        continue
    inventory["all"]["children"]["xaisen"]["hosts"][host_name] = {}
    for group in host.get("groups", []):
        inventory["all"]["children"].setdefault(group, {"hosts": {}})
        inventory["all"]["children"][group]["hosts"][host_name] = {}

for instance in topology_instances:
    host_name = instance.get("name")
    if not host_name or host_name not in inventory_hosts:
        continue
    inventory["all"]["children"]["xaisen"]["hosts"][host_name] = {}
    service = instance.get("service")
    provider = instance.get("provider")
    if service:
        inventory["all"]["children"].setdefault(service, {"hosts": {}})
        inventory["all"]["children"][service]["hosts"][host_name] = {}
    if provider:
        inventory["all"]["children"].setdefault(provider, {"hosts": {}})
        inventory["all"]["children"][provider]["hosts"][host_name] = {}

pulumi.export(
    "cloudCredentials",
    {
        "aws": bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE")),
        "gcp": bool(os.getenv("GOOGLE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        "azure": bool(os.getenv("ARM_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")),
        "digitalOcean": bool(os.getenv("DIGITALOCEAN_TOKEN")),
        "alibabaCloud": bool(os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID") and os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")),
        "alibabaRegion": os.getenv("ALIBABA_CLOUD_REGION", ""),
        "tencentCloud": bool(os.getenv("TENCENTCLOUD_SECRET_ID") and os.getenv("TENCENTCLOUD_SECRET_KEY")),
    },
)
pulumi.export("topology", topology)
pulumi.export("ansibleInventory", inventory)
