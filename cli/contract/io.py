from __future__ import annotations

import re
from pathlib import Path
from typing import Dict

from cli.config import CONTRACT_ENV_DIR, CONTRACT_ENV_KEYS


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
        if "Created Objects:" in stripped:
            in_created_objects = True
            in_published_objects = False
            in_gas_object = False
            current_object_id = None
            continue
        if "Mutated Objects:" in stripped:
            in_created_objects = False
            in_published_objects = False
            current_object_id = None
            continue
        if "Published Objects:" in stripped:
            in_created_objects = False
            in_published_objects = True
            in_gas_object = False
            current_object_id = None
            continue
        if "Gas Object:" in stripped:
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


def write_contract_env(network: str, metadata: dict) -> None:
    contract_env_file = CONTRACT_ENV_DIR / f"{network}.env"
    contract_env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={metadata.get(key, '')}" for key in CONTRACT_ENV_KEYS]
    lines.insert(0, f"# Auto-generated by `vidctl.py contract deploy --network {network}`")
    contract_env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote contract metadata to {contract_env_file}")
