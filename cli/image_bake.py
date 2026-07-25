from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib

from . import infra
from .context import RUNTIME_IMAGES_TOML, command_env

# Providers with a real create_vm() adapter AND a documented (even if
# unverified for upcloud/akamai) native stop+create-image CLI path. Distinct
# from infra.PROVIDERS, which also includes tencent (no VM support at all)
# and cloudflare (no compute product) -- neither can ever be baked.
#
# "azure" deliberately excluded -- confirmed live: a managed image captured
# from a bake VM boots fine on the SAME SKU it was captured from in theory,
# but Azure rejected it outright on a real "Standard_D2als_v7" VM with
# InvalidParameter "cannot boot with OS image or disk ... disk controller
# types", something the stock Canonical marketplace image never hits (3/3
# hosts using the stock image booted clean). Combined with the per-region
# LowPriorityCores quota making every bake attempt in an already-occupied
# region fail outright anyway, baking buys Azure nothing here -- every host
# just uses the stock image (Ansible installs Docker fresh at first boot,
# same as it always has for azure-node-1..3).
SUPPORTED_PROVIDERS = ("aws", "gcp", "alibaba", "digitalocean", "upcloud", "akamai", "oci")

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
}

# Bare-literal fallback region, used only when neither an explicit
# scenario-file `region` nor the env var above is set. Mirrors
# regions.py's _DEFAULTS. gcp uses its zone default (matches
# provider_zone(), not _DEFAULTS["gcp"]="US" which is a different concern).
# oci has no known env-var convention yet, so it stays a bare literal.
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


@dataclass(frozen=True)
class BakedImage:
    provider: str
    region: str
    image_id: str
    baked_at: str
    base_image: str
    docker_version: str = ""


def image_key(provider: str, region: str) -> str:
    return f"{provider}:{region}"


