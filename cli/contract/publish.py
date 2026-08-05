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
from .deployment import (
    clear_published_entry,
    load_deployment,
    sync_frontend_env,
    write_dependency_pubfile,
    write_runtime_pubfile,
)
from .package import CONTRACT_A, CONTRACT_B, LOCAL_DEPENDENCIES, ContractPackage
from .publish_ops import (
    REGISTRY_CREATE_SPECS,
    real_publish_command,
    real_upgrade_command,
    test_publish,
    test_upgrade,
)

# Keys in runtime/contract/<env>.env "owned" by each package -- used by the
# `--force` fresh-republish path to wipe only THIS package's record while
# preserving the other package's, since both packages share one env file.
_A_OWNED_KEYS = {
    "CONTRACT_NETWORK", "CONTRACT_CHAIN_ID", "CONTRACT_PACKAGE_ID", "CONTRACT_ORIGINAL_PACKAGE_ID",
    "CONTRACT_UPGRADE_CAP_ID", "CONTRACT_DEPLOYER_ADDRESS", "CONTRACT_PUBLISH_TX_DIGEST",
    "CONTRACT_UPGRADE_TX_DIGEST", "CONTRACT_ADMIN_CAP_ID", "NETWORK_REGISTRY_ID", "MINER_STORE_ID",
    "LIVENESS_VOTE_BOX_ID", "LIVENESS_VOTING_ORIGIN_PACKAGE_ID", "ROOM_HEALTH_ALERT_BOX_ID",
    "ROOM_HEALTH_ALERTS_ORIGIN_PACKAGE_ID",
} | {env_key for _, _, _, env_key in REGISTRY_CREATE_SPECS}
_B_OWNED_KEYS = {
    "CONTRACT_B_NETWORK", "CONTRACT_B_CHAIN_ID", "CONTRACT_B_PACKAGE_ID", "CONTRACT_B_ORIGINAL_PACKAGE_ID",
    "CONTRACT_B_UPGRADE_CAP_ID", "CONTRACT_B_DEPLOYER_ADDRESS", "CONTRACT_B_PUBLISH_TX_DIGEST",
    "CONTRACT_B_UPGRADE_TX_DIGEST", "ROLE_VOTE_BOX_ID",
}


def _owned_keys(pkg: ContractPackage) -> set[str]:
    return _A_OWNED_KEYS if pkg is CONTRACT_A else _B_OWNED_KEYS


