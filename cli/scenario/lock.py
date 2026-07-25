from __future__ import annotations

import sys
from typing import Any

import tomllib

from .. import infra


def read_lock() -> dict[str, Any] | None:
    # Deferred self-import: RUNTIME_SCENARIO_LOCK is patched by tests as a
    # flat cli.scenario attribute -- looking it up through the package at
    # call time is what makes that patch take effect here.
    from .. import scenario

    if not scenario.RUNTIME_SCENARIO_LOCK.exists():
        return None
    return tomllib.loads(scenario.RUNTIME_SCENARIO_LOCK.read_text(encoding="utf-8"))


def write_lock(scenario_path: str, scenario_hash: str, env: str, status: str) -> None:
    from .. import scenario

    scenario.RUNTIME_SCENARIO_LOCK.parent.mkdir(parents=True, exist_ok=True)
    existing = read_lock()
    # Preserve the original applied_at across a same-scenario (same path)
    # re-apply (drift reconcile) so `status` can show "held since"; a
    # genuinely new scenario (different path) gets a fresh applied_at.
    applied_at = (
        existing["applied_at"]
        if existing and existing.get("scenario_path") == scenario_path and existing.get("applied_at")
        else infra.timestamp()
    )
    lines = [
        f"scenario_path = {infra.toml_value(scenario_path)}",
        f"scenario_hash = {infra.toml_value(scenario_hash)}",
        f"env = {infra.toml_value(env)}",
        f"status = {infra.toml_value(status)}",
        f"applied_at = {infra.toml_value(applied_at)}",
        f"updated_at = {infra.toml_value(infra.timestamp())}",
        "",
    ]
    scenario.RUNTIME_SCENARIO_LOCK.write_text("\n".join(lines), encoding="utf-8")


def clear_lock() -> None:
    from .. import scenario

    scenario.RUNTIME_SCENARIO_LOCK.unlink(missing_ok=True)


def guard_manual_infra(action: str) -> int | None:
    """Called from cli/vidctl.py's infra handlers only -- the scenario runner
    itself calls infra.control()/contract.publish()/registry.publish()
    directly as plain Python calls, never through those CLI handlers, so it
    never hits this guard."""
    lock = read_lock()
    if lock is None or lock.get("status") not in {"active", "applying"}:
        return None
    print(
        f"Refusing manual 'vidctl infra {action}': scenario '{lock.get('scenario_path')}' "
        f"currently owns the infra (status={lock.get('status')}). Run 'vidctl scenario status' "
        "to inspect it, or 'vidctl scenario destroy' to release it before using manual infra commands.",
        file=sys.stderr,
    )
    return 3
