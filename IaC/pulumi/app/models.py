from __future__ import annotations

from typing import TypedDict


class HostConfig(TypedDict, total=False):
    name: str
    address: str
    user: str
    port: int
    groups: list[str]


class TopologyInstance(TypedDict, total=False):
    name: str
    service: str
    provider: str
    env: str
    backend: str
    address: str
    user: str
    port: int
    bucket: str
    desired_state: str
    last_status: str
    contract_env: str
    artifact_dir: str
    region: str
    zone: str
    ssh_key_dir: str
    size: str
