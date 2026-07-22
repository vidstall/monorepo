from __future__ import annotations

from typing import TypedDict


class HostConfig(TypedDict, total=False):
    name: str
    address: str
    user: str
    port: int
    groups: list[str]


class ServicePort(TypedDict):
    service: str
    port: int
    # Per-service desired_state, distinct from the host-level aggregate
    # (TopologyInstance.desired_state is "running" if ANY colocated service
    # wants to run) -- Ansible needs this to correctly pause/resume one
    # container without disturbing others sharing the host.
    desired_state: str
    # 1-based; distinguishes multiple colocated instances of the SAME
    # service on one host (vidctl.py's count-prefix --service syntax, e.g.
    # `5cp-daemon`). index=1 is the pre-existing single-instance identity.
    index: int
    # service if index == 1, else f"{service}-{index}" -- the namespacing
    # key Ansible uses for the container name / state dir / wallet file,
    # as opposed to `service`, which stays the base type for image/tag
    # lookups and env-var-name mapping (shared across replicas).
    instance_key: str


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
    # 1-based; see ServicePort.index above. Always present on real topology
    # rows (cli/infra.py's new_instance always sets it, default 1).
    instance_index: int
    # Runtime-only: populated by program.py's group-by-name merge for
    # multi-service-per-VM colocation (digitalocean provider only). Never
    # persisted to topology.toml -- each topology row still carries exactly
    # one `service`/`port`; this field holds the union across all rows
    # sharing one `name`.
    services: list[ServicePort]
