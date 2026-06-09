from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Mapping

from cli.config import ANSIBLE_PLAYBOOK, PROVIDER_CHOICES, SSH_CONFIG_DIR, TERRAFORM_ENV_DIR
from cli.env import build_env
from cli.process import run_command


def ensure_runtime_dirs() -> None:
    SSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def provider_terraform_root(provider: str) -> Path:
    return TERRAFORM_ENV_DIR / provider


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
    inventory_path.write_text(str(inventory_data), encoding="utf-8")
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
    ensure_runtime_dirs()
    env = build_env(args.provider)
    terraform_apply(args.provider, args, env)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    ansible_playbook(inventory_path, env)


def cmd_destroy(args: argparse.Namespace) -> None:
    ensure_runtime_dirs()
    if args.provider == "all":
        for provider in PROVIDER_CHOICES:
            env = build_env(provider)
            terraform_destroy(provider, args, env)
            cleanup_provider_artifacts(provider)
        return

    env = build_env(args.provider)
    terraform_destroy(args.provider, args, env)
    cleanup_provider_artifacts(args.provider)


def cmd_inventory(args: argparse.Namespace) -> None:
    ensure_runtime_dirs()
    env = build_env(args.provider)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    print(inventory_path)
