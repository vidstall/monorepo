from __future__ import annotations

import base64
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from .. import infra
from .provider_cli import SUPPORTED_PROVIDERS, provider_error
from .registry import lookup_image, write_runtime_image

# Env var override per provider -- MUST mirror IaC/pulumi/app/common/
# regions.py's _ENV_KEYS exactly (same names, duplicated rather than
# imported since that module lives under the separate Pulumi program's
# Python path). Verified live: without this, a scenario worker that relies
# on an env override instead of an explicit per-worker `region` (e.g.
# azure-node-1 via secrets/cloud/azure.env's AZURE_LOCATION=eastus2) baked
# into the WRONG region ("eastus", the bare hardcoded default) -- wasting a
# full bake cycle on a region nothing in the scenario actually targets.
_BAKE_REGION_ENV_KEYS = {
    "aws": "AWS_REGION",
    "gcp": "GCP_REGION",
    "azure": "AZURE_LOCATION",
    "alibaba": "ALIBABA_CLOUD_REGION",
    "digitalocean": "DIGITALOCEAN_REGION",
    "upcloud": "UPCLOUD_ZONE",
    "akamai": "AKAMAI_REGION",
    "oci": "OCI_REGION",
}

# Bare-literal fallback region, used only when neither an explicit
# scenario-file `region` nor the env var above is set. Mirrors
# regions.py's _DEFAULTS. gcp uses its zone default (matches
# provider_zone(), not _DEFAULTS["gcp"]="US" which is a different concern).
DEFAULT_BAKE_REGIONS = {
    "aws": "us-east-1",
    "gcp": "us-central1-a",
    "azure": "eastus",
    "alibaba": "cn-hangzhou",
    "digitalocean": "nyc3",
    "upcloud": "fi-hel1",
    "akamai": "us-east",
    "oci": "us-ashburn-1",
}

BAKE_SERVICE = "__bake__"

BOOTSTRAP_SCRIPT = """
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io
systemctl enable --now docker
docker --version || true

# Clock sync -- fleet-wide log/metric timestamps (Prometheus/Loki) are
# compared across independently-clocked hosts, so every VM cloned from
# this image needs a real NTP client
# running from first boot, not just whatever the base image happens to
# ship. chrony replaces systemd-timesyncd (stopped first so the two don't
# fight over clock control); `|| true` since not every base image ships
# timesyncd as a unit.
apt-get install -y chrony
systemctl disable --now systemd-timesyncd || true
systemctl enable --now chrony

# Golden-image cleanup -- without this every VM cloned from the resulting
# image would share this bake VM's machine-id, SSH host keys, and cached
# cloud-init first-boot state, which is a real correctness/security problem
# (identical SSH host keys across independently-addressed hosts, stale
# per-instance metadata replayed instead of re-fetched, etc), not cosmetic.
apt-get clean
rm -rf /var/lib/apt/lists/*
if command -v cloud-init >/dev/null 2>&1; then
    cloud-init clean --logs || true
else
    rm -rf /var/lib/cloud/instances/* /var/lib/cloud/data/* || true
fi
rm -f /etc/machine-id
touch /etc/machine-id
rm -f /etc/ssh/ssh_host_*
history -c || true
rm -f /root/.bash_history
"""

# Azure requires Linux deprovisioning before `az vm generalize` -- run this
# right before shutdown, azure-only.
#
# `waagent -deprovision+user` deletes the very login account (azureuser) the
# SSH session is authenticated as -- verified live that systemd's PAM session
# handling kills the whole login session (and everything under it, including
# backgrounded/nohup/setsid/disowned children -- systemd's user-session scope
# doesn't spare them) the moment that account is removed, not just the
# foreground process. So there is no way to keep this SSH round-trip alive
# for its own exit code; Microsoft's own docs describe this exact "the
# connection to the VM will be lost" behavior as normal. See the ssh_run()
# call below: its result is deliberately NOT treated as fatal.
AZURE_DEPROVISION_SCRIPT = "waagent -deprovision+user -force"

# Generous timeout for docker login + N image pulls over the bake VM's own
# network link -- one-time cost paid once per bake, not per fleet VM
# afterwards, so erring toward "wait longer" over "time out and skip a real
# prefetch" is the right tradeoff here.
IMAGE_PREFETCH_TIMEOUT_SECONDS = 900


