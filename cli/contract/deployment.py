from __future__ import annotations

import sys
from pathlib import Path

import tomllib

from ..context import CONTRACT_CORE_DIR, read_env_file, sync_env_keys
from .package import CONTRACT_A, ContractPackage

PUBLISHED_TOML = CONTRACT_CORE_DIR / "Published.toml"
MOVE_TOML = CONTRACT_CORE_DIR / "Move.toml"

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
    "ROOM_HEALTH_ALERT_BOX_ID": "VITE_ROOM_HEALTH_ALERT_BOX_ID",
    # dvconf_role_voting (package split, see services/contract-role-voting)
    "CONTRACT_B_PACKAGE_ID": "VITE_ROLE_VOTING_PACKAGE_ID",
}


# Maps runtime/contract/<env>.env keys to the keys read by the bot's shared
# chain-config loader (services/worker/packages/shared/src/chain/client.ts's
# loadNetworkConfig()). Unlike the frontend, almost every key here is the
# SAME name as runtime/contract/<env>.env -- only CONTRACT_PACKAGE_ID and
# CONTRACT_NETWORK get renamed (mirroring the exact alias convention
# cli/infra/ansible.py's docker_deploy_extra_vars() already uses for the
# remote-container path, so local and remote deploys agree on names).
#
# The bot is the only worker app vidctl ever runs LOCALLY (`vidctl utils bot
# start`) -- relay/signaling/cp-daemon/validator-daemon only run in Docker
# containers on remote VMs, which already get correct env injected fresh on
# every deploy, so they carry no staleness risk this sync needs to cover.
BOT_ENV_KEY_MAP: dict[str, str] = {
    "CONTRACT_NETWORK": "SUI_NETWORK",
    "CONTRACT_PACKAGE_ID": "PACKAGE_ID",
    "CONTRACT_ORIGINAL_PACKAGE_ID": "CONTRACT_ORIGINAL_PACKAGE_ID",
    "CONTRACT_B_PACKAGE_ID": "CONTRACT_B_PACKAGE_ID",
    "NETWORK_REGISTRY_ID": "NETWORK_REGISTRY_ID",
    "MINER_STORE_ID": "MINER_STORE_ID",
    "CP_REGISTRY_ID": "CP_REGISTRY_ID",
    "RELAY_REGISTRY_ID": "RELAY_REGISTRY_ID",
    "VALIDATOR_REGISTRY_ID": "VALIDATOR_REGISTRY_ID",
    "USER_REGISTRY_ID": "USER_REGISTRY_ID",
    "ROOM_MANAGER_ID": "ROOM_MANAGER_ID",
    "SIGNALING_REGISTRY_ID": "SIGNALING_REGISTRY_ID",
    "ROLE_VOTE_BOX_ID": "ROLE_VOTE_BOX_ID",
    "LIVENESS_VOTE_BOX_ID": "LIVENESS_VOTE_BOX_ID",
    "ROOM_HEALTH_ALERT_BOX_ID": "ROOM_HEALTH_ALERT_BOX_ID",
}


def sync_bot_env(deployment: dict[str, str]) -> None:
    """Push the just-published contract's package/registry object IDs into
    services/worker/apps/bot/.env, leaving every other line (PRIVATE_KEY,
    CLIENT_URL, ...) untouched. Mirrors sync_frontend_env exactly -- see its
    docstring; this exists because the bot is the one worker app that runs
    locally off a checked-out .env file instead of getting fresh env
    injected per-deploy (see BOT_ENV_KEY_MAP's comment)."""
    from .. import contract

    mapping = {bot_key: deployment.get(key, "") for key, bot_key in BOT_ENV_KEY_MAP.items()}
    mapping = {key: value for key, value in mapping.items() if value}
    if not mapping:
        return
    if sync_env_keys(contract.BOT_ENV_PATH, mapping):
        print(f"Synced contract object IDs -> {contract.BOT_ENV_PATH}")
    else:
        print(
            f"Note: {contract.BOT_ENV_PATH} not found; skipping bot env sync "
            f"(copy {contract.BOT_ENV_PATH.name}.example to {contract.BOT_ENV_PATH.name} first).",
            file=sys.stderr,
        )


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


