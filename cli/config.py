from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
SSH_CONFIG_DIR = ARTIFACTS_DIR / "ssh_config"
TERRAFORM_ENV_DIR = REPO_ROOT / "IaC" / "terraform" / "environments"
ANSIBLE_PLAYBOOK = REPO_ROOT / "IaC" / "ansible" / "playbooks" / "site.yml"

PROVIDER_CHOICES = ("aws", "digital-ocean", "hetzner", "alibaba-cloud")
ROLE_CHOICES = ("media", "routes", "vclient", "coordinator")
PROVIDER_ENV_FILES = {
    "aws": "aws.env",
    "digital-ocean": "digital-ocean.env",
    "hetzner": "hetzner.env",
    "alibaba-cloud": "alibaba-cloud.env",
}

TERRAFORM_REGISTRY_DIR = REPO_ROOT / "IaC" / "terraform" / "registries"

PROVIDER_CR_REGISTRY_KEY: dict[str, str] = {
    "alibaba-cloud": "ALICLOUD_CR_REGISTRY",
}

IMAGE_SERVICES = {
    "media": "src/livekit",
    "routes": "src/routes",
    "client": "src/client",
    "vclient": "src/vclient",
}

CONTRACT_NETWORK_CHOICES = ("devnet", "testnet", "mainnet")
CONTRACT_ENV_FILE = REPO_ROOT / "secrets" / "contract.env"
CONTRACT_ENV_DIR = REPO_ROOT / "secrets" / "contract"
CONTRACT_PACKAGE_PATH = REPO_ROOT / "src" / "contract"
CONTRACT_ENV_KEYS = (
    "CONTRACT_NETWORK",
    "CONTRACT_PREVIOUS_PACKAGE_ID",
    "CONTRACT_PACKAGE_ID",
    "CONTRACT_REGISTRY_OBJECT_ID",
    "CONTRACT_UPGRADE_CAP_ID",
    "CONTRACT_DEPLOYER_ADDRESS",
    "CONTRACT_PUBLISH_TX_DIGEST",
    "CONTRACT_UPDATE_TX_DIGEST",
    "CONTRACT_GAS_OBJECT_ID",
    "CONTRACT_GAS_OBJECT_VERSION",
    "CONTRACT_GAS_OBJECT_DIGEST",
)
