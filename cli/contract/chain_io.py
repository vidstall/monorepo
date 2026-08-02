from __future__ import annotations

import json
import subprocess


def run_sui_json(args: list[str]) -> tuple[int, dict | None, str]:
    completed = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, check=False)
    output = f"{completed.stdout}{completed.stderr}"
    payload = parse_json_payload(output) if output else None
    return completed.returncode, payload, output


def parse_json_payload(output: str) -> dict | None:
    decoder = json.JSONDecoder()
    best: tuple[int, dict] | None = None
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        score = end
        if "objectChanges" in value:
            score += len(output)
        if "effects" in value:
            score += len(output)
        if best is None or score > best[0]:
            best = (score, value)
    return best[1] if best else None


def fetch_object(object_id: str) -> dict | None:
    """Read a live on-chain object's current field values via `sui client
    object <id> --json`. Unlike everything else in this file (which only
    ever parses `objectChanges` at publish time), this is a read against
    present chain state -- used by the GUI to show a shared object's
    current contents, not just its ID. `content` holds the Move struct's
    fields directly (e.g. `content["total_users"]`, `content["cp_miners"]
    ["contents"]`) -- no intermediate "fields" wrapper, unlike objectChanges
    payloads elsewhere in this file."""
    code, payload, output = run_sui_json(["sui", "client", "object", object_id, "--json"])
    if code != 0 or payload is None:
        return None
    return payload.get("content")


def run_sui_devinspect(args: list[str]) -> tuple[int, dict | None, str]:
    """Same idea as run_sui_json(), for `sui client call --dev-inspect --json`
    (or `sui client ptb --dev-inspect --json`, though as of sui 1.77 that
    subcommand ignores --json for dev-inspect and prints a terminal box
    instead -- use `sui client call` for devInspect reads). The dev-inspect
    payload's shape (top-level keys: transaction/command_outputs/
    suggested_gas_price) doesn't contain "objectChanges" or "effects" as a
    TOP-LEVEL key the way publish/upgrade payloads do (parse_json_payload()'s
    scoring bonus for those keys would wrongly prefer the much shorter nested
    transaction.effects sub-object instead) -- so this picks the candidate
    with the largest raw_decode span instead, which is simply the outermost
    object for any clean `--json` output. Each Move return value ends up at
    payload["command_outputs"][i]["returnValues"][j]["json"] -- the `sui` CLI
    itself decodes the raw BCS bytes into plain JSON, no manual BCS parsing
    needed."""
    completed = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, check=False)
    output = f"{completed.stdout}{completed.stderr}"
    decoder = json.JSONDecoder()
    best: tuple[int, dict] | None = None
    for index, char in enumerate(output):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if best is None or end > best[0]:
            best = (end, value)
    return completed.returncode, (best[1] if best else None), output


def run_sui_json_list(args: list[str]) -> tuple[int, list | None, str]:
    """Same shape as run_sui_json(), for Sui CLI subcommands (e.g. `sui
    client objects <address> --json`) whose --json output is a JSON array
    rather than a single object."""
    completed = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, check=False)
    output = f"{completed.stdout}{completed.stderr}"
    decoder = json.JSONDecoder()
    payload = None
    for index, char in enumerate(output):
        if char != "[":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            payload = value
            break
    return completed.returncode, payload, output


def parse_published_package_id(payload: dict) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "published":
            return change.get("packageId")
    return None


def parse_upgrade_cap_id(payload: dict) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "created" and str(change.get("objectType", "")).endswith("UpgradeCap"):
            return change.get("objectId")
    return None


def parse_created_object_id(payload: dict, type_fragment: str) -> str | None:
    for change in payload.get("objectChanges", []):
        if change.get("type") == "created" and type_fragment in str(change.get("objectType", "")):
            return change.get("objectId")
    return None


def parse_sender(payload: dict) -> str | None:
    input_payload = payload.get("input", {})
    if isinstance(input_payload, dict):
        return input_payload.get("sender")
    return None


def parse_transaction_digest(payload: dict) -> str | None:
    effects = payload.get("effects", {})
    if isinstance(effects, dict):
        return effects.get("transactionDigest")
    return None
