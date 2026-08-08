from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..context import run
from .storage import _timestamp

MIN_GAS_MIST = 2_000_000_000  # 2 SUI
FAUCET_NETWORKS = ("devnet", "testnet")

# Env var each daemon checks on boot to skip auto-registration (see
# apps/*/src/auto-register.ts). cp-daemon gets a ControlPlaneCap; every other
# role gets a (shared-type) MinerCap distinguished on-chain by its role field.
CAP_ENV_VARS = {
    "cp-daemon": "CP_CAP_ID",
    "relay": "MINER_CAP_ID",
    "validator-daemon": "VALIDATOR_CAP_ID",
}
CAP_STRUCT_NAMES = {
    "cp-daemon": "ControlPlaneCap",
}  # everything else owns a MinerCap


def faucet_if_needed(entry: dict[str, Any], env_name: str) -> None:
    if env_name not in FAUCET_NETWORKS:
        return
    try:
        balance = current_balance_mist(entry["address"])
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
        print(f"Warning: could not check wallet balance for {entry['address']}: {exc}", file=sys.stderr)
        return
    entry["last_balance_mist"] = balance
    if balance >= MIN_GAS_MIST:
        return
    from .. import contract

    code = contract.ensure_active_sui_env(env_name)
    if code != 0:
        print(f"Warning: could not switch sui client to {env_name}; skipping faucet request.", file=sys.stderr)
        return
    print(f"Requesting faucet gas for {entry['address']} ({env_name})...")
    code = run(["sui", "client", "faucet", "--address", entry["address"]])
    if code == 0:
        entry["last_faucet_at"] = _timestamp()
        # Re-check so last_balance_mist reflects the post-faucet balance --
        # otherwise it's stuck at the pre-faucet snapshot taken above
        # (near-zero for a fresh wallet) forever, even though the wallet is
        # actually funded from here on.
        try:
            entry["last_balance_mist"] = current_balance_mist(entry["address"])
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            pass  # keep the pre-faucet snapshot; next checkout will retry
    else:
        print(f"Warning: faucet request failed for {entry['address']}.", file=sys.stderr)


def resolve_cap_id(entry: dict[str, Any], service: str, env_name: str) -> None:
    """Populate entry['cap_id'] from chain state if this wallet has already
    registered on-chain but the pool has no record of it yet (e.g. it
    registered on a prior run before this field existed, or the pool file
    was recreated). A wallet only ever registers once for its lifetime (see
    checkout_wallet's docstring), so once cap_id is cached for the CURRENTLY
    deployed package there is nothing left to look up on subsequent checkouts.

    A cached cap_id is only trustworthy for the DEPLOYMENT it was minted
    under (tracked in entry['cap_id_package'], keyed on
    CONTRACT_ORIGINAL_PACKAGE_ID -- NOT CONTRACT_PACKAGE_ID). Sui pins a
    struct's fully-qualified type to the package that first defined it: a
    routine `contract upgrade` bumps CONTRACT_PACKAGE_ID (the latest
    bytecode version) but keeps the SAME MinerStore/registries and the SAME
    CONTRACT_ORIGINAL_PACKAGE_ID, so an existing MinerCap/StakePosition
    stays perfectly valid across upgrades -- keying staleness on
    CONTRACT_PACKAGE_ID would wrongly invalidate it after every upgrade and
    send the daemon to re-run register(), which aborts with
    E_ALREADY_REGISTERED since this miner_id already has a profile in that
    (unchanged) MinerStore.

    A genuinely NEW deployment (contract.publish()'s force-republish on a
    devnet chain-id mismatch) mints a brand-new ORIGINAL package with its
    own fresh MinerStore/registries/staking module -- THAT is what actually
    orphans a cap_id (and its StakePosition), since it belongs to a
    completely different, unrelated deployment lineage. If the currently
    deployed original package has moved on (or cap_id_package was never
    recorded, e.g. an older pool entry), drop the stale cap_id so the daemon
    re-runs full Step-1 registration (fresh stake, fresh cap) against the
    current deployment instead of crash-looping on a cap it can never use.

    Best-effort: any lookup failure just leaves cap_id unresolved, and the
    daemon falls through to its normal auto-registration path (which will
    itself fail loudly with E_ALREADY_REGISTERED if that assumption turns
    out to be wrong -- better than silently deploying a wrong/stale cap id).
    """
    from .. import contract

    deployment = contract.load_deployment(env_name)
    original_package_id = deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", "") or deployment.get("CONTRACT_PACKAGE_ID", "")
    if entry.get("cap_id"):
        if original_package_id and entry.get("cap_id_package") == original_package_id:
            return
        print(
            f"Warning: cached cap_id {entry['cap_id']} for wallet {entry['address']} was minted "
            f"under a previous contract deployment; dropping it so this worker re-registers fresh "
            "against the current deployment.",
            file=sys.stderr,
        )
        entry["cap_id"] = ""
        entry["cap_id_package"] = ""
    try:
        found = find_cap_id(entry["address"], env_name)
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Warning: could not check on-chain registration for {entry['address']}: {exc}", file=sys.stderr)
        return
    if found is None:
        return
    struct_name, object_id = found
    expected_struct = CAP_STRUCT_NAMES.get(service, "MinerCap")
    if struct_name != expected_struct:
        # staking::determine_role() (registration.move) picks the on-chain
        # role from stake amount + current cp_count at register() time -- it
        # does NOT read back which service binary vidctl intends to run.
        # This wallet landed on a different role than `service`, so it can
        # never present a valid cap to this daemon; injecting object_id here
        # would just fail on-chain with a type mismatch. Surface it loudly
        # instead of silently deploying broken state -- the fix is to
        # release this wallet (it's now permanently pinned to whatever role
        # it landed on) and let checkout_wallet mint a fresh one.
        print(
            f"Warning: wallet {entry['address']} was assigned for '{service}' but registered "
            f"on-chain as {struct_name} instead of {expected_struct}. It can never run as "
            f"'{service}'; quarantining it and it will not be reassigned. Release this worker "
            "and start/restart again to pick up a fresh wallet.",
            file=sys.stderr,
        )
        entry["role_mismatch"] = struct_name
        return
    entry["cap_id"] = object_id
    entry["cap_id_package"] = original_package_id