def read_runtime_images() -> dict[str, BakedImage]:
    if not RUNTIME_IMAGES_TOML.exists():
        return {}
    try:
        data = tomllib.loads(RUNTIME_IMAGES_TOML.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    images = data.get("images")
    if not isinstance(images, dict):
        return {}
    result: dict[str, BakedImage] = {}
    for key, row in images.items():
        if not isinstance(row, dict):
            continue
        provider, _, region = str(key).partition(":")
        result[str(key)] = BakedImage(
            provider=provider,
            region=region,
            image_id=str(row.get("image_id", "")),
            baked_at=str(row.get("baked_at", "")),
            base_image=str(row.get("base_image", "")),
            docker_version=str(row.get("docker_version", "")),
        )
    return result


def write_runtime_image(provider: str, region: str, image_id: str, base_image: str, docker_version: str = "") -> None:
    images = read_runtime_images()
    key = image_key(provider, region)
    images[key] = BakedImage(
        provider=provider,
        region=region,
        image_id=image_id,
        baked_at=infra.timestamp(),
        base_image=base_image,
        docker_version=docker_version,
    )
    RUNTIME_IMAGES_TOML.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# generated by vidctl utils image-bake", ""]
    for row_key, image in sorted(images.items()):
        lines.append(f"[images.{infra.toml_value(row_key)}]")
        lines.append(f"image_id = {infra.toml_value(image.image_id)}")
        lines.append(f"baked_at = {infra.toml_value(image.baked_at)}")
        lines.append(f"base_image = {infra.toml_value(image.base_image)}")
        lines.append(f"docker_version = {infra.toml_value(image.docker_version)}")
        lines.append("")
    RUNTIME_IMAGES_TOML.write_text("\n".join(lines), encoding="utf-8")


def lookup_image(provider: str, region: str) -> str | None:
    """Find a baked image for (provider, region), with two provider-specific
    special cases: gcp images are project-global (not region-scoped), and
    akamai images auto-replicate across regions -- see plan doc for both.
    oci images are region- AND compartment-scoped (unlike akamai), so they
    deliberately do NOT get the any-region fallback -- exact match only."""
    images = read_runtime_images()
    if provider == "gcp":
        entry = images.get(image_key("gcp", "global"))
        return entry.image_id if entry else None
    exact = images.get(image_key(provider, region))
    if exact:
        return exact.image_id
    if provider == "akamai":
        for entry in images.values():
            if entry.provider == "akamai":
                return entry.image_id
    return None


def list_images() -> int:
    images = read_runtime_images()
    if not images:
        print("No golden images baked yet.")
        return 0
    for key, image in sorted(images.items()):
        print(f"{key}: {image.image_id} (baked {image.baked_at}, base {image.base_image})")
    return 0


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


def provider_cli_env() -> dict[str, str]:
    """command_env(), plus env var aliases the provider CLI tools
    (doctl/aws/gcloud/az/aliyun/upctl/linode-cli) expect but that don't
    match secrets/cloud/*.env's Pulumi-provider-oriented names. Applied
    unconditionally -- an alias irrelevant to whichever CLI is actually
    being invoked in a given call is simply unused, not harmful.

    aws cli reads AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY directly (already
    loaded as-is). aliyun cli reads ALIBABA_CLOUD_ACCESS_KEY_ID/_SECRET
    directly (already loaded as-is via context.py's ALICLOUD_* mapping).
    gcloud/az need an actual authenticated `gcloud auth`/`az login` session,
    not just env vars -- not fixable with a simple alias, flagged as a real
    gap (see the bake plan's risk list) until that bootstrap step exists.
    """
    env = command_env()
    aliases = {
        "DIGITALOCEAN_ACCESS_TOKEN": "DIGITALOCEAN_TOKEN",  # doctl
        "LINODE_CLI_TOKEN": "LINODE_TOKEN",  # linode-cli
        "OCI_CLI_TENANCY": "OCI_TENANCY_OCID",  # oci cli
        "OCI_CLI_USER": "OCI_USER_OCID",
        "OCI_CLI_FINGERPRINT": "OCI_FINGERPRINT",
        "OCI_CLI_REGION": "OCI_REGION",
    }
    for new_key, old_key in aliases.items():
        if env.get(old_key) and not env.get(new_key):
            env[new_key] = env[old_key]
    # OCI_PRIVATE_KEY stores the PEM inline with literal "\n" line breaks
    # (secrets/cloud/*.env is parsed one KEY=VALUE per line); the oci CLI's
    # inline-key env var (OCI_CLI_KEY_CONTENT) expects real newlines.
    if env.get("OCI_PRIVATE_KEY") and not env.get("OCI_CLI_KEY_CONTENT"):
        env["OCI_CLI_KEY_CONTENT"] = env["OCI_PRIVATE_KEY"].replace("\\n", "\n")
    return env


def run_capture(args: list[str], *, timeout: int | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, env=provider_cli_env(), check=False
        )
        return result.returncode, result.stdout, result.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)


def ssh_run(
    address: str, key_path: Path, script: str, *, user: str = "root", timeout: int = 300
) -> tuple[int, str, str]:
    # Non-root logins (Azure "azureuser", AWS/GCP/OCI "ubuntu") can't run the
    # bootstrap/deprovision scripts (apt-get, systemctl, waagent) directly --
    # route through passwordless sudo, which cloud-init default users have by
    # design. Root logins (digitalocean/upcloud/akamai/alibaba) run the
    # script directly, unchanged, since some of those minimal bake images
    # don't even have a `sudo` binary installed.
    remote_cmd = "bash -s" if user == "root" else "sudo -n bash -s"
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=15",
                "-i", str(key_path),
                f"{user}@{address}",
                remote_cmd,
            ],
            input=script,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=command_env(),
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, "", str(exc)


def wait_for_ssh(
    address: str, key_path: Path, *, user: str = "root", attempts: int = 24, delay_seconds: float = 5.0
) -> bool:
    """Poll until sshd on a freshly-created VM actually accepts connections.

    Cloud APIs commonly report a VM as active with an IP assigned well
    before its sshd is actually reachable -- attempting the real bootstrap
    script immediately after that races a "Connection refused" window of a
    few seconds up to roughly a minute, depending on provider/image boot
    time. Default budget: ~24 * 5s = 120s.
    """
    for _ in range(attempts):
        code, _, _ = run_capture(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=8",
                "-o", "BatchMode=yes",
                "-i", str(key_path),
                f"{user}@{address}",
                "true",
            ],
            timeout=12,
        )
        if code == 0:
            return True
        time.sleep(delay_seconds)
    return False


