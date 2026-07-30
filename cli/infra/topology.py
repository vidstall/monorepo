from __future__ import annotations

from typing import Any

import tomllib

from ._constants import NETWORKS, PROVIDERS, SERVICE_BACKENDS
from .history import toml_value
from .validation import validate_network


def active_stack() -> str:
    # Deferred self-import: RUNTIME_TOPOLOGY_TOML/command_env are patched by
    # tests as flat cli.infra attributes (patch.object(infra, "X", ...)) --
    # looking them up through the package at call time (instead of binding
    # a direct name from ..context at module load time) is what makes those
    # patches actually take effect here.
    from .. import infra

    if infra.RUNTIME_TOPOLOGY_TOML.exists():
        return validate_network(str(read_topology().get("active_env", "devnet")))
    stack = infra.command_env().get("PULUMI_STACK", "devnet")
    return stack if stack in NETWORKS else "devnet"


def ensure_topology(env_name: str) -> dict[str, Any]:
    from .. import infra

    topology = read_topology() if infra.RUNTIME_TOPOLOGY_TOML.exists() else default_topology(env_name)
    topology["active_env"] = env_name
    topology["contract_env"] = relative_contract_env(env_name)
    topology.setdefault("providers", {provider: {"enabled": False} for provider in PROVIDERS})
    for provider in PROVIDERS:
        topology["providers"].setdefault(provider, {"enabled": False})
    topology.setdefault("workers", [])
    topology.setdefault("objects", [])
    for worker in topology["workers"]:
        worker.setdefault("backend", service_backend(str(worker.get("service", ""))))
    write_topology(topology)
    return topology


def read_topology() -> dict[str, Any]:
    from .. import infra

    data = tomllib.loads(infra.RUNTIME_TOPOLOGY_TOML.read_text(encoding="utf-8"))
    data.setdefault("workers", [])
    data.setdefault("objects", [])
    data.setdefault("providers", {provider: {"enabled": False} for provider in PROVIDERS})
    for provider in PROVIDERS:
        data["providers"].setdefault(provider, {"enabled": False})
    return data


def write_topology(topology: dict[str, Any]) -> None:
    from .. import infra

    infra.RUNTIME_TOPOLOGY_TOML.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'active_env = "{topology.get("active_env", "devnet")}"',
        f'contract_env = "{topology.get("contract_env", relative_contract_env("devnet"))}"',
        "",
    ]
    providers = topology.get("providers", {})
    for provider in PROVIDERS:
        values = providers.get(provider, {"enabled": False}) if isinstance(providers, dict) else {"enabled": False}
        lines.append(f"[providers.{provider}]")
        for key, value in values.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    for worker in topology.get("workers", []):
        lines.append("[[workers]]")
        for key, value in worker.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    for obj in topology.get("objects", []):
        lines.append("[[objects]]")
        for key, value in obj.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    infra.RUNTIME_TOPOLOGY_TOML.write_text("\n".join(lines), encoding="utf-8")


def find_worker(
    topology: dict[str, Any],
    env_name: str,
    host: str,
    service: str,
    provider: str,
    worker_index: int = 1,
) -> dict[str, Any] | None:
    for worker in topology.get("workers", []):
        if (
            worker.get("host") == host
            and worker.get("service") == service
            and worker.get("provider") == provider
            and worker.get("env", env_name) == env_name
            and worker.get("worker_index", 1) == worker_index
        ):
            return worker
    return None


def find_pinned_alibaba_worker(topology: dict[str, Any], service: str, provider: str) -> dict[str, Any] | None:
    for item in topology.get("workers", []):
        if item.get("service") == service and item.get("provider") == provider and item.get("region") and item.get("size"):
            return item
    return None


def worker_identifier(provider: str, host: str, service: str, worker_index: int) -> str:
    # <provider>-<host>-<service>-<worker_index>, used everywhere a worker
    # needs a single stable string identity: container name, sslip.io public
    # hostname, wallet-pool/registry lookup key. `host` stands in for a real
    # cloud-provider resource id (droplet id, ECS instance id, ...) rather
    # than using the actual one: the real id is only assigned by the
    # provider AFTER `pulumi up` creates the resource, and changes on every
    # destroy+recreate -- embedding it would churn the container name/DNS
    # hostname/Caddy cert on every redeploy. `host` is chosen once, up front,
    # in the scenario TOML and never changes, so it's a stable stand-in.
    # Always includes worker_index (no more "index 1 is unsuffixed" special
    # case) since a droplet can colocate several services, and each needs an
    # unambiguous identity regardless of how many replicas of it exist.
    return f"{provider}-{host}-{service}-{worker_index}"


def new_worker(env_name: str, host: str, service: str, provider: str, worker_index: int = 1) -> dict[str, Any]:
    return {
        "host": host,
        "service": service,
        "provider": provider,
        "env": env_name,
        "backend": service_backend(service),
        "worker_index": worker_index,
    }


def service_backend(service: str) -> str:
    return SERVICE_BACKENDS.get(service, "vm")


def relative_contract_env(env_name: str) -> str:
    return f"runtime/contract/{env_name}.env"


def default_topology(env_name: str) -> dict[str, Any]:
    return {
        "active_env": env_name,
        "contract_env": relative_contract_env(env_name),
        "providers": {provider: {"enabled": False} for provider in PROVIDERS},
        "workers": [],
        "objects": [],
    }
