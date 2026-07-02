from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .context import RUNTIME_WALLET_TOML, run

MIN_GAS_MIST = 2_000_000_000  # 2 SUI
FAUCET_NETWORKS = ("devnet", "testnet")


def ensure_wallet(name: str, service: str, env_name: str) -> tuple[dict[str, Any], bool]:
    wallets = read_wallets()
    entry = find_wallet(wallets, name, env_name)
    created = False
    if entry is None:
        address, secret_key = generate_sui_keypair()
        livekit_key, livekit_secret = generate_livekit_keys()
        entry = {
            "name": name,
            "service": service,
            "env": env_name,
            "address": address,
            "secret_key": secret_key,
            "x25519_secret": generate_x25519_secret(),
            "node_id": "",
            "cluster_id": "",
            "livekit_api_key": livekit_key,
            "livekit_api_secret": livekit_secret,
            "created_at": _timestamp(),
            "last_balance_mist": 0,
            "last_faucet_at": "",
        }
        wallets.setdefault("wallets", []).append(entry)
        created = True
    else:
        entry["service"] = service

    faucet_if_needed(entry, env_name)
    write_wallets(wallets)
    return entry, created


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


def media_broker_key_content(entry: dict[str, Any]) -> str:
    """The x25519_secret re-encoded as unpadded base64 (RawStdEncoding), the
    format services/media/pkg/service/xaisen_broker.go's loadOrCreateX25519Key
    expects on disk. Same underlying 32-byte scalar as x25519_secret."""
    raw_secret = base64.b64decode(entry["x25519_secret"])
    return base64.b64encode(raw_secret).decode().rstrip("=")


def generate_livekit_keys() -> tuple[str, str]:
    import secrets

    return f"xaisen{secrets.token_hex(6)}", secrets.token_urlsafe(32)


def livekit_keys_env_value(entry: dict[str, Any]) -> str:
    return f"{entry['livekit_api_key']}: {entry['livekit_api_secret']}"


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


def find_wallet_by_service(wallets: dict[str, Any], service: str, env_name: str) -> dict[str, Any] | None:
    for entry in wallets.get("wallets", []):
        if entry.get("service") == service and entry.get("env", env_name) == env_name:
            return entry
    return None


def operator_state_json(entry: dict[str, Any]) -> str:
    return json.dumps(
        {
            "secretKey": entry["secret_key"],
            "nodeId": entry["node_id"] or None,
            "x25519Secret": entry["x25519_secret"],
        }
    )


def find_wallet(wallets: dict[str, Any], name: str, env_name: str) -> dict[str, Any] | None:
    for entry in wallets.get("wallets", []):
        if entry.get("name") == name and entry.get("env", env_name) == env_name:
            return entry
    return None


def read_wallets() -> dict[str, Any]:
    import tomllib

    if not RUNTIME_WALLET_TOML.exists():
        return {"wallets": []}
    data = tomllib.loads(RUNTIME_WALLET_TOML.read_text(encoding="utf-8"))
    data.setdefault("wallets", [])
    return data


def write_wallets(wallets: dict[str, Any]) -> None:
    from .infra import toml_value

    RUNTIME_WALLET_TOML.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for entry in wallets.get("wallets", []):
        lines.append("[[wallets]]")
        for key, value in entry.items():
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    RUNTIME_WALLET_TOML.write_text("\n".join(lines), encoding="utf-8")
    RUNTIME_WALLET_TOML.chmod(0o600)


def _timestamp() -> str:
    from .infra import timestamp

    return timestamp()
