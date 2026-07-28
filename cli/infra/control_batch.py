from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..context import DOCKER_SERVICES, PINNED_IMAGES
from ._constants import PROVIDERS
from .history import record_history, timestamp
from .inventory import registry_status
from .pulumi import set_vm_defaults
from .topology import find_worker, new_worker, read_topology, relative_contract_env, service_backend, write_topology
from .validation import desired_state_for, missing_contract_keys, missing_vm_provider_keys, validate_network, vm_provider_error


def control_many(
    action: str,
    host: str,
    provider: str,
    rows: list[dict[str, Any]],
    yes: bool = False,
) -> int:
    """Batched variant of control() for multiple vm-backed services
    colocated on ONE host (same host+provider). control() does a full
    pulumi_up()+inventory()+configure() pass per (host, service) row -- fine
    for a single service, but wasteful when many services share a host
    (e.g. a scenario colocating 8 services on one DigitalOcean droplet):
    the same host would get a full pulumi apply and a full Ansible
    playbook run 8 times in a row, each one re-walking every
    already-configured service on that host again before doing anything
    new. This runs the per-row bookkeeping (wallet checkout, topology
    update) for every row, then ONE pulumi_up()+inventory()+configure()
    pass covering the whole batch.

    Each row is a dict with keys: service, size (optional), worker_index
    (optional, default 1), region (optional). Only supports action in
    {"start", "restart"} -- kill/pause aren't batched since they're not the
    slow path this exists to fix.

    Callers are responsible for only grouping rows that are safe to batch:
    all vm-backed, and (if more than one row) on a colocation-capable
    provider -- this mirrors control()'s own colocation gate but doesn't
    repeat every one of its checks (e.g. it assumes the caller already
    filtered out cloudflare/tencent).
    """
    # Deferred self-import: contract_env_path/pulumi_up/inventory/
    # persist_vm_resolution/configure/host_address are patched by tests as
    # flat cli.infra attributes -- looking them up through the package at
    # call time is what makes those patches take effect here.
    from .. import infra

    if action not in {"start", "restart"}:
        raise ValueError("control_many only supports action in {'start', 'restart'}")
    if not rows:
        return 0
    if provider not in PROVIDERS:
        print(f"Unknown provider: {provider}", file=sys.stderr)
        return 2
    if len(rows) > 1 and provider not in {"digitalocean", "upcloud", "akamai", "azure", "oci"}:
        message = (
            f"Colocating multiple service workers on one --host is only supported for "
            f"--provider digitalocean, --provider upcloud, --provider akamai, --provider azure, or "
            f"--provider oci (got --provider {provider})."
        )
        print(message, file=sys.stderr)
        return 1

    topology = read_topology()
    env_name = validate_network(str(topology.get("active_env", "devnet")))
    contract_path = infra.contract_env_path(env_name)

    missing_keys = missing_contract_keys(contract_path)
    if missing_keys:
        message = (
            f"{contract_path} is missing required contract keys: {', '.join(missing_keys)}. "
            f"Run ./vidctl contract publish --env {env_name} --yes first."
        )
        print(message, file=sys.stderr)
        for row in rows:
            record_history(action, env=env_name, name=host, service=str(row["service"]), provider=provider, result_for_code=1, error=message)
        return 1

    missing_provider_keys = missing_vm_provider_keys(provider)
    if missing_provider_keys:
        message = vm_provider_error(provider, missing_provider_keys)
        print(message, file=sys.stderr)
        for row in rows:
            record_history(action, env=env_name, name=host, service=str(row["service"]), provider=provider, result_for_code=1, error=message)
        return 1

    from .. import wallet

    prepared: list[dict[str, Any]] = []
    for row in rows:
        service = str(row["service"])
        worker_index = int(row.get("worker_index") or 1)
        worker_key = service if worker_index == 1 else f"{service}-{worker_index}"
        from ..image_bake import BAKE_SERVICE

        if service not in DOCKER_SERVICES and service not in PINNED_IMAGES and service != BAKE_SERVICE:
            print(f"Unknown service: {service}", file=sys.stderr)
            return 2
        if service_backend(service) != "vm":
            print(f"control_many only supports vm-backed services (got '{service}')", file=sys.stderr)
            return 2

        try:
            wallet_entry, _created = wallet.checkout_wallet(host, service, provider, env_name, worker_index)
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
        worker["backend"] = "vm"
        worker["desired_state"] = next_state
        worker["last_operation"] = action
        worker["last_updated"] = timestamp()
        worker["contract_env"] = relative_contract_env(env_name)
        set_vm_defaults(
            worker,
            topology,
            find_instance_type=False,
            size=row.get("size"),
            region=row.get("region"),
            worker_index=worker_index,
        )
        prepared.append(
            {
                "service": service,
                "worker_index": worker_index,
                "worker_key": worker_key,
                "worker": worker,
                "previous": previous,
                "next_state": next_state,
                "wallet_entry": wallet_entry,
            }
        )

    write_topology(topology)

    failed_stage = "pulumi"
    code = infra.pulumi_up(env_name)

    if code == 0:
        failed_stage = "inventory"
        code = infra.inventory()
        if code == 0:
            for item in prepared:
                infra.persist_vm_resolution(topology, env_name, host, item["service"], provider)
        if code == 0:
            failed_stage = "configure"
            container_state = "restarted" if action == "restart" else "started"
            extra_vars = {
                "xaisen_operator_wallets": {
                    host: {
                        item["worker_key"]: wallet.operator_state_json(item["wallet_entry"])
                        for item in prepared
                        if item["wallet_entry"] is not None
                    }
                }
            }
            code = infra.configure(host_limit=host, container_state=container_state, extra_vars=extra_vars)

    for item in prepared:
        worker = item["worker"]
        if code == 0:
            worker["last_status"] = item["next_state"]
            worker["last_error"] = ""
        else:
            if failed_stage == "pulumi":
                worker["desired_state"] = item["previous"]
            worker["last_error"] = f"{failed_stage} failed with exit code {code}"
    write_topology(topology)

    if code == 0:
        address = infra.host_address(host)
        reportable = [item for item in prepared if item["wallet_entry"] is not None]

        # Same rationale as control_fleet.control_many_hosts(): each item
        # does a devnet RPC balance lookup plus an SSH probe (up to a 20s
        # timeout each) -- I/O-bound, so run them concurrently rather than
        # one colocated service at a time.
        def _gather(item: dict[str, Any]) -> tuple[str, int, str]:
            wallet_entry = item["wallet_entry"]
            wallet_address = str(wallet_entry.get("address", ""))
            try:
                balance_mist = wallet.current_balance_mist(wallet_address)
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                balance_mist = int(wallet_entry.get("last_balance_mist", 0))
            registry = registry_status(host, item["worker_key"], address)
            return wallet_address, balance_mist, registry

        if reportable:
            with ThreadPoolExecutor(max_workers=min(16, len(reportable))) as pool:
                results = list(pool.map(_gather, reportable))

            for wallet_address, balance_mist, registry in results:
                print(f"IP:      {address or 'unknown'}")
                print(f"Wallet:  {wallet_address[:8]}...")
                print(f"Balance: {balance_mist / 1_000_000_000:.4f} SUI")
                print(f"Registry: {registry}")

    for item in prepared:
        worker = item["worker"]
        record_history(
            action,
            env=env_name,
            name=host,
            service=item["worker_key"],
            provider=str(worker.get("provider", "")),
            resource_id=str(worker.get("resource_id", "")),
            previous_status=item["previous"],
            next_status=str(worker.get("desired_state", "")),
            result_for_code=code,
            error=str(worker.get("last_error", "")),
        )

    return code
