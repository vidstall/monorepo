import os
from typing import Any, TypedDict

import pulumi


class HostConfig(TypedDict, total=False):
    name: str
    address: str
    user: str
    port: int
    groups: list[str]
    vars: dict[str, str | int | bool]


config = pulumi.Config("xaisen")
hosts = config.get_object("hosts") or []


def host_entry(host: HostConfig) -> dict[str, Any]:
    entry: dict[str, Any] = {"ansible_host": host["address"]}
    if host.get("user"):
        entry["ansible_user"] = host["user"]
    if host.get("port"):
        entry["ansible_port"] = host["port"]
    entry.update(host.get("vars", {}))
    return entry


inventory: dict[str, Any] = {
    "all": {
        "hosts": {
            host["name"]: host_entry(host)
            for host in hosts
            if host.get("name") and host.get("address")
        },
        "children": {
            "xaisen": {
                "hosts": {},
            },
        },
    },
}

for host in hosts:
    host_name = host.get("name")
    if not host_name:
        continue
    for group in host.get("groups", []):
        inventory["all"]["children"].setdefault(group, {"hosts": {}})
        inventory["all"]["children"][group]["hosts"][host_name] = {}

pulumi.export("cloudCredentials", {
    "digitalOcean": bool(os.getenv("DIGITALOCEAN_TOKEN")),
    "alibabaCloud": bool(os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID") and os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")),
    "alibabaRegion": os.getenv("ALIBABA_CLOUD_REGION", ""),
})
pulumi.export("ansibleInventory", inventory)
