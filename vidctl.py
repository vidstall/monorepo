#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
SSH_CONFIG_DIR = ARTIFACTS_DIR / "ssh_config"
TERRAFORM_ENV_DIR = REPO_ROOT / "IaC" / "terraform" / "environments"
ANSIBLE_PLAYBOOK = REPO_ROOT / "IaC" / "ansible" / "playbooks" / "site.yml"

PROVIDER_CHOICES = ("aws", "digital-ocean", "hetzner", "alibaba-cloud")
ROLE_CHOICES = ("worker", "client", "coordinator")
PROVIDER_ENV_FILES = {
    "aws": "aws.env",
    "digital-ocean": "digital-ocean.env",
    "hetzner": "hetzner.env",
    "alibaba-cloud": "alibaba-cloud.env",
}
CONTRACT_NETWORK_CHOICES = ("devnet", "testnet", "mainnet")
CONTRACT_ENV_FILE = REPO_ROOT / "secrets" / "contract.env"
CONTRACT_ENV_DIR = REPO_ROOT / "secrets" / "contract"
CONTRACT_PACKAGE_PATH = REPO_ROOT / "src" / "contract"
CONTRACT_ENV_KEYS = (
    "CONTRACT_NETWORK",
    "CONTRACT_PACKAGE_ID",
    "CONTRACT_REGISTRY_OBJECT_ID",
    "CONTRACT_UPGRADE_CAP_ID",
    "CONTRACT_DEPLOYER_ADDRESS",
    "CONTRACT_PUBLISH_TX_DIGEST",
    "CONTRACT_GAS_OBJECT_ID",
    "CONTRACT_GAS_OBJECT_VERSION",
    "CONTRACT_GAS_OBJECT_DIGEST",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vidctl.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy = subparsers.add_parser("deploy", help="Apply Terraform, then configure Docker with Ansible")
    deploy.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    deploy.add_argument("--testbed-name", default="depin-testbed")
    deploy.add_argument("--node-registry-contract-id", default=None)
    deploy.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    deploy.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    deploy.add_argument("--coordinator-nodes", type=int, default=1)
    deploy.set_defaults(func=cmd_deploy)

    deploy_contract = subparsers.add_parser(
        "deploy-contract",
        help="Switch a Sui environment, build the Move package, and publish the contract",
    )
    deploy_contract.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    deploy_contract.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    deploy_contract.add_argument("--gas-budget", type=int, default=1_000_000_000)
    deploy_contract.add_argument(
        "--gas-coin",
        dest="gas_coins",
        action="append",
        default=[],
        help="Explicit gas coin object ID to use for publish; repeatable.",
    )
    deploy_contract.set_defaults(func=cmd_deploy_contract)

    init_contract = subparsers.add_parser(
        "init-contract",
        help="Create the shared SUI registry object for a published contract",
    )
    init_contract.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    init_contract.add_argument("--gas-budget", type=int, default=100_000_000)
    init_contract.add_argument(
        "--gas-coin",
        dest="gas_coins",
        action="append",
        default=[],
        help="Explicit gas coin object ID to use for registry initialization; repeatable.",
    )
    init_contract.set_defaults(func=cmd_init_contract)

    destroy = subparsers.add_parser("destroy", help="Tear down Terraform-managed infrastructure")
    destroy.add_argument(
        "--provider",
        required=True,
        choices=(*PROVIDER_CHOICES, "all"),
        help="Destroy one provider or every provider.",
    )
    destroy.add_argument("--testbed-name", default="depin-testbed")
    destroy.add_argument("--node-registry-contract-id", default=None)
    destroy.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    destroy.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    destroy.add_argument("--coordinator-nodes", type=int, default=1)
    destroy.add_argument("--auto-approve", action="store_true", default=True)
    destroy.set_defaults(func=cmd_destroy)

    inventory = subparsers.add_parser("inventory", help="Render a transient Ansible inventory from Terraform output")
    inventory.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    inventory.add_argument("--testbed-name", default="depin-testbed")
    inventory.add_argument("--node-registry-contract-id", default=None)
    inventory.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    inventory.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    inventory.add_argument("--coordinator-nodes", type=int, default=1)
    inventory.set_defaults(func=cmd_inventory)

    return parser.parse_args()


def load_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        values[key] = value
    return values


def build_env(provider: str) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file(REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider]))
    return env