def _build_image_prefetch_script(
    images: dict[str, str], tags: dict[str, str], registry_host_value: str, username: str, password: str
) -> tuple[str, dict[str, str]]:
    """Builds the remote script that logs into the registry and `docker
    pull`s every service's currently-deployed image:tag -- base64-round-
    trips the username/password so the script text (sent verbatim over SSH
    stdin, see ssh_run()) never needs shell-quoting around whatever
    characters a registry credential happens to contain. Pulling by
    `image:tag` (not by digest) matters: it's what leaves the golden image
    with a LOCAL image tagged exactly `xaisen_images[service]:xaisen_tags
    [service]`, the same repo:tag deploy_one_service.yml's docker_container
    task references and xaisen_needs_pull's docker_image_info check
    inspects -- pulling by digest alone would cache the layers but skip
    tagging them, so the later digest-match check would still see no local
    image under that repo:tag and pull again anyway.

    Returns the script plus the {service: tag} map it actually attempts
    (only services with BOTH an image ref and a resolved deployed tag --
    skips any DOCKER_SERVICES entry never actually deployed yet, same as
    docker_deploy_extra_vars()'s xaisen_tags would leave it unset for)."""
    to_pull = {service: tags[service] for service in sorted(images) if tags.get(service)}
    user_b64 = base64.b64encode(username.encode()).decode()
    pass_b64 = base64.b64encode(password.encode()).decode()
    lines = [
        "set -eu",
        f'echo "{pass_b64}" | base64 -d | docker login {registry_host_value} '
        f'-u "$(echo {user_b64} | base64 -d)" --password-stdin',
    ]
    for service, tag in to_pull.items():
        lines.append(f"docker pull {images[service]}:{tag}")
    lines.append(f"docker logout {registry_host_value} || true")
    return "\n".join(lines) + "\n", to_pull


def _prefetch_app_images(address: str, key_path: Path, ssh_user: str) -> dict[str, str]:
    """Best-effort pre-pull of every currently-deployed app image (relay,
    signaling, cp-daemon, ...) onto the bake VM before it's snapshotted --
    lets a scenario apply that provisions brand-new VMs from this golden
    image skip their first `docker pull` entirely (the existing digest-skip
    optimization in deploy_one_service.yml only helps a VM that's pulled an
    image BEFORE; a fresh VM's docker cache is otherwise empty regardless of
    golden-image status). Docker itself is already baked in by the caller
    before this runs; a failure/skip here never undoes that -- it's purely
    an additional warm-start optimization layered on top, matching
    ensure_image()'s own "best-effort, not a functional requirement"
    philosophy for the same reason (apply.py still installs/pulls fresh via
    Ansible if this never ran, or ran against a since-rotated tag).

    Returns {service: tag} for whatever was actually pulled -- empty if no
    registry is configured/logged into yet, credentials are missing, or the
    SSH round-trip itself fails."""
    from .. import registry

    try:
        state = registry.read_runtime_registry()
    except ValueError as exc:
        print(f"Skipping app-image prefetch: {exc}")
        return {}
    try:
        config = registry.provider_config(state.provider, require_credentials=True)
    except ValueError as exc:
        print(f"Skipping app-image prefetch: {exc}")
        return {}

    # require_credentials=True above already guarantees these are non-None
    # (raises ValueError otherwise) -- `or ""` only satisfies the type
    # checker, never actually used.
    script, to_pull = _build_image_prefetch_script(
        state.images, state.deployed, state.host, config.username or "", config.password or ""
    )
    if not to_pull:
        print("Skipping app-image prefetch: no service has a deployed tag yet.")
        return {}

    # Deferred self-import: ssh_run is patched by tests as a flat
    # cli.image_bake attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import image_bake

    code, out, err = image_bake.ssh_run(address, key_path, script, user=ssh_user, timeout=IMAGE_PREFETCH_TIMEOUT_SECONDS)
    if code != 0:
        print(f"App-image prefetch failed (exit {code}), continuing without it: {err or out}", file=sys.stderr)
        return {}
    return to_pull


def new_bake_worker(env_name: str, provider: str, region: str) -> dict[str, Any]:
    host = f"bake-{provider}-{region}-{int(time.time())}".replace(".", "-").replace(":", "-")
    return {
        "host": host,
        "service": BAKE_SERVICE,
        "provider": provider,
        "env": env_name,
        "backend": "vm",
        "worker_index": 1,
        "desired_state": "running",
        "region": region,
    }