def provider_error(provider: str) -> str | None:
    if provider not in SUPPORTED_PROVIDERS:
        return (
            f"'{provider}' does not support golden-image baking "
            f"(supported: {', '.join(SUPPORTED_PROVIDERS)})."
        )
    return None


def _stop_and_create_image(provider: str, address: str, region: str, resource_id: str, image_name: str) -> tuple[bool, str, str]:
    """Stop the bake VM and create a provider-native image/snapshot from it.

    Returns (success, image_id, error_message). Commands below are the
    documented/best-confidence CLI invocations per provider (see plan doc);
    upcloud and akamai flags are explicitly best-effort/unverified -- confirm
    against `upctl --help` / `linode-cli images create --help` before relying
    on them for a real bake.
    """
    if provider == "aws":
        code, _, err = run_capture(["aws", "ec2", "stop-instances", "--instance-ids", resource_id, "--region", region])
        if code != 0:
            return False, "", f"aws ec2 stop-instances failed: {err}"
        run_capture(["aws", "ec2", "wait", "instance-stopped", "--instance-ids", resource_id, "--region", region], timeout=600)
        code, out, err = run_capture(
            ["aws", "ec2", "create-image", "--instance-id", resource_id, "--name", image_name, "--region", region, "--output", "text", "--query", "ImageId"]
        )
        if code != 0 or not out.strip():
            return False, "", f"aws ec2 create-image failed: {err}"
        return True, out.strip(), ""

    if provider == "gcp":
        code, _, err = run_capture(["gcloud", "compute", "instances", "stop", resource_id, "--zone", region])
        if code != 0:
            return False, "", f"gcloud compute instances stop failed: {err}"
        code, out, err = run_capture(
            ["gcloud", "compute", "images", "create", image_name, "--source-disk", resource_id, "--source-disk-zone", region, "--format", "value(name)"]
        )
        if code != 0 or not out.strip():
            return False, "", f"gcloud compute images create failed: {err}"
        return True, out.strip(), ""

    if provider == "azure":
        # resource_id here is the deterministic VM name azure.py sets
        # (f"{name}-vm"). Resource group naming MUST mirror azure.py's
        # shared_network()/_LEGACY_LOCATION exactly: "eastus2" (the region
        # azure-node-1 was originally deployed in, before multi-region
        # support existed) keeps the bare legacy "xaisen-rg" name; every
        # other region gets its own "xaisen-rg-{region}" group. Verified
        # live: hardcoding the bare name unconditionally 404'd baking in
        # westus2, since that bake VM actually landed in "xaisen-rg-westus2".
        resource_group = "xaisen-rg" if region == "eastus2" else f"xaisen-rg-{region}"
        code, _, err = run_capture(["az", "vm", "deallocate", "--resource-group", resource_group, "--name", resource_id])
        if code != 0:
            return False, "", f"az vm deallocate failed: {err}"
        code, _, err = run_capture(["az", "vm", "generalize", "--resource-group", resource_group, "--name", resource_id])
        if code != 0:
            return False, "", f"az vm generalize failed: {err}"
        # The image MUST NOT live in the same resource group as the bake VM
        # (resource_group above) -- verified live: bake()'s own post-bake
        # teardown removes the bake host's topology row and re-runs
        # `pulumi up`, which then sees NOTHING in topology still needing that
        # region's shared network (azure.py's shared_network()), so it
        # deletes the whole per-region ResourceGroup/VNet/Subnet -- cascading
        # the image's deletion too, since deleting a resource group deletes
        # every resource inside it regardless of what created it (the image
        # is plain `az` output, entirely untracked by Pulumi). All 3 images
        # baked in one run vanished this way before this fix.
        #
        # Fix: put every region's image in its own Pulumi-unmanaged
        # "xaisen-images-<region>" resource group instead -- Pulumi never
        # touches these (doesn't know they exist), so they survive every
        # reconcile regardless of topology state. One shared RG across
        # regions does NOT work, though (confirmed live): unlike a plain
        # resource, a managed image is region-bound to its resource group --
        # `az image create` rejects a source VM whose region doesn't match
        # the target RG's location with "Source Virtual Machine ... does not
        # exist in this Azure location", even though the VM is real and the
        # RG itself accepts resources from anywhere. So the RG's location
        # must equal `region` here, which also means each region needs its
        # own RG (a second `az group create` call with a different
        # `--location` against an already-existing RG name is separately
        # rejected outright -- a resource group's location can't change).
        # `--source` needs the VM's full ARM resource ID (not just its bare
        # name) since it's no longer in the same resource group as `-g`.
        images_rg = f"xaisen-images-{region}"
        code, _, err = run_capture(["az", "group", "create", "--name", images_rg, "--location", region])
        if code != 0:
            return False, "", f"az group create (images RG) failed: {err}"
        code, vm_id, err = run_capture(
            ["az", "vm", "show", "--resource-group", resource_group, "--name", resource_id, "--query", "id", "-o", "tsv"]
        )
        if code != 0 or not vm_id.strip():
            return False, "", f"az vm show (resolving full VM id) failed: {err}"
        # --hyper-v-generation is required -- verified live: `az image create`
        # defaults to V1 and rejects a Gen2 source VM with a mismatch error.
        # azure.py's create_vm() always uses the "22_04-lts-gen2" SKU, so the
        # source is unconditionally Gen2, never V1.
        code, out, err = run_capture(
            [
                "az", "image", "create",
                "--resource-group", images_rg,
                "--name", image_name,
                "--source", vm_id.strip(),
                "--hyper-v-generation", "V2",
                "--query", "id", "-o", "tsv",
            ]
        )
        if code != 0 or not out.strip():
            return False, "", f"az image create failed: {err}"
        return True, out.strip(), ""

    if provider == "alibaba":
        code, _, err = run_capture(["aliyun", "ecs", "StopInstance", "--InstanceId", resource_id, "--RegionId", region])
        if code != 0:
            return False, "", f"aliyun ecs StopInstance failed: {err}"
        code, out, err = run_capture(
            ["aliyun", "ecs", "CreateImage", "--RegionId", region, "--InstanceId", resource_id, "--ImageName", image_name]
        )
        if code != 0 or not out.strip():
            return False, "", f"aliyun ecs CreateImage failed: {err}"
        try:
            image_id = json.loads(out).get("ImageId", "")
        except ValueError:
            image_id = ""
        if not image_id:
            return False, "", f"Could not parse ImageId from aliyun output: {out}"
        return True, image_id, ""

    if provider == "digitalocean":
        code, _, err = run_capture(["doctl", "compute", "droplet-action", "shutdown", resource_id, "--wait"])
        if code != 0:
            return False, "", f"doctl droplet-action shutdown failed: {err}"
        code, out, err = run_capture(
            ["doctl", "compute", "droplet-action", "snapshot", resource_id, "--snapshot-name", image_name, "--wait", "--format", "Resource", "--no-header"]
        )
        if code != 0:
            return False, "", f"doctl droplet-action snapshot failed: {err}"
        # doctl's snapshot action doesn't directly return the new image ID --
        # look it up by name.
        code, out, err = run_capture(["doctl", "compute", "image", "list", "--format", "ID,Name", "--no-header"])
        if code != 0:
            return False, "", f"doctl compute image list failed: {err}"
        for line in out.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2 and parts[1].strip() == image_name:
                return True, parts[0].strip(), ""
        return False, "", f"Could not find snapshot '{image_name}' in doctl compute image list output."

    if provider == "upcloud":
        # Verified live against the UpCloud API (2026-07-25): `resource_id` is
        # the SERVER's UUID (persisted by upcloud.py::create_vm), but
        # `upctl storage clone` needs the boot DISK's own UUID, which is a
        # different identifier -- `upctl server show <server-uuid> -o json`
        # resolves it via storage_devices[].storage. create_vm() always
        # attaches exactly one disk to a bake VM, so there's no ambiguity to
        # resolve (its `boot_disk` field is unreliably "0" even when it's the
        # server's only disk -- don't filter on it, just take the one device).
        code, _, err = run_capture(["upctl", "server", "stop", resource_id, "--wait"])
        if code != 0:
            return False, "", f"upctl server stop failed: {err}"
        code, out, err = run_capture(["upctl", "server", "show", resource_id, "-o", "json"])
        if code != 0 or not out.strip():
            return False, "", f"upctl server show failed while resolving boot disk: {err}"
        try:
            devices = json.loads(out).get("storage_devices") or []
            storage_id = devices[0]["storage"] if devices else None
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            return False, "", f"Could not parse boot disk from 'upctl server show' output: {exc}"
        if not storage_id:
            return False, "", "No storage device found on bake server to clone"
        # `-o json` is required to get a parseable UUID back -- plain/human
        # output only prints "Cloning storage ... done" progress text, no ID
        # (verified live: with -o json, that progress text goes to stderr and
        # stdout is clean single-object JSON with a `uuid` field).
        code, out, err = run_capture(
            ["upctl", "storage", "clone", storage_id, "--title", image_name, "--zone", region, "-o", "json"]
        )
        if code != 0 or not out.strip():
            return False, "", f"upctl storage clone failed: {err}"
        try:
            new_storage_id = json.loads(out)["uuid"]
        except (json.JSONDecodeError, KeyError) as exc:
            return False, "", f"Could not parse cloned storage UUID from 'upctl storage clone' output: {exc}"
        return True, new_storage_id, ""

    if provider == "akamai":
        code, _, err = run_capture(["linode-cli", "linodes", "shutdown", resource_id])
        if code != 0:
            return False, "", f"linode-cli linodes shutdown failed: {err}"
        # shutdown is async (schedules a job) -- poll until the Linode
        # actually reports offline before snapshotting its disk, mirroring
        # aws/gcp's explicit stop-then-wait pattern above.
        for _ in range(24):
            code, out, err = run_capture(
                ["linode-cli", "linodes", "view", resource_id, "--text", "--no-headers", "--format", "status"]
            )
            if code == 0 and out.strip() == "offline":
                break
            time.sleep(5)
        else:
            return False, "", f"Linode {resource_id} did not reach 'offline' status in time: {err}"
        # `images create` snapshots a specific disk, not the Linode itself --
        # resolve the boot disk id (excluding the swap disk) rather than
        # passing the Linode's own id.
        code, out, err = run_capture(
            ["linode-cli", "linodes", "disks-list", resource_id, "--text", "--no-headers", "--format", "id,filesystem"]
        )
        if code != 0 or not out.strip():
            return False, "", f"linode-cli linodes disks-list failed: {err}"
        disk_id = ""
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].strip().lower() != "swap":
                disk_id = parts[0].strip()
                break
        if not disk_id:
            return False, "", f"Could not resolve a non-swap disk id from disks-list output: {out}"
        code, out, err = run_capture(
            ["linode-cli", "images", "create", "--disk_id", disk_id, "--label", image_name, "--text", "--no-headers", "--format", "id"]
        )
        if code != 0 or not out.strip():
            return False, "", f"linode-cli images create failed: {err}"
        return True, out.strip().splitlines()[0], ""

    if provider == "oci":
        code, _, err = run_capture(["oci", "compute", "instance", "action", "--instance-id", resource_id, "--action", "STOP"])
        if code != 0:
            return False, "", f"oci compute instance action --action STOP failed: {err}"
        for _ in range(24):
            code, out, err = run_capture(
                ["oci", "compute", "instance", "get", "--instance-id", resource_id, "--query", "data.\"lifecycle-state\"", "--raw-output"]
            )
            if code == 0 and out.strip() == "STOPPED":
                break
            time.sleep(5)
        else:
            return False, "", f"OCI instance {resource_id} did not reach 'STOPPED' state in time: {err}"
        code, out, err = run_capture(
            ["oci", "compute", "image", "create", "--instance-id", resource_id, "--display-name", image_name, "--query", "data.id", "--raw-output"]
        )
        if code != 0 or not out.strip():
            return False, "", f"oci compute image create failed: {err}"
        return True, out.strip(), ""

    return False, "", f"No image-creation path implemented for provider '{provider}'."


