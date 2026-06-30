from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from typing import Any

from cli.config import CONTRACT_ENV_DIR, REPO_ROOT
from cli.env import build_contract_env

_STATUS_WIDTH = 18
_SUI_RPC_URLS = {
    "devnet": "https://fullnode.devnet.sui.io:443",
    "testnet": "https://fullnode.testnet.sui.io:443",
    "mainnet": "https://fullnode.mainnet.sui.io:443",
}


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _status_value(value: str | None) -> str:
    return value.strip() if value and value.strip() else "-"


def _print_status_row(label: str, value: str | None) -> None:
    print(f"  {label:<{_STATUS_WIDTH}} {_status_value(value)}")


def _format_sui_balance(mist: str) -> str:
    try:
        value = int(mist)
    except ValueError:
        return f"{mist} MIST"
    whole, fraction = divmod(value, 1_000_000_000)
    if fraction == 0:
        return f"{whole} SUI"
    fraction_text = f"{fraction:09d}".rstrip("0")
    return f"{whole}.{fraction_text} SUI"


def _short_coin_type(coin_type: str) -> str:
    if coin_type == "0x2::sui::SUI":
        return "SUI"
    return coin_type


def _load_wallet_addresses() -> tuple[str | None, list[tuple[str, str]]]:
    try:
        result = subprocess.run(
            ["sui", "client", "addresses", "--json"],
            cwd=str(REPO_ROOT),
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        raise SystemExit("sui CLI not found; install Sui CLI to list wallets")
    except subprocess.TimeoutExpired:
        raise SystemExit("sui client addresses timed out")

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "sui client addresses failed"
        raise SystemExit(_one_line(message))

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse sui client addresses JSON: {exc}") from exc

    active_address = data.get("activeAddress")
    addresses: list[tuple[str, str]] = []
    for entry in data.get("addresses", []):
        if isinstance(entry, list) and len(entry) >= 2:
            alias, address = entry[0], entry[1]
            addresses.append((str(alias), str(address)))

    return str(active_address) if active_address else None, addresses


def _rpc_request(network: str, method: str, params: list[Any]) -> dict[str, Any]:
    rpc_url = _SUI_RPC_URLS[network]
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode("utf-8")
    request = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _wallet_balances(address: str, network: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        data = _rpc_request(network, "suix_getAllBalances", [address])
    except json.JSONDecodeError:
        return [], "invalid RPC response"
    except urllib.error.HTTPError as exc:
        return [], f"RPC HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return [], _one_line(str(exc.reason))
    except TimeoutError:
        return [], "RPC request timed out"

    error = data.get("error")
    if error:
        return [], _one_line(str(error))

    result = data.get("result")
    if not isinstance(result, list):
        return [], "RPC response missing balances"

    balances = [item for item in result if isinstance(item, dict)]
    return balances, None


def _format_balances(balances: list[dict[str, Any]]) -> str:
    if not balances:
        return "0 SUI"
    formatted: list[str] = []
    for balance in balances:
        coin_type = str(balance.get("coinType", "unknown"))
        total = str(balance.get("totalBalance", "0"))
        if coin_type == "0x2::sui::SUI":
            formatted.append(_format_sui_balance(total))
        else:
            formatted.append(f"{total} {_short_coin_type(coin_type)}")
    return ", ".join(formatted)


def _print_wallet_status(network: str, active_address: str | None, addresses: list[tuple[str, str]]) -> None:
    print(f"contract wallet — {network}")
    if not addresses:
        print("  no local Sui wallet addresses found")
        return
    print(f"  {'alias':<24} {'active':<6} {'balance':<20} address")
    for alias, address in addresses:
        balances, error = _wallet_balances(address, network)
        active = "*" if active_address == address else ""
        balance_text = f"unchecked; {error}" if error else _format_balances(balances)
        print(f"  {alias:<24} {active:<6} {balance_text:<20} {address}")


def _sui_object_status(object_id: str, network: str) -> tuple[str, str | None]:
    try:
        data = _rpc_request(
            network,
            "sui_getObject",
            [object_id, {"showType": True, "showOwner": True, "showContent": False, "showPreviousTransaction": True}],
        )
    except json.JSONDecodeError:
        return "unchecked", "invalid RPC response"
    except urllib.error.HTTPError as exc:
        return "unchecked", f"RPC HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return "unchecked", _one_line(str(exc.reason))
    except TimeoutError:
        return "unchecked", "RPC request timed out"

    error = data.get("error")
    if error:
        return "unreachable", _one_line(str(error))

    result = data.get("result")
    if not isinstance(result, dict):
        return "unchecked", "RPC response missing result"

    object_error = result.get("error")
    if object_error:
        return "unreachable", _one_line(str(object_error))

    if isinstance(result.get("data"), dict):
        return "reachable", None

    return "unreachable", "object data missing"


def _print_object_check(label: str, object_id: str | None, network: str) -> None:
    if not object_id or not object_id.strip():
        _print_status_row(label, "-")
        return
    status, detail = _sui_object_status(object_id.strip(), network)
    value = f"{status} ({object_id.strip()})"
    if detail:
        value = f"{value}: {detail}"
    _print_status_row(label, value)


def _print_contract_status(network: str) -> None:
    env_file = CONTRACT_ENV_DIR / f"{network}.env"
    env = build_contract_env(network)

    print(f"contract status — {network}")
    _print_status_row("env file", str(env_file) if env_file.exists() else "missing")
    _print_status_row("package", env.get("CONTRACT_PACKAGE_ID"))
    _print_status_row("registry", env.get("CONTRACT_REGISTRY_OBJECT_ID"))
    _print_status_row("upgrade cap", env.get("CONTRACT_UPGRADE_CAP_ID"))
    _print_status_row("deployer", env.get("CONTRACT_DEPLOYER_ADDRESS"))
    _print_status_row("publish tx", env.get("CONTRACT_PUBLISH_TX_DIGEST"))
    _print_status_row("update tx", env.get("CONTRACT_UPDATE_TX_DIGEST"))

    package_id = env.get("CONTRACT_PACKAGE_ID", "").strip()
    registry_id = env.get("CONTRACT_REGISTRY_OBJECT_ID", "").strip()
    if package_id or registry_id:
        _print_object_check("package object", package_id, network)
        _print_object_check("registry object", registry_id, network)
    else:
        _print_status_row("chain check", "skipped; no package or registry id")
