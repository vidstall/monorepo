from __future__ import annotations

from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .config import TOPOLOGY_PATH


def load_topology() -> dict[str, Any]:
    if not TOPOLOGY_PATH.exists():
        return {
            "active_env": "devnet",
            "contract_env": "runtime/contract/devnet.env",
            "instances": [],
            "objects": [],
        }
    data = tomllib.loads(TOPOLOGY_PATH.read_text(encoding="utf-8"))
    data.setdefault("objects", [])
    return data