def publish(
    env: str,
    dry_run: bool,
    yes: bool,
    gas_budget: str | None,
    create_registry_if_missing: bool = False,
    force: bool = False,
    pkg: ContractPackage = CONTRACT_A,
) -> int:
    # Deferred self-import: contract_env_path/run_sui_json/
    # sync_devnet_chain_id/upgrade_existing are patched by tests as flat
    # cli.contract attributes -- looking them up through the package at
    # call time is what makes those patches take effect here.
    from .. import contract

    prefix = pkg.env_prefix

    if not dry_run and not yes:
        print("Refusing to publish contract without --dry-run or --yes.", file=sys.stderr)
        return 2

    live_chain_id = contract.sync_devnet_chain_id(pkg) if env == "devnet" else None

    code = ensure_active_sui_env(env)
    if code != 0:
        return code

    deployment = load_deployment(env, pkg)

    if not force and live_chain_id:
        # devnet is wiped periodically, which mints a new chain-id -- any
        # package/upgrade-cap recorded against the OLD chain-id no longer
        # exists on-chain, so a normal upgrade is impossible (Sui itself
        # rejects it: "cannot be used to publish to chain with id ...").
        # Detect that here and fall back to a fresh publish automatically,
        # the same recovery `--force` provides manually, so a scenario apply
        # survives a devnet reset without operator intervention.
        recorded_chain_id = deployment.get(f"{prefix}_CHAIN_ID")
        if recorded_chain_id and recorded_chain_id != live_chain_id:
            print(
                f"devnet chain-id changed ({recorded_chain_id} -> {live_chain_id}); the network was "
                "reset since the last publish, so the recorded package/upgrade-cap no longer exist "
                "there. Forcing a fresh publish instead of an upgrade.",
            )
            force = True

    if force:
        if not dry_run:
            clear_published_entry(env, pkg)
        # Wipe only this package's own keys (self-heals NETWORK/CHAIN_ID),
        # keep every key belonging to the other package or unrelated.
        owned = _owned_keys(pkg)
        deployment = {
            key: value
            for key, value in load_deployment(env, pkg).items()
            if key not in owned or key in {f"{prefix}_NETWORK", f"{prefix}_CHAIN_ID"}
        }
        if live_chain_id:
            # load_deployment() re-reads runtime/contract/<env>.env, whose
            # own CHAIN_ID may still be the stale pre-reset value -- always
            # prefer the just-fetched live one when we have it.
            deployment[f"{prefix}_CHAIN_ID"] = live_chain_id

    existing_package_id = deployment.get(f"{prefix}_PACKAGE_ID")
    existing_upgrade_cap_id = deployment.get(f"{prefix}_UPGRADE_CAP_ID")
    if existing_package_id:
        if not existing_upgrade_cap_id:
            print(
                f"Cannot upgrade {env} ({pkg.slug}): missing {prefix}_UPGRADE_CAP_ID in "
                f"{contract.contract_env_path(env)} and {pkg.dir / 'Published.toml'}.",
                file=sys.stderr,
            )
            return 1
        return contract.upgrade_existing(
            env,
            deployment,
            dry_run,
            gas_budget,
            create_registry_if_missing,
            pkg,
        )

    dependency_packages = LOCAL_DEPENDENCIES.get(pkg, ())
    dependency_pubfile_path = (
        write_dependency_pubfile(env, pkg, dependency_packages) if dependency_packages else None
    )

    preview = test_publish(env, gas_budget, pkg, dependency_pubfile_path)
    if preview is None:
        return 1
    if dry_run:
        return 0

    publish_code, publish_result, publish_error = contract.run_sui_json(
        real_publish_command(env, gas_budget, pkg, dependency_pubfile_path)
    )
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

    identity = {
        f"{prefix}_NETWORK": env,
        # Prefer the just-fetched live chain-id over whatever's in
        # `deployment` (which can still be a stale pre-reset value via
        # load_deployment()'s env-file merge) so runtime/contract/<env>.env
        # always records an accurate chain-id for the next publish's reset
        # check above.
        f"{prefix}_CHAIN_ID": live_chain_id or deployment.get(f"{prefix}_CHAIN_ID", ""),
        f"{prefix}_PACKAGE_ID": package_id,
        f"{prefix}_ORIGINAL_PACKAGE_ID": package_id,
        f"{prefix}_UPGRADE_CAP_ID": upgrade_cap_id or "",
        f"{prefix}_DEPLOYER_ADDRESS": deployer_address or "",
        f"{prefix}_PUBLISH_TX_DIGEST": publish_tx_digest or "",
    }

    if pkg is CONTRACT_A:
        # NetworkRegistry/MinerStore/AdminCap are created by their own
        # modules' `init` functions, which run automatically in this same
        # publish transaction -- no separate call needed, just parse them
        # out. RoleVoteBox no longer lives here post-package-split (see
        # CONTRACT_B below).
        admin_cap_id = parse_created_object_id(publish_result, "AdminCap")
        network_registry_id = parse_created_object_id(publish_result, "NetworkRegistry")
        miner_store_id = parse_created_object_id(publish_result, "MinerStore")
        liveness_vote_box_id = parse_created_object_id(publish_result, "LivenessVoteBox")
        room_health_alert_box_id = parse_created_object_id(publish_result, "RoomHealthAlertBox")
        if not admin_cap_id:
            print("Could not determine AdminCap object ID from publish.", file=sys.stderr)
            return 1

        registries = contract.create_registries(package_id, admin_cap_id, gas_budget)
        if registries is None:
            return 1

        new_deployment = {
            **identity,
            f"{prefix}_ADMIN_CAP_ID": admin_cap_id,
            "NETWORK_REGISTRY_ID": network_registry_id or "",
            "MINER_STORE_ID": miner_store_id or "",
            "LIVENESS_VOTE_BOX_ID": liveness_vote_box_id or "",
            "ROOM_HEALTH_ALERT_BOX_ID": room_health_alert_box_id or "",
            **registries,
        }
    else:
        # Package B (dvconf_role_voting): no AdminCap, no registries -- just
        # the RoleVoteBox its own `init` auto-creates.
        role_vote_box_id = parse_created_object_id(publish_result, "RoleVoteBox")
        new_deployment = {
            **identity,
            "ROLE_VOTE_BOX_ID": role_vote_box_id or "",
        }

    # Merge onto the existing env file rather than overwriting it wholesale,
    # so the OTHER package's already-recorded keys survive this package's
    # publish (both packages share one runtime/contract/<env>.env file).
    # Truthy-filtered before merging: an empty result value here must never
    # blank out a real value the other package already wrote.
    merged = {**deployment, **{key: value for key, value in new_deployment.items() if value}}
    write_kv_env_file(contract.contract_env_path(env), merged)
    sync_frontend_env(merged)
    return 0


