from __future__ import annotations

import json
import sys
from typing import Any

from ..context import ANSIBLE_DIR, CONTRACT_RUNTIME_DIR, PINNED_IMAGES, read_env_file, venv_bin
from .history import record_history
from .secrets import metrics_auth_token, otel_exporter_vars
from .topology import active_stack


def ansible_playbook(
    playbook: str,
    extra_vars: dict[str, Any] | None = None,
    host_limit: str | None = None,
) -> int:
    # Deferred self-import: `run` is patched by tests as a flat cli.infra
    # attribute -- looking it up through the package at call time is what
    # makes that patch take effect here.
    from .. import infra

    executable = venv_bin("ansible-playbook")
    if not executable.exists():
        print("Ansible is missing. Run: ./vidctl bootstrap", file=sys.stderr)
        return 1
    args = [executable, f"playbooks/{playbook}"]
    if host_limit:
        args += ["--limit", host_limit]
    if extra_vars:
        args += ["--extra-vars", json.dumps(extra_vars)]
    return infra.run(args, cwd=ANSIBLE_DIR)


def ansible_inventory() -> int:
    from .. import infra

    executable = venv_bin("ansible-inventory")
    if not executable.exists():
        print("Ansible is missing. Run: ./vidctl bootstrap", file=sys.stderr)
        return 1
    return infra.run([executable, "--list"], cwd=ANSIBLE_DIR)


def ping() -> int:
    code = ansible_playbook("ping.yml")
    record_history("infra ping", env=active_stack(), result_for_code=code)
    return code


def configure(
    host_limit: str | None = None,
    container_state: str = "started",
    extra_vars: dict[str, Any] | None = None,
) -> int:
    all_extra_vars = docker_deploy_extra_vars()
    all_extra_vars["xaisen_container_state"] = container_state
    if extra_vars:
        all_extra_vars.update(extra_vars)
    code = ansible_playbook("site.yml", extra_vars=all_extra_vars, host_limit=host_limit)
    record_history("infra configure", env=active_stack(), result_for_code=code)
    return code


def _otel_extra_vars() -> dict[str, str]:
    """Flat xaisen_otel_exporter_endpoint/headers vars, same style as
    xaisen_metrics_auth_token, derived from otel_exporter_vars()'s
    OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS -- empty strings (not omitted keys)
    when unset, so deploy_one_service.yml's env: combine() can uniformly
    check truthiness without an `is defined` guard."""
    values = otel_exporter_vars()
    return {
        "xaisen_otel_exporter_endpoint": values.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        "xaisen_otel_exporter_headers": values.get("OTEL_EXPORTER_OTLP_HEADERS", ""),
    }


def docker_deploy_extra_vars() -> dict[str, Any]:
    from .. import registry

    try:
        state = registry.read_runtime_registry()
    except ValueError as exc:
        print(f"Skipping docker image deployment: {exc}", file=sys.stderr)
        # Pinned (prometheus) images never touch the private registry read
        # above -- they can still deploy even when no registry provider has
        # been logged into yet.
        return {
            "xaisen_pinned_images": dict(PINNED_IMAGES),
            "xaisen_metrics_auth_token": metrics_auth_token(),
            **_otel_extra_vars(),
        }

    # loadNetworkConfig() (services/worker/packages/shared/src/chain/client.ts)
    # reads PACKAGE_ID/NETWORK_REGISTRY_ID/etc. straight from process.env --
    # it never reads CONTRACT_ENV_PATH itself, that var only tells the app
    # where the file *would* be if it wanted to load it. Parse each
    # runtime/contract/<env>.env here and inject its keys as real container
    # env vars so every worker actually gets its contract config.
    contract_values: dict[str, dict[str, str]] = {
        env_file.stem: read_env_file(env_file)
        for env_file in sorted(CONTRACT_RUNTIME_DIR.glob("*.env"))
    } if CONTRACT_RUNTIME_DIR.exists() else {}
    for values in contract_values.values():
        # Every other key matches loadNetworkConfig()'s expectations
        # verbatim (NETWORK_REGISTRY_ID, CP_REGISTRY_ID, ...) -- only the
        # package id is written as CONTRACT_PACKAGE_ID in the contract file
        # but read as bare PACKAGE_ID by the worker apps. Alias it.
        if "CONTRACT_PACKAGE_ID" in values:
            values.setdefault("PACKAGE_ID", values["CONTRACT_PACKAGE_ID"])
        # cp-daemon's startCapTokenIssuer() bootstrap (index.ts) bypasses
        # loadNetworkConfig() and reads these two raw off process.env under
        # different names than what contract.py's create_registries() writes
        # (CP_REGISTRY_ID / QUORUM_CONFIG_ID). Left unaliased, both come back
        # empty, startCapTokenIssuer's QUORUM_STATE_OBJECT_ID guard fails
        # closed, and cp-daemon crashes on every boot -- which also kills the
        # role-voting loop (role_voting.move) that promotes newly-registered
        # relay/signaling/validator miners out of role_user() into their
        # requested role, so they get stuck failing E_NOT_RELAY/E_NOT_SIGNALING
        # etc. forever. Alias to the names index.ts actually reads.
        if "CP_REGISTRY_ID" in values:
            values.setdefault("CP_REGISTRY_OBJECT_ID", values["CP_REGISTRY_ID"])
        if "QUORUM_CONFIG_ID" in values:
            values.setdefault("QUORUM_STATE_OBJECT_ID", values["QUORUM_CONFIG_ID"])

    extra_vars: dict[str, Any] = {
        "xaisen_images": state.images,
        "xaisen_tags": state.deployed,
        "xaisen_image_digests": state.digests,
        "xaisen_registry_host": state.host,
        "xaisen_contract_values": contract_values,
        "xaisen_pinned_images": dict(PINNED_IMAGES),
        "xaisen_metrics_auth_token": metrics_auth_token(),
        **_otel_extra_vars(),
    }
    try:
        config = registry.provider_config(state.provider, require_credentials=True)
    except ValueError as exc:
        print(f"Skipping registry login: {exc}", file=sys.stderr)
        return extra_vars
    extra_vars["xaisen_registry_username"] = config.username
    extra_vars["xaisen_registry_password"] = config.password
    return extra_vars
