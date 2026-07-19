from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import tomllib

from .context import (
    ADMIN_ENV_PATH,
    CLIENT_ENV_PATH,
    CONTRACT_DIR,
    RUNTIME_DIR,
    contract_env_path,
    read_env_file,
    run,
    sync_env_keys,
    write_kv_env_file,
)

PUBLISHED_TOML = CONTRACT_DIR / "Published.toml"
MOVE_TOML = CONTRACT_DIR / "Move.toml"

# Maps runtime/contract/<env>.env keys to the VITE_* keys read by
# services/client/{client,admin}/src/config.ts. Only keys the frontend apps
# actually consume are included -- CONTRACT_CHAIN_ID, CONTRACT_UPGRADE_CAP_ID,
# CONTRACT_ADMIN_CAP_ID, etc. are deploy-tooling-only and stay out of the sync.
#
# CONTRACT_NETWORK -> VITE_SUI_NETWORK is included for devnet/testnet: both
# frontends' SuiClientProvider (main.tsx) now wires localnet/devnet/testnet.
# mainnet is NOT wired into either app yet -- a mainnet publish will still
# write VITE_SUI_NETWORK=mainnet, which SuiClientProvider will reject at
# runtime. Add a mainnet network entry to both main.tsx files before
# publishing to mainnet through vidctl.
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
}


def sync_frontend_env(deployment: dict[str, str]) -> None:
    """Push the just-published contract's package/registry object IDs into
    services/client/{client,admin}/.env as VITE_* vars, leaving every other
    line (signaling/relay URLs, poll intervals, region, ...) untouched."""
    mapping = {vite_key: deployment.get(key, "") for key, vite_key in FRONTEND_ENV_KEY_MAP.items()}
    mapping = {key: value for key, value in mapping.items() if value}
    if not mapping:
        return
    for path in (CLIENT_ENV_PATH, ADMIN_ENV_PATH):
        if sync_env_keys(path, mapping):
            print(f"Synced contract object IDs -> {path}")
        else:
            print(
                f"Note: {path} not found; skipping frontend env sync (copy {path.name}.example to {path.name} first).",
                file=sys.stderr,
            )


def build(env: str) -> int:
    if env == "devnet":
        sync_devnet_chain_id()
    return run(["sui", "move", "--build-env", env, "build", "--path", CONTRACT_DIR])


def test(env: str) -> int:
    if env == "devnet":
        sync_devnet_chain_id()
    return run(["sui", "move", "--build-env", env, "test", "--path", CONTRACT_DIR])


def check(env: str) -> int:
    code = build(env)
    if code != 0:
        return code
    return test(env)


def sync_devnet_chain_id() -> None:
    """Best-effort: refresh Move.toml's `devnet` chain identifier from the
    live network before a devnet build, since devnet resets its genesis
    (and therefore its chain identifier) periodically and vidctl has no
    other mechanism to detect that drift. Never blocks the build — on any
    failure (no network, sui not on PATH, etc.) it warns and leaves
    Move.toml as-is, since the existing value might still be correct.
    """
    try:
        result = subprocess.run(
            ["sui", "client", "--client.env", "devnet", "chain-identifier", "--json"],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"Warning: could not refresh devnet chain-id ({exc}); using existing Move.toml value.", file=sys.stderr)
        return
    if result.returncode != 0:
        print(
            f"Warning: could not refresh devnet chain-id ({result.stderr.strip() or 'sui command failed'}); "
            "using existing Move.toml value.",
            file=sys.stderr,
        )
        return
    try:
        chain_id = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        print("Warning: could not parse devnet chain-id response; using existing Move.toml value.", file=sys.stderr)
        return

    if not MOVE_TOML.exists():
        return
    text = MOVE_TOML.read_text()
    new_line = f'devnet = "{chain_id}"'
    if re.search(r'(?m)^devnet\s*=\s*".*"$', text):
        updated = re.sub(r'(?m)^devnet\s*=\s*".*"$', new_line, text)
    elif "[environments]" in text:
        updated = text.replace("[environments]", f"[environments]\n{new_line}", 1)
    else:
        return
    if updated != text:
        MOVE_TOML.write_text(updated)
        print(f"Move.toml: devnet chain-id refreshed -> {chain_id}")


