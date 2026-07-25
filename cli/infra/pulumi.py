from __future__ import annotations

import json
import subprocess
from typing import Any

from ..context import PULUMI_DIR
from ._constants import SERVICE_PORTS, VM_INSTANCE_SIZE_OVERRIDES, VM_INSTANCE_SIZES
from .topology import find_pinned_alibaba_worker, find_worker


def pulumi_stack(default: str | None = None) -> str:
    from .. import infra

    return default or infra.command_env().get("PULUMI_STACK", "dev")


def select_or_create_stack(stack: str) -> int:
    # Deferred self-import: command_env/run are patched by tests as flat
    # cli.infra attributes -- looking them up through the package at call
    # time is what makes those patches take effect here.
    from .. import infra

    env = infra.command_env()
    env["PULUMI_STACK"] = stack
    selected = subprocess.run(
        ["pulumi", "stack", "select", stack],
        cwd=PULUMI_DIR,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if selected.returncode == 0:
        print(f"Selected Pulumi stack {stack}")
        return 0
    return infra.run(["pulumi", "stack", "init", stack], cwd=PULUMI_DIR, env=env)


def pulumi_up(
    stack: str,
    parallel: int | None = None,
    targets: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> int:
    from .. import infra

    env = infra.command_env()
    env["PULUMI_STACK"] = stack
    if extra_env:
        env.update(extra_env)
    args = ["pulumi", "up", "--yes", "--stack", stack]
    for target in targets or []:
        args.extend(["--target", target])
    if parallel is not None:
        args.extend(["--parallel", str(parallel)])
    return infra.run(args, cwd=PULUMI_DIR, env=env)


def stack_has_urns(stack: str, urns: list[str]) -> bool:
    from .. import infra

    try:
        raw = subprocess.check_output(
            ["pulumi", "stack", "export", "--stack", stack],
            cwd=PULUMI_DIR,
            env=infra.command_env(),
            text=True,
        )
        existing = {res.get("urn") for res in json.loads(raw).get("deployment", {}).get("resources", [])}
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return False
    return all(urn in existing for urn in urns)


def alibaba_vm_target_urns(
    stack: str,
    host: str,
    service: str,
    has_service_port: bool,
) -> list[str]:
    prefix = f"urn:pulumi:{stack}::xaisen-iac::"
    resources = [
        ("pulumi:providers:alicloud", f"{host}-vm-provider"),
        ("alicloud:vpc/network:Network", f"{host}-vm-vpc"),
        ("alicloud:vpc/switch:Switch", f"{host}-vm-vswitch"),
        ("alicloud:ecs/keyPair:KeyPair", f"{host}-vm-key"),
        ("alicloud:ecs/securityGroup:SecurityGroup", f"{host}-vm-sg"),
        ("alicloud:ecs/securityGroupRule:SecurityGroupRule", f"{host}-vm-sg-ssh"),
        ("alicloud:ecs/instance:Instance", f"{host}-vm"),
    ]
    # TODO: relay needs UDP security-group rules for its RTC/pipe port ranges
    # (10000-10100, 40000-40100 — see services/worker/apps/relay/.env.example),
    # which this single-TCP-port model doesn't express yet. Only the plain
    # service port (e.g. relay's WS_PORT, signaling's SIGNALING_PORT) is
    # opened below until that's designed.
    if has_service_port:
        resources.append(("alicloud:ecs/securityGroupRule:SecurityGroupRule", f"{host}-vm-sg-port"))
    return [f"{prefix}{resource_type}::{resource_name}" for resource_type, resource_name in resources]


def persist_vm_resolution(
    topology: dict[str, Any],
    env_name: str,
    host: str,
    service: str,
    provider: str,
) -> None:
    """Copy the region/zone/size Pulumi resolved for this VM back into
    topology.toml.

    Originally alibaba-only (spot-search can land on a different region/size
    than requested); generalized to every provider so runtime/images.toml's
    per-(provider, region) golden-image lookup in set_vm_defaults() has a
    real region to key off after the first deploy, for providers whose
    compute module doesn't otherwise persist one. Best-effort: a failure here
    shouldn't fail an otherwise-successful deploy, it just means the next run
    re-resolves the default instead of reusing what got recorded.
    """
    from .. import infra

    try:
        raw = subprocess.check_output(
            ["pulumi", "stack", "output", "topology", "--json", "--stack", env_name],
            cwd=PULUMI_DIR,
            env=infra.command_env(),
            text=True,
        )
        remote_topology = json.loads(raw)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return

    for remote_worker in remote_topology.get("workers", []):
        if (
            remote_worker.get("host") == host
            and remote_worker.get("service") == service
            and remote_worker.get("provider") == provider
            and remote_worker.get("env", env_name) == env_name
        ):
            local_worker = find_worker(topology, env_name, host, service, provider)
            if local_worker is not None:
                if remote_worker.get("region"):
                    local_worker["region"] = remote_worker["region"]
                if remote_worker.get("zone"):
                    local_worker["zone"] = remote_worker["zone"]
                if remote_worker.get("size"):
                    local_worker["size"] = remote_worker["size"]
                if remote_worker.get("resource_id"):
                    local_worker["resource_id"] = remote_worker["resource_id"]
            return


def ensure_ssh_keypair(worker: dict[str, Any]) -> str:
    from .. import infra

    host = str(worker["host"])
    key_dir = infra.SSH_KEY_ROOT / host
    private_key = key_dir / "id_ed25519"
    if not private_key.exists():
        key_dir.mkdir(parents=True, exist_ok=True)
        infra.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(private_key),
                "-C",
                f"xaisen-{host}",
            ]
        )
        private_key.chmod(0o600)
        (key_dir / "id_ed25519.pub").chmod(0o644)
    return f"runtime/ssh_key/{host}"


