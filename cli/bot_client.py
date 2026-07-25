from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import infra

REQUEST_TIMEOUT_SECONDS = 6
MEDIA_MODES = ("listen", "camera", "mic", "both")


def _base_url(host: str) -> str | None:
    address = infra.host_address(host)
    if not address:
        return None
    return f"http://{address}:{infra.SERVICE_PORTS['bot']}"


def _request(host: str, method: str, path: str, body: dict | None = None) -> object | None:
    """Shared GET/POST helper for apps/bot's control API. Returns the parsed
    JSON response, or None on any failure (unreachable host, bad token,
    non-2xx, malformed JSON) -- printed so it lands in the GUI's Activity
    log via ActionRunner's stdout/stderr capture, same convention as
    contract.fetch_object/wallet.find_cap_id."""
    base_url = _base_url(host)
    if base_url is None:
        print(f"bot {host}: host address not resolved yet (run infra inventory first).")
        return None

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {infra.bot_control_token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"bot {host}: {method} {path} failed -- HTTP {exc.code}: {detail}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"bot {host}: {method} {path} failed -- {exc}")
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"bot {host}: {method} {path} returned invalid JSON -- {exc}")
        return None


def list_sessions(host: str) -> list[dict] | None:
    """GET /bots -- every session currently live in the bot process's
    memory. apps/bot keeps no history: a stopped session or a process
    restart erases it, so this is a live snapshot, not a log. Two entries
    can share the same roomId (no dedupe on the bot's side) -- that's what
    "joined a room twice" looks like here."""
    result = _request(host, "GET", "/bots")
    return result if isinstance(result, list) else None


def join_room(host: str, room_id: str, media_mode: str) -> dict | None:
    """POST /bots {roomMode: 'join', roomId, mediaMode} -- makes this bot
    join an existing room. Spends real gas and spawns a real ffmpeg/
    mediasoup process on the worker, so callers should confirm with the
    user first."""
    result = _request(
        host,
        "POST",
        "/bots",
        {"roomMode": "join", "roomId": room_id, "mediaMode": media_mode},
    )
    return result if isinstance(result, dict) else None
