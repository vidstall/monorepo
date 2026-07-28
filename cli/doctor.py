from __future__ import annotations

import shutil
import subprocess

from .context import REGISTRY_SECRETS_DIR, ROOT, command_env, mitogen_strategy_path, venv_bin
def run() -> int:
    env = command_env()
    checks = {
        "pulumi_cli": shutil.which("pulumi") is not None,
        "sui_cli": shutil.which("sui") is not None,
        "docker_cli": shutil.which("docker") is not None,
        "docker_daemon": docker_daemon_ok(),
        "venv_python": venv_bin("python").exists(),
        "aws_credentials": bool(env.get("AWS_ACCESS_KEY_ID") or env.get("AWS_PROFILE")),
        "gcp_credentials": bool(env.get("GOOGLE_CREDENTIALS") or env.get("GOOGLE_APPLICATION_CREDENTIALS")),
        "azure_credentials": bool(env.get("ARM_CLIENT_ID") or env.get("AZURE_CLIENT_ID")),
        "digitalocean_token": bool(env.get("DIGITALOCEAN_TOKEN")),
        "upcloud_credentials": bool(env.get("UPCLOUD_TOKEN")),
        "akamai_credentials": bool(env.get("LINODE_TOKEN")),
        "alibaba_access_key": bool(env.get("ALIBABA_CLOUD_ACCESS_KEY_ID")),
        "alibaba_secret_key": bool(env.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")),
        "alibaba_region": bool(env.get("ALIBABA_CLOUD_REGION")),
        "tencent_credentials": bool(env.get("TENCENTCLOUD_SECRET_ID") and env.get("TENCENTCLOUD_SECRET_KEY")),
        "cloudflare_credentials": bool(env.get("CLOUDFLARE_API_TOKEN") and env.get("CLOUDFLARE_ACCOUNT_ID")),
        "cloudflare_r2_credentials": bool(env.get("CLOUDFLARE_R2_ACCESS_KEY_ID") and env.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY")),
        "oci_credentials": bool(
            env.get("OCI_TENANCY_OCID") and env.get("OCI_USER_OCID") and env.get("OCI_FINGERPRINT") and env.get("OCI_PRIVATE_KEY")
        ),
        "registry_provider_files": REGISTRY_SECRETS_DIR.exists() and any(REGISTRY_SECRETS_DIR.glob("*.env")),
        "mitogen_strategy_plugins": bool(mitogen_strategy_path()),
    }

    for name, ok in checks.items():
        if ok:
            print(f"{name}: ok")
        elif name == "docker_daemon":
            print(f"docker_daemon: missing{docker_daemon_hint()}")
        else:
            print(f"{name}: missing")

    # Provider CLIs used only by `vidctl utils image-bake` -- optional,
    # never gate the overall doctor exit code, since most workflows never
    # bake a golden image.
    optional_checks = {
        "aws_cli (image-bake)": shutil.which("aws") is not None,
        "gcloud_cli (image-bake)": shutil.which("gcloud") is not None,
        "az_cli (image-bake)": shutil.which("az") is not None,
        "aliyun_cli (image-bake)": shutil.which("aliyun") is not None,
        "doctl_cli (image-bake)": shutil.which("doctl") is not None,
        "upctl_cli (image-bake)": shutil.which("upctl") is not None,
        "linode_cli (image-bake)": shutil.which("linode-cli") is not None,
        "oci_cli (image-bake)": shutil.which("oci") is not None,
    }
    for name, ok in optional_checks.items():
        print(f"{name}: {'ok' if ok else 'missing'}")

    if venv_bin("python").exists():
        imports = (
            "import ansible, ansible_mitogen, pulumi, pulumi_alicloud, "
            "pulumi_aws, pulumi_azure_native, pulumi_digitalocean, pulumi_gcp, "
            "pulumi_tencentcloud, pulumi_upcloud, pulumi_linode, pulumi_oci, yaml"
        )
        checks["python_dependencies"] = subprocess.call([str(venv_bin("python")), "-c", imports], cwd=ROOT, env=env) == 0
    else:
        checks["python_dependencies"] = False
    print(f"python_dependencies: {'ok' if checks['python_dependencies'] else 'missing'}")

    checks["ansible_inventory"] = ansible_inventory_ok()
    print(f"ansible_inventory: {'ok' if checks['ansible_inventory'] else 'missing'}")

    return 0 if all(checks.values()) else 1


def docker_daemon_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    # Backend-agnostic: `docker info` talks through whatever the active
    # `docker` CLI context / DOCKER_HOST points at, so this works the same
    # whether the daemon is Docker Desktop, Colima, or anything else.
    return subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def docker_daemon_hint() -> str:
    """Extra detail for the `docker_daemon: missing` line, since the fix
    differs by backend (Colima vs. Docker Desktop vs. no docker at all)."""
    if shutil.which("colima") is not None:
        status = subprocess.run(
            ["colima", "status"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if status.returncode != 0:
            return " (colima detected but not running -- run `colima start`)"
        return " (colima is running but the active docker context/DOCKER_HOST doesn't point at it -- run `docker context use colima`)"
    if shutil.which("docker") is not None:
        return " (docker CLI found but daemon unreachable -- start Docker Desktop or another docker backend)"
    return ""


def ansible_inventory_ok() -> bool:
    executable = venv_bin("ansible-inventory")
    if not executable.exists():
        return False
    return subprocess.run(
        [str(executable), "--list"],
        cwd=ROOT / "IaC" / "ansible",
        env=command_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
