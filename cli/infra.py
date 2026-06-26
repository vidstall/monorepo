from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

from cli.config import ANSIBLE_PLAYBOOK, CONTRACT_PACKAGE_PATH, IMAGE_SERVICES, PROVIDER_CHOICES, PROVIDER_CR_REGISTRY_KEY, PROVIDER_ENV_FILES, REPO_ROOT, SSH_CONFIG_DIR, TERRAFORM_ENV_DIR, TERRAFORM_REGISTRY_DIR
from cli.env import build_env
from cli.process import run_command

SSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

REQUIRED_RUNTIME_VARS = (
    "XAISEN_CLIENT_IMAGE",
    "XAISEN_ROUTES_IMAGE",
    "XAISEN_WORKER_IMAGE",
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


def provider_terraform_root(provider: str) -> Path:
    return TERRAFORM_ENV_DIR / provider


def terraform_args(
    testbed_name: str,
    worker_nodes: int,
    client_nodes: int,
    coordinator_nodes: int,
    node_registry_contract_id: str | None,
) -> List[str]:
    args = [
        "-input=false",
        f"-var=testbed_name={testbed_name}",
        f"-var=worker_count={worker_nodes}",
        f"-var=client_count={client_nodes}",
        f"-var=coordinator_count={coordinator_nodes}",
    ]
    if node_registry_contract_id is not None:
        args.append(f"-var=node_registry_contract_id={node_registry_contract_id}")
    return args


def terraform_init(provider: str, env: Mapping[str, str]) -> None:
    run_command(["terraform", "init", "-input=false"], cwd=provider_terraform_root(provider), env=env)


def terraform_apply(provider: str, args: argparse.Namespace, env: Mapping[str, str]) -> None:
    root = provider_terraform_root(provider)
    terraform_init(provider, env)
    run_command(
        [
            "terraform",
            "apply",
            "-auto-approve",
            *terraform_args(
                testbed_name=args.testbed_name,
                worker_nodes=args.worker_nodes,
                client_nodes=args.client_nodes,
                coordinator_nodes=args.coordinator_nodes,
                node_registry_contract_id=args.node_registry_contract_id,
            ),
        ],
        cwd=root,
        env=env,
    )


def terraform_destroy(provider: str, args: argparse.Namespace, env: Mapping[str, str]) -> None:
    root = provider_terraform_root(provider)
    terraform_init(provider, env)
    run_command(
        [
            "terraform",
            "destroy",
            "-auto-approve",
            *terraform_args(
                testbed_name=args.testbed_name,
                worker_nodes=args.worker_nodes,
                client_nodes=args.client_nodes,
                coordinator_nodes=args.coordinator_nodes,
                node_registry_contract_id=args.node_registry_contract_id,
            ),
        ],
        cwd=root,
        env=env,
    )


def terraform_output(provider: str, env: Mapping[str, str]) -> Dict[str, object]:
    root = provider_terraform_root(provider)
    terraform_init(provider, env)
    completed = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=str(root),
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def terraform_value(outputs: Mapping[str, object], name: str) -> object:
    output = outputs.get(name)
    if not isinstance(output, dict) or "value" not in output:
        raise SystemExit(f"Terraform output did not include {name}")
    return output["value"]


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
    for role in ("worker", "client", "coordinator"):
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
    for key in ("LIVEKIT_URL", "NEXT_PUBLIC_SHOW_SETTINGS_MENU", *ROUTES_CONTRACT_ENV_KEYS):
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
) -> Dict[str, object]:
    require_runtime_env(env)
    inventory_data = terraform_value(outputs, "inventory")
    worker = first_host(inventory_data, "worker")
    coordinator = first_host(inventory_data, "coordinator")

    values: Dict[str, object] = runtime_env(env)
    if node_registry_contract_id:
        values["node_registry_contract_id"] = node_registry_contract_id
    if not values.get("LIVEKIT_URL"):
        if not worker:
            raise SystemExit("Cannot derive LIVEKIT_URL because Terraform output has no worker hosts")
        values["LIVEKIT_URL"] = f"ws://{worker['public_ip']}:7880"
    if coordinator:
        values["coordinator_private_ip"] = coordinator["private_ip"] or coordinator["public_ip"]
        values["redis_address"] = f"{values['coordinator_private_ip']}:6379"
    else:
        values["coordinator_private_ip"] = ""
        values["redis_address"] = ""
    return values


