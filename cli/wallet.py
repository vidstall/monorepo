from __future__ import annotations

import base64
import json
import random
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .context import (
    RUNTIME_WALLET_TOML,
    WALLET_SECRETS_DIR,
    admin_wallet_secrets_path,
    run,
    wallet_secrets_path,
)

MIN_GAS_MIST = 2_000_000_000  # 2 SUI
FAUCET_NETWORKS = ("devnet", "testnet")

# Env var each daemon checks on boot to skip auto-registration (see
# apps/*/src/auto-register.ts). cp-daemon gets a ControlPlaneCap; every other
# role gets a (shared-type) MinerCap distinguished on-chain by its role field.
CAP_ENV_VARS = {
    "cp-daemon": "CP_CAP_ID",
    "relay": "MINER_CAP_ID",
    "signaling": "MINER_CAP_ID",
    "validator-daemon": "VALIDATOR_CAP_ID",
}
CAP_STRUCT_NAMES = {
    "cp-daemon": "ControlPlaneCap",
}  # everything else owns a MinerCap

_ALIAS_ADJECTIVES = [
    "affectionate", "amused", "brave", "calm", "clever", "cosmic", "curious",
    "daring", "eager", "elegant", "fearless", "fierce", "gentle", "golden",
    "graceful", "happy", "humble", "jolly", "keen", "lively", "lucky",
    "mellow", "merry", "mighty", "noble", "nimble", "patient", "playful",
    "proud", "quiet", "quick", "radiant", "serene", "sharp", "silent",
    "silver", "sincere", "spirited", "steady", "sunny", "swift", "tender",
    "tranquil", "vivid", "witty", "wise", "zealous", "bold", "bright", "cozy",
]
_ALIAS_NOUNS = [
    "jet", "falcon", "otter", "harbor", "meadow", "canyon", "comet", "delta",
    "ember", "fjord", "glacier", "grove", "horizon", "island", "lagoon",
    "lantern", "maple", "meridian", "nebula", "orbit", "orchid", "panther",
    "pebble", "phoenix", "prairie", "quartz", "raven", "reef", "ridge",
    "river", "sable", "sequoia", "shore", "sparrow", "summit", "tundra",
    "valley", "willow", "wren", "zephyr", "brook", "cedar", "cliff", "coral",
    "dune", "forest", "glade", "hollow", "isle", "marsh",
]


