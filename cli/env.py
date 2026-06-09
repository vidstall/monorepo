from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

from cli.config import CONTRACT_ENV_DIR, CONTRACT_ENV_FILE, PROVIDER_ENV_FILES, REPO_ROOT


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
