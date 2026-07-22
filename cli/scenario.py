from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import tomllib

from . import contract, infra, registry
from .context import ROOT, RUNTIME_SCENARIO_LOCK, contract_env_path

SCENARIO_DIR = ROOT / "scenario"

InstanceKey = tuple[str, str, str, str, int]


def load_scenario(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Scenario file not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    env = str(data.get("env", ""))
    if env not in infra.NETWORKS:
        raise ValueError(f"Scenario env must be one of {', '.join(infra.NETWORKS)}, got {env!r}.")

    raw_instances = data.get("instances", [])
    if not isinstance(raw_instances, list) or not raw_instances:
        raise ValueError("Scenario must declare at least one [[instances]] entry.")

    seen: set[InstanceKey] = set()
    instances: list[dict[str, Any]] = []
    for row in raw_instances:
        name = str(row.get("name", ""))
        service = str(row.get("service", ""))
        provider = str(row.get("provider", ""))
        instance_index = int(row.get("instance_index", 1) or 1)
        if not name:
            raise ValueError("Every scenario instance needs a 'name'.")
        if service not in infra.DOCKER_SERVICES:
            raise ValueError(f"Unknown service '{service}' for instance '{name}'.")
        if provider not in infra.PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' for instance '{name}'.")
        key: InstanceKey = (name, service, provider, env, instance_index)
        if key in seen:
            raise ValueError(
                f"Duplicate scenario instance: name={name} service={service} "
                f"provider={provider} instance_index={instance_index}."
            )
        seen.add(key)
        instances.append(
            {
                "name": name,
                "service": service,
                "provider": provider,
                "instance_index": instance_index,
                "size": row.get("size") or None,
            }
        )

    contract_opts = data.get("contract", {})
    contract_opts = contract_opts if isinstance(contract_opts, dict) else {}
    registry_opts = data.get("registry", {})
    registry_opts = registry_opts if isinstance(registry_opts, dict) else {}

    return {
        "name": str(data.get("name") or path.stem),
        "env": env,
        "contract": {
            "gas_budget": contract_opts.get("gas_budget") or None,
            "create_registry_if_missing": bool(contract_opts.get("create_registry_if_missing", False)),
            "force": bool(contract_opts.get("force", False)),
        },
        "registry": {
            "tag": registry_opts.get("tag") or None,
        },
        "instances": instances,
    }


def scenario_hash_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_lock() -> dict[str, Any] | None:
    if not RUNTIME_SCENARIO_LOCK.exists():
        return None
    return tomllib.loads(RUNTIME_SCENARIO_LOCK.read_text(encoding="utf-8"))


def write_lock(scenario_path: str, scenario_hash: str, env: str, status: str) -> None:
    RUNTIME_SCENARIO_LOCK.parent.mkdir(parents=True, exist_ok=True)
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
    RUNTIME_SCENARIO_LOCK.write_text("\n".join(lines), encoding="utf-8")


def clear_lock() -> None:
    RUNTIME_SCENARIO_LOCK.unlink(missing_ok=True)


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


def diff_instances(
    wanted: dict[InstanceKey, dict[str, Any]],
    current: dict[InstanceKey, dict[str, Any]],
) -> tuple[list[InstanceKey], list[InstanceKey]]:
    to_kill = sorted(current.keys() - wanted.keys())
    to_start = list(wanted.keys())
    return to_kill, to_start


def _topology_instance_key(item: dict[str, Any], default_env: str) -> InstanceKey:
    return (
        str(item.get("name")),
        str(item.get("service")),
        str(item.get("provider")),
        str(item.get("env", default_env)),
        int(item.get("instance_index", 1) or 1),
    )


def _active_instances_for_env(env: str) -> list[dict[str, Any]]:
    # ensure_topology (not read_topology) since topology.toml may not exist
    # yet on a first-ever `scenario apply` (normally created by `vidctl infra
    # init`, which a scenario apply doesn't require running first).
    topology = infra.ensure_topology(env)
    return [
        item
        for item in topology.get("instances", [])
        if item.get("env", env) == env and item.get("desired_state") != "deleted"
    ]


def apply(path_str: str, yes: bool) -> int:
    if not yes:
        print("Refusing to apply a scenario without --yes.", file=sys.stderr)
        return 2

    path = Path(path_str)
    try:
        scenario = load_scenario(path)
    except ValueError as exc:
        print(f"Invalid scenario file: {exc}", file=sys.stderr)
        return 2

    try:
        scenario_hash = scenario_hash_of(path)
    except OSError as exc:
        print(f"Unable to read scenario file: {exc}", file=sys.stderr)
        return 2

    # Identity is by resolved path, not content -- editing this exact file
    # and re-applying it is the intended drift-reconcile flow (the hash is
    # still recorded, purely for `status` to show whether the content
    # changed since the last apply). A *different* path is a different
    # scenario and stays blocked while one is locked.
    scenario_path_display = str(path.resolve())
    env = scenario["env"]

    lock = read_lock()
    if lock is not None and lock.get("scenario_path") != scenario_path_display:
        print(
            f"Refusing to apply '{scenario_path_display}': scenario '{lock.get('scenario_path')}' "
            f"already owns the infra (status={lock.get('status')}). Run 'vidctl scenario destroy' "
            "first, or re-apply the same scenario file to reconcile it.",
            file=sys.stderr,
        )
        return 1

    write_lock(scenario_path_display, scenario_hash, env, "applying")

    contract_opts = scenario["contract"]
    code = contract.publish(
        env,
        False,
        True,
        contract_opts["gas_budget"],
        contract_opts["create_registry_if_missing"],
        contract_opts["force"],
    )
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Scenario apply failed at contract publish (exit {code}).", file=sys.stderr)
        return code

    missing = infra.missing_contract_keys(contract_env_path(env))
    if missing:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(
            f"Contract publish succeeded but {', '.join(missing)} still missing from "
            f"{contract_env_path(env)}; aborting.",
            file=sys.stderr,
        )
        return 1

    code = registry.publish(None, True, scenario["registry"]["tag"])
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Scenario apply failed at image publish (exit {code}).", file=sys.stderr)
        return code

    try:
        state = registry.read_runtime_registry()
    except ValueError as exc:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Image publish succeeded but registry state unreadable: {exc}", file=sys.stderr)
        return 1
    missing_images = [service for service in infra.DOCKER_SERVICES if service not in state.deployed]
    if missing_images:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Image publish succeeded but missing deployed tags for: {', '.join(missing_images)}.", file=sys.stderr)
        return 1

    wanted: dict[InstanceKey, dict[str, Any]] = {
        (row["name"], row["service"], row["provider"], env, row["instance_index"]): row
        for row in scenario["instances"]
    }
    current: dict[InstanceKey, dict[str, Any]] = {
        _topology_instance_key(item, env): item for item in _active_instances_for_env(env)
    }
    to_kill, to_start = diff_instances(wanted, current)

    for name, service, provider, _env, instance_index in to_kill:
        code = infra.control("kill", name, service, provider, yes=True, instance_index=instance_index)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(
                f"Scenario apply failed killing extra instance {name}/{service}/{provider}"
                f"#{instance_index} (exit {code}).",
                file=sys.stderr,
            )
            return code

    for key in to_start:
        row = wanted[key]
        name, service, provider, instance_index = row["name"], row["service"], row["provider"], row["instance_index"]
        code = infra.control(
            "start",
            name,
            service,
            provider,
            yes=True,
            size=row.get("size"),
            instance_index=instance_index,
        )
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(
                f"Scenario apply failed starting instance {name}/{service}/{provider}"
                f"#{instance_index} (exit {code}).",
                file=sys.stderr,
            )
            return code

    write_lock(scenario_path_display, scenario_hash, env, "active")
    print(f"Scenario '{scenario['name']}' applied: {len(to_kill)} removed, {len(to_start)} reconciled.")
    return 0


def status(_args: Any) -> int:
    lock = read_lock()
    if lock is None:
        print("No scenario is currently active.")
        return 0

    print(f"Active scenario: {lock.get('scenario_path')}")
    print(f"  env:      {lock.get('env')}")
    print(f"  status:   {lock.get('status')}")
    print(f"  hash:     {lock.get('scenario_hash', '')}")
    print(f"  applied:  {lock.get('applied_at')}")
    print(f"  updated:  {lock.get('updated_at')}")

    env = str(lock.get("env", ""))
    rows = _active_instances_for_env(env)
    if not rows:
        print("No managed instances.")
        return 0

    print("Instances:")
    for item in sorted(rows, key=lambda r: (str(r.get("name")), str(r.get("service")), int(r.get("instance_index", 1) or 1))):
        instance_index = int(item.get("instance_index", 1) or 1)
        label = str(item.get("service")) if instance_index == 1 else f"{item.get('service')}-{instance_index}"
        state = item.get("last_status") or item.get("desired_state")
        error = f" ERROR: {item.get('last_error')}" if item.get("last_error") else ""
        print(f"  {item.get('name')}/{label}@{item.get('provider')}: {state}{error}")
    return 0


def destroy(_args: Any) -> int:
    lock = read_lock()
    if lock is None:
        print("No scenario is currently active; nothing to destroy.")
        return 0

    env = str(lock.get("env", ""))
    scenario_path_display = str(lock.get("scenario_path", ""))
    scenario_hash = str(lock.get("scenario_hash", ""))

    rows = sorted(
        _active_instances_for_env(env),
        key=lambda r: (str(r.get("name")), str(r.get("service")), int(r.get("instance_index", 1) or 1)),
    )
    for item in rows:
        name = str(item.get("name"))
        service = str(item.get("service"))
        provider = str(item.get("provider"))
        instance_index = int(item.get("instance_index", 1) or 1)
        code = infra.control("kill", name, service, provider, yes=True, instance_index=instance_index)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(
                f"Scenario destroy failed killing {name}/{service}/{provider}#{instance_index} "
                f"(exit {code}).",
                file=sys.stderr,
            )
            return code

    clear_lock()
    print(f"Scenario '{scenario_path_display}' destroyed; lock released.")
    return 0