def ensure_active_sui_env(env: str) -> int:
    completed = subprocess.run(
        ["sui", "client", "active-env"], capture_output=True, text=True, check=False
    )
    active = completed.stdout.strip()
    if active == env:
        return 0
    print(f"Switching sui client active environment: {active or '(unset)'} -> {env}")
    return run(["sui", "client", "switch", "--env", env])


def publish(
    env: str,
    dry_run: bool,
    yes: bool,
    gas_budget: str | None,
    create_registry_if_missing: bool = False,
    force: bool = False,
) -> int:
    if not dry_run and not yes:
        print("Refusing to publish contract without --dry-run or --yes.", file=sys.stderr)
        return 2

    if env == "devnet":
        sync_devnet_chain_id()

    code = ensure_active_sui_env(env)
    if code != 0:
        return code

    if force:
        if not dry_run:
            clear_published_entry(env)
        deployment: dict[str, str] = {
            key: value
            for key, value in load_deployment(env).items()
            if key in {"CONTRACT_NETWORK", "CONTRACT_CHAIN_ID"}
        }
    else:
        deployment = load_deployment(env)

    existing_package_id = deployment.get("CONTRACT_PACKAGE_ID")
    existing_upgrade_cap_id = deployment.get("CONTRACT_UPGRADE_CAP_ID")
    if existing_package_id:
        if not existing_upgrade_cap_id:
            print(
                f"Cannot upgrade {env}: missing CONTRACT_UPGRADE_CAP_ID in {contract_env_path(env)} "
                "and services/contract/Published.toml.",
                file=sys.stderr,
            )
            return 1
        return upgrade_existing(
            env,
            deployment,
            dry_run,
            gas_budget,
            create_registry_if_missing,
        )

    preview = test_publish(env, gas_budget)
    if preview is None:
        return 1
    if dry_run:
        return 0

    publish_code, publish_result, publish_error = run_sui_json(real_publish_command(env, gas_budget))
    if publish_result is None:
        if publish_error:
            sys.stderr.write(publish_error)
        return publish_code or 1

    package_id = parse_published_package_id(publish_result)
    upgrade_cap_id = parse_upgrade_cap_id(publish_result)
    deployer_address = parse_sender(publish_result)
    publish_tx_digest = parse_transaction_digest(publish_result)
    if not package_id:
        print("Could not determine published package ID.", file=sys.stderr)
        return 1

    # NetworkRegistry/MinerStore/RoleVoteBox/AdminCap are all created by their
    # own modules' `init` functions, which run automatically in this same
    # publish transaction -- no separate call needed, just parse them out.
    admin_cap_id = parse_created_object_id(publish_result, "AdminCap")
    network_registry_id = parse_created_object_id(publish_result, "NetworkRegistry")
    miner_store_id = parse_created_object_id(publish_result, "MinerStore")
    role_vote_box_id = parse_created_object_id(publish_result, "RoleVoteBox")
    if not admin_cap_id:
        print("Could not determine AdminCap object ID from publish.", file=sys.stderr)
        return 1

    registries = create_registries(package_id, admin_cap_id, gas_budget)
    if registries is None:
        return 1

    new_deployment = {
        "CONTRACT_NETWORK": env,
        "CONTRACT_CHAIN_ID": deployment.get("CONTRACT_CHAIN_ID", ""),
        "CONTRACT_PACKAGE_ID": package_id,
        "CONTRACT_ORIGINAL_PACKAGE_ID": package_id,
        "CONTRACT_UPGRADE_CAP_ID": upgrade_cap_id or "",
        "CONTRACT_DEPLOYER_ADDRESS": deployer_address or "",
        "CONTRACT_PUBLISH_TX_DIGEST": publish_tx_digest or "",
        "CONTRACT_ADMIN_CAP_ID": admin_cap_id,
        "NETWORK_REGISTRY_ID": network_registry_id or "",
        "MINER_STORE_ID": miner_store_id or "",
        "ROLE_VOTE_BOX_ID": role_vote_box_id or "",
        **registries,
    }
    write_kv_env_file(contract_env_path(env), new_deployment)
    sync_frontend_env(new_deployment)
    return 0


