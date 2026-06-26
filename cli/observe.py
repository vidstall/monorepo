from __future__ import annotations

import argparse
import json
import subprocess


def _load_registry_id(network: str) -> str:
    from cli.env import build_contract_env
    env = build_contract_env(network)
    registry_id = env.get("CONTRACT_REGISTRY_OBJECT_ID", "").strip()
    if not registry_id:
        raise SystemExit(
            f"CONTRACT_REGISTRY_OBJECT_ID not set for network '{network}'.\n"
            f"Run: python3 vidctl.py contract deploy --network {network}"
        )
    return registry_id


def _sui_object_json(object_id: str, network: str) -> dict:
    result = subprocess.run(
        ["sui", "client", "object", object_id, "--json"],
        capture_output=True,
        text=True,
        env=_sui_env(network),
    )
    if result.returncode != 0:
        raise SystemExit(f"sui client object failed:\n{result.stderr.strip()}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Failed to parse sui output: {e}") from e


def _sui_env(network: str) -> dict:
    from cli.env import build_contract_env
    return build_contract_env(network)


def cmd_observe_workers(args: argparse.Namespace) -> None:
    network = args.network
    registry_id = _load_registry_id(network)
    print(f"Querying registry {registry_id} on {network}...\n")
    data = _sui_object_json(registry_id, network)

    fields: dict = {}
    try:
        fields = data["content"]["fields"]
    except (KeyError, TypeError):
        pass

    node_count = fields.get("node_count", "?")
    active_workers = fields.get("active_worker_count", "?")
    next_node_id = fields.get("next_node_id", "?")

    print(f"  Registered nodes : {node_count}")
    print(f"  Active workers   : {active_workers}")
    print(f"  Next node ID     : {next_node_id}")

    nodes_table = fields.get("nodes")
    if nodes_table:
        print("\n  Workers:")
        items = nodes_table if isinstance(nodes_table, list) else []
        for item in items:
            f = item.get("fields", item) if isinstance(item, dict) else {}
            addr = f.get("owner") or f.get("address") or "?"
            stake = f.get("stake") or "?"
            active = f.get("is_active") or "?"
            print(f"    {addr}  stake={stake}  active={active}")
    else:
        print("\n  (no worker detail in object fields — use sui client object for raw JSON)")


def cmd_observe_rooms(args: argparse.Namespace) -> None:
    network = args.network
    registry_id = _load_registry_id(network)
    print(f"Querying registry {registry_id} on {network}...\n")
    data = _sui_object_json(registry_id, network)

    fields: dict = {}
    try:
        fields = data["content"]["fields"]
    except (KeyError, TypeError):
        pass

    next_rental_id = fields.get("next_rental_id", "?")
    total = int(next_rental_id) - 1 if isinstance(next_rental_id, (int, str)) and str(next_rental_id).isdigit() else "?"
    print(f"  Total rentals created : {total if total != '?' else next_rental_id}")

    rentals_table = fields.get("rentals")
    if rentals_table:
        print("\n  Active rentals:")
        items = rentals_table if isinstance(rentals_table, list) else []
        for item in items:
            f = item.get("fields", item) if isinstance(item, dict) else {}
            rental_id = f.get("id") or f.get("rental_id") or "?"
            room = f.get("room_name") or "?"
            client = f.get("client") or f.get("owner") or "?"
            print(f"    rental={rental_id}  room={room}  client={client}")
    else:
        print("  (no rental detail in object fields — use sui client object for raw JSON)")


def cmd_observe_stub(args: argparse.Namespace) -> None:
    subcommand = getattr(args, "subcommand", "?")
    print(f"observe {subcommand} — not yet implemented")
    print("Requires an active node deployment. Coming soon.")
