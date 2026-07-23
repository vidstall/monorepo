from __future__ import annotations

import os
import secrets as py_secrets
import subprocess
import venv
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
IAC_DIR = ROOT / "IaC"
VENV_DIR = IAC_DIR / ".venv"
PULUMI_DIR = IAC_DIR / "pulumi"
ANSIBLE_DIR = IAC_DIR / "ansible"
CONTRACT_DIR = ROOT / "services" / "contract"
CLIENT_WEBUI_DIR = ROOT / "services" / "client"
CLIENT_ENV_PATH = CLIENT_WEBUI_DIR / "client" / ".env"
ADMIN_ENV_PATH = CLIENT_WEBUI_DIR / "admin" / ".env"
RUNTIME_DIR = ROOT / "runtime"
RUNTIME_REGISTRY_TOML = RUNTIME_DIR / "registry.toml"
RUNTIME_TOPOLOGY_TOML = RUNTIME_DIR / "topology.toml"
RUNTIME_HISTORY_TOML = RUNTIME_DIR / "history.toml"
RUNTIME_WALLET_TOML = RUNTIME_DIR / "wallet.toml"
RUNTIME_SCENARIO_LOCK = RUNTIME_DIR / "scenario.lock"
RUNTIME_IMAGES_TOML = RUNTIME_DIR / "images.toml"
SECRETS_DIR = ROOT / "secrets" / "cloud"
REGISTRY_SECRETS_DIR = ROOT / "secrets" / "registry"
WALLET_SECRETS_DIR = ROOT / "secrets" / "wallets"
# Per-service secrets files consumed by deploy_one_service.yml's generic
# "Copy per-service secrets file to host" task (secrets/services/<service>.env
# -> that container's env_file). Currently only bot.env is vidctl-managed
# (see infra.bot_control_token()); the mechanism itself is service-agnostic.
SERVICE_SECRETS_DIR = ROOT / "secrets" / "services"
ADMIN_WALLET_SECRETS_DIR = CLIENT_WEBUI_DIR / "admin" / "public" / ".secrets"
CONTRACT_RUNTIME_DIR = RUNTIME_DIR / "contract"
PULUMI_STATE_DIR = ROOT / "secrets" / "pulumi-state"
PULUMI_PASSPHRASE_FILE = ROOT / "secrets" / "pulumi-passphrase"
GENERATED_INVENTORY = ANSIBLE_DIR / "inventory" / "hosts.generated.yml"

WORKER_DIR = ROOT / "services" / "worker"

# Every worker role's Dockerfile lives at services/worker/apps/<name>/Dockerfile,
# but the Docker build *context* for all of them is the pnpm workspace root
# (WORKER_DIR) so pnpm can resolve the full workspace dependency graph
# (workspace:* deps symlink to sibling packages/*). See DOCKERFILES below for
# the per-service Dockerfile path passed via `docker build -f`.
DOCKER_SERVICES = {
    "cp-daemon": WORKER_DIR,
    "relay": WORKER_DIR,
    "signaling": WORKER_DIR,
    "validator-daemon": WORKER_DIR,
    "bot": WORKER_DIR,
}
DOCKERFILES = {name: WORKER_DIR / "apps" / name / "Dockerfile" for name in DOCKER_SERVICES}


def venv_bin(name: str) -> Path:
    return VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / name


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def mitogen_strategy_path() -> Path | None:
    roots = [VENV_DIR / "lib", VENV_DIR / "Lib"]
    for root in roots:
        if not root.exists():
            continue
        matches = sorted(root.glob("python*/site-packages/ansible_mitogen/plugins/strategy"))
        matches.extend(sorted(root.glob("site-packages/ansible_mitogen/plugins/strategy")))
        for match in matches:
            if match.exists():
                return match
    return None