def real_publish_command(env: str, gas_budget: str | None) -> list[str]:
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
            "sui", "client", "test-publish", CONTRACT_DIR,
            "--build-env", env,
            "--pubfile-path", runtime_pubfile_path(env),
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
        ]
    return [
        "sui", "client", "publish", CONTRACT_DIR, "--json",
        *(["--gas-budget", gas_budget] if gas_budget else []),
    ]


def upgrade_existing(
    env: str,
    deployment: dict[str, str],
    dry_run: bool,
    gas_budget: str | None,
    create_registry_if_missing: bool,
) -> int:
    package_id = deployment["CONTRACT_PACKAGE_ID"]
    upgrade_cap_id = deployment["CONTRACT_UPGRADE_CAP_ID"]
    missing_registry_keys = [env_key for _, _, _, env_key in REGISTRY_CREATE_SPECS if not deployment.get(env_key)]

    if missing_registry_keys and not create_registry_if_missing:
        print(
            f"Refusing to upgrade {env}: missing {', '.join(missing_registry_keys)} in {contract_env_path(env)}. "
            "Add the existing registry object IDs, or rerun with --create-registry-if-missing "
            "to create fresh shared registries for whichever are missing.",
            file=sys.stderr,
        )
        return 1

    if missing_registry_keys and not deployment.get("CONTRACT_ADMIN_CAP_ID"):
        print(
            f"Cannot create missing registries for {env}: no CONTRACT_ADMIN_CAP_ID recorded in "
            f"{contract_env_path(env)}. Add the AdminCap object ID from the original publish.",
            file=sys.stderr,
        )
        return 1

    pubfile_path = write_runtime_pubfile(env, deployment)
    if pubfile_path is None:
        return 1

    preview = test_upgrade(env, upgrade_cap_id, gas_budget, pubfile_path)
    if preview is None:
        return 1
    if dry_run:
        return 0

    upgrade_code, upgrade_result, upgrade_error = run_sui_json(
        [
            "sui",
            "client",
            "upgrade",
            "--upgrade-capability",
            upgrade_cap_id,
            "--json",
            *(["--gas-budget", gas_budget] if gas_budget else []),
            CONTRACT_DIR,
        ]
    )
    if upgrade_result is None:
        if upgrade_error:
            sys.stderr.write(upgrade_error)
        return upgrade_code or 1

    package_id = parse_published_package_id(upgrade_result) or package_id
    upgrade_tx_digest = parse_transaction_digest(upgrade_result)

    registries = {env_key: deployment[env_key] for _, _, _, env_key in REGISTRY_CREATE_SPECS if deployment.get(env_key)}
    if missing_registry_keys:
        created = create_registries(package_id, deployment["CONTRACT_ADMIN_CAP_ID"], gas_budget)
        if created is None:
            return 1
        registries.update(created)

    new_deployment = {
        "CONTRACT_NETWORK": env,
        "CONTRACT_CHAIN_ID": deployment.get("CONTRACT_CHAIN_ID", ""),
        "CONTRACT_PACKAGE_ID": package_id,
        "CONTRACT_ORIGINAL_PACKAGE_ID": deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", deployment["CONTRACT_PACKAGE_ID"]),
        "CONTRACT_UPGRADE_CAP_ID": upgrade_cap_id,
        "CONTRACT_DEPLOYER_ADDRESS": deployment.get("CONTRACT_DEPLOYER_ADDRESS", ""),
        "CONTRACT_PUBLISH_TX_DIGEST": deployment.get("CONTRACT_PUBLISH_TX_DIGEST", ""),
        "CONTRACT_UPGRADE_TX_DIGEST": upgrade_tx_digest or "",
        "CONTRACT_ADMIN_CAP_ID": deployment.get("CONTRACT_ADMIN_CAP_ID", ""),
        "NETWORK_REGISTRY_ID": deployment.get("NETWORK_REGISTRY_ID", ""),
        "MINER_STORE_ID": deployment.get("MINER_STORE_ID", ""),
        "ROLE_VOTE_BOX_ID": deployment.get("ROLE_VOTE_BOX_ID", ""),
        **registries,
    }
    write_kv_env_file(contract_env_path(env), new_deployment)
    sync_frontend_env(new_deployment)
    return 0


