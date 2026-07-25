from __future__ import annotations

import sys
from pathlib import Path

import tomllib

from ..context import CONTRACT_DIR, read_env_file, sync_env_keys

PUBLISHED_TOML = CONTRACT_DIR / "Published.toml"
MOVE_TOML = CONTRACT_DIR / "Move.toml"

# Maps runtime/contract/<env>.env keys to the VITE_* keys read by
# services/client/client/src/config.ts. Only keys the frontend app
# actually consumes are included -- CONTRACT_CHAIN_ID, CONTRACT_UPGRADE_CAP_ID,
# CONTRACT_ADMIN_CAP_ID, etc. are deploy-tooling-only and stay out of the sync.
#
# CONTRACT_NETWORK -> VITE_SUI_NETWORK is included for devnet/testnet: the
# frontend's SuiClientProvider (main.tsx) now wires localnet/devnet/testnet.
# mainnet is NOT wired in yet -- a mainnet publish will still write
# VITE_SUI_NETWORK=mainnet, which SuiClientProvider will reject at runtime.
# Add a mainnet network entry to main.tsx before publishing to mainnet
# through vidctl.
FRONTEND_ENV_KEY_MAP: dict[str, str] = {
    "CONTRACT_NETWORK": "VITE_SUI_NETWORK",
    "CONTRACT_PACKAGE_ID": "VITE_PACKAGE_ID",
    "NETWORK_REGISTRY_ID": "VITE_NETWORK_REGISTRY_ID",
    "MINER_STORE_ID": "VITE_MINER_STORE_ID",
    "USER_REGISTRY_ID": "VITE_USER_REGISTRY_ID",
    "RELAY_REGISTRY_ID": "VITE_RELAY_REGISTRY_ID",
    "CP_REGISTRY_ID": "VITE_CONTROL_PLANE_REGISTRY_ID",
    "VALIDATOR_REGISTRY_ID": "VITE_VALIDATOR_REGISTRY_ID",
    "ROOM_MANAGER_ID": "VITE_ROOM_MANAGER_ID",
    "SIGNALING_REGISTRY_ID": "VITE_SIGNALING_REGISTRY_ID",
    "ROLE_VOTE_BOX_ID": "VITE_ROLE_VOTE_BOX_ID",
    "LIVENESS_VOTE_BOX_ID": "VITE_LIVENESS_VOTE_BOX_ID",
}


def sync_frontend_env(deployment: dict[str, str]) -> None:
    """Push the just-published contract's package/registry object IDs into
    services/client/client/.env as VITE_* vars, leaving every other line
    (signaling/relay URLs, poll intervals, region, ...) untouched."""
    # Deferred self-import: CLIENT_ENV_PATH is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    mapping = {vite_key: deployment.get(key, "") for key, vite_key in FRONTEND_ENV_KEY_MAP.items()}
    mapping = {key: value for key, value in mapping.items() if value}
    if not mapping:
        return
    if sync_env_keys(contract.CLIENT_ENV_PATH, mapping):
        print(f"Synced contract object IDs -> {contract.CLIENT_ENV_PATH}")
    else:
        print(
            f"Note: {contract.CLIENT_ENV_PATH} not found; skipping frontend env sync "
            f"(copy {contract.CLIENT_ENV_PATH.name}.example to {contract.CLIENT_ENV_PATH.name} first).",
            file=sys.stderr,
        )


def load_published_metadata(network: str) -> dict | None:
    # Deferred self-import: PUBLISHED_TOML is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    if not contract.PUBLISHED_TOML.exists():
        return None
    data = tomllib.loads(contract.PUBLISHED_TOML.read_text())
    return find_network_metadata(data, network)


