from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import tomllib

from .context import CONTRACT_DIR, contract_env_path, run, write_kv_env_file

SUI_COIN_TYPE = "0x2::sui::SUI"
PUBLISHED_TOML = CONTRACT_DIR / "Published.toml"


def build(env: str) -> int:
    return run(["sui", "move", "--build-env", env, "build", "--path", CONTRACT_DIR])


def test(env: str) -> int:
    return run(["sui", "move", "--build-env", env, "test", "--path", CONTRACT_DIR])


def check(env: str) -> int:
    code = build(env)
    if code != 0:
        return code
    return test(env)


def publish(env: str, dry_run: bool, yes: bool, gas_budget: str | None) -> int:
    if not dry_run and not yes:
        print("Refusing to publish contract without --dry-run or --yes.", file=sys.stderr)
        return 2

    preview = test_publish(env, gas_budget)
    if preview is None:
        return 1

    if dry_run:
        return 0

    publish_code, publish_result, publish_error = run_sui_json(
        [
            "sui",
            "client",
            "publish",
            CONTRACT_DIR,
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
        ]
    )

    published_metadata = None
    if publish_result is None and publish_error and "already published" in publish_error.lower():
        published_metadata = load_published_metadata(env)

    if publish_result is None and published_metadata is None:
        if publish_error:
            sys.stderr.write(publish_error)
        return publish_code or 1

    package_id = (
        parse_published_package_id(publish_result)
        if publish_result
        else (published_metadata or {}).get("published-at")
    )
    upgrade_cap_id = (
        parse_upgrade_cap_id(publish_result)
        if publish_result
        else (published_metadata or {}).get("upgrade-capability")
    )
    deployer_address = parse_sender(publish_result) if publish_result else None
    publish_tx_digest = parse_transaction_digest(publish_result) if publish_result else None

    if not package_id:
        print("Could not determine published package ID.", file=sys.stderr)
        return 1

    registry_code, registry_result, registry_error = run_sui_json(
        [
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
            SUI_COIN_TYPE,
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
        ]
    )
    if registry_result is None:
        if registry_error:
            sys.stderr.write(registry_error)
        return registry_code or 1

    registry_object_id = parse_created_object_id(registry_result, "Registry<")
    if not registry_object_id:
        print("Could not determine registry object ID.", file=sys.stderr)
        return 1

    write_kv_env_file(
        contract_env_path(env),
        {
            "CONTRACT_NETWORK": env,
            "CONTRACT_PACKAGE_ID": package_id,
            "CONTRACT_REGISTRY_OBJECT_ID": registry_object_id,
            "CONTRACT_UPGRADE_CAP_ID": upgrade_cap_id or "",
            "CONTRACT_DEPLOYER_ADDRESS": deployer_address or "",
            "CONTRACT_PUBLISH_TX_DIGEST": publish_tx_digest or "",
        },
    )
    return 0


def test_publish(env: str, gas_budget: str | None) -> dict | None:
    pubfile_path = str(Path(tempfile.gettempdir()) / f"vidctl-contract-{os.getpid()}.toml")
    try:
        os.unlink(pubfile_path)
    except FileNotFoundError:
        pass
    _code, result, error = run_sui_json(
        [
            "sui",
            "client",
            "test-publish",
            CONTRACT_DIR,
            "--build-env",
            env,
            "--pubfile-path",
            pubfile_path,
            "--dry-run",
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
        ]
    )
    try:
        os.unlink(pubfile_path)
    except FileNotFoundError:
        pass
    if result is None and error:
        sys.stderr.write(error)
    return result


def run_sui_json(args: list[str]) -> tuple[int, dict | None, str]:
    completed = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, check=False)
    output = f"{completed.stdout}{completed.stderr}"
    payload = parse_json_payload(output) if output else None
    return completed.returncode, payload, output


def parse_json_payload(output: str) -> dict | None:
    decoder = json.JSONDecoder()
    best: tuple[int, dict] | None = None
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        score = end
        if "objectChanges" in value:
            score += len(output)
        if "effects" in value:
            score += len(output)
        if best is None or score > best[0]:
            best = (score, value)
    return best[1] if best else None


def load_published_metadata(network: str) -> dict | None:
    if not PUBLISHED_TOML.exists():
        return None
    data = tomllib.loads(PUBLISHED_TOML.read_text())
    return find_network_metadata(data, network)


def find_network_metadata(node: object, network: str) -> dict | None:
    if isinstance(node, dict):
        if network in node and isinstance(node[network], dict):
            return node[network]
        for value in node.values():
            found = find_network_metadata(value, network)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_network_metadata(value, network)
            if found is not None:
                return found
    return None


def parse_published_package_id(payload: dict) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "published":
            return change.get("packageId")
    return None


def parse_upgrade_cap_id(payload: dict) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "created" and str(change.get("objectType", "")).endswith("UpgradeCap"):
            return change.get("objectId")
    return None


def parse_created_object_id(payload: dict, type_fragment: str) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "created" and type_fragment in str(change.get("objectType", "")):
            return change.get("objectId")
    return None


def parse_sender(payload: dict) -> str | None:
    input_payload = payload.get("input", {})
    if isinstance(input_payload, dict):
        return input_payload.get("sender")
    return None


def parse_transaction_digest(payload: dict) -> str | None:
    effects = payload.get("effects", {})
    if isinstance(effects, dict):
        return effects.get("transactionDigest")
    return None
