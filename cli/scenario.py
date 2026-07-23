from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import tomllib

from . import contract, image_bake, infra, registry
from . import object as object_cmd
from .context import ROOT, RUNTIME_SCENARIO_LOCK, contract_env_path

SCENARIO_DIR = ROOT / "scenario"

WorkerKey = tuple[str, str, str, str, int]
FrontendKey = tuple[str, str, str]


def load_scenario(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Scenario file not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    env = str(data.get("env", ""))
    if env not in infra.NETWORKS:
        raise ValueError(f"Scenario env must be one of {', '.join(infra.NETWORKS)}, got {env!r}.")

    raw_workers = data.get("workers", [])
    if not isinstance(raw_workers, list) or not raw_workers:
        raise ValueError("Scenario must declare at least one [[workers]] entry.")

    seen: set[WorkerKey] = set()
    workers: list[dict[str, Any]] = []
    for row in raw_workers:
        host = str(row.get("host", ""))
        service = str(row.get("service", ""))
        provider = str(row.get("provider", ""))
        worker_index = int(row.get("worker_index", 1) or 1)
        if not host:
            raise ValueError("Every scenario worker needs a 'host'.")
        if service not in infra.DOCKER_SERVICES:
            raise ValueError(f"Unknown service '{service}' for worker on host '{host}'.")
        if provider not in infra.PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' for worker on host '{host}'.")
        key: WorkerKey = (host, service, provider, env, worker_index)
        if key in seen:
            raise ValueError(
                f"Duplicate scenario worker: host={host} service={service} "
                f"provider={provider} worker_index={worker_index}."
            )
        seen.add(key)
        workers.append(
            {
                "host": host,
                "service": service,
                "provider": provider,
                "worker_index": worker_index,
                "size": row.get("size") or None,
                "region": row.get("region") or None,
            }
        )

    raw_frontends = data.get("frontends", [])
    if not isinstance(raw_frontends, list):
        raise ValueError("Scenario 'frontends' must be an array of tables ([[frontends]]).")

    seen_frontends: set[FrontendKey] = set()
    frontends: list[dict[str, Any]] = []
    for row in raw_frontends:
        name = str(row.get("name", ""))
        object_type = str(row.get("object") or "frontend")
        provider = str(row.get("provider", ""))
        if not name:
            raise ValueError("Every scenario frontend needs a 'name'.")
        if object_type not in object_cmd.OBJECT_TYPES:
            raise ValueError(f"Unknown object type '{object_type}' for frontend '{name}'.")
        if provider not in object_cmd.PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' for frontend '{name}'.")
        key: FrontendKey = (name, object_type, provider)
        if key in seen_frontends:
            raise ValueError(f"Duplicate scenario frontend: name={name} object={object_type} provider={provider}.")
        seen_frontends.add(key)
        frontends.append({"name": name, "object": object_type, "provider": provider})

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
            "provider": registry_opts.get("provider") or None,
            "tag": registry_opts.get("tag") or None,
        },
        "frontends": frontends,
        "workers": workers,
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


def diff_workers(
    wanted: dict[WorkerKey, dict[str, Any]],
    current: dict[WorkerKey, dict[str, Any]],
) -> tuple[list[WorkerKey], list[WorkerKey]]:
    to_kill = sorted(current.keys() - wanted.keys())
    to_start = list(wanted.keys())
    return to_kill, to_start


def _topology_worker_key(item: dict[str, Any], default_env: str) -> WorkerKey:
    return (
        str(item.get("host")),
        str(item.get("service")),
        str(item.get("provider")),
        str(item.get("env", default_env)),
        int(item.get("worker_index", 1) or 1),
    )


