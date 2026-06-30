from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Mapping

from cli.config import CONTRACT_ENV_KEYS


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _rpc_request_simple(network: str, method: str, params: list) -> dict:
    import json
    import urllib.request

    _SUI_RPC_URLS = {
        "devnet": "https://fullnode.devnet.sui.io:443",
        "testnet": "https://fullnode.testnet.sui.io:443",
        "mainnet": "https://fullnode.mainnet.sui.io:443",
    }
    rpc_url = _SUI_RPC_URLS[network]
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    request = urllib.request.Request(rpc_url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_chain_id(network: str) -> str | None:
    try:
        data = _rpc_request_simple(network, "sui_getChainIdentifier", [])
        return data.get("result")
    except Exception:
        return None


def _clear_published_toml_entry(package_path: Path, network: str) -> None:
    published_toml = package_path / "Published.toml"
    if not published_toml.exists():
        return

    target_section = f"[published.{network}]"
    lines = published_toml.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if stripped == target_section:
            skip = True
            continue
        if skip and stripped.startswith("["):
            skip = False
        if not skip:
            out.append(line)

    if len(out) != len(lines):
        published_toml.write_text("".join(out), encoding="utf-8")
        print(f"Cleared Published.toml [published.{network}] entry for re-publish.")


def _sync_move_toml_chain_id(package_path: Path, network: str) -> None:
    move_toml = package_path / "Move.toml"
    if not move_toml.exists():
        return

    chain_id = _fetch_chain_id(network)
    if not chain_id:
        return

    content = move_toml.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'^({re.escape(network)}\s*=\s*")[0-9a-fA-F]+(")$',
        re.MULTILINE,
    )
    match = pattern.search(content)
    if match:
        existing = match.group(0).split('"')[1]
        if existing == chain_id:
            return
        updated = pattern.sub(rf'\g<1>{chain_id}\g<2>', content)
        move_toml.write_text(updated, encoding="utf-8")
        print(f"Updated Move.toml {network} chain ID: {existing} → {chain_id}")
    else:
        if "[environments]" in content:
            updated = content.rstrip() + f'\n{network} = "{chain_id}"\n'
        else:
            updated = content.rstrip() + f'\n\n[environments]\n{network} = "{chain_id}"\n'
        move_toml.write_text(updated, encoding="utf-8")
        print(f"Added Move.toml {network} chain ID: {chain_id}")


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
