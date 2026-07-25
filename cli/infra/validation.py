from __future__ import annotations

from pathlib import Path

from ..context import read_env_file
from ._constants import NETWORKS, REQUIRED_CONTRACT_KEYS


def missing_contract_keys(path: Path) -> list[str]:
    values = read_env_file(path)
    return [key for key in REQUIRED_CONTRACT_KEYS if not values.get(key)]


def validate_network(env_name: str) -> str:
    if env_name not in NETWORKS:
        raise ValueError(f"Unsupported environment {env_name!r}; expected one of {', '.join(NETWORKS)}.")
    return env_name


def desired_state_for(action: str) -> str:
    return {
        "start": "running",
        "pause": "stopped",
        "restart": "running",
        "kill": "deleted",
    }[action]


def missing_vm_provider_keys(provider: str) -> list[str]:
    # Deferred self-import: command_env is patched by tests as a flat
    # cli.infra attribute -- looking it up through the package at call time
    # is what makes that patch take effect here.
    from .. import infra

    env = infra.command_env()
    required = {
        "aws": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
        "gcp": ("GCP_PROJECT", "GCP_ZONE"),
        "azure": ("ARM_CLIENT_ID", "ARM_CLIENT_SECRET", "ARM_SUBSCRIPTION_ID", "ARM_TENANT_ID"),
        "alibaba": ("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET", "ALIBABA_CLOUD_REGION"),
        "digitalocean": ("DIGITALOCEAN_TOKEN",),
        "upcloud": ("UPCLOUD_TOKEN",),
        "akamai": ("LINODE_TOKEN",),
        "tencent": ("TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY", "TENCENTCLOUD_REGION"),
        "oci": (
            "OCI_TENANCY_OCID",
            "OCI_USER_OCID",
            "OCI_FINGERPRINT",
            "OCI_PRIVATE_KEY",
            "OCI_COMPARTMENT_OCID",
        ),
    }.get(provider, ())
    return [key for key in required if not env.get(key)]


def vm_provider_error(provider: str, missing_keys: list[str]) -> str:
    secret_file = f"secrets/cloud/{provider}.env"
    if provider == "digitalocean":
        secret_file = "secrets/cloud/digital-ocean.env"
    return (
        f"{provider} VM provisioning is missing required credentials: "
        + ", ".join(missing_keys)
        + f". Add them to {secret_file} or export them before running ./vidctl infra."
    )