def resolve_bake_region(provider: str, region: str | None) -> str:
    """Pick the region to check/bake for when the caller doesn't already
    have a resolved one (e.g. a first-ever deploy with nothing persisted to
    topology.toml yet). Explicit region wins; otherwise the same env-var
    override provider_region() itself would apply; otherwise
    DEFAULT_BAKE_REGIONS."""
    if region:
        return region
    env_key = _BAKE_REGION_ENV_KEYS.get(provider)
    if env_key:
        override = command_env().get(env_key)
        if override:
            return override
    return DEFAULT_BAKE_REGIONS.get(provider, "")


def ensure_image(provider: str, region: str | None) -> tuple[bool, str]:
    """Bake an image for (provider, region) if one doesn't already exist.

    Returns (ok, error_message). A no-op (ok=True, "") if an image is
    already baked, or if the provider doesn't support baking at all (falls
    through to that provider's stock-image behavior, unchanged).
    """
    if provider not in SUPPORTED_PROVIDERS:
        return True, ""
    resolved_region = resolve_bake_region(provider, region)
    if not resolved_region:
        return False, f"Could not determine a region to bake {provider} into."
    if lookup_image(provider, resolved_region):
        return True, ""
    print(f"No golden image baked yet for {provider}:{resolved_region} -- baking one now...")
    code = bake(provider, resolved_region, True)
    if code != 0:
        return False, f"Baking {provider}:{resolved_region} failed (exit {code})."
    return True, ""