def checkout_wallet(
    name: str, service: str, provider: str, env_name: str, instance_index: int = 1
) -> tuple[dict[str, Any], bool]:
    """Assign a free pooled wallet to (name, service, provider, env_name, instance_index).

    `instance_index` (1-based) distinguishes multiple colocated instances of
    the SAME service on one --name (see vidctl.py's count-prefix --service
    syntax, e.g. `5cp-daemon`) -- each index gets its own independently
    checked-out wallet. It plays no part in the `registered_role` pin below:
    a replica is still fundamentally the same on-chain role as any other
    instance of that service.

    Idempotent: if this exact instance identity already holds an assignment
    (e.g. a `restart` on an already-running instance), that wallet is reused
    rather than checking out a second one.

    Otherwise, a free wallet is picked -- but ONLY from wallets whose
    `registered_role` is either unset (never checked out for anything yet)
    or already equal to `service`. On-chain registration is a one-time,
    permanent action per wallet (register() aborts if called again for a
    DIFFERENT role); `release_wallet()` frees a wallet for reassignment on
    the NEXT instance, but a wallet that already registered as (say) relay
    must only ever be reused as relay again, never reassigned to cp-daemon
    or any other service -- doing so previously caused
    `registration::E_ALREADY_REGISTERED` aborts when an instance was
    killed and recreated, since the wallet pool had no memory of which role
    a wallet had actually registered as on-chain.

    `registered_role` is set once, on this wallet's first-ever checkout, and
    is never cleared by `release_wallet()` -- it is permanent for the
    wallet's lifetime, unlike the assigned_* fields which just track the
    CURRENT holder. If the pool has no free wallet matching (or unpinned
    for) `service`, one is lazily generated and assigned. Returns (entry, created).
    """
    pool = _read_pool(env_name)
    wallets = pool.setdefault("wallets", [])

    for entry in wallets:
        if _matches(entry, name, service, provider, instance_index):
            faucet_if_needed(entry, env_name)
            resolve_cap_id(entry, service, env_name)
            _write_pool(env_name, pool)
            return entry, False

    free = [
        entry
        for entry in wallets
        if not entry.get("assigned_name")
        and entry.get("registered_role", "") in ("", service)
        and not entry.get("role_mismatch")
    ]
    created = False
    if free:
        entry = random.choice(free)
    else:
        existing_aliases = {w.get("alias", "") for w in wallets if w.get("alias")}
        address, secret_key = generate_sui_keypair()
        entry = {
            "id": uuid.uuid4().hex,
            "alias": _generate_alias(existing_aliases),
            "address": address,
            "secret_key": secret_key,
            "x25519_secret": generate_x25519_secret(),
            "node_id": "",
            "created_at": _timestamp(),
            "last_balance_mist": 0,
            "last_faucet_at": "",
            "assigned_name": "",
            "assigned_service": "",
            "assigned_provider": "",
            "assigned_instance_index": 0,
            "assigned_at": "",
            "released_at": "",
            "registered_role": "",
            "cap_id": "",
            "cap_id_package": "",
        }
        wallets.append(entry)
        created = True

    entry["assigned_name"] = name
    entry["assigned_service"] = service
    entry["assigned_provider"] = provider
    entry["assigned_instance_index"] = instance_index
    entry["assigned_at"] = _timestamp()
    if not entry.get("registered_role"):
        entry["registered_role"] = service

    faucet_if_needed(entry, env_name)
    resolve_cap_id(entry, service, env_name)
    _write_pool(env_name, pool)
    return entry, created


def release_wallet(
    name: str, service: str, provider: str, env_name: str, instance_index: int = 1
) -> dict[str, Any] | None:
    """Return the wallet assigned to (name, service, provider, env_name,
    instance_index) to the free pool. Clears assignment fields only; the
    wallet record (address, secret_key, x25519_secret) AND its permanent
    `registered_role` pin are kept for future reuse. Does not perform any
    on-chain registry cleanup. Returns the released entry, or None if no
    wallet was assigned to this instance."""
    pool = _read_pool(env_name)
    for entry in pool.get("wallets", []):
        if _matches(entry, name, service, provider, instance_index):
            entry["assigned_name"] = ""
            entry["assigned_service"] = ""
            entry["assigned_provider"] = ""
            entry["assigned_instance_index"] = 0
            entry["assigned_at"] = ""
            entry["released_at"] = _timestamp()
            _write_pool(env_name, pool)
            return entry
    return None


