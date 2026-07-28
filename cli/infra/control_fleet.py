from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..context import DOCKER_SERVICES, PINNED_IMAGES
from ._constants import PROVIDERS
from .history import record_history, timestamp
from .inventory import registry_status
from .pulumi import set_vm_defaults
from .topology import find_worker, new_worker, read_topology, relative_contract_env, service_backend, write_topology
from .validation import desired_state_for, missing_contract_keys, missing_vm_provider_keys, validate_network, vm_provider_error


def control_many_hosts(
    action: str,
    groups: list[tuple[str, str, list[dict[str, Any]]]],
    yes: bool = False,
) -> int:
    """Batched variant of control_many() for MULTIPLE hosts in one apply
    pass. control_many() already batches multiple services on one host into
    a single pulumi_up()+inventory()+configure() pass; this generalizes
    that one level up, batching multiple HOSTS (e.g. every host in a
    multi-host scenario.toml) into a single pass too -- one pulumi_up()
    covering every host's resources (Pulumi's own engine already
    parallelizes independent resource creation within one call, see
    --parallel) and one Ansible playbook run covering every host (via
    --limit <comma-joined hosts>, parallelized across hosts by Ansible's
    own forks), instead of the caller looping control()/control_many()
    once per host and paying a full pulumi diff plus a full
    ansible-playbook startup per host.

    Each group is (host, provider, rows), where rows has the same shape
    control_many() expects. Only supports action in {"start", "restart"}.

    xaisen_operator_wallets is nested by host in the Ansible extra_vars
    here (unlike control_many()'s flat dict), since more than one host is
    in play at once -- see IaC/ansible/roles/docker_service/tasks/
    deploy_one_service.yml's matching lookup.
    """
    # Deferred self-import: contract_env_path/pulumi_up/inventory/
    # persist_vm_resolution/configure/host_address are patched by tests as
    # flat cli.infra attributes -- looking them up through the package at
    # call time is what makes those patches take effect here.
    from .. import infra

    if action not in {"start", "restart"}:
        raise ValueError("control_many_hosts only supports action in {'start', 'restart'}")
    groups = [(host, provider, rows) for host, provider, rows in groups if rows]
    if not groups:
        return 0

    for host, provider, rows in groups:
        if provider not in PROVIDERS:
            print(f"Unknown provider: {provider}", file=sys.stderr)
            return 2
        if len(rows) > 1 and provider not in {"digitalocean", "upcloud", "akamai", "azure", "oci"}:
            message = (
                f"Colocating multiple service workers on one --host is only supported for "
                f"--provider digitalocean, --provider upcloud, --provider akamai, --provider azure, or "
                f"--provider oci (got --provider {provider} for host {host})."
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
        for host, provider, rows in groups:
            for row in rows:
                record_history(action, env=env_name, name=host, service=str(row["service"]), provider=provider, result_for_code=1, error=message)
        return 1

    checked_providers: set[str] = set()
    for host, provider, rows in groups:
        if provider in checked_providers:
            continue
        checked_providers.add(provider)
        missing_provider_keys = missing_vm_provider_keys(provider)
        if missing_provider_keys:
            message = vm_provider_error(provider, missing_provider_keys)
            print(message, file=sys.stderr)
            for other_host, other_provider, other_rows in groups:
                if other_provider != provider:
                    continue
                for row in other_rows:
                    record_history(action, env=env_name, name=other_host, service=str(row["service"]), provider=other_provider, result_for_code=1, error=message)
            return 1

    from .. import wallet

    prepared: list[dict[str, Any]] = []
    for host, provider, rows in groups:
        for row in rows:
            service = str(row["service"])
            worker_index = int(row.get("worker_index") or 1)
            worker_key = service if worker_index == 1 else f"{service}-{worker_index}"
            from ..image_bake import BAKE_SERVICE

            if service not in DOCKER_SERVICES and service not in PINNED_IMAGES and service != BAKE_SERVICE:
                print(f"Unknown service: {service}", file=sys.stderr)
                return 2
            if service_backend(service) != "vm":
                print(f"control_many_hosts only supports vm-backed services (got '{service}')", file=sys.stderr)
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
                    "host": host,
                    "provider": provider,
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

    sub_timings: list[tuple[str, float]] = []

    failed_stage = "pulumi"
    start = time.monotonic()
    code = infra.pulumi_up(env_name, parallel=20)
    sub_timings.append(("pulumi", time.monotonic() - start))

    if code == 0:
        failed_stage = "inventory"
        start = time.monotonic()
        code = infra.inventory()
        if code == 0:
            for item in prepared:
                infra.persist_vm_resolution(topology, env_name, item["host"], item["service"], item["provider"])
        sub_timings.append(("inventory", time.monotonic() - start))
        if code == 0:
            failed_stage = "configure"
            container_state = "restarted" if action == "restart" else "started"
            wallets_by_host: dict[str, dict[str, Any]] = {}
            for item in prepared:
                if item["wallet_entry"] is None:
                    continue
                wallets_by_host.setdefault(item["host"], {})[item["worker_key"]] = wallet.operator_state_json(item["wallet_entry"])
            extra_vars = {"xaisen_operator_wallets": wallets_by_host}
            host_limit = ",".join(sorted({item["host"] for item in prepared}))
            start = time.monotonic()
            code = infra.configure(host_limit=host_limit, container_state=container_state, extra_vars=extra_vars)
            sub_timings.append(("ansible configure", time.monotonic() - start))

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
        start = time.monotonic()
        reportable = [item for item in prepared if item["wallet_entry"] is not None]

        # Each item here does a devnet RPC balance lookup plus an SSH probe
        # (registry_status(), up to a 20s timeout) -- fully I/O-bound, so a
        # thread pool cuts a 26-worker scenario's reporting tail from
        # several minutes of serial SSH round-trips down to about the
        # slowest single probe.
        def _gather(item: dict[str, Any]) -> tuple[str, str, int, str]:
            wallet_entry = item["wallet_entry"]
            address = infra.host_address(item["host"])
            wallet_address = str(wallet_entry.get("address", ""))
            try:
                balance_mist = wallet.current_balance_mist(wallet_address)
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                balance_mist = int(wallet_entry.get("last_balance_mist", 0))
            registry = registry_status(item["host"], item["worker_key"], address)
            return address, wallet_address, balance_mist, registry

        if reportable:
            with ThreadPoolExecutor(max_workers=min(16, len(reportable))) as pool:
                results = list(pool.map(_gather, reportable))

            for item, (address, wallet_address, balance_mist, registry) in zip(reportable, results):
                print(f"Host:    {item['host']}")
                print(f"IP:      {address or 'unknown'}")
                print(f"Wallet:  {wallet_address[:8]}...")
                print(f"Balance: {balance_mist / 1_000_000_000:.4f} SUI")
                print(f"Registry: {registry}")
        sub_timings.append(("reporting", time.monotonic() - start))

    if sub_timings:
        print("  provision + configure breakdown:")
        for label, seconds in sub_timings:
            minutes, secs = divmod(int(round(seconds)), 60)
            print(f"    {label}: {minutes:02d}:{secs:02d}")

    for item in prepared:
        worker = item["worker"]
        record_history(
            action,
            env=env_name,
            name=item["host"],
            service=item["worker_key"],
            provider=str(worker.get("provider", "")),
            resource_id=str(worker.get("resource_id", "")),
            previous_status=item["previous"],
            next_status=str(worker.get("desired_state", "")),
            result_for_code=code,
            error=str(worker.get("last_error", "")),
        )

    return code
