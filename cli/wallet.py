from __future__ import annotations

import base64
import json
import random
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .context import RUNTIME_WALLET_TOML, WALLET_SECRETS_DIR, run, wallet_secrets_path

MIN_GAS_MIST = 2_000_000_000  # 2 SUI
FAUCET_NETWORKS = ("devnet", "testnet")


def checkout_wallet(name: str, service: str, provider: str, env_name: str) -> tuple[dict[str, Any], bool]:
    """Assign a free pooled wallet to (name, service, provider, env_name).

    Idempotent: if this exact instance identity already holds an assignment
    (e.g. a `restart` on an already-running instance), that wallet is reused
    rather than checking out a second one. Otherwise a uniformly random free
    wallet is picked; if the pool has none free, one is lazily generated and
    assigned. Returns (entry, created).
    """
    pool = _read_pool(env_name)
    wallets = pool.setdefault("wallets", [])

    for entry in wallets:
        if _matches(entry, name, service, provider):
            faucet_if_needed(entry, env_name)
            _write_pool(env_name, pool)
            return entry, False

    free = [entry for entry in wallets if not entry.get("assigned_name")]
    created = False
    if free:
        entry = random.choice(free)
    else:
        address, secret_key = generate_sui_keypair()
        entry = {
            "id": uuid.uuid4().hex,
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
            "assigned_at": "",
            "released_at": "",
        }
        wallets.append(entry)
        created = True

    entry["assigned_name"] = name
    entry["assigned_service"] = service
    entry["assigned_provider"] = provider
    entry["assigned_at"] = _timestamp()

    faucet_if_needed(entry, env_name)
    _write_pool(env_name, pool)
    return entry, created


def release_wallet(name: str, service: str, provider: str, env_name: str) -> dict[str, Any] | None:
    """Return the wallet assigned to (name, service, provider, env_name) to
    the free pool. Clears assignment fields only; the wallet record (address,
    secret_key, x25519_secret) is kept for future reuse. Does not perform any
    on-chain registry cleanup. Returns the released entry, or None if no
    wallet was assigned to this instance."""
    pool = _read_pool(env_name)
    for entry in pool.get("wallets", []):
        if _matches(entry, name, service, provider):
            entry["assigned_name"] = ""
            entry["assigned_service"] = ""
            entry["assigned_provider"] = ""
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
    live = {(i.get("name"), i.get("service"), i.get("provider"), i.get("env")) for i in topology.get("instances", [])}
    released: list[dict[str, Any]] = []
    for env_name in _all_pool_envs():
        pool = _read_pool(env_name)
        changed = False
        for entry in pool.get("wallets", []):
            if not entry.get("assigned_name"):
                continue
            key = (entry["assigned_name"], entry["assigned_service"], entry["assigned_provider"], env_name)
            if key not in live:
                entry["assigned_name"] = ""
                entry["assigned_service"] = ""
                entry["assigned_provider"] = ""
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
                state = "free"
            print(f"  {entry['address']}  {state}")
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


def _matches(entry: dict[str, Any], name: str, service: str, provider: str) -> bool:
    return (
        entry.get("assigned_name") == name
        and entry.get("assigned_service") == service
        and entry.get("assigned_provider") == provider
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
                "env": env_name,
                "address": entry.get("address", ""),
                "assigned_name": entry.get("assigned_name", ""),
                "assigned_service": entry.get("assigned_service", ""),
                "assigned_provider": entry.get("assigned_provider", ""),
                "assigned_at": entry.get("assigned_at", ""),
                "last_balance_mist": entry.get("last_balance_mist", 0),
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


def _timestamp() -> str:
    from .infra import timestamp

    return timestamp()
