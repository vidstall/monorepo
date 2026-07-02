from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from typing import Any

SUI_COIN_TYPE = "0x2::sui::SUI"
CLOCK_ID = "0x6"
ROLE_SFU = "0"
DEFAULT_PRICE_PER_RENTAL_MIST = "1"
MIN_WORKER_STAKE_MIST = "1000"
DEFAULT_GAS_BUDGET = "100000000"

JSON_RPC_URLS = {
    "devnet": "https://fullnode.devnet.sui.io:443",
    "testnet": "https://fullnode.testnet.sui.io:443",
    "mainnet": "https://fullnode.mainnet.sui.io:443",
}


def _run_json(args: list[str]) -> dict[str, Any] | None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("[media-bootstrap] command failed:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("[media-bootstrap] could not parse JSON output:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        return None


def _import_key(secret_key: str) -> None:
    subprocess.run(["sui", "keytool", "import", secret_key, "ed25519"], capture_output=True, text=True, check=False)


def _switch_address(address: str) -> bool:
    result = subprocess.run(["sui", "client", "switch", "--address", address], capture_output=True, text=True, check=False)
    return result.returncode == 0


def _find_event(payload: dict[str, Any], type_fragment: str) -> dict[str, Any] | None:
    for event in payload.get("events", []) or []:
        if type_fragment in str(event.get("type", "")):
            return event.get("parsedJson") or {}
    return None


def _bytes_to_move_vec_arg(data: bytes) -> str:
    return "[" + ",".join(str(b) for b in data) + "]"


def find_node_id_by_owner(original_package_id: str, sui_rpc_url: str, owner_address: str) -> str | None:
    """Mirror services/media/pkg/service/xaisen_broker.go's verifyRouterRole
    technique: scan WorkerRegistered events for one owned by this address.

    Event MoveEventTypes are tagged with the package ID that *originally
    defined* the struct, not whichever (possibly since-upgraded) package ID
    the emitting transaction happened to call through — so this must be
    queried against CONTRACT_ORIGINAL_PACKAGE_ID, not the current/latest
    CONTRACT_PACKAGE_ID, or upgraded deployments silently see zero events."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "suix_queryEvents",
        "params": [{"MoveEventType": f"{original_package_id}::worker_events::WorkerRegistered"}, None, 1000, False],
    }
    request = urllib.request.Request(
        sui_rpc_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = json.loads(response.read())
    data = body.get("result", {}).get("data", [])
    matched = [
        item["parsedJson"]
        for item in data
        if str(item.get("parsedJson", {}).get("owner", "")).lower() == owner_address.lower()
    ]
    if not matched:
        return None
    return str(matched[-1]["node_id"])


def register_worker(
    package_id: str, registry_id: str, public_url: str, sender_address: str, gas_budget: str,
) -> str | None:
    metadata_uri = public_url.encode()
    metadata_hash = hashlib.sha256(metadata_uri).digest()
    payload = _run_json([
        "sui", "client", "ptb",
        "--make-move-vec", "<u8>", _bytes_to_move_vec_arg(metadata_uri), "--assign", "metadata_uri_vec",
        "--make-move-vec", "<u8>", _bytes_to_move_vec_arg(metadata_hash), "--assign", "metadata_hash_vec",
        "--split-coins", "gas", f"[{MIN_WORKER_STAKE_MIST}]", "--assign", "stake_coin",
        "--move-call", f"{package_id}::workers::register_worker",
        f"<{SUI_COIN_TYPE}>",
        f"@{registry_id}", "metadata_uri_vec", "metadata_hash_vec", DEFAULT_PRICE_PER_RENTAL_MIST, "stake_coin.0",
        f"@{CLOCK_ID}",
        "--gas-budget", gas_budget,
        "--json",
    ])
    if payload is None:
        return None
    event = _find_event(payload, "WorkerRegistered")
    if not event:
        print("[media-bootstrap] register_worker succeeded but no WorkerRegistered event found", file=sys.stderr)
        return None
    return str(event["node_id"])


def propose_sfu_role(package_id: str, registry_id: str, node_id: str, gas_budget: str) -> str | None:
    payload = _run_json([
        "sui", "client", "call",
        "--package", package_id, "--module", "role_governance", "--function", "propose_role",
        "--type-args", SUI_COIN_TYPE,
        "--args", registry_id, node_id, node_id, ROLE_SFU, CLOCK_ID,
        "--gas-budget", gas_budget,
        "--json",
    ])
    if payload is None:
        return None
    event = _find_event(payload, "RoleProposalCreated")
    if not event:
        print("[media-bootstrap] propose_role succeeded but no RoleProposalCreated event found", file=sys.stderr)
        return None
    return str(event["proposal_id"])


def cast_vote(package_id: str, registry_id: str, voter_node_id: str, proposal_id: str, gas_budget: str) -> bool:
    payload = _run_json([
        "sui", "client", "call",
        "--package", package_id, "--module", "role_governance", "--function", "cast_role_vote",
        "--type-args", SUI_COIN_TYPE,
        "--args", registry_id, voter_node_id, proposal_id, CLOCK_ID,
        "--gas-budget", gas_budget,
        "--json",
    ])
    return payload is not None


def register_media_cluster(
    package_id: str, registry_id: str, node_id: str, public_url: str, gas_budget: str,
) -> str | None:
    payload = _run_json([
        "sui", "client", "ptb",
        "--make-move-vec", "<u8>", _bytes_to_move_vec_arg(public_url.encode()), "--assign", "client_url_vec",
        "--move-call", f"{package_id}::media_routing::register_media_cluster",
        f"<{SUI_COIN_TYPE}>",
        f"@{registry_id}", node_id, "client_url_vec", DEFAULT_PRICE_PER_RENTAL_MIST,
        "--gas-budget", gas_budget,
        "--json",
    ])
    if payload is None:
        return None
    event = _find_event(payload, "MediaClusterRegistered")
    if event and "cluster_id" in event:
        return str(event["cluster_id"])
    # register_media_cluster sets cluster_id = owner_node_id deterministically.
    return node_id


def set_node_profile(
    package_id: str, registry_id: str, node_id: str, cluster_id: str,
    x25519_public_key: bytes, broker_endpoint: str, region: str, gas_budget: str,
) -> bool:
    payload = _run_json([
        "sui", "client", "ptb",
        "--make-move-vec", "<u8>", _bytes_to_move_vec_arg(x25519_public_key), "--assign", "x25519_vec",
        "--make-move-vec", "<u8>", _bytes_to_move_vec_arg(broker_endpoint.encode()), "--assign", "broker_endpoint_vec",
        "--make-move-vec", "<u8>", _bytes_to_move_vec_arg(region.encode()), "--assign", "region_vec",
        "--move-call", f"{package_id}::media_routing::set_node_profile",
        f"<{SUI_COIN_TYPE}>",
        f"@{registry_id}", node_id, "x25519_vec", "broker_endpoint_vec", "region_vec", cluster_id,
        "--gas-budget", gas_budget,
        "--json",
    ])
    return payload is not None


def ensure_media_registered(
    media_entry: dict[str, Any],
    routes_entry: dict[str, Any] | None,
    env_name: str,
    package_id: str,
    original_package_id: str,
    registry_id: str,
    public_url: str,
    gas_budget: str = DEFAULT_GAS_BUDGET,
) -> None:
    """Idempotently registers media_entry's wallet as an SFU worker, gets it
    voted into ROLE_SFU, registers its media cluster, and publishes its node
    profile on-chain. No-ops entirely if media_entry already has a cluster_id
    (fully bootstrapped on a previous run). Mutates media_entry in place with
    node_id/cluster_id; caller is responsible for persisting it to disk."""
    if media_entry.get("cluster_id"):
        return

    from . import wallet as wallet_module

    sui_rpc_url = JSON_RPC_URLS[env_name]

    _import_key(media_entry["secret_key"])
    if not _switch_address(media_entry["address"]):
        raise RuntimeError(f"could not switch to media operator address {media_entry['address']}")

    node_id = media_entry.get("node_id") or find_node_id_by_owner(
        original_package_id, sui_rpc_url, media_entry["address"],
    )
    if not node_id:
        print(f"[media-bootstrap] registering {media_entry['name']} as a worker...")
        node_id = register_worker(package_id, registry_id, public_url, media_entry["address"], gas_budget)
        if not node_id:
            raise RuntimeError("media register_worker failed")
    media_entry["node_id"] = node_id

    print(f"[media-bootstrap] proposing node_id={node_id} for ROLE_SFU...")
    proposal_id = propose_sfu_role(package_id, registry_id, node_id, gas_budget)
    if not proposal_id:
        raise RuntimeError("propose_role succeeded but proposal_id could not be determined")
    if not routes_entry:
        print("[media-bootstrap] no routes wallet found to cast a second vote; SFU role proposal left pending", file=sys.stderr)
    else:
        routes_node_id = routes_entry.get("node_id") or find_node_id_by_owner(
            original_package_id, sui_rpc_url, routes_entry["address"],
        )
        if not routes_node_id:
            print("[media-bootstrap] could not resolve routes operator's node_id; SFU role proposal left pending", file=sys.stderr)
        else:
            _import_key(routes_entry["secret_key"])
            if not _switch_address(routes_entry["address"]):
                print(f"[media-bootstrap] could not switch to routes address {routes_entry['address']}", file=sys.stderr)
            else:
                print(f"[media-bootstrap] casting second vote from routes node_id={routes_node_id}...")
                if not cast_vote(package_id, registry_id, routes_node_id, proposal_id, gas_budget):
                    print("[media-bootstrap] cast_role_vote failed; SFU role proposal may be left pending", file=sys.stderr)
            _import_key(media_entry["secret_key"])
            _switch_address(media_entry["address"])

    print(f"[media-bootstrap] registering media cluster for node_id={node_id}...")
    cluster_id = register_media_cluster(package_id, registry_id, node_id, public_url, gas_budget)
    if not cluster_id:
        raise RuntimeError("register_media_cluster failed (likely ROLE_SFU vote did not finalize)")
    media_entry["cluster_id"] = cluster_id

    print(f"[media-bootstrap] publishing node profile (cluster_id={cluster_id})...")
    x25519_public_key = wallet_module.x25519_public_key_bytes(media_entry)
    ok = set_node_profile(
        package_id, registry_id, node_id, cluster_id, x25519_public_key, public_url, "global", gas_budget,
    )
    if not ok:
        raise RuntimeError("set_node_profile failed")

    print(f"[media-bootstrap] {media_entry['name']} fully registered: node_id={node_id} cluster_id={cluster_id}")
