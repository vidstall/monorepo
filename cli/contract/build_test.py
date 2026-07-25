from __future__ import annotations

import json
import re
import subprocess
import sys

from ..context import CONTRACT_DIR, run
from .deployment import MOVE_TOML


def build(env: str) -> int:
    if env == "devnet":
        sync_devnet_chain_id()
    return run(["sui", "move", "--build-env", env, "build", "--path", CONTRACT_DIR])


def test(env: str) -> int:
    if env == "devnet":
        sync_devnet_chain_id()
    return run(["sui", "move", "--build-env", env, "test", "--path", CONTRACT_DIR])


def check(env: str) -> int:
    code = build(env)
    if code != 0:
        return code
    return test(env)


def sync_devnet_chain_id() -> str | None:
    """Best-effort: refresh Move.toml's `devnet` chain identifier from the
    live network before a devnet build, since devnet resets its genesis
    (and therefore its chain identifier) periodically and vidctl has no
    other mechanism to detect that drift. Never blocks the build — on any
    failure (no network, sui not on PATH, etc.) it warns and leaves
    Move.toml as-is, since the existing value might still be correct.

    Returns the live chain-id on success (even if Move.toml already matched
    it, or couldn't be updated), or None if it couldn't be determined at
    all -- callers use this to detect a devnet reset (see `publish()`).
    """
    try:
        result = subprocess.run(
            ["sui", "client", "--client.env", "devnet", "chain-identifier", "--json"],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"Warning: could not refresh devnet chain-id ({exc}); using existing Move.toml value.", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(
            f"Warning: could not refresh devnet chain-id ({result.stderr.strip() or 'sui command failed'}); "
            "using existing Move.toml value.",
            file=sys.stderr,
        )
        return None
    try:
        parsed = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        print("Warning: could not parse devnet chain-id response; using existing Move.toml value.", file=sys.stderr)
        return None

    # Newer `sui` CLI versions return an object ({"base58": ..., "hex": ...})
    # instead of a bare JSON string -- normalize to the hex form Move.toml's
    # [environments] table expects either way.
    if isinstance(parsed, dict):
        chain_id = parsed.get("hex") or parsed.get("base58")
    else:
        chain_id = parsed
    if not isinstance(chain_id, str) or not chain_id:
        print(
            f"Warning: unrecognized devnet chain-id response shape ({parsed!r}); "
            "using existing Move.toml value.",
            file=sys.stderr,
        )
        return None

    if not MOVE_TOML.exists():
        return chain_id
    text = MOVE_TOML.read_text()
    new_line = f'devnet = "{chain_id}"'
    if re.search(r'(?m)^devnet\s*=\s*".*"$', text):
        updated = re.sub(r'(?m)^devnet\s*=\s*".*"$', new_line, text)
    elif "[environments]" in text:
        updated = text.replace("[environments]", f"[environments]\n{new_line}", 1)
    else:
        return chain_id
    if updated != text:
        MOVE_TOML.write_text(updated)
        print(f"Move.toml: devnet chain-id refreshed -> {chain_id}")
    return chain_id


def ensure_active_sui_env(env: str) -> int:
    completed = subprocess.run(
        ["sui", "client", "active-env"], capture_output=True, text=True, check=False
    )
    active = completed.stdout.strip()
    if active == env:
        return 0
    print(f"Switching sui client active environment: {active or '(unset)'} -> {env}")
    return run(["sui", "client", "switch", "--env", env])
