from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import bot_client, contract, image_bake, infra, local_bot, observer, registry
from .. import object as object_cmd
from .lock import clear_lock, read_lock, write_lock
from .spec import WorkerKey, load_scenario, scenario_hash_of
from .status import _active_workers_for_env, _topology_worker_key, diff_workers


def _format_duration(seconds: float) -> str:
    total_seconds = int(round(seconds))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def _print_timings(timings: list[tuple[str, float]]) -> None:
    if not timings:
        return
    print("Step timings:")
    for label, seconds in timings:
        print(f"  {label}: {_format_duration(seconds)}")
    print(f"  total: {_format_duration(sum(seconds for _, seconds in timings))}")


@contextmanager
def _timed(timings: list[tuple[str, float]], label: str) -> Iterator[None]:
    start = time.monotonic()
    try:
        yield
    finally:
        timings.append((label, time.monotonic() - start))


# Both helpers below are deliberately best-effort: `vidctl observer` is a
# fully decoupled, optional module (see cli/infra/secrets.py's
# otel_exporter_vars() docstring on why cli/infra never imports it) -- a
# scenario apply/destroy must succeed for the fleet exactly as before even
# when no observer host is registered, or it's unreachable. Silently no-op
# when nothing is registered (the common case); print a warning, never
# raise/propagate a failure, when a registered host errors.
def _refresh_observer_stack() -> None:
    """Called once the new/reconciled worker set is live (see apply()) --
    re-runs `vidctl observer deploy` so Prometheus's scrape config
    (rendered from the CURRENT merged Ansible inventory) picks up the
    just-applied worker set, and so any containers a prior `scenario
    destroy` cleaned away come back. Never touches stored data.

    observer.deploy(host=None) already covers EVERY registered observer
    host in one combined Ansible run (a single comma-joined --limit) --
    calling it once here, instead of looping and calling
    observer.deploy(name) per host, avoids paying a full separate
    ansible-playbook startup (SSH handshake + fact-gathering) per
    registered host. Loses per-host error attribution in the warning
    below, but this whole function is already best-effort (never raises),
    so that's an acceptable trade for cutting N sequential playbook
    startups down to 1."""
    try:
        hosts = observer.read_hosts()
    except Exception as exc:
        print(f"Warning: could not read observer hosts, skipping observer refresh: {exc}", file=sys.stderr)
        return
    if not hosts:
        return
    try:
        code = observer.deploy(None)
    except Exception as exc:
        print(f"Warning: observer refresh failed: {exc}", file=sys.stderr)
        return
    if code != 0:
        print(f"Warning: observer refresh failed (exit {code}).", file=sys.stderr)


def _push_contract_state(env: str) -> None:
    """Called once the reconciled worker set + observer stack are both live
    (see apply()) -- pushes a fresh wallet-pool/on-chain-registration/
    contract-metadata snapshot to whichever registered observer host actually
    runs pushgateway (see inventory.py's ALL_SERVICE_NAMES/host['services']
    split), so the Contract & Chain dashboard doesn't sit on stale or
    entirely-missing data until someone remembers to run
    `vidctl observer export-contract-state` by hand. Best-effort for the same
    reason as _refresh_observer_stack() above: this is a dashboard freshness
    nicety, not a functional requirement of the scenario itself."""
    from .. import observer
    from ..observer.inventory import ALL_SERVICE_NAMES

    try:
        hosts = observer.read_hosts()
    except Exception as exc:
        print(f"Warning: could not read observer hosts, skipping contract-state export: {exc}", file=sys.stderr)
        return
    target = next((h for h in hosts if "pushgateway" in (h.get("services") or ALL_SERVICE_NAMES)), None)
    if target is None:
        return
    name = str(target.get("name", ""))
    try:
        code = observer.export_contract_state(env, name)
    except Exception as exc:
        print(f"Warning: contract-state export failed for {name!r}: {exc}", file=sys.stderr)
        return
    if code != 0:
        print(f"Warning: contract-state export failed for {name!r} (exit {code}).", file=sys.stderr)