def _active_workers_for_env(env: str) -> list[dict[str, Any]]:
    # ensure_topology (not read_topology) since topology.toml may not exist
    # yet on a first-ever `scenario apply` (normally created by `vidctl infra
    # init`, which a scenario apply doesn't require running first).
    topology = infra.ensure_topology(env)
    return [
        item
        for item in topology.get("workers", [])
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

    # Frontend sites are publish-only here -- never killed/deleted by a
    # scenario, in apply() or destroy(). This depends only on the contract
    # step above (object_cmd.publish's pnpm build reads services/client/
    # client/.env, populated by contract.publish's sync_frontend_env), not
    # on the worker images below, so it runs before registry login/publish.
    for frontend in scenario["frontends"]:
        code = object_cmd.publish(frontend["name"], frontend["object"], frontend["provider"])
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(
                f"Scenario apply failed publishing frontend {frontend['name']}"
                f"@{frontend['provider']} (exit {code}).",
                file=sys.stderr,
            )
            return code

    registry_provider = scenario["registry"]["provider"]
    if registry_provider:
        code = registry.login(registry_provider)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(f"Scenario apply failed at registry login (exit {code}).", file=sys.stderr)
            return code

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

    wanted: dict[WorkerKey, dict[str, Any]] = {
        (row["host"], row["service"], row["provider"], env, row["worker_index"]): row
        for row in scenario["workers"]
    }
    current: dict[WorkerKey, dict[str, Any]] = {
        _topology_worker_key(item, env): item for item in _active_workers_for_env(env)
    }
    to_kill, to_start = diff_workers(wanted, current)

    for host, service, provider, _env, worker_index in to_kill:
        code = infra.control("kill", host, service, provider, yes=True, worker_index=worker_index)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(
                f"Scenario apply failed killing extra worker {host}/{service}/{provider}"
                f"#{worker_index} (exit {code}).",
                file=sys.stderr,
            )
            return code

    # Bake a golden image for any (provider, region) among the workers
    # about to start that doesn't have one yet -- set_vm_defaults() then
    # picks it up automatically for every infra.control("start", ...) call
    # below, same as if it had been baked ahead of time. Only providers
    # image_bake.SUPPORTED_PROVIDERS supports do anything here; others are a
    # no-op and keep today's stock-image behavior.
    needed_regions: dict[tuple[str, str | None], None] = {}
    for key in to_start:
        row = wanted[key]
        needed_regions[(row["provider"], row.get("region"))] = None
    for provider, region in needed_regions:
        ok, error_message = image_bake.ensure_image(provider, region)
        if not ok:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(f"Scenario apply failed ensuring a golden image: {error_message}", file=sys.stderr)
            return 1

    # Group by (host, provider): colocated services on the same host go
    # through infra.control_many() -- one pulumi_up()+inventory()+configure()
    # pass for the whole host instead of one full pass per service (see
    # control_many's docstring). Singleton hosts and non-colocation-capable
    # providers keep using infra.control() one row at a time, unchanged.
    host_groups: dict[tuple[str, str], list[WorkerKey]] = {}
    for key in to_start:
        row = wanted[key]
        host_groups.setdefault((row["host"], row["provider"]), []).append(key)

    COLOCATE_PROVIDERS = {"digitalocean", "upcloud", "akamai"}
    for (host_name, host_provider), keys in host_groups.items():
        if len(keys) > 1 and host_provider in COLOCATE_PROVIDERS and all(
            infra.service_backend(wanted[key]["service"]) == "vm" for key in keys
        ):
            batch_rows = [
                {
                    "service": wanted[key]["service"],
                    "size": wanted[key].get("size"),
                    "worker_index": wanted[key]["worker_index"],
                    "region": wanted[key].get("region"),
                }
                for key in keys
            ]
            code = infra.control_many("start", host_name, host_provider, batch_rows, yes=True)
            if code != 0:
                write_lock(scenario_path_display, scenario_hash, env, "failed")
                print(
                    f"Scenario apply failed starting host {host_name}@{host_provider} (exit {code}).",
                    file=sys.stderr,
                )
                return code
            continue

        for key in keys:
            row = wanted[key]
            host, service, provider, worker_index = row["host"], row["service"], row["provider"], row["worker_index"]
            code = infra.control(
                "start",
                host,
                service,
                provider,
                yes=True,
                size=row.get("size"),
                worker_index=worker_index,
                region=row.get("region"),
            )
            if code != 0:
                write_lock(scenario_path_display, scenario_hash, env, "failed")
                print(
                    f"Scenario apply failed starting worker {host}/{service}/{provider}"
                    f"#{worker_index} (exit {code}).",
                    file=sys.stderr,
                )
                return code

    # Mirror of contract.sync_frontend_env() (run earlier, right after
    # contract publish) but for the bot control server's URL/token -- bot
    # has no on-chain registry to discover an endpoint from (test/demo tool
    # only), so the frontends need a static VITE_BOT_CONTROL_URL/TOKEN
    # instead. Must run AFTER the host_groups reconcile loop above: only
    # then does infra.host_address() know the bot worker's actual droplet
    # IP. Vite bakes VITE_* in at build time, so a stale build would still
    # point at whatever URL/token was baked in last time -- rebuild+republish
    # every frontend when the value actually changed (new bot host, or the
    # very first time BOT_CONTROL_TOKEN gets generated).
    if infra.sync_bot_frontend_env(scenario):
        for frontend in scenario["frontends"]:
            code = object_cmd.publish(frontend["name"], frontend["object"], frontend["provider"])
            if code != 0:
                write_lock(scenario_path_display, scenario_hash, env, "failed")
                print(
                    f"Scenario apply failed republishing frontend {frontend['name']}"
                    f"@{frontend['provider']} after bot control env sync (exit {code}).",
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
    rows = _active_workers_for_env(env)
    if not rows:
        print("No managed workers.")
        return 0

    print("Workers:")
    for item in sorted(rows, key=lambda r: (str(r.get("host")), str(r.get("service")), int(r.get("worker_index", 1) or 1))):
        worker_index = int(item.get("worker_index", 1) or 1)
        label = str(item.get("service")) if worker_index == 1 else f"{item.get('service')}-{worker_index}"
        state = item.get("last_status") or item.get("desired_state")
        error = f" ERROR: {item.get('last_error')}" if item.get("last_error") else ""
        print(f"  {item.get('host')}/{label}@{item.get('provider')}: {state}{error}")
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
        _active_workers_for_env(env),
        key=lambda r: (str(r.get("host")), str(r.get("service")), int(r.get("worker_index", 1) or 1)),
    )
    for item in rows:
        host = str(item.get("host"))
        service = str(item.get("service"))
        provider = str(item.get("provider"))
        worker_index = int(item.get("worker_index", 1) or 1)
        code = infra.control("kill", host, service, provider, yes=True, worker_index=worker_index)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(
                f"Scenario destroy failed killing {host}/{service}/{provider}#{worker_index} "
                f"(exit {code}).",
                file=sys.stderr,
            )
            return code

    clear_lock()
    print(f"Scenario '{scenario_path_display}' destroyed; lock released.")
    return 0