def clear_published_entry(network: str) -> None:
    """Strip the `[published.<network>]` table out of Published.toml (a "this
    package is already published" marker Sui writes/reads for that build env).
    Used by `--force` to allow a genuinely fresh publish, e.g. when local
    source has diverged from what's actually deployed on-chain (a module was
    renamed/removed) and a normal upgrade is rejected as incompatible.
    """
    from .. import contract

    if contract.PUBLISHED_TOML.exists():
        lines = contract.PUBLISHED_TOML.read_text().splitlines(keepends=True)
        header = f"[published.{network}]"
        kept: list[str] = []
        skipping = False
        for line in lines:
            if line.strip() == header:
                skipping = True
                continue
            if skipping and line.strip().startswith("[") and line.strip() != header:
                skipping = False
            if not skipping:
                kept.append(line)
        contract.PUBLISHED_TOML.write_text("".join(kept))

    pubfile = Path(runtime_pubfile_path(network))
    if pubfile.exists():
        pubfile.unlink()


def load_deployment(network: str) -> dict[str, str]:
    # Deferred self-import: contract_env_path is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    deployment: dict[str, str] = {}
    published_metadata = load_published_metadata(network)
    if published_metadata:
        if published_metadata.get("chain-id"):
            deployment["CONTRACT_CHAIN_ID"] = published_metadata["chain-id"]
        if published_metadata.get("published-at"):
            deployment["CONTRACT_PACKAGE_ID"] = published_metadata["published-at"]
            deployment["CONTRACT_ORIGINAL_PACKAGE_ID"] = published_metadata.get(
                "original-id",
                published_metadata["published-at"],
            )
        if published_metadata.get("upgrade-capability"):
            deployment["CONTRACT_UPGRADE_CAP_ID"] = published_metadata["upgrade-capability"]

    if not deployment.get("CONTRACT_CHAIN_ID"):
        chain_id = load_move_environment_chain_id(network)
        if chain_id:
            deployment["CONTRACT_CHAIN_ID"] = chain_id

    env_values = read_env_file(contract.contract_env_path(network))
    deployment.update({key: value for key, value in env_values.items() if value})
    return deployment


def load_move_environment_chain_id(network: str) -> str | None:
    if not MOVE_TOML.exists():
        return None
    data = tomllib.loads(MOVE_TOML.read_text())
    environments = data.get("environments", {})
    if isinstance(environments, dict):
        chain_id = environments.get(network)
        if isinstance(chain_id, str):
            return chain_id
    return None


def write_runtime_pubfile(env: str, deployment: dict[str, str]) -> str | None:
    # Deferred self-import: contract_env_path is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    chain_id = deployment.get("CONTRACT_CHAIN_ID")
    if not chain_id:
        print(
            f"Cannot upgrade {env}: missing chain id. Add CONTRACT_CHAIN_ID to {contract.contract_env_path(env)}.",
            file=sys.stderr,
        )
        return None

    package_id = deployment["CONTRACT_PACKAGE_ID"]
    original_package_id = deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", package_id)
    upgrade_cap_id = deployment["CONTRACT_UPGRADE_CAP_ID"]
    pubfile_path = Path(runtime_pubfile_path(env))
    pubfile_path.parent.mkdir(parents=True, exist_ok=True)
    pubfile_path.write_text(
        "\n".join(
            [
                "# generated by vidctl",
                "# this file contains metadata from ephemeral publications",
                "# this file should not be committed to source control",
                "",
                f'build-env = "{env}"',
                f'chain-id = "{chain_id}"',
                "",
                "[[published]]",
                "",
                f'source = {{ local = "{CONTRACT_DIR}" }}',
                f'published-at = "{package_id}"',
                f'original-id = "{original_package_id}"',
                "version = 1",
                'build-config = { flavor = "sui", edition = "2024" }',
                f'upgrade-capability = "{upgrade_cap_id}"',
                "",
            ]
        )
    )
    return str(pubfile_path)


def runtime_pubfile_path(env: str) -> str:
    # Deferred self-import: RUNTIME_DIR is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    contract.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return str(contract.RUNTIME_DIR / f"Pub.{env}.toml")


def find_network_metadata(node: object, network: str) -> dict | None:
    if isinstance(node, dict):
        if network in node and isinstance(node[network], dict):
            return node[network]
        for value in node.values():
            found = find_network_metadata(value, network)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_network_metadata(value, network)
            if found is not None:
                return found
    return None