def load_published_metadata(network: str, pkg: ContractPackage = CONTRACT_A) -> dict | None:
    # Deferred self-import: PUBLISHED_TOML is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here. Only package A's
    # default path goes through that patchable attribute; package B (never
    # exercised by the existing single-package test suite) reads straight
    # off its own directory.
    from .. import contract

    published_toml = contract.PUBLISHED_TOML if pkg is CONTRACT_A else pkg.dir / "Published.toml"
    if not published_toml.exists():
        return None
    data = tomllib.loads(published_toml.read_text())
    return find_network_metadata(data, network)


def clear_published_entry(network: str, pkg: ContractPackage = CONTRACT_A) -> None:
    """Strip the `[published.<network>]` table out of Published.toml (a "this
    package is already published" marker Sui writes/reads for that build env).
    Used by `--force` to allow a genuinely fresh publish, e.g. when local
    source has diverged from what's actually deployed on-chain (a module was
    renamed/removed) and a normal upgrade is rejected as incompatible.
    """
    from .. import contract

    published_toml = contract.PUBLISHED_TOML if pkg is CONTRACT_A else pkg.dir / "Published.toml"
    if published_toml.exists():
        lines = published_toml.read_text().splitlines(keepends=True)
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
        published_toml.write_text("".join(kept))

    pubfile = Path(runtime_pubfile_path(network, pkg))
    if pubfile.exists():
        pubfile.unlink()


def load_deployment(network: str, pkg: ContractPackage = CONTRACT_A) -> dict[str, str]:
    # Deferred self-import: contract_env_path is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    prefix = pkg.env_prefix
    deployment: dict[str, str] = {}
    published_metadata = load_published_metadata(network, pkg)
    if published_metadata:
        if published_metadata.get("chain-id"):
            deployment[f"{prefix}_CHAIN_ID"] = published_metadata["chain-id"]
        if published_metadata.get("published-at"):
            deployment[f"{prefix}_PACKAGE_ID"] = published_metadata["published-at"]
            deployment[f"{prefix}_ORIGINAL_PACKAGE_ID"] = published_metadata.get(
                "original-id",
                published_metadata["published-at"],
            )
        if published_metadata.get("upgrade-capability"):
            deployment[f"{prefix}_UPGRADE_CAP_ID"] = published_metadata["upgrade-capability"]

    if not deployment.get(f"{prefix}_CHAIN_ID"):
        chain_id = load_move_environment_chain_id(network, pkg)
        if chain_id:
            deployment[f"{prefix}_CHAIN_ID"] = chain_id

    # Both packages' object IDs live in the SAME runtime/contract/<env>.env
    # file (distinguished by prefix) -- this reads the whole file, not just
    # this pkg's keys, so callers that need to preserve the OTHER package's
    # already-recorded keys (see publish.py's merge-before-write) have them.
    env_values = read_env_file(contract.contract_env_path(network))
    deployment.update({key: value for key, value in env_values.items() if value})
    return deployment


def load_move_environment_chain_id(network: str, pkg: ContractPackage = CONTRACT_A) -> str | None:
    move_toml = MOVE_TOML if pkg is CONTRACT_A else pkg.dir / "Move.toml"
    if not move_toml.exists():
        return None
    data = tomllib.loads(move_toml.read_text())
    environments = data.get("environments", {})
    if isinstance(environments, dict):
        chain_id = environments.get(network)
        if isinstance(chain_id, str):
            return chain_id
    return None


def _pubfile_entry_lines(dir_path: Path, package_id: str, original_package_id: str, upgrade_cap_id: str) -> list[str]:
    lines = [
        "[[published]]",
        "",
        f'source = {{ local = "{dir_path}" }}',
        f'published-at = "{package_id}"',
        f'original-id = "{original_package_id}"',
        "version = 1",
        'build-config = { flavor = "sui", edition = "2024" }',
    ]
    if upgrade_cap_id:
        lines.append(f'upgrade-capability = "{upgrade_cap_id}"')
    lines.append("")
    return lines


