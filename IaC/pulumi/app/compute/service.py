from __future__ import annotations

from typing import Any, Callable

from ..models import TopologyInstance
from .ssh import read_ssh_public_key

VMResult = dict[str, Any]
VMAdapter = Callable[[TopologyInstance, str], VMResult]


def vm_instances(instances: list[TopologyInstance]) -> list[TopologyInstance]:
    return [instance for instance in instances if instance.get("backend") == "vm"]


def adapter(provider: str) -> VMAdapter:
    if provider == "digitalocean":
        from .digitalocean import create_vm
    elif provider == "aws":
        from .aws import create_vm
    elif provider == "gcp":
        from .gcp import create_vm
    elif provider == "azure":
        from .azure import create_vm
    elif provider == "alibaba":
        from .alibaba import create_vm
    elif provider == "tencent":
        raise ValueError(
            "tencent VM provisioning is not yet supported (no working Pulumi Python SDK path was "
            "found for Tencent compute/VPC resources) - choose another --provider for now."
        )
    else:
        raise ValueError(f"No VM provisioning adapter for provider: {provider}")
    return create_vm


def create_vm_instance(instance: TopologyInstance) -> VMResult:
    provider = str(instance.get("provider", ""))
    desired_state = str(instance.get("desired_state", ""))
    # "unknown" means a prior provisioning attempt failed before anything was
    # actually created (see cli/infra.py control()'s rollback-to-previous
    # logic) -- skip it like "deleted", or every future apply for ANY
    # instance keeps retrying and can abort on the same dead entry.
    if desired_state in ("deleted", "unknown"):
        return {
            "provider": provider,
            "desired_state": desired_state,
            "address": None,
            "user": None,
        }
    result = adapter(provider)(instance, read_ssh_public_key(instance))
    result["provider"] = provider
    result["desired_state"] = desired_state
    return result
