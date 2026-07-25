from __future__ import annotations

import sys

from ..context import write_kv_env_file
from .build_test import ensure_active_sui_env
from .chain_io import (
    parse_created_object_id,
    parse_published_package_id,
    parse_sender,
    parse_transaction_digest,
    parse_upgrade_cap_id,
)
from .deployment import clear_published_entry, load_deployment, sync_frontend_env, write_runtime_pubfile
from .publish_ops import (
    REGISTRY_CREATE_SPECS,
    real_publish_command,
    real_upgrade_command,
    test_publish,
    test_upgrade,
)


def publish(
    env: str,
    dry_run: bool,
    yes: bool,
    gas_budget: str | None,
    create_registry_if_missing: bool = False,
    force: bool = False,
) -> int:
    # Deferred self-import: contract_env_path/run_sui_json/
    # sync_devnet_chain_id/upgrade_existing are patched by tests as flat
    # cli.contract attributes -- looking them up through the package at
    # call time is what makes those patches take effect here.
    from .. import contract

    if not dry_run and not yes:
        print("Refusing to publish contract without --dry-run or --yes.", file=sys.stderr)
        return 2

    live_chain_id = contract.sync_devnet_chain_id() if env == "devnet" else None

    code = ensure_active_sui_env(env)
    if code != 0:
        return code

    deployment = load_deployment(env)

    if not force and live_chain_id:
        # devnet is wiped periodically, which mints a new chain-id -- any
        # package/upgrade-cap recorded against the OLD chain-id no longer
        # exists on-chain, so a normal upgrade is impossible (Sui itself
        # rejects it: "cannot be used to publish to chain with id ...").
        # Detect that here and fall back to a fresh publish automatically,
        # the same recovery `--force` provides manually, so a scenario apply
        # survives a devnet reset without operator intervention.
        recorded_chain_id = deployment.get("CONTRACT_CHAIN_ID")
        if recorded_chain_id and recorded_chain_id != live_chain_id:
            print(
                f"devnet chain-id changed ({recorded_chain_id} -> {live_chain_id}); the network was "
                "reset since the last publish, so the recorded package/upgrade-cap no longer exist "
                "there. Forcing a fresh publish instead of an upgrade.",
            )
            force = True

    if force:
        if not dry_run:
            clear_published_entry(env)
        deployment = {
            key: value
            for key, value in load_deployment(env).items()
            if key in {"CONTRACT_NETWORK", "CONTRACT_CHAIN_ID"}
        }
        if live_chain_id:
            # load_deployment() re-reads runtime/contract/<env>.env, whose
            # own CONTRACT_CHAIN_ID may still be the stale pre-reset value --
            # always prefer the just-fetched live one when we have it.
            deployment["CONTRACT_CHAIN_ID"] = live_chain_id

    existing_package_id = deployment.get("CONTRACT_PACKAGE_ID")
    existing_upgrade_cap_id = deployment.get("CONTRACT_UPGRADE_CAP_ID")
    if existing_package_id:
        if not existing_upgrade_cap_id:
            print(
                f"Cannot upgrade {env}: missing CONTRACT_UPGRADE_CAP_ID in {contract.contract_env_path(env)} "
                "and services/contract/Published.toml.",
                file=sys.stderr,
            )
            return 1
        return contract.upgrade_existing(
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

    publish_code, publish_result, publish_error = contract.run_sui_json(real_publish_command(env, gas_budget))
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
    liveness_vote_box_id = parse_created_object_id(publish_result, "LivenessVoteBox")
    if not admin_cap_id:
        print("Could not determine AdminCap object ID from publish.", file=sys.stderr)
        return 1

    registries = contract.create_registries(package_id, admin_cap_id, gas_budget)
    if registries is None:
        return 1

    new_deployment = {
        "CONTRACT_NETWORK": env,
        # Prefer the just-fetched live chain-id over whatever's in
        # `deployment` (which can still be a stale pre-reset value via
        # load_deployment()'s env-file merge) so runtime/contract/<env>.env
        # always records an accurate chain-id for the next publish's reset
        # check above.
        "CONTRACT_CHAIN_ID": live_chain_id or deployment.get("CONTRACT_CHAIN_ID", ""),
        "CONTRACT_PACKAGE_ID": package_id,
        "CONTRACT_ORIGINAL_PACKAGE_ID": package_id,
        "CONTRACT_UPGRADE_CAP_ID": upgrade_cap_id or "",
        "CONTRACT_DEPLOYER_ADDRESS": deployer_address or "",
        "CONTRACT_PUBLISH_TX_DIGEST": publish_tx_digest or "",
        "CONTRACT_ADMIN_CAP_ID": admin_cap_id,
        "NETWORK_REGISTRY_ID": network_registry_id or "",
        "MINER_STORE_ID": miner_store_id or "",
        "ROLE_VOTE_BOX_ID": role_vote_box_id or "",
        "LIVENESS_VOTE_BOX_ID": liveness_vote_box_id or "",
        **registries,
    }
    write_kv_env_file(contract.contract_env_path(env), new_deployment)
    sync_frontend_env(new_deployment)
    return 0


def upgrade_existing(
    env: str,
    deployment: dict[str, str],
    dry_run: bool,
    gas_budget: str | None,
    create_registry_if_missing: bool,
) -> int:
    # Deferred self-import: contract_env_path/run_sui_json are patched by
    # tests as flat cli.contract attributes -- looking them up through the
    # package at call time is what makes those patches take effect here.
    from .. import contract

    package_id = deployment["CONTRACT_PACKAGE_ID"]
    upgrade_cap_id = deployment["CONTRACT_UPGRADE_CAP_ID"]
    missing_registry_keys = [env_key for _, _, _, env_key in REGISTRY_CREATE_SPECS if not deployment.get(env_key)]

    if missing_registry_keys and not create_registry_if_missing:
        print(
            f"Refusing to upgrade {env}: missing {', '.join(missing_registry_keys)} in {contract.contract_env_path(env)}. "
            "Add the existing registry object IDs, or rerun with --create-registry-if-missing "
            "to create fresh shared registries for whichever are missing.",
            file=sys.stderr,
        )
        return 1

    if missing_registry_keys and not deployment.get("CONTRACT_ADMIN_CAP_ID"):
        print(
            f"Cannot create missing registries for {env}: no CONTRACT_ADMIN_CAP_ID recorded in "
            f"{contract.contract_env_path(env)}. Add the AdminCap object ID from the original publish.",
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

    upgrade_code, upgrade_result, upgrade_error = contract.run_sui_json(
        real_upgrade_command(env, upgrade_cap_id, gas_budget, pubfile_path)
    )
    if upgrade_result is None:
        if upgrade_error:
            sys.stderr.write(upgrade_error)
        return upgrade_code or 1

    package_id = parse_published_package_id(upgrade_result) or package_id
    upgrade_tx_digest = parse_transaction_digest(upgrade_result)

    # A module ADDED in this upgrade (e.g. liveness_voting) has its `init` run as
    # part of the SAME upgrade transaction, auto-creating any shared object it
    # declares -- same as a fresh publish, just discovered in objectChanges here
    # instead. Falls back to whatever was already recorded (a no-op re-upgrade
    # after the object already exists, or an env that hasn't upgraded yet).
    liveness_vote_box_id = parse_created_object_id(upgrade_result, "LivenessVoteBox") or deployment.get(
        "LIVENESS_VOTE_BOX_ID", ""
    )
    # Sui pins an event struct's type to whichever package FIRST DEFINED it,
    # forever -- not the latest upgraded package. liveness_voting was added in
    # a later upgrade than the package's original publish, so daemons need
    # THIS upgrade's package_id (the one where LivenessVoteBox was actually
    # created) to filter its events, not CONTRACT_ORIGINAL_PACKAGE_ID. Captured
    # once, on the upgrade that creates it, then carried forward unchanged --
    # same pattern as CONTRACT_ORIGINAL_PACKAGE_ID.
    liveness_voting_origin_package_id = deployment.get("LIVENESS_VOTING_ORIGIN_PACKAGE_ID", "")
    if not liveness_voting_origin_package_id and parse_created_object_id(upgrade_result, "LivenessVoteBox"):
        liveness_voting_origin_package_id = package_id

    registries = {env_key: deployment[env_key] for _, _, _, env_key in REGISTRY_CREATE_SPECS if deployment.get(env_key)}
    if missing_registry_keys:
        created = contract.create_registries(package_id, deployment["CONTRACT_ADMIN_CAP_ID"], gas_budget)
        if created is None:
            return 1
        registries.update(created)

    new_deployment = {
        "CONTRACT_NETWORK": env,
        "CONTRACT_CHAIN_ID": deployment.get("CONTRACT_CHAIN_ID", ""),
        "CONTRACT_PACKAGE_ID": package_id,
        "CONTRACT_ORIGINAL_PACKAGE_ID": deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", deployment["CONTRACT_PACKAGE_ID"]),
        "LIVENESS_VOTING_ORIGIN_PACKAGE_ID": liveness_voting_origin_package_id,
        "CONTRACT_UPGRADE_CAP_ID": upgrade_cap_id,
        "CONTRACT_DEPLOYER_ADDRESS": deployment.get("CONTRACT_DEPLOYER_ADDRESS", ""),
        "CONTRACT_PUBLISH_TX_DIGEST": deployment.get("CONTRACT_PUBLISH_TX_DIGEST", ""),
        "CONTRACT_UPGRADE_TX_DIGEST": upgrade_tx_digest or "",
        "CONTRACT_ADMIN_CAP_ID": deployment.get("CONTRACT_ADMIN_CAP_ID", ""),
        "NETWORK_REGISTRY_ID": deployment.get("NETWORK_REGISTRY_ID", ""),
        "MINER_STORE_ID": deployment.get("MINER_STORE_ID", ""),
        "ROLE_VOTE_BOX_ID": deployment.get("ROLE_VOTE_BOX_ID", ""),
        "LIVENESS_VOTE_BOX_ID": liveness_vote_box_id,
        **registries,
    }
    write_kv_env_file(contract.contract_env_path(env), new_deployment)
    sync_frontend_env(new_deployment)
    return 0
