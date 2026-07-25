from __future__ import annotations

import subprocess
import time
from pathlib import Path

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
    # Deferred self-import: command_env is patched by tests as a flat
    # cli.image_bake attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import image_bake

    env = image_bake.command_env()
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
    from .. import image_bake

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
            env=image_bake.command_env(),
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
    # Deferred self-import: run_capture is patched by tests as a flat
    # cli.image_bake attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import image_bake

    for _ in range(attempts):
        code, _, _ = image_bake.run_capture(
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
