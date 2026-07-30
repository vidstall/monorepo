from __future__ import annotations

from typing import Any

from .chain_io import run_sui_devinspect

# services/contract/sources/core/constants.move's ROOM_STATUS_* -- mirrored
# here since Move's u8 status code carries no label of its own in the
# devInspect JSON (see list_active_rooms()).
ROOM_STATUS_NAMES = {0: "pending", 1: "ready", 2: "active", 3: "closed"}


def _devinspect_view(package_id: str, room_manager_id: str, function: str) -> Any:
    """One `sui client call --dev-inspect --json` read of a RoomManager view
    function that takes only `&RoomManager` (get_active_room_ids/
    get_active_rooms) -- returns the decoded JSON of its single return
    value, or None on any failure. No real gas is spent (dev-inspect never
    executes on-chain), but the Sui CLI still needs an active address/env
    configured to build the simulated transaction."""
    code, payload, _ = run_sui_devinspect(
        [
            "sui", "client", "call",
            "--package", package_id,
            "--module", "room_manager",
            "--function", function,
            "--args", room_manager_id,
            "--dev-inspect",
            "--json",
        ]
    )
    if code != 0 or payload is None:
        return None
    outputs = payload.get("command_outputs") or []
    if not outputs:
        return None
    return_values = outputs[0].get("returnValues") or []
    if not return_values:
        return None
    return return_values[0].get("json")


def list_active_rooms(network: str) -> list[dict[str, Any]] | None:
    """Every currently-active (non-closed) room on-chain, via RoomManager's
    get_active_room_ids/get_active_rooms view functions -- both explicitly
    documented in room_manager.move as "for client devInspect for dashboard
    batch-fetch" (this GUI's Room tab is that dashboard). Returns None if
    the deployment/RoomManager isn't configured yet, or either devInspect
    call fails (e.g. no active `sui` env/address).

    The two reads are separate CLI invocations, not one atomic PTB call --
    `sui client ptb --dev-inspect --json` doesn't honor --json as of sui
    1.77 (see run_sui_devinspect()'s docstring in chain_io.py), so there's a
    small window where a room opens/closes between the two calls. Acceptable
    for a monitoring dashboard; not a correctness-critical read."""
    # Deferred self-import: load_deployment is patched by tests as a flat
    # cli.contract attribute -- looking it up through the package at call
    # time is what makes that patch take effect here (same convention as
    # deployment.py/publish.py/publish_ops.py in this same package).
    from .. import contract

    deployment = contract.load_deployment(network)
    package_id = deployment.get("CONTRACT_PACKAGE_ID")
    room_manager_id = deployment.get("ROOM_MANAGER_ID")
    if not package_id or not room_manager_id:
        return None

    room_ids = _devinspect_view(package_id, room_manager_id, "get_active_room_ids")
    rooms = _devinspect_view(package_id, room_manager_id, "get_active_rooms")
    if room_ids is None or rooms is None:
        return None

    return [
        {
            "room_id": room_id,
            "status": ROOM_STATUS_NAMES.get(int(info.get("status", 0) or 0), "unknown"),
            "expected_participants": int(info.get("expected_participants", 0) or 0),
            "creator": info.get("creator", ""),
            "created_at": int(info.get("created_at", 0) or 0),
        }
        for room_id, info in zip(room_ids, rooms)
    ]