def upgrade_existing(
    env: str,
    deployment: dict[str, str],
    dry_run: bool,
    gas_budget: str | None,
    create_registry_if_missing: bool,
    pkg: ContractPackage = CONTRACT_A,
) -> int:
    # Deferred self-import: contract_env_path/run_sui_json are patched by
    # tests as flat cli.contract attributes -- looking them up through the
    # package at call time is what makes those patches take effect here.
    from .. import contract

    prefix = pkg.env_prefix
    package_id = deployment[f"{prefix}_PACKAGE_ID"]
    upgrade_cap_id = deployment[f"{prefix}_UPGRADE_CAP_ID"]
    missing_registry_keys = (
        [env_key for _, _, _, env_key in REGISTRY_CREATE_SPECS if not deployment.get(env_key)]
        if pkg is CONTRACT_A
        else []
    )

    if missing_registry_keys and not create_registry_if_missing:
        print(
            f"Refusing to upgrade {env}: missing {', '.join(missing_registry_keys)} in {contract.contract_env_path(env)}. "
            "Add the existing registry object IDs, or rerun with --create-registry-if-missing "
            "to create fresh shared registries for whichever are missing.",
            file=sys.stderr,
        )
        return 1

    if missing_registry_keys and not deployment.get(f"{prefix}_ADMIN_CAP_ID"):
        print(
            f"Cannot create missing registries for {env}: no {prefix}_ADMIN_CAP_ID recorded in "
            f"{contract.contract_env_path(env)}. Add the AdminCap object ID from the original publish.",
            file=sys.stderr,
        )
        return 1

    pubfile_path = write_runtime_pubfile(env, deployment, pkg, LOCAL_DEPENDENCIES.get(pkg, ()))
    if pubfile_path is None:
        return 1

    preview = test_upgrade(env, upgrade_cap_id, gas_budget, pubfile_path, pkg)
    if preview is None:
        return 1
    if dry_run:
        return 0

    upgrade_code, upgrade_result, upgrade_error = contract.run_sui_json(
        real_upgrade_command(env, upgrade_cap_id, gas_budget, pubfile_path, pkg)
    )
    if upgrade_result is None:
        if upgrade_error:
            sys.stderr.write(upgrade_error)
        return upgrade_code or 1

    package_id = parse_published_package_id(upgrade_result) or package_id
    upgrade_tx_digest = parse_transaction_digest(upgrade_result)

    identity = {
        f"{prefix}_NETWORK": env,
        f"{prefix}_CHAIN_ID": deployment.get(f"{prefix}_CHAIN_ID", ""),
        f"{prefix}_PACKAGE_ID": package_id,
        f"{prefix}_ORIGINAL_PACKAGE_ID": deployment.get(f"{prefix}_ORIGINAL_PACKAGE_ID", deployment[f"{prefix}_PACKAGE_ID"]),
        f"{prefix}_UPGRADE_CAP_ID": upgrade_cap_id,
        f"{prefix}_DEPLOYER_ADDRESS": deployment.get(f"{prefix}_DEPLOYER_ADDRESS", ""),
        f"{prefix}_PUBLISH_TX_DIGEST": deployment.get(f"{prefix}_PUBLISH_TX_DIGEST", ""),
        f"{prefix}_UPGRADE_TX_DIGEST": upgrade_tx_digest or "",
    }

    if pkg is CONTRACT_A:
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

        # Same pattern as LivenessVoteBox/LIVENESS_VOTING_ORIGIN_PACKAGE_ID above:
        # room_health_alerts was added in a later upgrade than the package's
        # original publish, so its RoomHealthAlertBox shared object is only
        # created the FIRST TIME this upgrade includes that module, and its
        # events are pinned to THIS upgrade's package_id forever.
        room_health_alert_box_id = parse_created_object_id(upgrade_result, "RoomHealthAlertBox") or deployment.get(
            "ROOM_HEALTH_ALERT_BOX_ID", ""
        )
        room_health_alerts_origin_package_id = deployment.get("ROOM_HEALTH_ALERTS_ORIGIN_PACKAGE_ID", "")
        if not room_health_alerts_origin_package_id and parse_created_object_id(upgrade_result, "RoomHealthAlertBox"):
            room_health_alerts_origin_package_id = package_id

        registries = {env_key: deployment[env_key] for _, _, _, env_key in REGISTRY_CREATE_SPECS if deployment.get(env_key)}
        if missing_registry_keys:
            created = contract.create_registries(package_id, deployment[f"{prefix}_ADMIN_CAP_ID"], gas_budget)
            if created is None:
                return 1
            registries.update(created)

        new_deployment = {
            **identity,
            "LIVENESS_VOTING_ORIGIN_PACKAGE_ID": liveness_voting_origin_package_id,
            "ROOM_HEALTH_ALERTS_ORIGIN_PACKAGE_ID": room_health_alerts_origin_package_id,
            f"{prefix}_ADMIN_CAP_ID": deployment.get(f"{prefix}_ADMIN_CAP_ID", ""),
            "NETWORK_REGISTRY_ID": deployment.get("NETWORK_REGISTRY_ID", ""),
            "MINER_STORE_ID": deployment.get("MINER_STORE_ID", ""),
            "LIVENESS_VOTE_BOX_ID": liveness_vote_box_id,
            "ROOM_HEALTH_ALERT_BOX_ID": room_health_alert_box_id,
            **registries,
        }
    else:
        new_deployment = {
            **identity,
            "ROLE_VOTE_BOX_ID": deployment.get("ROLE_VOTE_BOX_ID", ""),
        }

    # Merge onto the existing env file rather than overwriting it wholesale --
    # see the matching comment in publish() above.
    merged = {**deployment, **{key: value for key, value in new_deployment.items() if value}}
    write_kv_env_file(contract.contract_env_path(env), merged)
    sync_frontend_env(merged)
    return 0
