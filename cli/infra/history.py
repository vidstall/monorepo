from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def record_history(
    command: str,
    env: str = "",
    name: str = "",
    service: str = "",
    provider: str = "",
    resource_id: str = "",
    previous_status: str = "",
    next_status: str = "",
    result: str | None = None,
    exit_code: int | None = None,
    result_for_code: int | None = None,
    error: str = "",
) -> None:
    # Deferred self-import: RUNTIME_HISTORY_TOML is patched by tests as a
    # flat cli.infra attribute (patch.object(infra, "RUNTIME_HISTORY_TOML",
    # ...)) -- looking it up through the package at call time is what makes
    # that patch actually take effect here.
    from .. import infra

    if result_for_code is not None:
        exit_code = result_for_code
        result = "success" if result_for_code == 0 else "failure"
    if result is None:
        result = "success"
    if exit_code is None:
        exit_code = 0 if result == "success" else 1
    event = {
        "timestamp": timestamp(),
        "command": command,
        "env": env,
        "name": name,
        "service": service,
        "provider": provider,
        "resource_id": resource_id,
        "previous_status": previous_status,
        "next_status": next_status,
        "result": result,
        "exit_code": exit_code,
        "error": error,
    }
    infra.RUNTIME_HISTORY_TOML.parent.mkdir(parents=True, exist_ok=True)
    with infra.RUNTIME_HISTORY_TOML.open("a", encoding="utf-8") as history:
        history.write("[[events]]\n")
        for key, value in event.items():
            history.write(f"{key} = {toml_value(value)}\n")
        history.write("\n")


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if value is None:
        return '""'
    return json.dumps(str(value))
