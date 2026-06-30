from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from cli.config import CONTRACT_ENV_DIR, CONTRACT_ENV_FILE, PROVIDER_ENV_FILES, REPO_ROOT


def update_env_file(path: Path, updates: Dict[str, str]) -> None:
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

RUNTIME_ENV_FILE = REPO_ROOT / "secrets" / "runtime.env"
DEFAULT_CONTRACT_NETWORK = "devnet"


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


def build_contract_env(network: str) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file(CONTRACT_ENV_FILE))
    env["CONTRACT_NETWORK"] = network
    env["SUI_NETWORK"] = network
    env.update(load_env_file(CONTRACT_ENV_DIR / f"{network}.env"))
    env["CONTRACT_NETWORK"] = network
    env["SUI_NETWORK"] = network
    return env


def build_env(provider: str) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(load_env_file(REPO_ROOT / "secrets" / "cloud" / PROVIDER_ENV_FILES[provider]))
    env.update(load_env_file(RUNTIME_ENV_FILE))

    configured_network = env.get("CONTRACT_NETWORK") or env.get("SUI_NETWORK")
    legacy_contract_env = load_env_file(CONTRACT_ENV_FILE)
    env.update(legacy_contract_env)
    contract_network = configured_network or env.get("CONTRACT_NETWORK") or env.get("SUI_NETWORK") or DEFAULT_CONTRACT_NETWORK
    env["CONTRACT_NETWORK"] = contract_network
    env["SUI_NETWORK"] = contract_network

    env.update(load_env_file(CONTRACT_ENV_DIR / f"{contract_network}.env"))

    contract_network = env.get("CONTRACT_NETWORK") or env.get("SUI_NETWORK") or DEFAULT_CONTRACT_NETWORK
    env["CONTRACT_NETWORK"] = contract_network
    env["SUI_NETWORK"] = contract_network
    return env
