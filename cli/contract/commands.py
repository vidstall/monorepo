from __future__ import annotations

import argparse
import shlex
import subprocess

from cli.config import CONTRACT_ENV_DIR, REPO_ROOT
from cli.contract.display import _load_wallet_addresses, _print_contract_status, _print_wallet_status
from cli.contract.io import (
    parse_publish_metadata,
    parse_registry_object_id,
    parse_upgrade_metadata,
    write_contract_env,
)
from cli.contract.toml import (
    _clear_published_toml_entry,
    _sync_move_toml_chain_id,
    merge_published_fallback,
)
from cli.env import build_contract_env
from cli.process import run_command


def cmd_contract_status(args: argparse.Namespace) -> None:
    networks = [args.network] if args.network else ("devnet", "testnet", "mainnet")
    for index, network in enumerate(networks):
        if index:
            print()
        _print_contract_status(network)


def cmd_contract_wallet(args: argparse.Namespace) -> None:
    active_address, addresses = _load_wallet_addresses()
    networks = [args.network] if args.network else ("devnet", "testnet", "mainnet")
    for index, network in enumerate(networks):
        if index:
            print()
        _print_wallet_status(network, active_address, addresses)


def cmd_set_coordinator_endpoint(network: str, package_id: str, registry_id: str, endpoint: str) -> None:
    env = build_contract_env(network)
    endpoint_hex = "0x" + endpoint.encode().hex()
    run_command(
        [
            "sui", "client", "call",
            "--package", package_id,
            "--module", "node_registry",
            "--function", "set_coordinator_endpoint",
            "--args", registry_id, endpoint_hex,
            "--gas-budget", "100000000",
        ],
        cwd=REPO_ROOT,
        env=env,
    )
    print(f"coordinator_endpoint set on-chain → {endpoint}")


def cmd_deploy_contract(args: argparse.Namespace) -> None:
    if not args.package_path.exists():
        raise SystemExit(f"Missing contract package path: {args.package_path}")

    env = build_contract_env(args.network)

    if env.get("CONTRACT_PACKAGE_ID") and not getattr(args, "force", False):
        print(f"Contract already published to {args.network} (package {env['CONTRACT_PACKAGE_ID']}). Skipping publish.")
        _init_contract(args)
        return
    if env.get("CONTRACT_PACKAGE_ID") and getattr(args, "force", False):
        print(f"--force: re-publishing contract on {args.network} (clearing existing package {env['CONTRACT_PACKAGE_ID']}).")
    print(f"Switching Sui CLI to {args.network}...")
    run_command(["sui", "client", "switch", "--env", args.network], cwd=REPO_ROOT, env=env)

    _sync_move_toml_chain_id(args.package_path, args.network)
    if getattr(args, "force", False):
        _clear_published_toml_entry(args.package_path, args.network)

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
    print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="")
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
    _init_contract(args)


def cmd_update_contract(args: argparse.Namespace) -> None:
    if not args.package_path.exists():
        raise SystemExit(f"Missing contract package path: {args.package_path}")

    env = build_contract_env(args.network)
    metadata = merge_published_fallback(env, args.package_path, args.network)
    package_id = metadata.get("CONTRACT_PACKAGE_ID")
    upgrade_cap_id = metadata.get("CONTRACT_UPGRADE_CAP_ID")
    if not package_id:
        raise SystemExit(
            f"Missing CONTRACT_PACKAGE_ID in {CONTRACT_ENV_DIR / f'{args.network}.env'}; "
            "run contract deploy first."
        )
    if not upgrade_cap_id:
        raise SystemExit(
            f"Missing CONTRACT_UPGRADE_CAP_ID in {CONTRACT_ENV_DIR / f'{args.network}.env'}; "
            "cannot upgrade without the package UpgradeCap."
        )

    print(f"Switching Sui CLI to {args.network}...")
    run_command(["sui", "client", "switch", "--env", args.network], cwd=REPO_ROOT, env=env)

    print(f"Building Move package at {args.package_path} for {args.network}...")
    run_command(
        ["sui", "move", "build", "--path", str(args.package_path), "--build-env", args.network],
        cwd=REPO_ROOT,
        env=env,
    )

    print(f"Upgrading contract package {package_id} on {args.network}...")
    upgrade_args = [
        "sui", "client", "upgrade",
        "--upgrade-capability", upgrade_cap_id,
        "--gas-budget", str(args.gas_budget),
    ]
    if args.skip_verify_compatibility:
        upgrade_args.append("--skip-verify-compatibility")
    if args.gas_coins:
        upgrade_args.extend(["--gas", *args.gas_coins])
    upgrade_args.append(str(args.package_path))

    print(f"+ {shlex.join(upgrade_args)}", flush=True)
    completed = subprocess.run(
        upgrade_args,
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
            upgrade_args,
            output=completed.stdout,
            stderr=completed.stderr,
        )

    metadata["CONTRACT_NETWORK"] = args.network
    metadata["CONTRACT_PREVIOUS_PACKAGE_ID"] = package_id
    metadata.update(parse_upgrade_metadata(completed.stdout))
    write_contract_env(args.network, metadata)


def _init_contract(args: argparse.Namespace) -> None:
    env = build_contract_env(args.network)

    if env.get("CONTRACT_REGISTRY_OBJECT_ID") and not getattr(args, "force", False):
        print(f"Registry already initialized on {args.network} (object {env['CONTRACT_REGISTRY_OBJECT_ID']}). Skipping init.")
        return
    if env.get("CONTRACT_REGISTRY_OBJECT_ID") and getattr(args, "force", False):
        print(f"--force: re-initializing registry on {args.network} (replacing {env['CONTRACT_REGISTRY_OBJECT_ID']}).")

    metadata = merge_published_fallback(env, args.package_path, args.network)
    package_id = metadata.get("CONTRACT_PACKAGE_ID")
    if not package_id:
        raise SystemExit(
            f"Missing CONTRACT_PACKAGE_ID in {CONTRACT_ENV_DIR / f'{args.network}.env'}; "
            "run contract deploy first or keep Published.toml in the package path."
        )

    print(f"Switching Sui CLI to {args.network}...")
    run_command(["sui", "client", "switch", "--env", args.network], cwd=REPO_ROOT, env=env)

    print(f"Creating shared Registry<0x2::sui::SUI> for package {package_id}...")
    call_args = [
        "sui", "client", "call",
        "--package", package_id,
        "--module", "node_registry",
        "--function", "create_registry",
        "--type-args", "0x2::sui::SUI",
        "--gas-budget", str(args.gas_budget),
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

    metadata["CONTRACT_NETWORK"] = args.network
    metadata["CONTRACT_REGISTRY_OBJECT_ID"] = parse_registry_object_id(completed.stdout)
    write_contract_env(args.network, metadata)
