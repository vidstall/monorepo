from __future__ import annotations

import sys

from .chain_io import parse_created_object_id
from .deployment import runtime_pubfile_path
from .package import CONTRACT_A, ContractPackage


def real_publish_command(
    env: str,
    gas_budget: str | None,
    pkg: ContractPackage = CONTRACT_A,
    pubfile_path: str | None = None,
) -> list[str]:
    """The real (non-dry-run) publish transaction command for `env`.

    devnet is ephemeral (Sui wipes it periodically) and the persistent
    `sui client publish` path is broken for it in the currently available
    Sui CLI ("the package does not define an `devnet` environment", even
    though it does — Sui's own error message recommends `test-publish`
    instead). `sui client test-publish` (without --dry-run) still executes
    a real on-chain transaction, it just skips recording into
    Published.toml, which is correct for an ephemeral network anyway.
    testnet/mainnet are unaffected and keep using `sui client publish`.
    """
    if env == "devnet":
        return [
            "sui", "client", "test-publish", pkg.dir,
            "--build-env", env,
            "--pubfile-path", pubfile_path or runtime_pubfile_path(env, pkg),
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
        ]
    return [
        "sui", "client", "publish", pkg.dir, "--json",
        *(["--gas-budget", gas_budget] if gas_budget else []),
    ]


def real_upgrade_command(
    env: str,
    upgrade_cap_id: str,
    gas_budget: str | None,
    pubfile_path: str,
    pkg: ContractPackage = CONTRACT_A,
) -> list[str]:
    """The real (non-dry-run) upgrade transaction command for `env`.

    Same devnet special-case as real_publish_command(): the persistent
    `sui client upgrade` path relies on Move.lock's per-environment publish
    record, which devnet publishes never get (they go through test-publish/
    test-upgrade specifically to skip that ephemeral-network bookkeeping) --
    so `sui client upgrade` on devnet fails with the same "package does not
    define a devnet environment" error `real_publish_command` already works
    around. `sui client test-upgrade` (without --dry-run) executes a real
    on-chain upgrade the same way test-publish does for a fresh publish.
    testnet/mainnet are unaffected and keep using `sui client upgrade`.
    """
    if env == "devnet":
        return [
            "sui", "client", "test-upgrade",
            "--upgrade-capability", upgrade_cap_id,
            "--build-env", env,
            "--pubfile-path", pubfile_path,
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
            pkg.dir,
        ]
    return [
        "sui", "client", "upgrade",
        "--upgrade-capability", upgrade_cap_id,
        "--json",
        *(["--gas-budget", gas_budget] if gas_budget else []),
        pkg.dir,
    ]


def test_publish(
    env: str,
    gas_budget: str | None,
    pkg: ContractPackage = CONTRACT_A,
    pubfile_path: str | None = None,
) -> dict | None:
    # Deferred self-import: run_sui_json is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import contract

    pubfile_path = pubfile_path or runtime_pubfile_path(env, pkg)
    _code, result, error = contract.run_sui_json(
        [
            "sui",
            "client",
            "test-publish",
            pkg.dir,
            "--build-env",
            env,
            "--pubfile-path",
            pubfile_path,
            "--dry-run",
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
        ]
    )
    if result is None and error:
        sys.stderr.write(error)
    return result


def test_upgrade(
    env: str,
    upgrade_cap_id: str,
    gas_budget: str | None,
    pubfile_path: str,
    pkg: ContractPackage = CONTRACT_A,
) -> dict | None:
    from .. import contract

    _code, result, error = contract.run_sui_json(
        [
            "sui",
            "client",
            "test-upgrade",
            "--upgrade-capability",
            upgrade_cap_id,
            "--build-env",
            env,
            "--pubfile-path",
            pubfile_path,
            "--dry-run",
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
            pkg.dir,
        ]
    )
    if result is None and error:
        sys.stderr.write(error)
    return result


# module, function, struct type fragment, env-var key -- one shared registry
# object per role, each gated by the AdminCap minted in network_registry's
# `init` (auto-created in the same transaction as publish, see publish()).
# NetworkRegistry/MinerStore/RoleVoteBox are *also* auto-created via their own
# module `init` functions at publish time -- they don't need a create() call.
REGISTRY_CREATE_SPECS: list[tuple[str, str, str, str]] = [
    ("control_plane_registry", "create", "ControlPlaneRegistry", "CP_REGISTRY_ID"),
    ("relay_registry", "create", "RelayRegistry", "RELAY_REGISTRY_ID"),
    ("validator_registry", "create", "ValidatorRegistry", "VALIDATOR_REGISTRY_ID"),
    ("user_registry", "create", "UserRegistry", "USER_REGISTRY_ID"),
    ("room_manager", "create", "RoomManager", "ROOM_MANAGER_ID"),
    ("cp_quorum_sig", "create_config", "QuorumConfigState", "QUORUM_CONFIG_ID"),
]


def create_registries(package_id: str, admin_cap_id: str, gas_budget: str | None) -> dict[str, str] | None:
    """Create the 6 AdminCap-gated shared registries a fresh deployment
    needs (control-plane/relay/validator/user registries, the
    room manager, and the CP-quorum config). Returns env-var-key -> object-id,
    or None (with an error already printed) if any single call fails --
    fail-fast, since a partially-bootstrapped network isn't useful."""
    from .. import contract

    object_ids: dict[str, str] = {}
    for module, function, type_fragment, env_key in REGISTRY_CREATE_SPECS:
        code, result, error = contract.run_sui_json(
            [
                "sui",
                "client",
                "call",
                "--package",
                package_id,
                "--module",
                module,
                "--function",
                function,
                "--args",
                admin_cap_id,
                "--json",
                *(["--gas-budget", gas_budget] if gas_budget else []),
            ]
        )
        if result is None:
            if error:
                sys.stderr.write(error)
            print(f"Failed to create {module}::{function} (for {env_key}).", file=sys.stderr)
            return None

        object_id = parse_created_object_id(result, type_fragment)
        if not object_id:
            print(f"Could not determine object ID for {module}::{function} (for {env_key}).", file=sys.stderr)
            return None
        object_ids[env_key] = object_id
    return object_ids