def _sync_client_observability_env() -> None:
    """Called once the observer stack has been refreshed + the contract-state
    push has landed (see apply()) -- writes the registered loki/pushgateway
    hosts' public URLs and auth tokens into services/client/client/.env, so a
    scenario apply is enough on its own to make the browser's direct-to-
    observer log/metrics push (lib/log.ts, lib/metrics-push.ts) work -- this
    isn't exposed as its own subcommand (see client_env.py's module
    docstring); apply() and object.py's frontend publish are the only call
    sites. Best-effort for the same reason as _refresh_observer_stack() above: no observer host
    registered is the common case (this is a dashboard/testbed nicety, not a
    functional requirement of the scenario itself), and sync_client_
    observability_env() already no-ops per-endpoint when a host isn't
    registered -- this wrapper only needs to swallow the "not registered at
    all" / unexpected-exception cases so apply() itself never fails on it."""
    from .. import observer

    try:
        hosts = observer.read_hosts()
    except Exception as exc:
        print(f"Warning: could not read observer hosts, skipping client env sync: {exc}", file=sys.stderr)
        return
    if not hosts:
        return
    try:
        code = observer.sync_client_observability_env()
    except Exception as exc:
        print(f"Warning: client env sync failed: {exc}", file=sys.stderr)
        return
    if code != 0:
        print(f"Warning: client env sync failed (exit {code}).", file=sys.stderr)


def _clean_observer_stack() -> None:
    """Called once the fleet is fully torn down (see destroy()) -- wipes
    Prometheus/Tempo's stored history via `vidctl observer clean` per
    registered host, so the NEXT `apply()` (via _refresh_observer_stack())
    starts observing a genuinely fresh scenario instead of mixing in dead
    workers' old metrics/traces. Grafana's own data (dashboards, logins)
    is left alone -- see observer_clean.yml."""
    try:
        hosts = observer.read_hosts()
    except Exception as exc:
        print(f"Warning: could not read observer hosts, skipping observer data cleanup: {exc}", file=sys.stderr)
        return
    for host in hosts:
        name = str(host.get("name", ""))
        try:
            code = observer.clean(name)
        except Exception as exc:
            print(f"Warning: observer data cleanup failed for {name!r}: {exc}", file=sys.stderr)
            continue
        if code != 0:
            print(f"Warning: observer data cleanup failed for {name!r} (exit {code}).", file=sys.stderr)


