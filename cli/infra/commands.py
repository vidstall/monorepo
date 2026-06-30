from __future__ import annotations

import argparse
import subprocess
from typing import Iterable

from cli.config import PROVIDER_CHOICES, SSH_CONFIG_DIR
from cli.env import build_contract_env, build_env
from cli.infra.inventory import (
    _update_env_file,
    ansible_playbook,
    normalize_role_hosts,
    render_ansible_vars,
    render_inventory,
    require_runtime_env,
)
from cli.infra.terraform import (
    provider_terraform_root,
    purge_terraform_state,
    terraform_apply,
    terraform_destroy,
    terraform_output,
    terraform_value,
)

SSH_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


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

    try:
        if getattr(args, "deploy_contract", False):
            from cli.contract import cmd_deploy_contract

            contract_network = getattr(args, "contract_network", "devnet")
            from cli.config import CONTRACT_PACKAGE_PATH
            contract_args = argparse.Namespace(
                network=contract_network,
                package_path=CONTRACT_PACKAGE_PATH,
                gas_budget=1_000_000_000,
                gas_coins=[],
            )
            cmd_deploy_contract(contract_args)
            env = build_env(args.provider)

        if getattr(args, "client_oss", False) and getattr(args, "oss_bucket", None):
            from cli.oss import cmd_oss_init, cmd_oss_deploy
            cmd_oss_init(args)
            cmd_oss_deploy(args)
            env = build_env(args.provider)

        outputs = terraform_output(args.provider, env)
        inventory_path = render_inventory(args.provider, outputs)
        vars_path = render_ansible_vars(
            args.provider, outputs, env, args.node_registry_contract_id,
            client_oss=getattr(args, "client_oss", False),
        )
        ansible_playbook(inventory_path, vars_path, env)

        contract_network = getattr(args, "contract_network", "devnet")
        contract_env = build_contract_env(contract_network)
        pkg_id = contract_env.get("CONTRACT_PACKAGE_ID", "").strip()
        reg_id = contract_env.get("CONTRACT_REGISTRY_OBJECT_ID", "").strip()
        if pkg_id and reg_id:
            inv_data = terraform_value(outputs, "inventory")
            dist_hosts = normalize_role_hosts(inv_data, "dist")
            if dist_hosts:
                dist_ip = dist_hosts[0]["ansible_host"]
                from cli.contract import cmd_set_coordinator_endpoint
                cmd_set_coordinator_endpoint(contract_network, pkg_id, reg_id, f"http://{dist_ip}/api")
    except Exception as exc:
        print(f"\n[atomic] step failed — purging infrastructure to avoid partial state...")
        try:
            cmd_purge(args)
        except Exception as purge_exc:
            print(f"[atomic] purge also failed: {purge_exc}")
        raise


def cmd_inventory(args: argparse.Namespace) -> None:
    env = build_env(args.provider)
    outputs = terraform_output(args.provider, env)
    inventory_path = render_inventory(args.provider, outputs)
    print(inventory_path)


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
            from cli.registry.commands import destroy_registry
            destroy_registry(provider, env)
        except subprocess.CalledProcessError:
            print(f"  registry destroy failed for {provider}, cleaning up anyway")
        print("Destroying OSS bucket (if configured)...")
        try:
            from cli.oss import cmd_oss_purge
            oss_args = argparse.Namespace(provider=provider, oss_bucket=None)
            cmd_oss_purge(oss_args)
        except Exception as oss_exc:
            print(f"  OSS purge skipped: {oss_exc}")
        print("Cleaning artifacts...")
        cleanup_provider_artifacts(provider)
        print("Cleaning Terraform local state...")
        purge_terraform_state(provider_terraform_root(provider))
        print(f"  {provider} purged")
