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
        "alibaba_access_key": bool(env.get("ALIBABA_CLOUD_ACCESS_KEY_ID")),
        "alibaba_secret_key": bool(env.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")),
        "alibaba_region": bool(env.get("ALIBABA_CLOUD_REGION")),
        "tencent_credentials": bool(env.get("TENCENTCLOUD_SECRET_ID") and env.get("TENCENTCLOUD_SECRET_KEY")),
        "registry_provider_files": REGISTRY_SECRETS_DIR.exists() and any(REGISTRY_SECRETS_DIR.glob("*.env")),
        "mitogen_strategy_plugins": bool(mitogen_strategy_path()),
    }

    for name, ok in checks.items():
        print(f"{name}: {'ok' if ok else 'missing'}")

    if venv_bin("python").exists():
        imports = (
            "import ansible, ansible_mitogen, pulumi, pulumi_alicloud, "
            "pulumi_aws, pulumi_azure_native, pulumi_digitalocean, pulumi_gcp, "
            "pulumi_tencentcloud, yaml"
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
    return subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


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
