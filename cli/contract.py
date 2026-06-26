from __future__ import annotations

import argparse
import re
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Mapping

from cli.config import CONTRACT_ENV_DIR, CONTRACT_ENV_KEYS, REPO_ROOT
from cli.env import build_contract_env
from cli.process import run_command


def parse_simple_toml_value(value: str) -> str:
    value = value.strip()
    if value and value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    return value


def load_published_metadata(package_path: Path, network: str) -> Dict[str, str]:
    published_file = package_path / "Published.toml"
    if not published_file.exists():
        return {}

    section = f"published.{network}"
    in_section = False
    values: Dict[str, str] = {}

    for raw_line in published_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip() == section
            continue
        if not in_section or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = parse_simple_toml_value(value)

    metadata: Dict[str, str] = {}
    if published_at := values.get("published-at"):
        metadata["CONTRACT_PACKAGE_ID"] = published_at
    if upgrade_capability := values.get("upgrade-capability"):
        metadata["CONTRACT_UPGRADE_CAP_ID"] = upgrade_capability
    return metadata


def merge_published_fallback(env: Mapping[str, str], package_path: Path, network: str) -> Dict[str, str]:
    metadata = {key: env.get(key, "") for key in CONTRACT_ENV_KEYS}
    for key, value in load_published_metadata(package_path, network).items():
        if not metadata.get(key):
            metadata[key] = value
    metadata["CONTRACT_NETWORK"] = network
    return metadata