def pool_status(env_name: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Read-only listing for `vidctl wallet list`, secret fields stripped."""
    envs = [env_name] if env_name else _all_pool_envs()
    result: dict[str, list[dict[str, Any]]] = {}
    for env in envs:
        entries = _read_pool(env).get("wallets", [])
        result[env] = [{k: v for k, v in entry.items() if k not in ("secret_key", "x25519_secret")} for entry in entries]
    return result


def gc_orphaned_assignments(topology: dict[str, Any]) -> list[dict[str, Any]]:
    """Release wallets assigned to (name, service, provider, env) tuples that
    no longer exist in the live topology. Returns the list of released
    entries."""
    live = {
        (i.get("name"), i.get("service"), i.get("provider"), i.get("env"), i.get("instance_index", 1))
        for i in topology.get("instances", [])
    }
    released: list[dict[str, Any]] = []
    for env_name in _all_pool_envs():
        pool = _read_pool(env_name)
        changed = False
        for entry in pool.get("wallets", []):
            if not entry.get("assigned_name"):
                continue
            key = (
                entry["assigned_name"],
                entry["assigned_service"],
                entry["assigned_provider"],
                env_name,
                entry.get("assigned_instance_index", 1),
            )
            if key not in live:
                entry["assigned_name"] = ""
                entry["assigned_service"] = ""
                entry["assigned_provider"] = ""
                entry["assigned_instance_index"] = 0
                entry["assigned_at"] = ""
                entry["released_at"] = _timestamp()
                changed = True
                released.append(entry)
        if changed:
            _write_pool(env_name, pool)
    return released


def list_pool(env_name: str | None) -> int:
    status = pool_status(env_name)
    if not any(status.values()):
        print("No pooled wallets yet.")
        return 0
    for env, entries in status.items():
        free = sum(1 for entry in entries if not entry.get("assigned_name"))
        print(f"[{env}] {len(entries)} wallet(s), {free} free, {len(entries) - free} assigned")
        for entry in entries:
            if entry.get("assigned_name"):
                state = f"assigned -> {entry['assigned_name']}/{entry['assigned_service']}/{entry['assigned_provider']}"
            else:
                role = entry.get("registered_role", "")
                state = f"free (pinned: {role})" if role else "free (unpinned)"
            print(f"  {entry.get('alias', '(no alias)')}  {entry['address']}  {state}")
    return 0


def gc() -> int:
    from .context import RUNTIME_TOPOLOGY_TOML
    from .infra import read_topology

    topology = read_topology() if RUNTIME_TOPOLOGY_TOML.exists() else {"instances": []}
    released = gc_orphaned_assignments(topology)
    for entry in released:
        print(f"Released {entry['address']}")
    print(f"{len(released)} wallet(s) released.")
    return 0


def _generate_alias(existing_aliases: set[str]) -> str:
    """Adjective-noun alias, e.g. 'affectionate-jet', unique within existing_aliases."""
    for _ in range(200):
        candidate = f"{random.choice(_ALIAS_ADJECTIVES)}-{random.choice(_ALIAS_NOUNS)}"
        if candidate not in existing_aliases:
            return candidate
    # Combinatorial space exhausted (very large pool) -- fall back to a
    # suffixed variant, still guaranteed unique.
    base = f"{random.choice(_ALIAS_ADJECTIVES)}-{random.choice(_ALIAS_NOUNS)}"
    suffix = 2
    candidate = f"{base}-{suffix}"
    while candidate in existing_aliases:
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _matches(entry: dict[str, Any], name: str, service: str, provider: str, instance_index: int = 1) -> bool:
    return (
        entry.get("assigned_name") == name
        and entry.get("assigned_service") == service
        and entry.get("assigned_provider") == provider
        and entry.get("assigned_instance_index", 1) == instance_index
    )


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
    from . import contract

    code = contract.ensure_active_sui_env(env_name)
    if code != 0:
        print(f"Warning: could not switch sui client to {env_name}; skipping faucet request.", file=sys.stderr)
        return
    print(f"Requesting faucet gas for {entry['address']} ({env_name})...")
    code = run(["sui", "client", "faucet", "--address", entry["address"]])
    if code == 0:
        entry["last_faucet_at"] = _timestamp()
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
    from . import contract

    deployment = contract.load_deployment(env_name)
    original_package_id = deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", "") or deployment.get("CONTRACT_PACKAGE_ID", "")
    if entry.get("cap_id"):
        if original_package_id and entry.get("cap_id_package") == original_package_id:
            return
        print(
            f"Warning: cached cap_id {entry['cap_id']} for wallet {entry['address']} was minted "
            f"under a previous contract deployment; dropping it so this instance re-registers fresh "
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
            f"'{service}'; quarantining it and it will not be reassigned. Release this instance "
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
    from . import contract

    code = contract.ensure_active_sui_env(env_name)
    if code != 0:
        raise RuntimeError(f"could not switch sui client to {env_name}")

    deployment = contract.load_deployment(env_name)
    original_package_id = deployment.get("CONTRACT_ORIGINAL_PACKAGE_ID", "") or deployment.get("CONTRACT_PACKAGE_ID", "")

    result = subprocess.run(
        ["sui", "client", "objects", address],
        capture_output=True,
        text=True,
        check=True,
    )
    object_ids = re.findall(r"objectId\s*\│\s*(0x[0-9a-fA-F]+)", result.stdout)
    object_types = re.findall(r"objectType\s*\│\s*(\S+)", result.stdout)
    for object_id, object_type in zip(object_ids, object_types):
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


def _read_pool(env_name: str) -> dict[str, Any]:
    """Read secrets/wallets/<env>.toml (private store, has secrets)."""
    import tomllib

    path = wallet_secrets_path(env_name)
    if not path.exists():
        return {"wallets": []}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    data.setdefault("wallets", [])
    return data


def _write_pool(env_name: str, pool: dict[str, Any]) -> None:
    """Write secrets/wallets/<env>.toml, chmod 0o600, then refresh the public view."""
    from .infra import toml_value

    path = wallet_secrets_path(env_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for entry in pool.get("wallets", []):
        lines.append("[[wallets]]")
        for key, value in entry.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o600)
    _refresh_public_view()
    _refresh_admin_secrets_view(env_name)


def _all_pool_envs() -> list[str]:
    """Every env with a pool file on disk, e.g. for the public-view rebuild."""
    if not WALLET_SECRETS_DIR.exists():
        return []
    return sorted(path.stem for path in WALLET_SECRETS_DIR.glob("*.toml"))


def _refresh_public_view() -> None:
    """Rebuild runtime/wallet.toml (no secrets) from every secrets/wallets/*.toml."""
    from .infra import toml_value

    lines: list[str] = []
    stats: dict[str, dict[str, int]] = {}
    for env_name in _all_pool_envs():
        entries = _read_pool(env_name).get("wallets", [])
        free = sum(1 for entry in entries if not entry.get("assigned_name"))
        stats[env_name] = {"total": len(entries), "free": free, "assigned": len(entries) - free}
        for entry in entries:
            lines.append("[[wallets]]")
            public_fields = {
                "id": entry.get("id", ""),
                "alias": entry.get("alias", ""),
                "env": env_name,
                "address": entry.get("address", ""),
                "assigned_name": entry.get("assigned_name", ""),
                "assigned_service": entry.get("assigned_service", ""),
                "assigned_provider": entry.get("assigned_provider", ""),
                "assigned_at": entry.get("assigned_at", ""),
                "last_balance_mist": entry.get("last_balance_mist", 0),
                "registered_role": entry.get("registered_role", ""),
            }
            for key, value in public_fields.items():
                lines.append(f"{key} = {toml_value(value)}")
            lines.append("")
    for env_name, env_stats in stats.items():
        lines.append(f"[stats.{env_name}]")
        for key, value in env_stats.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    RUNTIME_WALLET_TOML.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_WALLET_TOML.write_text("\n".join(lines), encoding="utf-8")


def _refresh_admin_secrets_view(env_name: str) -> None:
    """Sync the FULL (secret-including) wallet records for one env to
    services/client/admin/public/.secrets/<env>.toml, so the admin SPA can
    fetch and display them client-side. Testbed-only: private key material is
    included deliberately. The output dir is gitignored."""
    from .infra import toml_value

    entries = _read_pool(env_name).get("wallets", [])
    lines: list[str] = []
    for entry in entries:
        lines.append("[[wallets]]")
        for key, value in entry.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    path = admin_wallet_secrets_path(env_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o600)


def _timestamp() -> str:
    from .infra import timestamp

    return timestamp()