def set_vm_defaults(
    worker: dict[str, Any],
    topology: dict[str, Any],
    find_instance_type: bool = False,
    size: str | None = None,
    region: str | None = None,
    worker_index: int = 1,
) -> None:
    service = str(worker.get("service", ""))
    provider = str(worker.get("provider", ""))
    # relay/signaling/bot have a real listening port -- cp-daemon/
    # validator-daemon (SERVICE_PORTS has no entry for them, so base_port is
    # 0) are exactly the services this count-prefix feature was built for
    # and have zero port-collision risk regardless of replica count. For
    # services with a real port, offset each replica's host port by
    # (worker_index - 1) so multiple workers on one droplet don't bind
    # the same port. NOTE: this does NOT extend to relay's hardcoded UDP RTC
    # ranges (10000-10100/40000-40100, see deploy_one_service.yml) -- running
    # more than one relay replica on the same host will still collide there;
    # that's a known, unaddressed limitation, not a bug.
    base_port = SERVICE_PORTS.get(service, 0)
    worker.setdefault("port", base_port + (worker_index - 1) if base_port else 0)

    if size:
        # Explicit --size always wins over any default/pin below, and
        # persists on the topology row for subsequent restarts. When
        # colocating multiple services under one --host, every call sharing
        # that host must agree (enforced by program.py's merge step).
        worker["size"] = size

    if region:
        # Same "explicit always wins, persists on the topology row" shape as
        # size above -- lets a scenario file's declared region actually
        # steer the real deploy, not just which region image_bake bakes
        # into for it (cli/scenario.py's ensure_image()/DEFAULT_BAKE_REGIONS
        # would otherwise pick a bake target this VM never actually uses).
        worker["region"] = region

    if provider == "alibaba":
        if find_instance_type:
            worker.pop("region", None)
            worker.pop("size", None)
        elif not (worker.get("region") and worker.get("size")):
            pinned = find_pinned_alibaba_worker(topology, service, provider)
            if pinned:
                worker["region"] = pinned["region"]
                worker["size"] = pinned["size"]
    else:
        default_size = VM_INSTANCE_SIZE_OVERRIDES.get((provider, service), VM_INSTANCE_SIZES.get(provider, ""))
        worker.setdefault("size", default_size)

    if not worker.get("image"):
        from .. import image_bake

        region = str(worker.get("region") or worker.get("zone") or "")
        if region:
            baked = image_bake.lookup_image(provider, region)
            if baked:
                worker["image"] = baked

    worker["ssh_key_dir"] = ensure_ssh_keypair(worker)