def parse_publish_metadata(output: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    patterns = {
        "CONTRACT_PUBLISH_TX_DIGEST": r"Transaction Digest:\s+(\S+)",
        "CONTRACT_DEPLOYER_ADDRESS": r"Sender:\s+(\S+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            result[key] = match.group(1)

    in_created_objects = False
    in_published_objects = False
    in_gas_object = False
    current_object_id: str | None = None
    upgrade_cap_id: str | None = None
    gas_object_id: str | None = None
    gas_object_version: str | None = None
    gas_object_digest: str | None = None

    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "Created Objects:":
            in_created_objects = True
            in_published_objects = False
            in_gas_object = False
            current_object_id = None
            continue
        if stripped == "Published Objects:":
            in_created_objects = False
            in_published_objects = True
            in_gas_object = False
            current_object_id = None
            continue
        if stripped == "Gas Object:":
            in_created_objects = False
            in_published_objects = False
            in_gas_object = True
            current_object_id = None
            continue

        object_match = re.search(r"\b(?:ObjectID|ID):\s+(0x[0-9a-fA-F]+)", stripped)
        if object_match:
            current_object_id = object_match.group(1)
            if in_gas_object:
                gas_object_id = current_object_id
            continue

        if "ObjectType:" in stripped and "::package::UpgradeCap" in stripped and current_object_id:
            upgrade_cap_id = current_object_id
            result["CONTRACT_UPGRADE_CAP_ID"] = upgrade_cap_id
            continue

        package_match = re.search(r"\bPackageID:\s+(0x[0-9a-fA-F]+)", stripped)
        if in_published_objects and package_match:
            result["CONTRACT_PACKAGE_ID"] = package_match.group(1)
            continue

        version_match = re.search(r"\bVersion:\s+(\d+)", stripped)
        if in_gas_object and version_match:
            gas_object_version = version_match.group(1)
            continue
        digest_match = re.search(r"\bDigest:\s+(\S+)", stripped)
        if in_gas_object and digest_match:
            gas_object_digest = digest_match.group(1)
            continue

    if upgrade_cap_id is not None:
        result["CONTRACT_UPGRADE_CAP_ID"] = upgrade_cap_id
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
        object_match = re.search(r"\b(?:ObjectID|ID):\s+(0x[0-9a-fA-F]+)", line)
        if object_match:
            current_object_id = object_match.group(1)
            if fallback_object_id is None:
                fallback_object_id = current_object_id
        elif "ObjectType:" in line and "::node_registry::Registry<" in line and current_object_id:
            return current_object_id

    if fallback_object_id:
        return fallback_object_id
    raise SystemExit("Could not parse registry object ID from Sui output")


def parse_upgrade_metadata(output: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    digest_match = re.search(r"Transaction Digest:\s+(\S+)", output)
    sender_match = re.search(r"Sender:\s+(\S+)", output)
    package_match = re.search(r"PackageID:\s+(\S+)", output)
    if digest_match:
        result["CONTRACT_UPDATE_TX_DIGEST"] = digest_match.group(1)
    if sender_match:
        result["CONTRACT_DEPLOYER_ADDRESS"] = sender_match.group(1)
    if package_match:
        result["CONTRACT_PACKAGE_ID"] = package_match.group(1)

    in_published_objects = False
    in_gas_object = False
    current_object_id: str | None = None
    gas_object_id: str | None = None
    gas_object_version: str | None = None
    gas_object_digest: str | None = None

    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "Published Objects:":
            in_published_objects = True
            in_gas_object = False
            current_object_id = None
            continue
        if stripped == "Gas Object:":
            in_published_objects = False
            in_gas_object = True
            current_object_id = None
            continue

        object_match = re.search(r"\b(?:ObjectID|ID):\s+(0x[0-9a-fA-F]+)", stripped)
        if object_match:
            current_object_id = object_match.group(1)
            if in_gas_object:
                gas_object_id = current_object_id
            continue

        package_match = re.search(r"\bPackageID:\s+(0x[0-9a-fA-F]+)", stripped)
        if in_published_objects and package_match:
            result["CONTRACT_PACKAGE_ID"] = package_match.group(1)
            continue

        version_match = re.search(r"\bVersion:\s+(\d+)", stripped)
        if in_gas_object and version_match:
            gas_object_version = version_match.group(1)
            continue
        digest_match = re.search(r"\bDigest:\s+(\S+)", stripped)
        if in_gas_object and digest_match:
            gas_object_digest = digest_match.group(1)
            continue

    if gas_object_id is not None:
        result["CONTRACT_GAS_OBJECT_ID"] = gas_object_id
    if gas_object_version is not None:
        result["CONTRACT_GAS_OBJECT_VERSION"] = gas_object_version
    if gas_object_digest is not None:
        result["CONTRACT_GAS_OBJECT_DIGEST"] = gas_object_digest

    required = ("CONTRACT_PACKAGE_ID", "CONTRACT_UPDATE_TX_DIGEST")
    missing = [key for key in required if key not in result]
    if missing:
        raise SystemExit(f"Could not parse upgrade metadata from Sui output: {', '.join(missing)}")
    return result


def write_contract_env(network: str, metadata: Mapping[str, str]) -> None:
    contract_env_file = CONTRACT_ENV_DIR / f"{network}.env"
    contract_env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={metadata.get(key, '')}" for key in CONTRACT_ENV_KEYS]
    lines.insert(0, f"# Auto-generated by `vidctl.py deploy-contract --network {network}`")
    contract_env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote contract metadata to {contract_env_file}")


def cmd_deploy_contract(args: argparse.Namespace) -> None:
    if not args.package_path.exists():
        raise SystemExit(f"Missing contract package path: {args.package_path}")

    env = build_contract_env(args.network)

    if env.get("CONTRACT_PACKAGE_ID"):
        print(f"Contract already published to {args.network} (package {env['CONTRACT_PACKAGE_ID']}). Skipping publish.")
        return
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
            "run deploy-contract first."
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
        "sui",
        "client",
        "upgrade",
        "--upgrade-capability",
        upgrade_cap_id,
        "--gas-budget",
        str(args.gas_budget),
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


def cmd_init_contract(args: argparse.Namespace) -> None:
    env = build_contract_env(args.network)

    if env.get("CONTRACT_REGISTRY_OBJECT_ID"):
        print(f"Registry already initialized on {args.network} (object {env['CONTRACT_REGISTRY_OBJECT_ID']}). Skipping init.")
        return

    metadata = merge_published_fallback(env, args.package_path, args.network)
    package_id = metadata.get("CONTRACT_PACKAGE_ID")
    if not package_id:
        raise SystemExit(
            f"Missing CONTRACT_PACKAGE_ID in {CONTRACT_ENV_DIR / f'{args.network}.env'}; "
            "run deploy-contract first or keep Published.toml in the package path."
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

    metadata["CONTRACT_NETWORK"] = args.network
    metadata["CONTRACT_REGISTRY_OBJECT_ID"] = parse_registry_object_id(completed.stdout)
    write_contract_env(args.network, metadata)