def _dependency_pubfile_entries(env: str, dependency_packages: tuple[ContractPackage, ...]) -> list[str]:
    """Build [[published]] entries for each already-published LOCAL dependency
    of the package about to be published/upgraded. Needed because devnet
    publishes go through `sui client test-publish`/`test-upgrade` (see
    real_publish_command's docstring), which never writes a normal Move.lock
    [environments] entry -- so a package with a `{ local = ... }` dependency on
    another vidctl-managed package (e.g. dvconf_role_voting -> dvconf_contracts)
    can't resolve that dependency's on-chain address at publish time without
    this ephemeral pubfile mechanism (`--pubfile-path`)."""
    lines: list[str] = []
    for dep_pkg in dependency_packages:
        dep_deployment = load_deployment(env, dep_pkg)
        dep_prefix = dep_pkg.env_prefix
        dep_package_id = dep_deployment.get(f"{dep_prefix}_PACKAGE_ID")
        if not dep_package_id:
            continue
        dep_original_id = dep_deployment.get(f"{dep_prefix}_ORIGINAL_PACKAGE_ID", dep_package_id)
        dep_upgrade_cap_id = dep_deployment.get(f"{dep_prefix}_UPGRADE_CAP_ID", "")
        lines.extend(_pubfile_entry_lines(dep_pkg.dir, dep_package_id, dep_original_id, dep_upgrade_cap_id))
    return lines


def write_runtime_pubfile(
    env: str,
    deployment: dict[str, str],
    pkg: ContractPackage = CONTRACT_A,
    dependency_packages: tuple[ContractPackage, ...] = (),
) -> str | None:
    # Deferred self-import: contract_env_path is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    prefix = pkg.env_prefix
    chain_id = deployment.get(f"{prefix}_CHAIN_ID")
    if not chain_id:
        print(
            f"Cannot upgrade {env}: missing chain id. Add {prefix}_CHAIN_ID to {contract.contract_env_path(env)}.",
            file=sys.stderr,
        )
        return None

    package_id = deployment[f"{prefix}_PACKAGE_ID"]
    original_package_id = deployment.get(f"{prefix}_ORIGINAL_PACKAGE_ID", package_id)
    upgrade_cap_id = deployment[f"{prefix}_UPGRADE_CAP_ID"]
    pubfile_path = Path(runtime_pubfile_path(env, pkg))
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
                *_pubfile_entry_lines(pkg.dir, package_id, original_package_id, upgrade_cap_id),
                *_dependency_pubfile_entries(env, dependency_packages),
            ]
        )
    )
    return str(pubfile_path)


def write_dependency_pubfile(
    env: str,
    pkg: ContractPackage,
    dependency_packages: tuple[ContractPackage, ...],
) -> str | None:
    """Like write_runtime_pubfile, but for a FRESH publish -- `pkg` has no
    package_id of its own yet, so there's no self entry, only entries for its
    already-published local dependencies (see _dependency_pubfile_entries).
    Returns None if none of the dependencies have a recorded package_id
    (nothing to resolve; caller's normal build/publish flow will surface the
    real "unpublished dependency" error itself)."""
    entries = _dependency_pubfile_entries(env, dependency_packages)
    if not entries:
        return None

    chain_id = ""
    if dependency_packages:
        first = dependency_packages[0]
        chain_id = load_deployment(env, first).get(f"{first.env_prefix}_CHAIN_ID", "")

    pubfile_path = Path(runtime_pubfile_path(env, pkg))
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
                *entries,
            ]
        )
    )
    return str(pubfile_path)


def runtime_pubfile_path(env: str, pkg: ContractPackage = CONTRACT_A) -> str:
    # Deferred self-import: RUNTIME_DIR is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    contract.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if pkg is CONTRACT_A:
        return str(contract.RUNTIME_DIR / f"Pub.{env}.toml")
    return str(contract.RUNTIME_DIR / f"Pub.{env}.{pkg.slug}.toml")


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
