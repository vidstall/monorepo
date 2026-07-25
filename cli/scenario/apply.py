from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .. import contract, image_bake, infra, registry
from .. import object as object_cmd
from .lock import clear_lock, read_lock, write_lock
from .spec import WorkerKey, load_scenario, scenario_hash_of
from .status import _active_workers_for_env, _topology_worker_key, diff_workers


def apply(path_str: str, yes: bool) -> int:
    # Deferred self-import: contract_env_path is patched by tests as a flat
    # cli.scenario attribute -- looking it up through the package at call
    # time is what makes that patch take effect here. Aliased since `scenario`
    # is also used below as the local name for the loaded scenario dict.
    from .. import scenario as scenario_pkg

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

    missing = infra.missing_contract_keys(scenario_pkg.contract_env_path(env))
    if missing:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(
            f"Contract publish succeeded but {', '.join(missing)} still missing from "
            f"{scenario_pkg.contract_env_path(env)}; aborting.",
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
            # Best-effort only -- a golden image is a boot-time optimization
            # (skips installing Docker at first boot), not a functional
            # requirement; Ansible still installs it on a stock image.
            # Aborting the whole apply over e.g. a quota-blocked bake VM
            # would refuse to (re)start workers that don't actually need
            # baking to work (confirmed live: azure-node-1 has run fine
            # without one since its region's temp-bake-VM quota headroom is
            # consumed by azure-node-1 itself).
            print(
                f"Warning: could not ensure a golden image for {provider}:{region} "
                f"({error_message}); continuing with the stock image.",
                file=sys.stderr,
            )

    # Group by (host, provider), then start EVERY host group in one shot via
    # infra.control_many_hosts() -- one pulumi_up()+inventory()+configure()
    # pass across the whole batch instead of looping one full pass per host
    # (which was the dominant cost on multi-host scenarios: each host paid
    # its own full-stack pulumi diff plus its own ansible-playbook startup).
    # Whether a group is colocated (multiple vm-backed services on one host,
    # colocation-capable provider) or a singleton doesn't matter here -- that
    # distinction only affects Pulumi's OWN resource grouping in
    # IaC/pulumi/app/program.py (which reads topology.toml directly), not
    # how many Python-level calls produced it. See control_many_hosts()'s
    # docstring for the full rationale.
    host_groups: dict[tuple[str, str], list[WorkerKey]] = {}
    for key in to_start:
        row = wanted[key]
        host_groups.setdefault((row["host"], row["provider"]), []).append(key)

    if host_groups:
        groups = [
            (
                host_name,
                host_provider,
                [
                    {
                        "service": wanted[key]["service"],
                        "size": wanted[key].get("size"),
                        "worker_index": wanted[key]["worker_index"],
                        "region": wanted[key].get("region"),
                    }
                    for key in keys
                ],
            )
            for (host_name, host_provider), keys in host_groups.items()
        ]
        code = infra.control_many_hosts("start", groups, yes=True)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(f"Scenario apply failed starting the host batch (exit {code}).", file=sys.stderr)
            return code

    write_lock(scenario_path_display, scenario_hash, env, "active")
    print(f"Scenario '{scenario['name']}' applied: {len(to_kill)} removed, {len(to_start)} reconciled.")
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