def resolve_bake_region(provider: str, region: str | None) -> str:
    """Pick the region to check/bake for when the caller doesn't already
    have a resolved one (e.g. a first-ever deploy with nothing persisted to
    topology.toml yet). Explicit region wins; otherwise the same env-var
    override provider_region() itself would apply; otherwise
    DEFAULT_BAKE_REGIONS."""
    # Deferred self-import: command_env is patched by tests as a flat
    # cli.image_bake attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import image_bake

    if region:
        return region
    env_key = _BAKE_REGION_ENV_KEYS.get(provider)
    if env_key:
        override = image_bake.command_env().get(env_key)
        if override:
            return override
    return DEFAULT_BAKE_REGIONS.get(provider, "")


def ensure_image(provider: str, region: str | None, force: bool = False) -> tuple[bool, str]:
    """Bake an image for (provider, region) if one doesn't already exist.

    Returns (ok, error_message). A no-op (ok=True, "") if an image is
    already baked, or if the provider doesn't support baking at all (falls
    through to that provider's stock-image behavior, unchanged).

    force=True skips the "already baked" no-op and bakes a fresh image
    unconditionally -- for `vidctl scenario apply --rebake`, so an operator
    who just republished new app images (see bake.py's
    _prefetch_app_images()) can get them pre-pulled into a fresh golden
    image without first deleting the old runtime/images.toml entry by hand.
    """
    # Deferred self-import: bake is patched by tests as a flat cli.image_bake
    # attribute -- looking it up through the package at call time is what
    # makes that patch take effect here.
    from .. import image_bake

    if provider not in SUPPORTED_PROVIDERS:
        return True, ""
    resolved_region = resolve_bake_region(provider, region)
    if not resolved_region:
        return False, f"Could not determine a region to bake {provider} into."
    if not force and lookup_image(provider, resolved_region):
        return True, ""
    if force:
        print(f"Rebaking {provider}:{resolved_region} (--rebake)...")
    else:
        print(f"No golden image baked yet for {provider}:{resolved_region} -- baking one now...")
    code = image_bake.bake(provider, resolved_region, True)
    if code != 0:
        return False, f"Baking {provider}:{resolved_region} failed (exit {code})."
    return True, ""


