from __future__ import annotations

import json
import os  # needed for chmod on private key and vars files
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from cli.config import ANSIBLE_PLAYBOOK, SSH_CONFIG_DIR
from cli.env import update_env_file as _update_env_file
from cli.process import run_command
from cli.infra.terraform import terraform_value

REQUIRED_RUNTIME_VARS = (
    "XAISEN_CLIENT_IMAGE",
    "XAISEN_ROUTES_IMAGE",
    "XAISEN_MEDIA_IMAGE",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)

DEFAULT_RUNTIME_VARS = {
    "XAISEN_COORDINATOR_IMAGE": "redis:7.4-alpine",
    "XAISEN_PROXY_IMAGE": "caddy:2-alpine",
}

ROUTES_CONTRACT_ENV_KEYS = (
    "CONTRACT_NETWORK",
    "CONTRACT_PACKAGE_ID",
    "CONTRACT_REGISTRY_OBJECT_ID",
    "CONTRACT_UPGRADE_CAP_ID",
    "CONTRACT_DEPLOYER_ADDRESS",
    "CONTRACT_PUBLISH_TX_DIGEST",
    "CONTRACT_UPDATE_TX_DIGEST",
)

IMAGE_TAR_KEYS = (
    "XAISEN_MEDIA_IMAGE_TAR",
    "XAISEN_ROUTES_IMAGE_TAR",
    "XAISEN_CLIENT_IMAGE_TAR",
    "XAISEN_VCLIENT_IMAGE_TAR",
)


def write_private_key(provider: str, outputs: Mapping[str, object], output_dir: Path = SSH_CONFIG_DIR) -> Path:
    private_key = str(terraform_value(outputs, "private_key_pem"))
    key_path = output_dir / f"{provider}-id_ed25519"
    if "BEGIN PRIVATE KEY" in private_key and "BEGIN OPENSSH" not in private_key:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            load_pem_private_key,
        )
        key_obj = load_pem_private_key(private_key.encode(), password=None)
        openssh_bytes = key_obj.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
        key_path.write_bytes(openssh_bytes)
    else:
        key_path.write_text(private_key, encoding="utf-8")
    os.chmod(key_path, 0o600)
    return key_path


def normalize_role_hosts(inventory_data: object, role: str) -> List[Dict[str, str]]:
    if not isinstance(inventory_data, dict):
        raise SystemExit("Terraform inventory output must be an object")
    raw_hosts = inventory_data.get(role, [])
    if not isinstance(raw_hosts, list):
        raise SystemExit(f"Terraform inventory output group {role} must be a list")

    hosts: List[Dict[str, str]] = []
    for index, raw_host in enumerate(raw_hosts):
        if not isinstance(raw_host, dict):
            raise SystemExit(f"Terraform inventory output group {role} contains a non-object host")
        name = str(raw_host.get("name") or f"{role}-{index}")
        public_ip = str(raw_host.get("public_ip") or raw_host.get("host") or raw_host.get("public_ip_address") or "")
        private_ip = str(raw_host.get("private_ip") or raw_host.get("private_ip_address") or "")
        ssh_user = str(raw_host.get("ssh_user") or raw_host.get("user") or "root")
        if not public_ip:
            raise SystemExit(f"Terraform inventory host {name} is missing public_ip")
        hosts.append(
            {
                "name": name,
                "ansible_host": public_ip,
                "ansible_user": ssh_user,
                "public_ip": public_ip,
                "private_ip": private_ip,
                "role": str(raw_host.get("role") or role),
            }
        )
    return hosts


def inventory_from_outputs(outputs: Mapping[str, object], key_path: Path) -> Dict[str, object]:
    inventory_data = terraform_value(outputs, "inventory")
    children: Dict[str, object] = {}
    for role in ("media", "routes", "vclient", "coordinator"):
        role_hosts = normalize_role_hosts(inventory_data, role)
        children[role] = {
            "hosts": {
                host.pop("name"): host
                for host in role_hosts
            }
        }
    return {
        "all": {
            "vars": {
                "ansible_ssh_private_key_file": str(key_path),
                "ansible_ssh_common_args": "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
                "ansible_python_interpreter": "/usr/bin/python3",
            },
            "children": children,
        }
    }


def yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def yaml_lines(value: object, indent: int = 0) -> List[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: List[str] = []
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(child)}")
        return lines
    if isinstance(value, list):
        lines = []
        for child in value:
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}-")
                lines.extend(yaml_lines(child, indent + 2))
            else:
                lines.append(f"{prefix}- {yaml_scalar(child)}")
        return lines
    return [f"{prefix}{yaml_scalar(value)}"]


def write_yaml(path: Path, value: Mapping[str, object]) -> None:
    path.write_text("\n".join(yaml_lines(value)) + "\n", encoding="utf-8")


def render_inventory(provider: str, outputs: Mapping[str, object], output_dir: Path = SSH_CONFIG_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    key_path = write_private_key(provider, outputs, output_dir)
    inventory = inventory_from_outputs(outputs, key_path)
    inventory_path = output_dir / f"{provider}-inventory.yml"
    write_yaml(inventory_path, inventory)
    return inventory_path


def first_host(inventory_data: object, role: str) -> Dict[str, str] | None:
    hosts = normalize_role_hosts(inventory_data, role)
    if not hosts:
        return None
    return hosts[0]


def runtime_env(env: Mapping[str, str]) -> Dict[str, str]:
    values = {**DEFAULT_RUNTIME_VARS}
    values.update({key: env[key] for key in REQUIRED_RUNTIME_VARS if key in env})
    for key in DEFAULT_RUNTIME_VARS:
        if key in env:
            values[key] = env[key]
    for key in ("LIVEKIT_URL", "NEXT_PUBLIC_SHOW_SETTINGS_MENU", *ROUTES_CONTRACT_ENV_KEYS, *IMAGE_TAR_KEYS):
        if key in env and env[key] != "":
            values[key] = env[key]
    return values


def missing_required_env(env: Mapping[str, str]) -> List[str]:
    return [key for key in REQUIRED_RUNTIME_VARS if not env.get(key)]


def require_runtime_env(env: Mapping[str, str]) -> None:
    missing = missing_required_env(env)
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(f"Missing required runtime env vars in secrets/runtime.env or environment: {joined}")


def ansible_extra_vars(
    outputs: Mapping[str, object],
    env: Mapping[str, str],
    node_registry_contract_id: str | None = None,
    client_oss: bool = False,
) -> Dict[str, object]:
    require_runtime_env(env)
    inventory_data = terraform_value(outputs, "inventory")
    media = first_host(inventory_data, "media")
    coordinator = first_host(inventory_data, "coordinator")
    routes = first_host(inventory_data, "routes")

    values: Dict[str, object] = runtime_env(env)
    if node_registry_contract_id:
        values["node_registry_contract_id"] = node_registry_contract_id
    if not values.get("LIVEKIT_URL"):
        if not media:
            raise SystemExit("Cannot derive LIVEKIT_URL because Terraform output has no media hosts")
        values["LIVEKIT_URL"] = f"ws://{media['public_ip']}:7880"
    if coordinator:
        values["coordinator_private_ip"] = coordinator["private_ip"] or coordinator["public_ip"]
        values["redis_address"] = f"{values['coordinator_private_ip']}:6379"
    else:
        values["coordinator_private_ip"] = ""
        values["redis_address"] = ""
    values["routes_url"] = f"http://{routes['public_ip']}" if routes else ""
    values["client_oss"] = client_oss
    return values


def render_ansible_vars(
    provider: str,
    outputs: Mapping[str, object],
    env: Mapping[str, str],
    node_registry_contract_id: str | None = None,
    output_dir: Path = SSH_CONFIG_DIR,
    client_oss: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    vars_path = output_dir / f"{provider}-vars.json"
    vars_path.write_text(
        json.dumps(ansible_extra_vars(outputs, env, node_registry_contract_id, client_oss=client_oss), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(vars_path, 0o600)
    return vars_path


def ansible_playbook(inventory_path: Path, vars_path: Path, env: Mapping[str, str]) -> None:
    if not ANSIBLE_PLAYBOOK.exists():
        raise SystemExit(f"Missing Ansible playbook: {ANSIBLE_PLAYBOOK}")
    run_command(
        ["ansible-playbook", "-i", str(inventory_path), str(ANSIBLE_PLAYBOOK), "-e", f"@{vars_path}"],
        cwd=ANSIBLE_PLAYBOOK.parent.parent,
        env=env,
    )