def render_ansible_vars(
    provider: str,
    outputs: Mapping[str, object],
    env: Mapping[str, str],
    node_registry_contract_id: str | None = None,
    output_dir: Path = SSH_CONFIG_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    vars_path = output_dir / f"{provider}-vars.json"
    vars_path.write_text(
        json.dumps(ansible_extra_vars(outputs, env, node_registry_contract_id), indent=2, sort_keys=True) + "\n",
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


def cleanup_provider_artifacts(provider: str) -> None:
    for suffix in ("-inventory.ini", "-inventory.yml", "-id_ed25519", "-vars.json"):
        target = SSH_CONFIG_DIR / f"{provider}{suffix}"
        target.unlink(missing_ok=True)


def ensure_runtime_dirs() -> None:
    SSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def destroy_providers(provider: str) -> Iterable[str]:
    if provider == "all":
        return PROVIDER_CHOICES
    return (provider,)


def cmd_deploy(args: argparse.Namespace) -> None:
    ensure_runtime_dirs()
    env = build_env(args.provider)
    require_runtime_env(env)
    terraform_apply(args.provider, args, env)

    if getattr(args, "deploy_contract", False):
        from cli.contract import cmd_deploy_contract, cmd_init_contract

        contract_network = getattr(args, "contract_network", "testnet")
        contract_args = argparse.Namespace(
            network=contract_network,
            package_path=CONTRACT_PACKAGE_PATH,
            gas_budget=1_000_000_000,
            gas_coins=[],
        )
        cmd_deploy_contract(contract_args)
        cmd_init_contract(contract_args)
        env = build_env(args.provider)

    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    vars_path = render_ansible_vars(args.provider, outputs, env, args.node_registry_contract_id)
    ansible_playbook(inventory_path, vars_path, env)


def cmd_inventory(args: argparse.Namespace) -> None:
    env = build_env(args.provider)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    print(inventory_path)


def _update_env_file(path: Path, updates: Dict[str, str]) -> None:
    existing: Dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if val and val[0] in {'"', "'"} and val[-1] == val[0]:
                val = val[1:-1]
            existing[key] = val
    existing.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def cmd_build_images(args: argparse.Namespace) -> None:
    provider = getattr(args, "provider", None)
    explicit_registry = getattr(args, "registry", None)

    if provider and explicit_registry:
        raise SystemExit("--registry and --provider are mutually exclusive")
    if not provider and not explicit_registry:
        raise SystemExit("One of --registry or --provider is required")

    if provider:
        env = build_env(provider)
        registry_key = PROVIDER_CR_REGISTRY_KEY.get(provider)
        if not registry_key:
            raise SystemExit(f"No registry configured for provider '{provider}'")
        registry_url = env.get(registry_key, "").strip()
        if not registry_url:
            raise SystemExit(
                f"{registry_key} is not set for {provider}. "
                f"Run: python3 vidctl.py setup-registry --provider {provider}"
            )
        registry = registry_url.rstrip("/")
    else:
        env = {}
        registry = explicit_registry.rstrip("/")

    tag = args.tag
    push = args.push
    platform = args.platform

    if push and provider:
        registry_host = registry.split("/")[0]
        username = env.get("ALICLOUD_CR_USERNAME", "").strip() if provider == "alibaba-cloud" else ""
        password = env.get("ALICLOUD_CR_PASSWORD", "").strip() if provider == "alibaba-cloud" else ""
        if username and password:
            print(f"\n=== Logging in to {registry_host} ===")
            subprocess.run(
                ["docker", "login", registry_host, "-u", username, "--password-stdin"],
                input=password,
                text=True,
                check=True,
            )
        else:
            print(f"\n  Skipping docker login (ALICLOUD_CR_USERNAME / ALICLOUD_CR_PASSWORD not set)")

    image_map: Dict[str, str] = {}
    for service, src_dir in IMAGE_SERVICES.items():
        image_name = f"{registry}/xaisen-{service}:{tag}"
        build_context = REPO_ROOT / src_dir
        if not build_context.exists():
            raise SystemExit(f"Build context not found: {build_context}")

        print(f"\n=== Building {service} ===")
        print(f"  image: {image_name}")
        print(f"  platform: {platform}")
        print(f"  context: {build_context}")

        build_cmd = ["docker", "build", "--platform", platform, "-t", image_name]
        if push:
            build_cmd.append("--push")
        build_cmd.append(".")

        subprocess.run(build_cmd, cwd=str(build_context), check=True)
        image_map[service] = image_name

    runtime_env_path = REPO_ROOT / "secrets" / "runtime.env"
    _update_env_file(runtime_env_path, {
        "XAISEN_WORKER_IMAGE": image_map["worker"],
        "XAISEN_ROUTES_IMAGE": image_map["routes"],
        "XAISEN_CLIENT_IMAGE": image_map["client"],
    })

    existing = {}
    for line in runtime_env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            existing[k.strip()] = v.strip()
    if "LIVEKIT_API_KEY" not in existing or not existing["LIVEKIT_API_KEY"]:
        import secrets as _secrets
        _update_env_file(runtime_env_path, {
            "LIVEKIT_API_KEY": f"devkey_{_secrets.token_hex(8)}",
            "LIVEKIT_API_SECRET": _secrets.token_hex(32),
        })
        print("\n  generated LIVEKIT_API_KEY and LIVEKIT_API_SECRET")

    print(f"\n  wrote {runtime_env_path}")
    print("\nDone. Images ready" + (" and pushed." if push else ". Use --push to push to registry."))


def cmd_setup_registry(args: argparse.Namespace) -> None:
    provider = args.provider
    if provider not in PROVIDER_CR_REGISTRY_KEY:
        raise SystemExit(f"setup-registry does not support provider '{provider}' yet")

    env = build_env(provider)
    tf_root = TERRAFORM_REGISTRY_DIR / provider
    if not tf_root.exists():
        raise SystemExit(f"No registry Terraform config found at {tf_root}")

    region = env.get("ALICLOUD_REGION", "cn-hangzhou")

    run_command(["terraform", "init", "-input=false"], cwd=tf_root, env=env)
    run_command(
        [
            "terraform", "apply", "-auto-approve", "-input=false",
            f"-var=namespace={args.namespace}",
            f"-var=region={region}",
        ],
        cwd=tf_root,
        env=env,
    )

    result = subprocess.run(
        ["terraform", "output", "-raw", "registry"],
        cwd=str(tf_root),
        env=dict(env),
        check=True,
        capture_output=True,
        text=True,
    )
    registry_url = result.stdout.strip()

    secrets_file = REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider]
    registry_key = PROVIDER_CR_REGISTRY_KEY[provider]
    _update_env_file(secrets_file, {registry_key: registry_url})

    print(f"\nRegistry ready: {registry_url}")
    print(f"  {registry_key} written to {secrets_file}")
    print(
        f"\nNext: add credentials to {secrets_file}:\n"
        f"  ALICLOUD_CR_USERNAME=<your-ram-username>\n"
        f"  ALICLOUD_CR_PASSWORD=<acr-fixed-password>\n"
        f"\nThen push images:\n"
        f"  python3 vidctl.py build-images --provider {provider} --push"
    )


def purge_terraform_state(root: Path) -> None:
    tf_dir = root / ".terraform"
    if tf_dir.exists():
        import shutil
        shutil.rmtree(tf_dir)
        print(f"  removed {tf_dir}")
    for pattern in ("*.tfstate", "*.tfstate.*", ".terraform.lock.hcl"):
        for f in root.glob(pattern):
            f.unlink()
            print(f"  removed {f}")


def destroy_registry(provider: str, env: Mapping[str, str]) -> None:
    tf_root = TERRAFORM_REGISTRY_DIR / provider
    state_file = tf_root / "terraform.tfstate"
    if not state_file.exists():
        print(f"  no registry state found for {provider}, skipping")
        return
    run_command(["terraform", "init", "-input=false"], cwd=tf_root, env=env)
    run_command(["terraform", "destroy", "-auto-approve", "-input=false"], cwd=tf_root, env=env)
    purge_terraform_state(tf_root)


def cmd_purge(args: argparse.Namespace) -> None:
    ensure_runtime_dirs()
    for provider in destroy_providers(args.provider):
        env = build_env(provider)
        print(f"\n=== Purging {provider} ===")
        print("Destroying infrastructure...")
        try:
            terraform_destroy(provider, args, env)
        except subprocess.CalledProcessError:
            print(f"  terraform destroy failed for {provider}, cleaning up anyway")
        print("Destroying container registry...")
        try:
            destroy_registry(provider, env)
        except subprocess.CalledProcessError:
            print(f"  registry destroy failed for {provider}, cleaning up anyway")
        print("Cleaning artifacts...")
        cleanup_provider_artifacts(provider)
        print("Cleaning Terraform local state...")
        purge_terraform_state(provider_terraform_root(provider))
        print(f"  {provider} purged")
