from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

from ..context import DOCKER_SERVICES, PINNED_IMAGES
from ._constants import PROVIDERS
from .history import record_history, timestamp
from .inventory import registry_status
from .pulumi import alibaba_vm_target_urns, set_vm_defaults, stack_has_urns
from .topology import (
    find_worker,
    new_worker,
    read_topology,
    relative_contract_env,
    service_backend,
    worker_identifier,
    write_topology,
)
from .validation import (
    desired_state_for,
    missing_contract_keys,
    missing_vm_provider_keys,
    validate_network,
    vm_provider_error,
)


def control(
    action: str,
    host: str,
    service: str,
    provider: str,
    yes: bool = False,
    find_instance_type: bool = False,
    all_region: bool = False,
    size: str | None = None,
    worker_index: int = 1,
    region: str | None = None,
    detach: bool = False,
    docker_only: bool = False,
) -> int:
    # Lazy import: image_bake.py imports `infra` at module load time, so a
    # top-level import here would be circular.
    from ..image_bake import BAKE_SERVICE

    # Deferred self-import: contract_env_path/pulumi_up/inventory/
    # persist_vm_resolution/configure/SSH_KEY_ROOT are patched by tests as
    # flat cli.infra attributes -- looking them up through the package at
    # call time is what makes those patches take effect here.
    from .. import infra

    if service not in DOCKER_SERVICES and service not in PINNED_IMAGES and service != BAKE_SERVICE:
        print(f"Unknown service: {service}", file=sys.stderr)
        return 2
    if provider not in PROVIDERS:
        print(f"Unknown provider: {provider}", file=sys.stderr)
        return 2

    topology = read_topology()
    env_name = validate_network(str(topology.get("active_env", "devnet")))
    contract_path = infra.contract_env_path(env_name)
    backend = service_backend(service)
    # worker_index (1-based) distinguishes multiple colocated workers of the
    # SAME service on one --host (vidctl.py's count-prefix --service syntax,
    # e.g. `5cp-daemon`). worker_key (<provider>-<host>-<service>-<index>,
    # see topology.worker_identifier()) namespaces everything unique per
    # replica (container name, state/wallet dir, xaisen_operator_wallets
    # key) -- but NOT the base docker image/tag or the wallet's permanent
    # registered_role pin, which stay keyed on the bare `service` string.
    worker_key = worker_identifier(provider, host, service, worker_index)
    # Matches run_container.yml's `name: "xaisen-{{ worker_key }}"` exactly
    # -- used by the docker_only fast path (toggle_container.yml) below to
    # target the one already-provisioned container directly.
    container_name = f"xaisen-{worker_key}"

    if backend == "vm" and action in {"pause", "restart"} and not docker_only and provider not in {"alibaba", "akamai"}:
        # Only guards the REAL VM power-lifecycle path (pulumi_up below
        # translating desired_state into an actual cloud stop/start via the
        # alibaba/akamai adapters -- see IaC/pulumi/app/compute/alibaba.py's
        # `status=` and akamai.py's `booted=`). docker_only=True (scenario
        # worker.leave/join churn -- see actions.py) never reaches pulumi_up
        # at all (skipped below) and only ever runs a plain SSH `docker
        # stop`/`docker start` against one already-provisioned container, so
        # it isn't subject to this per-provider restriction.
        message = (
            f"{action} is not yet supported for {provider} VM services; "
            "powered lifecycle support currently requires --provider alibaba or --provider akamai."
        )
        print(message, file=sys.stderr)
        record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
        return 1

    if backend == "vm" and action in {"start", "restart"} and provider not in {"digitalocean", "upcloud", "akamai", "azure", "oci"}:
        other_active = any(
            item.get("host") == host
            and item.get("provider") == provider
            and item.get("env", env_name) == env_name
            and item.get("backend") == "vm"
            and item.get("desired_state") != "deleted"
            and not (item.get("service") == service and item.get("worker_index", 1) == worker_index)
            for item in topology.get("workers", [])
        )
        if worker_index > 1 or other_active:
            message = (
                f"Colocating multiple service workers on one --host is only supported for "
                f"--provider digitalocean, --provider upcloud, --provider akamai, --provider azure, or "
                f"--provider oci (got --provider {provider}). Use a separate --host per worker, or "
                "redeploy this worker with --provider digitalocean, upcloud, akamai, azure, or oci."
            )
            print(message, file=sys.stderr)
            record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
            return 1

    if action in {"start", "restart"}:
        missing_keys = missing_contract_keys(contract_path)
        if missing_keys:
            message = (
                f"{contract_path} is missing required contract keys: {', '.join(missing_keys)}. "
                f"Run ./vidctl contract publish --env {env_name} --yes first."
            )
            print(message, file=sys.stderr)
            record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
            return 1
        if backend == "vm":
            if service in ("prometheus", "tempo", "grafana", "pushgateway", "loki"):
                message = (
                    f"{service} is no longer deployed via `vidctl infra` -- it now runs on a dedicated, "
                    "operator-owned monitoring host managed by `vidctl observer` (see `vidctl observer --help`), "
                    "not a disposable Pulumi-provisioned VM."
                )
                print(message, file=sys.stderr)
                record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
                return 1
            if provider == "cloudflare":
                message = "cloudflare has no compute/VM product; choose another --provider for vm-backed services."
                print(message, file=sys.stderr)
                record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
                return 1
            if provider == "tencent":
                message = (
                    "tencent VM provisioning is not yet supported (no working Pulumi Python SDK path was "
                    "found for Tencent compute/VPC resources); choose another --provider for now."
                )
                print(message, file=sys.stderr)
                record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
                return 1
            missing_provider_keys = missing_vm_provider_keys(provider)
            if missing_provider_keys:
                message = vm_provider_error(provider, missing_provider_keys)
                print(message, file=sys.stderr)
                record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
                return 1

    if action == "kill" and not yes:
        message = "Refusing to delete infrastructure without --yes."
        print(message, file=sys.stderr)
        record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=2, error=message)
        return 2

    wallet_entry: dict[str, Any] | None = None
    wallet_created = False
    if backend == "vm" and action in {"start", "restart"}:
        from .. import wallet

        try:
            wallet_entry, wallet_created = wallet.checkout_wallet(host, service, provider, env_name, worker_index)
        except (subprocess.CalledProcessError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            message = f"Failed to create/load operator wallet for {host}: {exc}"
            print(message, file=sys.stderr)
            record_history(action, env=env_name, name=host, service=worker_key, provider=provider, result_for_code=1, error=message)
            return 1

    worker = find_worker(topology, env_name, host, service, provider, worker_index)
    if worker is None:
        worker = new_worker(env_name, host, service, provider, worker_index)
        topology.setdefault("workers", []).append(worker)

    previous = str(worker.get("desired_state", worker.get("last_status", "unknown")))
    next_state = desired_state_for(action)
    worker["backend"] = backend
    worker["desired_state"] = next_state
    worker["last_operation"] = action
    worker["last_updated"] = timestamp()
    worker["contract_env"] = relative_contract_env(env_name)
    if backend == "vm" and action in {"start", "restart"}:
        set_vm_defaults(worker, topology, find_instance_type=find_instance_type, size=size, region=region, worker_index=worker_index)
    write_topology(topology)

    code = 0
    failed_stage = "pulumi"
    # docker_only pause/restart (scenario worker.leave/join churn) never
    # needs Pulumi reconciliation -- the VM/container was already fully
    # provisioned by an earlier `vidctl scenario apply`, and skipping this
    # also guarantees desired_state can never cascade into a real cloud VM
    # power change via the alibaba/akamai adapters (see the provider guard
    # above). The docker_only branches further down (toggle_container over
    # SSH) run unconditionally regardless, since `code` stays 0 here.
    skip_pulumi = docker_only and backend == "vm" and action in {"pause", "restart"}
    if code == 0 and not skip_pulumi:
        failed_stage = "pulumi"
        if backend == "vm" and provider == "alibaba":
            # An --all-region search may create ad-hoc region-probe provider
            # resources that aren't in the fixed target URN list, so fall back
            # to an untargeted apply whenever that scan is in play. Likewise,
            # `--target` only accepts URNs that already exist in the stack's
            # state, so a brand-new worker (nothing created yet) must also
            # go through an untargeted apply.
            target_urns = alibaba_vm_target_urns(env_name, host, service, bool(worker.get("port")))
            use_targets = not all_region and stack_has_urns(env_name, target_urns)
            code = infra.pulumi_up(
                env_name,
                targets=target_urns if use_targets else None,
                extra_env={"ALIBABA_SCAN_ALL_REGIONS": "1" if all_region else "0"},
            )
        else:
            code = infra.pulumi_up(env_name)

    if code == 0:
        if action == "kill":
            topology["workers"] = [
                item
                for item in topology.get("workers", [])
                if not (
                    item.get("host") == host
                    and item.get("service") == service
                    and item.get("provider") == provider
                    and item.get("env", env_name) == env_name
                    and item.get("worker_index", 1) == worker_index
                )
            ]
            if backend == "vm":
                # Colocated hosts share one SSH keypair across services --
                # only remove it once no other still-active VM-backed
                # service remains under this host/provider/env, or a
                # sibling service's future `configure()` run would lose
                # host access.
                other_active_vm = any(
                    item.get("host") == host
                    and item.get("provider") == provider
                    and item.get("env", env_name) == env_name
                    and item.get("backend") == "vm"
                    and item.get("desired_state") != "deleted"
                    for item in topology.get("workers", [])
                )
                if not other_active_vm:
                    shutil.rmtree(infra.SSH_KEY_ROOT / host, ignore_errors=True)
                from .. import wallet

                wallet.release_wallet(host, service, provider, env_name, worker_index)
        elif backend == "vm" and action == "restart" and docker_only:
            # Fast path for scenario worker.join churn (pooled-worker
            # reuse -- see actions.py's _worker_join): the container
            # already exists with correct config from an earlier full
            # `configure()` provision (vidctl scenario apply), so there's
            # nothing to reconcile -- just resume it. Skips inventory()/
            # persist_vm_resolution() too (churn never recreates the VM,
            # so the resolved address hasn't changed) and the whole
            # site.yml play (SSH-reconnect wait, common/docker_service
            # roles, the per-colocated-service reconcile loop, Caddy) in
            # favor of one bare `docker start <container>` over SSH.
            failed_stage = "toggle_container"
            log_path = infra.ANSIBLE_DETACHED_LOG_ROOT / f"{worker_key}-{timestamp()}.log" if detach else None
            code = infra.toggle_container(
                host_limit=host, container_name=container_name, action="start", detach=detach, log_path=log_path
            )
        elif backend == "vm" and action in {"start", "restart"}:
            failed_stage = "inventory"
            code = infra.inventory()
            if code == 0:
                infra.persist_vm_resolution(topology, env_name, host, service, provider)
            if code == 0:
                failed_stage = "configure"
                container_state = "restarted" if action == "restart" else "started"
                configure_extra_vars = (
                    {"xaisen_operator_wallets": {host: {worker_key: wallet.operator_state_json(wallet_entry)}}}
                    if wallet_entry is not None
                    else None
                )
                # detach=True (scenario worker.join/leave churn -- see
                # actions.py): the actual Docker container start is just a
                # few `docker run`/`docker restart` calls at the tail of
                # site.yml, but getting there still pays SSH-reconnect wait
                # plus a per-service reconcile loop over every OTHER service
                # colocated on this host (see docker_service/tasks/main.yml)
                # -- minutes of Ansible overhead per worker action on a
                # busy host. Firing it detached (nohup-style, via
                # infra.run_detached()) lets the scenario's scripted
                # timeline keep moving instead of blocking on that
                # overhead. Trade-off: `code` below is "started", not
                # "succeeded" -- pulumi/inventory (already synchronous,
                # above) are the only stages still verified before this
                # returns. Real success/failure lands in log_path only.
                log_path = (
                    infra.ANSIBLE_DETACHED_LOG_ROOT / f"{worker_key}-{timestamp()}.log" if detach else None
                )
                code = infra.configure(
                    host_limit=host,
                    container_state=container_state,
                    extra_vars=configure_extra_vars,
                    detach=detach,
                    log_path=log_path,
                )
        elif backend == "vm" and action == "pause" and docker_only:
            # Fast path for scenario worker.leave churn (see actions.py's
            # _worker_leave): always just SSH in and stop the one named
            # container, regardless of whether any sibling worker is still
            # active on this host -- pulumi_up is skipped entirely for
            # docker_only pause/restart now (see the `skip_pulumi` check
            # above), so there's no cloud VM power-off this could ever fall
            # back to.
            failed_stage = "toggle_container"
            log_path = infra.ANSIBLE_DETACHED_LOG_ROOT / f"{worker_key}-{timestamp()}.log" if detach else None
            code = infra.toggle_container(
                host_limit=host,
                container_name=container_name,
                action="stop",
                detach=detach,
                log_path=log_path,
            )

        if code == 0 and action != "kill":
            worker["last_status"] = next_state
            worker["last_error"] = ""
        write_topology(topology)

    if code != 0:
        if failed_stage == "pulumi":
            worker["desired_state"] = previous
        worker["last_error"] = f"{failed_stage} failed with exit code {code}"
        write_topology(topology)

    if code == 0 and backend == "vm" and action in {"start", "restart"} and wallet_entry is not None:
        if docker_only and action == "restart":
            print(f"Toggled {container_name} on {host}.")
        elif detach:
            # Ansible hasn't actually run yet at this point (it's still
            # starting up in the background) -- querying registry_status()
            # now would just report "not registered", not a real answer.
            print(f"Provisioning {host} in the background (log: {log_path}).")
        else:
            address = infra.host_address(host)
            wallet_address = str(wallet_entry.get("address", ""))
            try:
                balance_mist = wallet.current_balance_mist(wallet_address)
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                balance_mist = int(wallet_entry.get("last_balance_mist", 0))
            print(f"IP:      {address or 'unknown'}")
            print(f"Wallet:  {wallet_address[:8]}...")
            print(f"Balance: {balance_mist / 1_000_000_000:.4f} SUI")
            print(f"Registry: {registry_status(host, worker_key, address)}")

    record_history(
        action,
        env=env_name,
        name=host,
        service=worker_key,
        provider=str(worker.get("provider", "")),
        resource_id=str(worker.get("resource_id", "")),
        previous_status=previous,
        next_status=str(worker.get("desired_state", "")),
        result_for_code=code,
        error=str(worker.get("last_error", "")),
    )
    return code