def apply(path_str: str | None, yes: bool, rebake: bool = False, force_contract: bool = False) -> int:
    # Deferred self-import: contract_env_path is patched by tests as a flat
    # cli.scenario attribute -- looking it up through the package at call
    # time is what makes that patch take effect here. Aliased since `scenario`
    # is also used below as the local name for the loaded scenario dict.
    from .. import scenario as scenario_pkg

    if not yes:
        print("Refusing to apply a scenario without --yes.", file=sys.stderr)
        return 2

    if path_str is None:
        previous = read_lock()
        if previous is None or not previous.get("scenario_path"):
            print(
                "Refusing to apply: no scenario path given and no previously applied scenario to reuse.",
                file=sys.stderr,
            )
            return 2
        path_str = str(previous["scenario_path"])
        print(f"No scenario path given; reusing previously applied scenario: {path_str}")

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

    timings: list[tuple[str, float]] = []

    contract_opts = scenario["contract"]
    with _timed(timings, "contract publish"):
        code = contract.publish(
            env,
            False,
            True,
            contract_opts["gas_budget"],
            contract_opts["create_registry_if_missing"],
            contract_opts["force"] or force_contract,
        )
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Scenario apply failed at contract publish (exit {code}).", file=sys.stderr)
        _print_timings(timings)
        return code

    # dvconf_role_voting (package B, see services/contract-role-voting) must
    # publish AFTER package A: its Move.toml resolves package A's on-chain
    # address via a local dependency, which only exists once A's Move.lock
    # records a real publish for this env. Never has registries to backfill.
    with _timed(timings, "contract publish (role-voting)"):
        code = contract.publish(
            env,
            False,
            True,
            contract_opts["gas_budget"],
            False,
            contract_opts["force"] or force_contract,
            pkg=contract.CONTRACT_B,
        )
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Scenario apply failed at contract publish for role-voting package (exit {code}).", file=sys.stderr)
        _print_timings(timings)
        return code

    missing = infra.missing_contract_keys(scenario_pkg.contract_env_path(env))
    if missing:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(
            f"Contract publish succeeded but {', '.join(missing)} still missing from "
            f"{scenario_pkg.contract_env_path(env)}; aborting.",
            file=sys.stderr,
        )
        _print_timings(timings)
        return 1

    # Frontend sites are publish-only here -- never killed/deleted by a
    # scenario, in apply() or destroy(). This depends only on the contract
    # step above (object_cmd.publish's pnpm build reads services/client/
    # client/.env, populated by contract.publish's sync_frontend_env), not
    # on the worker images below, so it runs before registry login/publish.
    with _timed(timings, "frontend publish"):
        for frontend in scenario["frontends"]:
            code = object_cmd.publish(frontend["name"], frontend["object"], frontend["provider"])
            if code != 0:
                break
        else:
            code = 0
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(
            f"Scenario apply failed publishing frontend {frontend['name']}"
            f"@{frontend['provider']} (exit {code}).",
            file=sys.stderr,
        )
        _print_timings(timings)
        return code

    registry_provider = scenario["registry"]["provider"]
    if registry_provider:
        with _timed(timings, "registry login"):
            code = registry.login(registry_provider)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(f"Scenario apply failed at registry login (exit {code}).", file=sys.stderr)
            _print_timings(timings)
            return code

    with _timed(timings, "image publish"):
        code = registry.publish(None, True, scenario["registry"]["tag"])
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Scenario apply failed at image publish (exit {code}).", file=sys.stderr)
        _print_timings(timings)
        return code

    try:
        state = registry.read_runtime_registry()
    except ValueError as exc:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Image publish succeeded but registry state unreadable: {exc}", file=sys.stderr)
        _print_timings(timings)
        return 1
    missing_images = [service for service in infra.DOCKER_SERVICES if service not in state.deployed]
    if missing_images:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(f"Image publish succeeded but missing deployed tags for: {', '.join(missing_images)}.", file=sys.stderr)
        _print_timings(timings)
        return 1

    wanted: dict[WorkerKey, dict[str, Any]] = {
        (row["host"], row["service"], row["provider"], env, row["worker_index"]): row
        for row in scenario["workers"]
    }
    current: dict[WorkerKey, dict[str, Any]] = {
        _topology_worker_key(item, env): item for item in _active_workers_for_env(env)
    }
    to_kill, to_start = diff_workers(wanted, current)
    # `await=true` workers are declared intent, not eager-start intent --
    # they stay out of `to_kill` (still present in `wanted`, so a scenario
    # that already brought one up via a worker.join action won't have it
    # torn down as "extra" on a later apply) but are excluded here from
    # `to_start` so `apply` never provisions them itself; only a matching
    # worker.join action (during `scenario run`) does.
    deferred_count = sum(1 for key in to_start if wanted[key].get("await"))
    to_start = [key for key in to_start if not wanted[key].get("await")]

    with _timed(timings, "worker teardown"):
        code = 0
        for host, service, provider, _env, worker_index in to_kill:
            code = infra.control("kill", host, service, provider, yes=True, worker_index=worker_index)
            if code != 0:
                break
    if code != 0:
        write_lock(scenario_path_display, scenario_hash, env, "failed")
        print(
            f"Scenario apply failed killing extra worker {host}/{service}/{provider}"
            f"#{worker_index} (exit {code}).",
            file=sys.stderr,
        )
        _print_timings(timings)
        return code

    # Bake a golden image for any (provider, region) among the workers
    # about to start that doesn't have one yet -- set_vm_defaults() then
    # picks it up automatically for every infra.control("start", ...) call
    # below, same as if it had been baked ahead of time. Only providers
    # image_bake.SUPPORTED_PROVIDERS supports do anything here; others are a
    # no-op and keep today's stock-image behavior. `--rebake` (force=rebake
    # below) bakes a fresh image even for a (provider, region) that already
    # has one -- for after a `vidctl registry publish`, so the new golden
    # image's pre-pulled app images (see bake.py's _prefetch_app_images())
    # aren't stale relative to what's about to actually be deployed.
    needed_regions: dict[tuple[str, str | None], None] = {}
    for key in to_start:
        row = wanted[key]
        needed_regions[(row["provider"], row.get("region"))] = None
    with _timed(timings, "image bake"):
        for provider, region in needed_regions:
            ok, error_message = image_bake.ensure_image(provider, region, force=rebake)
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
        with _timed(timings, "provision + configure"):
            code = infra.control_many_hosts("start", groups, yes=True)
        if code != 0:
            write_lock(scenario_path_display, scenario_hash, env, "failed")
            print(f"Scenario apply failed starting the host batch (exit {code}).", file=sys.stderr)
            _print_timings(timings)
            return code

    write_lock(scenario_path_display, scenario_hash, env, "active")
    with _timed(timings, "observer refresh"):
        _refresh_observer_stack()
        _push_contract_state(env)
        _sync_client_observability_env()
    print(
        f"Scenario '{scenario['name']}' applied: {len(to_kill)} removed, {len(to_start)} reconciled, "
        f"{deferred_count} awaiting worker.join."
    )
    _print_timings(timings)
    return 0