def command_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(read_env_file(SECRETS_DIR / "aws.env"))
    env.update(read_env_file(SECRETS_DIR / "gcp.env"))
    env.update(read_env_file(SECRETS_DIR / "azure.env"))
    env.update(read_env_file(SECRETS_DIR / "digital-ocean.env"))
    env.update(read_env_file(SECRETS_DIR / "upcloud.env"))
    env.update(read_env_file(SECRETS_DIR / "akamai.env"))
    env.update(read_env_file(SECRETS_DIR / "alibaba.env"))
    env.update(read_env_file(SECRETS_DIR / "tencent.env"))
    env.update(read_env_file(SECRETS_DIR / "cloudflare.env"))

    mappings = {
        "ALICLOUD_ACCESS_KEY": "ALIBABA_CLOUD_ACCESS_KEY_ID",
        "ALICLOUD_SECRET_KEY": "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "ALICLOUD_REGION": "ALIBABA_CLOUD_REGION",
        "ACCOUNT_ID": "CLOUDFLARE_ACCOUNT_ID",
        "API_TOKEN": "CLOUDFLARE_API_TOKEN",
        "ACCESS_KEY_ID": "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "SECRET_ACCESS_KEY": "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "S3_API_ENDPOINT": "CLOUDFLARE_R2_ENDPOINT",
    }
    for old_key, new_key in mappings.items():
        if old_key in env and new_key not in env:
            env[new_key] = env[old_key]

    PULUMI_STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not PULUMI_PASSPHRASE_FILE.exists():
        PULUMI_PASSPHRASE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PULUMI_PASSPHRASE_FILE.write_text(py_secrets.token_urlsafe(48))
        PULUMI_PASSPHRASE_FILE.chmod(0o600)

    env.setdefault("PULUMI_BACKEND_URL", f"file://{PULUMI_STATE_DIR}")
    env.setdefault("PULUMI_CONFIG_PASSPHRASE_FILE", str(PULUMI_PASSPHRASE_FILE))
    env.setdefault("PULUMI_STACK", "devnet")
    env.setdefault("ANSIBLE_CONFIG", str(ANSIBLE_DIR / "ansible.cfg"))
    env.setdefault("ANSIBLE_LOCAL_TEMP", str(ANSIBLE_DIR / "tmp"))

    mitogen_plugins = mitogen_strategy_path()
    if mitogen_plugins:
        env.setdefault("ANSIBLE_STRATEGY_PLUGINS", str(mitogen_plugins))
    return env


def run(
    args: Iterable[str | Path],
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> int:
    return subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        env=env or command_env(),
        input=input_text,
        text=True,
        check=False,
    ).returncode


def ensure_venv() -> None:
    if not VENV_DIR.exists():
        venv.create(VENV_DIR, with_pip=True)


def bootstrap() -> int:
    ensure_venv()
    code = run([venv_bin("python"), "-m", "pip", "install", "-r", IAC_DIR / "requirements.txt"])
    if code != 0:
        return code
    return run(
        [venv_bin("ansible-galaxy"), "collection", "install", "-r", ANSIBLE_DIR / "requirements.yml"]
    )


def git_short_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    tag = result.stdout.strip()
    return tag if result.returncode == 0 and tag else "dev"


def contract_env_path(network: str) -> Path:
    return CONTRACT_RUNTIME_DIR / f"{network}.env"


def wallet_secrets_path(env_name: str) -> Path:
    return WALLET_SECRETS_DIR / f"{env_name}.toml"


def admin_wallet_secrets_path(env_name: str) -> Path:
    return ADMIN_WALLET_SECRETS_DIR / f"{env_name}.toml"


def write_kv_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in values.items() if value]
    path.write_text("\n".join(lines) + "\n")


def sync_env_keys(path: Path, mapping: dict[str, str]) -> bool:
    """Update matching KEY=value lines in an existing .env file in place,
    preserving every other line (comments, unrelated settings) untouched.
    Appends any mapped key not already present. Returns False without
    writing anything if the file doesn't exist -- these frontend .env files
    also carry manually-configured, non-contract settings (signaling URL,
    poll intervals, ...) that vidctl has no source of truth for, so it never
    creates one from scratch."""
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(mapping)
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key and key in remaining:
            updated.append(f"{key}={remaining.pop(key)}")
        else:
            updated.append(line)
    for key, value in remaining.items():
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return True