def find_cap_id(address: str, env_name: str) -> tuple[str, str] | None:
    """Look up the on-chain Cap object (ControlPlaneCap or MinerCap) this
    address already owns, if any -- i.e. whether it has already registered,
    and under which role. Returns (struct_name, object_id), or None for a
    fresh/never-registered wallet.

    Only matches caps minted by the CURRENTLY deployed ORIGINAL package --
    a bare struct-name suffix match (no package check) previously let a
    stale cap from a prior `contract publish --force` (new original package
    + new registries) get cached and injected forever, since cap_id is only
    ever resolved once (see resolve_cap_id). That stale object may no
    longer even exist on-chain, permanently wedging the daemon's
    registration.

    Deliberately compares against CONTRACT_ORIGINAL_PACKAGE_ID, not
    CONTRACT_PACKAGE_ID: Sui pins a struct's fully-qualified type to the
    package that first defined it, so a cap minted before a routine
    `contract upgrade` still reports its ORIGINAL package id in
    objectType, not the latest one. Comparing against the latest package id
    would make this permanently fail to match right after every upgrade
    even though the cap is still perfectly valid."""
    from .. import contract

    code = contract.ensure_active_sui_env(env_name)
    if code != 0:
        raise RuntimeError(f"could not switch sui client to {env_name}")

    deployment = contract.load_deployment(env_name)
    original_package_id = deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", "") or deployment.get("CONTRACT_PACKAGE_ID", "")

    code, objects, output = contract.run_sui_json_list(["sui", "client", "objects", address, "--json"])
    if code != 0 or objects is None:
        raise RuntimeError(f"could not list objects for {address}: {output}")
    for entry in objects:
        data = entry.get("data") or {}
        object_id = data.get("objectId", "")
        object_type = data.get("type", "") or ""
        if not object_id or not object_type:
            continue
        for struct_name in ("ControlPlaneCap", "MinerCap"):
            if not object_type.endswith(f"::caps::{struct_name}"):
                continue
            if original_package_id and not object_type.startswith(f"{original_package_id}::"):
                continue
            return struct_name, object_id
    return None


def generate_sui_keypair() -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        generated = subprocess.run(
            ["sui", "keytool", "generate", "ed25519", "--json"],
            cwd=tmp,
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(generated.stdout)
        address = str(data["suiAddress"])

        key_files = list(Path(tmp).glob("*.key"))
        if not key_files:
            raise RuntimeError("sui keytool generate did not write a keypair file")
        raw_b64 = key_files[0].read_text().strip()

        converted = subprocess.run(
            ["sui", "keytool", "convert", raw_b64, "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        secret_key = str(json.loads(converted.stdout)["bech32WithFlag"])
    return address, secret_key


def generate_x25519_secret() -> str:
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    key = X25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode()


def x25519_public_key_bytes(entry: dict[str, Any]) -> bytes:
    """Raw 32-byte X25519 public key derived from a wallet entry's x25519_secret."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw_secret = base64.b64decode(entry["x25519_secret"])
    key = X25519PrivateKey.from_private_bytes(raw_secret)
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def current_balance_mist(address: str) -> int:
    result = subprocess.run(
        ["sui", "client", "balance", address, "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    coin_groups = data[0] if data else []
    total = 0
    for group in coin_groups:
        balance = group.get("balance", {})
        if str(balance.get("coinType", "")).endswith("::sui::SUI"):
            total += int(balance.get("balance", 0))
    return total


def operator_state_json(entry: dict[str, Any]) -> str:
    return json.dumps(
        {
            "secretKey": entry["secret_key"],
            "nodeId": entry["node_id"] or None,
            "x25519Secret": entry["x25519_secret"],
            "capId": entry.get("cap_id") or None,
        }
    )