def destroy(_args: Any) -> int:
    lock = read_lock()
    if lock is None:
        print("No scenario is currently active; nothing to destroy.")
        return 0

    # Local bot dev-server sessions (`vidctl utils bot start`) hold this
    # scenario's contract addresses baked into their process env for their
    # whole lifetime -- a `tsx watch` process never reloads `.env` on its
    # own. Left running past this destroy, they'd keep submitting
    # transactions against a package/RoomManager nothing watches anymore
    # (see the local-bot-vs-scenario-destroy investigation this
    # accompanies). Stop them (tracked AND orphaned) before tearing down
    # the infra those sessions were talking to.
    local_bot.stop_all()

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

    _clean_observer_stack()
    clear_lock()
    print(f"Scenario '{scenario_path_display}' destroyed; lock released.")
    return 0


def clean(_args: Any) -> int:
    """Clear a finished/crashed run's leftovers WITHOUT tearing down the
    fleet `destroy()` would -- for when a `scenario run` dies mid-timeline
    (crash, Ctrl-C, an action erroring out) and leaves bot sessions still
    holding rooms open on otherwise-healthy bot workers, plus stale
    Prometheus/Tempo history from that run mixed into the NEXT run's
    observation window. Infra stays up and the lock stays held (or absent)
    exactly as it was -- this only clears run-scoped state, not the
    scenario's own reconciled workers."""
    lock = read_lock()
    if lock is None:
        print("No scenario is currently active; nothing to clean.")
        return 0
    env = str(lock.get("env", ""))

    bot_rows = sorted(
        (item for item in _active_workers_for_env(env) if item.get("service") == "bot"),
        key=lambda r: (str(r.get("host")), int(r.get("worker_index", 1) or 1)),
    )
    stopped = 0
    for item in bot_rows:
        host = str(item.get("host"))
        result = bot_client.delete_all_sessions(host)
        if result is None:
            print(f"clean: failed to reach bot worker {host}, skipping.", file=sys.stderr)
            continue
        count = int(result.get("stopped", 0) or 0)
        stopped += count
        if count:
            print(f"clean: stopped {count} leftover bot session(s) (rooms) on {host}")
    print(f"clean: stopped {stopped} leftover bot session(s) total.")

    # _clean_observer_stack() removes EVERY monitoring container (including
    # Grafana itself, see observer_clean.yml) before wiping data -- fine for
    # destroy(), which is always followed by a fresh apply() that redeploys
    # the whole stack, but clean() has no such follow-up: left as-is, the
    # operator's Grafana dashboard would just go dark (container gone, not
    # merely reset) until they happened to run something else that
    # redeploys it. Immediately re-running _refresh_observer_stack() here
    # brings every container -- Grafana included -- straight back up with
    # empty data, so `clean` reads as "reset", not "tear down and abandon".
    _clean_observer_stack()
    _refresh_observer_stack()
    print("clean: wiped Prometheus/Tempo history and redeployed the observer stack.")
    return 0