def build_contract_env(network: str) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file(CONTRACT_ENV_FILE))
    env.update(load_env_file(CONTRACT_ENV_DIR / f"{network}.env"))
    env["SUI_NETWORK"] = network
    return env


def parse_publish_metadata(output: str) -> Dict[str, str]:
    result: Dict[str, str] = {}

    patterns = {
        "CONTRACT_PUBLISH_TX_DIGEST": r"^Transaction Digest:\s*([0-9A-Za-z]+)$",
        "CONTRACT_DEPLOYER_ADDRESS": r"^│ Sender:\s*(0x[0-9a-fA-F]+)\s*│$",
        "CONTRACT_PACKAGE_ID": r"^│ │ PackageID:\s*(0x[0-9a-fA-F]+)\s+Version:\s*\d+\s+Digest:\s*[0-9A-Za-z]+\s*│$",
        "CONTRACT_UPGRADE_CAP_ID": r"^│ │ ID:\s*(0x[0-9a-fA-F]+)\s*│$",
        "CONTRACT_GAS_OBJECT_ID": r"^│ │ ID:\s*(0x[0-9a-fA-F]+)\s*│$",
        "CONTRACT_GAS_OBJECT_VERSION": r"^│ │ Version:\s*(\d+)\s*│$",
        "CONTRACT_GAS_OBJECT_DIGEST": r"^│ │ Digest:\s*([0-9A-Za-z]+)\s*│$",
    }

    lines = output.splitlines()

    for line in lines:
        for key, pattern in patterns.items():
            if key in result:
                continue
            match = re.match(pattern, line)
            if match:
                result[key] = match.group(1)

    upgrade_cap_id = None
    gas_object_id = None
    gas_object_version = None
    gas_object_digest = None
    in_created_objects = False
    in_gas_object = False
    in_published_objects = False

    for line in lines:
        stripped = line.strip()
        if stripped == "Created Objects:":
            in_created_objects = True
            in_gas_object = False
            continue
        if stripped == "Published Objects:":
            in_published_objects = True
            in_created_objects = False
            in_gas_object = False
            continue
        if stripped == "Gas Object:":
            in_gas_object = True
            continue

        if in_created_objects and stripped.startswith("ID:") and "UpgradeCap" not in result:
            upgrade_cap_id = stripped.split()[1]
            result["CONTRACT_UPGRADE_CAP_ID"] = upgrade_cap_id
        if in_gas_object and stripped.startswith("ID:"):
            gas_object_id = stripped.split()[1]
        if in_gas_object and stripped.startswith("Version:"):
            gas_object_version = stripped.split()[1]
        if in_gas_object and stripped.startswith("Digest:"):
            gas_object_digest = stripped.split()[1]
            in_gas_object = False
        if in_published_objects and stripped.startswith("PackageID:"):
            result["CONTRACT_PACKAGE_ID"] = stripped.split()[1]

    if gas_object_id is not None:
        result["CONTRACT_GAS_OBJECT_ID"] = gas_object_id
    if gas_object_version is not None:
        result["CONTRACT_GAS_OBJECT_VERSION"] = gas_object_version
    if gas_object_digest is not None:
        result["CONTRACT_GAS_OBJECT_DIGEST"] = gas_object_digest

    required = (
        "CONTRACT_PACKAGE_ID",
        "CONTRACT_UPGRADE_CAP_ID",
        "CONTRACT_DEPLOYER_ADDRESS",
        "CONTRACT_PUBLISH_TX_DIGEST",
        "CONTRACT_GAS_OBJECT_ID",
        "CONTRACT_GAS_OBJECT_VERSION",
        "CONTRACT_GAS_OBJECT_DIGEST",
    )
    missing = [key for key in required if key not in result]
    if missing:
        raise SystemExit(f"Could not parse publish metadata from Sui output: {', '.join(missing)}")

    return result


