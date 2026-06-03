#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
IMAGE_ARTIFACT_DIR = ARTIFACTS_DIR / "image"
IMAGE_MANIFEST = IMAGE_ARTIFACT_DIR / "manifest.json"
SSH_CONFIG_DIR = ARTIFACTS_DIR / "ssh_config"
PACKER_DIR = REPO_ROOT / "IaC" / "packer"
TERRAFORM_ENV_DIR = REPO_ROOT / "IaC" / "terraform" / "environments"
ANSIBLE_PLAYBOOK = REPO_ROOT / "IaC" / "ansible" / "playbooks" / "site.yml"

PROVIDER_CHOICES = ("aws", "digital-ocean", "hetzner", "alibaba-cloud")
ROLE_CHOICES = ("worker", "client", "stateful")
ROLE_ALIASES = {
    "worker": "worker",
    "client": "client",
    "stateful": "stateful",
    "livekit": "worker",
    "meet": "client",
}
PROVIDER_ENV_FILES = {
    "aws": "aws.env",
    "digital-ocean": "digital-ocean.env",
    "hetzner": "hetzner.env",
    "alibaba-cloud": "alibaba-cloud.env",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vidctl.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build cloud-native images with Packer")
    build.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    build.add_argument(
        "--role",
        default="all",
        choices=("all", *ROLE_ALIASES.keys()),
        help="Build all roles or a single role.",
    )
    build.add_argument("--testbed-name", default="depin-testbed")
    build.set_defaults(func=cmd_build)

    deploy = subparsers.add_parser("deploy", help="Build images, apply Terraform, then run Ansible")
    deploy.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    deploy.add_argument("--testbed-name", default="depin-testbed")
    deploy.add_argument("--node-registry-contract-id", default=None)
    deploy.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    deploy.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    deploy.add_argument("--stateful-nodes", type=int, default=1)
    deploy.set_defaults(func=cmd_deploy)

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
    destroy.add_argument("--stateful-nodes", type=int, default=1)
    destroy.add_argument("--auto-approve", action="store_true", default=True)
    destroy.set_defaults(func=cmd_destroy)

    inventory = subparsers.add_parser("inventory", help="Render a transient Ansible inventory from Terraform output")
    inventory.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    inventory.add_argument("--testbed-name", default="depin-testbed")
    inventory.add_argument("--node-registry-contract-id", default=None)
    inventory.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    inventory.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    inventory.add_argument("--stateful-nodes", type=int, default=1)
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


def ensure_runtime_dirs() -> None:
    IMAGE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    SSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def provider_packer_template(provider: str) -> Path:
    return PACKER_DIR / f"{provider}.pkr.hcl"


def provider_terraform_root(provider: str) -> Path:
    return TERRAFORM_ENV_DIR / provider


def canonical_role(role: str) -> str:
    if role == "all":
        return role
    try:
        return ROLE_ALIASES[role]
    except KeyError as exc:
        raise SystemExit(f"Unsupported role: {role}") from exc


def run_command(args: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> None:
    print(f"+ {shlex.join(args)}", flush=True)
    subprocess.run(args, cwd=str(cwd), env=dict(env), check=True)


def validate_manifest(expected_roles: Iterable[str]) -> None:
    if not IMAGE_MANIFEST.exists():
        raise SystemExit(f"Missing manifest: {IMAGE_MANIFEST}")

    manifest = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    found_roles = set()
    for build in manifest.get("builds", []):
        name = build.get("name", "")
        if "." in name:
            found_roles.add(name.rsplit(".", 1)[-1])

    missing = set(expected_roles) - found_roles
    if missing:
        raise SystemExit(
            "Manifest does not include the expected roles: "
            + ", ".join(sorted(missing))
        )


def packer_build(provider: str, role: str, testbed_name: str) -> None:
    ensure_runtime_dirs()
    env = build_env(provider)
    env["PKR_VAR_testbed_name"] = testbed_name
    env["PKR_VAR_artifacts_dir"] = str(ARTIFACTS_DIR.resolve())

    template = provider_packer_template(provider)
    if not template.exists():
        raise SystemExit(f"Missing Packer template: {template}")

    run_command(["packer", "init", "."], cwd=PACKER_DIR, env=env)

    args: List[str] = ["packer", "build", "-force"]
    if role != "all":
        args.extend(["-only", f"*.{role}"])
    args.append(".")

    run_command(args, cwd=PACKER_DIR, env=env)

    expected_roles = ROLE_CHOICES if role == "all" else [role]
    validate_manifest(expected_roles)


def terraform_args(
    *,
    testbed_name: str,
    worker_nodes: int,
    client_nodes: int,
    stateful_nodes: int,
    node_registry_contract_id: str | None,
) -> List[str]:
    args = [
        "-input=false",
        f"-var=testbed_name={testbed_name}",
        f"-var=worker_count={worker_nodes}",
        f"-var=client_count={client_nodes}",
        f"-var=stateful_count={stateful_nodes}",
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
                stateful_nodes=args.stateful_nodes,
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
                stateful_nodes=args.stateful_nodes,
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
    run_command(["ansible-playbook", "-i", str(inventory_path), str(ANSIBLE_PLAYBOOK)], cwd=REPO_ROOT, env=env)


def cleanup_provider_artifacts(provider: str) -> None:
    for suffix in ("-inventory.ini", "-id_ed25519"):
        target = SSH_CONFIG_DIR / f"{provider}{suffix}"
        target.unlink(missing_ok=True)


def cleanup_global_artifacts() -> None:
    IMAGE_MANIFEST.unlink(missing_ok=True)


def cmd_build(args: argparse.Namespace) -> None:
    role = canonical_role(args.role)
    packer_build(args.provider, role, args.testbed_name)


def cmd_deploy(args: argparse.Namespace) -> None:
    env = build_env(args.provider)
    packer_build(args.provider, "all", args.testbed_name)
    terraform_apply(args.provider, args, env)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    ansible_playbook(inventory_path, env)


def cmd_destroy(args: argparse.Namespace) -> None:
    if args.provider == "all":
        for provider in PROVIDER_CHOICES:
            env = build_env(provider)
            terraform_destroy(provider, args, env)
            cleanup_provider_artifacts(provider)
    else:
        env = build_env(args.provider)
        terraform_destroy(args.provider, args, env)
        cleanup_provider_artifacts(args.provider)
    cleanup_global_artifacts()


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
