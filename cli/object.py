from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import infra
from .context import ROOT, command_env, run

# Frontend's static build lives at services/client/client (Vite), publishing
# services/client/client/dist to object storage. This is the only object type
# today; cli/object.py was deleted in edc04a8 when "frontend" was dropped from
# DOCKER_SERVICES, then restored here as its own module since the object-storage
# publish flow (topology["objects"] + Pulumi frontend adapters under
# IaC/pulumi/app/frontend/) never went away.
OBJECT_TYPES = {"frontend": ROOT / "services" / "client" / "client"}
PROVIDERS = infra.PROVIDERS


def publish(name: str, object_type: str, provider: str) -> int:
    error = validate(object_type, provider)
    if error:
        print(error, file=sys.stderr)
        return 2

    topology = infra.read_topology()
    env_name = infra.validate_network(str(topology.get("active_env", "devnet")))

    missing_provider_keys = missing_object_storage_provider_keys(provider)
    if missing_provider_keys:
        message = object_storage_provider_error(object_type, provider, missing_provider_keys)
        print(message, file=sys.stderr)
        record(object_type, "publish", env_name, name, provider, 1, message)
        return 1

    obj = find_object(topology, env_name, name, object_type, provider)
    if obj is None:
        obj = new_object(env_name, name, object_type, provider)
        topology.setdefault("objects", []).append(obj)

    obj["desired_state"] = "running"
    obj["last_operation"] = "publish"
    obj["last_updated"] = infra.timestamp()
    set_object_storage_defaults(obj, env_name)
    infra.write_topology(topology)

    code = build_static_artifacts(object_type)
    if code == 0:
        code = infra.pulumi_up(env_name, parallel=4)

    if code == 0:
        obj["last_status"] = "running"
        obj["last_error"] = ""
    else:
        obj["desired_state"] = "stopped"
        obj["last_error"] = f"publish failed with exit code {code}"
    infra.write_topology(topology)

    record(object_type, "publish", env_name, name, provider, code, str(obj.get("last_error", "")))
    return code


def delete(name: str, object_type: str, provider: str, yes: bool) -> int:
    error = validate(object_type, provider)
    if error:
        print(error, file=sys.stderr)
        return 2

    if not yes:
        message = "Refusing to delete an object-storage site without --yes."
        print(message, file=sys.stderr)
        record(object_type, "delete", "", name, provider, 2, message)
        return 2

    topology = infra.read_topology()
    env_name = infra.validate_network(str(topology.get("active_env", "devnet")))

    obj = find_object(topology, env_name, name, object_type, provider)
    if obj is None:
        obj = new_object(env_name, name, object_type, provider)
        topology.setdefault("objects", []).append(obj)

    obj["desired_state"] = "deleted"
    obj["last_operation"] = "delete"
    obj["last_updated"] = infra.timestamp()
    set_object_storage_defaults(obj, env_name)
    infra.write_topology(topology)

    code = infra.pulumi_up(env_name)

    if code == 0:
        topology["objects"] = [
            item
            for item in topology.get("objects", [])
            if not (
                item.get("name") == name
                and item.get("object") == object_type
                and item.get("provider") == provider
                and item.get("env", env_name) == env_name
            )
        ]
    else:
        obj["last_error"] = f"delete failed with exit code {code}"
    infra.write_topology(topology)

    record(object_type, "delete", env_name, name, provider, code, "" if code == 0 else str(obj.get("last_error", "")))
    return code


def validate(object_type: str, provider: str) -> str:
    if object_type not in OBJECT_TYPES:
        return f"Unknown object type: {object_type}"
    if provider not in PROVIDERS:
        return f"Unknown provider: {provider}"
    return ""


def find_object(
    topology: dict[str, Any],
    env_name: str,
    name: str,
    object_type: str,
    provider: str,
) -> dict[str, Any] | None:
    for obj in topology.get("objects", []):
        if (
            obj.get("name") == name
            and obj.get("object") == object_type
            and obj.get("provider") == provider
            and obj.get("env", env_name) == env_name
        ):
            return obj
    return None


def new_object(env_name: str, name: str, object_type: str, provider: str) -> dict[str, Any]:
    return {
        "name": name,
        "object": object_type,
        "provider": provider,
        "env": env_name,
        "backend": "object_storage",
    }


def set_object_storage_defaults(obj: dict[str, Any], env_name: str) -> None:
    bucket = str(obj.get("bucket") or storage_bucket_name(env_name, str(obj.get("name", "frontend")), str(obj.get("provider", ""))))
    obj["bucket"] = bucket
    obj.setdefault("resource_id", bucket)
    obj.setdefault("artifact_dir", "services/client/client/dist")
    if obj.get("provider") == "alibaba":
        obj.setdefault("region", command_env().get("ALIBABA_FRONTEND_REGION", "ap-southeast-1"))


def storage_bucket_name(env_name: str, name: str, provider: str) -> str:
    raw = f"xaisen-{env_name}-{provider}-{name}".lower()
    cleaned = "".join(char if char.isalnum() else "-" for char in raw)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:63]


def build_static_artifacts(object_type: str) -> int:
    service_dir: Path = OBJECT_TYPES[object_type]
    print(f"Building static {object_type} from {service_dir}")
    return run(["pnpm", "build"], cwd=service_dir, env=command_env())


def missing_object_storage_provider_keys(provider: str) -> list[str]:
    env = command_env()
    required = {
        "cloudflare": (
            "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_R2_ACCESS_KEY_ID",
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        ),
        "aws": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
        "digitalocean": ("DIGITALOCEAN_TOKEN",),
        "alibaba": ("ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET", "ALIBABA_CLOUD_REGION"),
        "gcp": (),
        "azure": (),
        "tencent": (),
    }.get(provider, ())
    return [key for key in required if not env.get(key)]


def object_storage_provider_error(object_type: str, provider: str, missing_keys: list[str]) -> str:
    secret_file = f"secrets/cloud/{provider}.env"
    if provider == "digitalocean":
        secret_file = "secrets/cloud/digital-ocean.env"
    return (
        f"{provider} {object_type} object storage is missing required credentials: "
        + ", ".join(missing_keys)
        + f". Add them to {secret_file} or export them before running ./vidctl object."
    )


def record(object_type: str, action: str, env_name: str, name: str, provider: str, code: int, error: str) -> None:
    infra.record_history(
        f"object {action}",
        env=env_name,
        name=name,
        service=object_type,
        provider=provider,
        result_for_code=code,
        error=error,
    )