def parse_registry_object_id(output: str) -> str:
    current_object_id: str | None = None
    fallback_object_id: str | None = None

    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("ObjectID:"):
            current_object_id = stripped.split()[1]
            if fallback_object_id is None:
                fallback_object_id = current_object_id
        elif stripped.startswith("ID:"):
            current_object_id = stripped.split()[1]
            if fallback_object_id is None:
                fallback_object_id = current_object_id
        elif "ObjectType:" in stripped and "::node_registry::Registry<" in stripped and current_object_id:
            return current_object_id

    if fallback_object_id:
        return fallback_object_id
    raise SystemExit("Could not parse registry object ID from Sui output")


def write_contract_env(network: str, metadata: Mapping[str, str]) -> None:
    contract_env_file = CONTRACT_ENV_DIR / f"{network}.env"
    contract_env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={metadata.get(key, '')}" for key in CONTRACT_ENV_KEYS]
    lines.insert(0, f"# Auto-generated by `vidctl.py deploy-contract --network {network}`")
    contract_env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote contract metadata to {contract_env_file}")


def ensure_runtime_dirs() -> None:
    SSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def provider_terraform_root(provider: str) -> Path:
    return TERRAFORM_ENV_DIR / provider


def run_command(args: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> None:
    print(f"+ {shlex.join(args)}", flush=True)
    subprocess.run(args, cwd=str(cwd), env=dict(env), check=True)


def terraform_args(
    *,
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
    root = provider_terraform_root(provider)
    run_command(["terraform", "init", "-input=false"], cwd=root, env=env)


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


def render_inventory(provider: str, outputs: Mapping[str, object]) -> Path:
    inventory_output = outputs.get("inventory")
    private_key_output = outputs.get("private_key_pem")
    if not isinstance(inventory_output, dict) or "value" not in inventory_output:
        raise SystemExit("Terraform output did not include inventory")
    if not isinstance(private_key_output, dict) or "value" not in private_key_output:
        raise SystemExit("Terraform output did not include private_key_pem")

    inventory_data = inventory_output["value"]
    private_key = private_key_output["value"]

    key_path = SSH_CONFIG_DIR / f"{provider}-id_ed25519"
    key_path.write_text(str(private_key), encoding="utf-8")
    os.chmod(key_path, 0o600)

    inventory_path = SSH_CONFIG_DIR / f"{provider}-inventory.ini"
    lines = [f"[all:vars]", f"ansible_ssh_private_key_file={key_path}"]
    for role in ROLE_CHOICES:
        lines.append("")
        lines.append(f"[{role}]")
        for host in inventory_data.get(role, []):
            if not isinstance(host, dict):
                continue
            name = host.get("name", role)
            address = host.get("host", "")
            user = host.get("user", "root")
            lines.append(f"{name} ansible_host={address} ansible_user={user}")
    inventory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return inventory_path


def ansible_playbook(inventory_path: Path, env: Mapping[str, str]) -> None:
    if not ANSIBLE_PLAYBOOK.exists():
        raise SystemExit(f"Missing Ansible playbook: {ANSIBLE_PLAYBOOK}")
    run_command(
        ["ansible-playbook", "-i", str(inventory_path), str(ANSIBLE_PLAYBOOK)],
        cwd=ANSIBLE_PLAYBOOK.parent.parent,
        env=env,
    )


def cleanup_provider_artifacts(provider: str) -> None:
    for suffix in ("-inventory.ini", "-id_ed25519"):
        target = SSH_CONFIG_DIR / f"{provider}{suffix}"
        target.unlink(missing_ok=True)


def cmd_deploy(args: argparse.Namespace) -> None:
    env = build_env(args.provider)
    terraform_apply(args.provider, args, env)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    ansible_playbook(inventory_path, env)


def cmd_deploy_contract(args: argparse.Namespace) -> None:
    if not args.package_path.exists():
        raise SystemExit(f"Missing contract package path: {args.package_path}")

    env = build_contract_env(args.network)
    print(f"Switching Sui CLI to {args.network}...")
    run_command(["sui", "client", "switch", "--env", args.network], cwd=REPO_ROOT, env=env)

    print(f"Building Move package at {args.package_path} for {args.network}...")
    run_command(
        ["sui", "move", "build", "--path", str(args.package_path), "--build-env", args.network],
        cwd=REPO_ROOT,
        env=env,
    )
    print(f"Publishing contract from {args.package_path} to {args.network}...")
    publish_args = ["sui", "client", "publish", "--gas-budget", str(args.gas_budget)]
    if args.gas_coins:
        publish_args.extend(["--gas", *args.gas_coins])
    print(f"+ {shlex.join(publish_args)}", flush=True)
    completed = subprocess.run(
        publish_args,
        cwd=str(args.package_path),
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n", file=sys.stderr)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            publish_args,
            output=completed.stdout,
            stderr=completed.stderr,
        )

    metadata = parse_publish_metadata(completed.stdout)
    metadata["CONTRACT_NETWORK"] = args.network
    write_contract_env(args.network, metadata)


def cmd_init_contract(args: argparse.Namespace) -> None:
    env = build_contract_env(args.network)
    package_id = env.get("CONTRACT_PACKAGE_ID")
    if not package_id:
        raise SystemExit(
            f"Missing CONTRACT_PACKAGE_ID in {CONTRACT_ENV_DIR / f'{args.network}.env'}; "
            "run deploy-contract first."
        )

    print(f"Switching Sui CLI to {args.network}...")
    run_command(["sui", "client", "switch", "--env", args.network], cwd=REPO_ROOT, env=env)

    print(f"Creating shared Registry<0x2::sui::SUI> for package {package_id}...")
    call_args = [
        "sui",
        "client",
        "call",
        "--package",
        package_id,
        "--module",
        "node_registry",
        "--function",
        "create_registry",
        "--type-args",
        "0x2::sui::SUI",
        "--gas-budget",
        str(args.gas_budget),
    ]
    if args.gas_coins:
        call_args.extend(["--gas", *args.gas_coins])

    print(f"+ {shlex.join(call_args)}", flush=True)
    completed = subprocess.run(
        call_args,
        cwd=str(REPO_ROOT),
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="")
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            call_args,
            output=completed.stdout,
            stderr=completed.stderr,
        )

    metadata = {key: env.get(key, "") for key in CONTRACT_ENV_KEYS}
    metadata["CONTRACT_NETWORK"] = args.network
    metadata["CONTRACT_REGISTRY_OBJECT_ID"] = parse_registry_object_id(completed.stdout)
    write_contract_env(args.network, metadata)


def cmd_destroy(args: argparse.Namespace) -> None:
    if args.provider == "all":
        for provider in PROVIDER_CHOICES:
            env = build_env(provider)
            terraform_destroy(provider, args, env)
            cleanup_provider_artifacts(provider)
        return
    else:
        env = build_env(args.provider)
        terraform_destroy(args.provider, args, env)
        cleanup_provider_artifacts(args.provider)


def cmd_inventory(args: argparse.Namespace) -> None:
    env = build_env(args.provider)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    print(inventory_path)


def main() -> int:
    args = parse_args()
    try:
        args.func(args)
    except subprocess.CalledProcessError as exc:
        print(
            f"Command failed with exit code {exc.returncode}: {shlex.join(exc.cmd)}",
            file=sys.stderr,
        )
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