def bake(provider: str, region: str, yes: bool) -> int:
    # Deferred self-import: wait_for_ssh/ssh_run/_stop_and_create_image are
    # patched by tests as flat cli.image_bake attributes -- looking them up
    # through the package at call time is what makes those patches take
    # effect here.
    from .. import image_bake

    error = provider_error(provider)
    if error:
        print(error, file=sys.stderr)
        return 2
    if not yes:
        print(
            "Refusing to bake a golden image without --yes (this provisions a "
            "real, temporary, billable cloud VM and creates an image/snapshot).",
            file=sys.stderr,
        )
        return 2

    missing = infra.missing_vm_provider_keys(provider)
    if missing:
        print(infra.vm_provider_error(provider, missing), file=sys.stderr)
        return 1

    # ensure_topology (not read_topology) since topology.toml may not exist
    # yet on a first-ever bake -- mirrors cli/scenario.py's same fix.
    env_name = infra.active_stack()
    topology = infra.ensure_topology(env_name)
    bake_worker = new_bake_worker(env_name, provider, region)
    infra.set_vm_defaults(bake_worker, topology)
    # A bake VM must always use the stock image (it's what's being turned
    # INTO a golden image) -- never a previously-baked one.
    bake_worker.pop("image", None)
    topology.setdefault("workers", []).append(bake_worker)
    infra.write_topology(topology)

    host = bake_worker["host"]

    def _abort(message: str, remove_row: bool) -> int:
        print(message, file=sys.stderr)
        if remove_row:
            current = infra.read_topology()
            current["workers"] = [i for i in current.get("workers", []) if i.get("host") != host]
            infra.write_topology(current)
        return 1

    code = infra.pulumi_up(env_name)
    if code != 0:
        return _abort(f"Bake failed provisioning the temporary VM (exit {code}).", remove_row=True)

    code = infra.inventory()
    if code != 0:
        return _abort(
            f"Bake VM '{host}' provisioned but inventory generation failed (exit {code}). "
            "Left in place for inspection -- run 'vidctl infra inventory' manually or clean up by "
            "removing its topology row and re-running pulumi up.",
            remove_row=False,
        )

    infra.persist_vm_resolution(topology, env_name, host, BAKE_SERVICE, provider)
    resolved = infra.find_worker(topology, env_name, host, BAKE_SERVICE, provider) or bake_worker
    resolved_region = str(resolved.get("region") or resolved.get("zone") or region)

    address = infra.host_address(host)
    if not address:
        return _abort(
            f"Bake VM '{host}' provisioned but has no resolved address. Left in place for inspection.",
            remove_row=False,
        )

    key_path = infra.SSH_KEY_ROOT / host / "id_ed25519"
    # Azure/AWS/GCP don't allow root SSH logins (create_vm() configures a
    # cloud-init default user instead -- azureuser/ubuntu) -- see
    # inventory.py's ansible_user propagation. Resolve it the same way the
    # real Ansible deploy path does, instead of the old hardcoded "root"
    # that only ever worked for digitalocean/upcloud/akamai/alibaba.
    ssh_user = infra.host_ssh_user(host)
    print(f"Waiting for SSH on {address} ...")
    if not image_bake.wait_for_ssh(address, key_path, user=ssh_user):
        return _abort(
            f"Bake VM '{host}' ({address}) never became SSH-reachable. Left in place for inspection.",
            remove_row=False,
        )

    print(f"Bootstrapping Docker on {address} ...")
    ssh_code, ssh_out, ssh_err = image_bake.ssh_run(address, key_path, BOOTSTRAP_SCRIPT, user=ssh_user)
    if ssh_code != 0:
        return _abort(
            f"Bake VM '{host}' ({address}) bootstrap script failed (exit {ssh_code}): {ssh_err or ssh_out}. "
            "Left in place for inspection.",
            remove_row=False,
        )
    docker_version = ""
    for line in ssh_out.splitlines():
        if line.startswith("Docker version"):
            docker_version = line.split("Docker version", 1)[-1].split(",")[0].strip()

    print(f"Pre-pulling application images onto {address} ...")
    baked_tags = image_bake._prefetch_app_images(address, key_path, ssh_user)
    if baked_tags:
        print(f"Pre-pulled {len(baked_tags)} application image(s): {', '.join(sorted(baked_tags))}")

    if provider == "azure":
        # A dropped connection here (exit 255, "Connection reset by peer" /
        # "kex_exchange_identification") is the EXPECTED outcome, not a
        # failure -- see AZURE_DEPROVISION_SCRIPT's comment. Only a clean
        # non-zero exit with real stderr (e.g. a genuine command error) is
        # worth surfacing; still non-fatal, since the subsequent `az vm
        # deallocate` call is the real gate and will fail loudly on its own
        # if the VM is actually in a bad state.
        ssh_code, _, ssh_err = image_bake.ssh_run(address, key_path, AZURE_DEPROVISION_SCRIPT, user=ssh_user)
        if ssh_code != 0:
            print(
                f"Azure deprovision SSH round-trip ended without a clean exit (code {ssh_code}: {ssh_err.strip()}) "
                "-- expected, since deprovisioning tears down its own session. Continuing.",
            )

    resource_id = str(resolved.get("resource_id") or host)
    image_name = f"xaisen-golden-{provider}-{resolved_region}-{int(time.time())}"
    print(f"Stopping VM and creating image '{image_name}' ...")
    success, image_id, error_message = image_bake._stop_and_create_image(
        provider, address, resolved_region, resource_id, image_name
    )
    if not success:
        return _abort(
            f"Bake VM '{host}' ({address}) image creation failed: {error_message}. Left in place for inspection.",
            remove_row=False,
        )

    write_runtime_image(
        provider, resolved_region, image_id, base_image="ubuntu-22.04", docker_version=docker_version, baked_tags=baked_tags
    )
    print(f"Baked {provider}:{resolved_region} -> {image_id}")

    current = infra.read_topology()
    current["workers"] = [i for i in current.get("workers", []) if i.get("host") != host]
    infra.write_topology(current)
    teardown_code = infra.pulumi_up(env_name)
    shutil.rmtree(infra.SSH_KEY_ROOT / host, ignore_errors=True)
    if teardown_code != 0:
        print(
            f"Warning: image baked successfully but tearing down bake VM '{host}' failed "
            f"(exit {teardown_code}); it may still be running and billing.",
            file=sys.stderr,
        )
        return teardown_code
    return 0