def test_publish(env: str, gas_budget: str | None) -> dict | None:
    pubfile_path = runtime_pubfile_path(env)
    _code, result, error = run_sui_json(
        [
            "sui",
            "client",
            "test-publish",
            CONTRACT_DIR,
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
) -> dict | None:
    _code, result, error = run_sui_json(
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
            CONTRACT_DIR,
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
    ("signaling_registry", "create", "SignalingRegistry", "SIGNALING_REGISTRY_ID"),
    ("validator_registry", "create", "ValidatorRegistry", "VALIDATOR_REGISTRY_ID"),
    ("user_registry", "create", "UserRegistry", "USER_REGISTRY_ID"),
    ("room_manager", "create", "RoomManager", "ROOM_MANAGER_ID"),
    ("cp_quorum_sig", "create_config", "QuorumConfigState", "QUORUM_CONFIG_ID"),
]


def create_registries(package_id: str, admin_cap_id: str, gas_budget: str | None) -> dict[str, str] | None:
    """Create the 7 AdminCap-gated shared registries a fresh deployment
    needs (control-plane/relay/signaling/validator/user registries, the
    room manager, and the CP-quorum config). Returns env-var-key -> object-id,
    or None (with an error already printed) if any single call fails --
    fail-fast, since a partially-bootstrapped network isn't useful."""
    object_ids: dict[str, str] = {}
    for module, function, type_fragment, env_key in REGISTRY_CREATE_SPECS:
        code, result, error = run_sui_json(
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


def run_sui_json(args: list[str]) -> tuple[int, dict | None, str]:
    completed = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, check=False)
    output = f"{completed.stdout}{completed.stderr}"
    payload = parse_json_payload(output) if output else None
    return completed.returncode, payload, output


def parse_json_payload(output: str) -> dict | None:
    decoder = json.JSONDecoder()
    best: tuple[int, dict] | None = None
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        score = end
        if "objectChanges" in value:
            score += len(output)
        if "effects" in value:
            score += len(output)
        if best is None or score > best[0]:
            best = (score, value)
    return best[1] if best else None


def load_published_metadata(network: str) -> dict | None:
    if not PUBLISHED_TOML.exists():
        return None
    data = tomllib.loads(PUBLISHED_TOML.read_text())
    return find_network_metadata(data, network)


def clear_published_entry(network: str) -> None:
    """Strip the `[published.<network>]` table out of Published.toml (a "this
    package is already published" marker Sui writes/reads for that build env).
    Used by `--force` to allow a genuinely fresh publish, e.g. when local
    source has diverged from what's actually deployed on-chain (a module was
    renamed/removed) and a normal upgrade is rejected as incompatible.
    """
    if PUBLISHED_TOML.exists():
        lines = PUBLISHED_TOML.read_text().splitlines(keepends=True)
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
        PUBLISHED_TOML.write_text("".join(kept))

    pubfile = Path(runtime_pubfile_path(network))
    if pubfile.exists():
        pubfile.unlink()


def load_deployment(network: str) -> dict[str, str]:
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

    env_values = read_env_file(contract_env_path(network))
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
    chain_id = deployment.get("CONTRACT_CHAIN_ID")
    if not chain_id:
        print(
            f"Cannot upgrade {env}: missing chain id. Add CONTRACT_CHAIN_ID to {contract_env_path(env)}.",
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
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return str(RUNTIME_DIR / f"Pub.{env}.toml")


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


def parse_published_package_id(payload: dict) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "published":
            return change.get("packageId")
    return None


def parse_upgrade_cap_id(payload: dict) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "created" and str(change.get("objectType", "")).endswith("UpgradeCap"):
            return change.get("objectId")
    return None


def parse_created_object_id(payload: dict, type_fragment: str) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "created" and type_fragment in str(change.get("objectType", "")):
            return change.get("objectId")
    return None


def parse_sender(payload: dict) -> str | None:
    input_payload = payload.get("input", {})
    if isinstance(input_payload, dict):
        return input_payload.get("sender")
    return None


def parse_transaction_digest(payload: dict) -> str | None:
    effects = payload.get("effects", {})
    if isinstance(effects, dict):
        return effects.get("transactionDigest")
    return None