def bake(provider: str, region: str, yes: bool) -> int:
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
    if not wait_for_ssh(address, key_path, user=ssh_user):
        return _abort(
            f"Bake VM '{host}' ({address}) never became SSH-reachable. Left in place for inspection.",
            remove_row=False,
        )

    print(f"Bootstrapping Docker on {address} ...")
    ssh_code, ssh_out, ssh_err = ssh_run(address, key_path, BOOTSTRAP_SCRIPT, user=ssh_user)
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

    if provider == "azure":
        # A dropped connection here (exit 255, "Connection reset by peer" /
        # "kex_exchange_identification") is the EXPECTED outcome, not a
        # failure -- see AZURE_DEPROVISION_SCRIPT's comment. Only a clean
        # non-zero exit with real stderr (e.g. a genuine command error) is
        # worth surfacing; still non-fatal, since the subsequent `az vm
        # deallocate` call is the real gate and will fail loudly on its own
        # if the VM is actually in a bad state.
        ssh_code, _, ssh_err = ssh_run(address, key_path, AZURE_DEPROVISION_SCRIPT, user=ssh_user)
        if ssh_code != 0:
            print(
                f"Azure deprovision SSH round-trip ended without a clean exit (code {ssh_code}: {ssh_err.strip()}) "
                "-- expected, since deprovisioning tears down its own session. Continuing.",
            )

    resource_id = str(resolved.get("resource_id") or host)
    image_name = f"xaisen-golden-{provider}-{resolved_region}-{int(time.time())}"
    print(f"Stopping VM and creating image '{image_name}' ...")
    success, image_id, error_message = _stop_and_create_image(
        provider, address, resolved_region, resource_id, image_name
    )
    if not success:
        return _abort(
            f"Bake VM '{host}' ({address}) image creation failed: {error_message}. Left in place for inspection.",
            remove_row=False,
        )

    write_runtime_image(provider, resolved_region, image_id, base_image="ubuntu-22.04", docker_version=docker_version)
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
