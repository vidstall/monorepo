from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import infra

REQUEST_TIMEOUT_SECONDS = 6
# join_room/create_room block server-side on register + create-room/escrow
# on-chain txs + relay-assignment polling (up to 30s alone for create --
# see CREATE_ROOM_POLL_OPTS in apps/bot/src/chain.ts) before responding, so
# they need much more headroom than the fast list/delete endpoints.
ROOM_ACTION_TIMEOUT_SECONDS = 45
MEDIA_MODES = ("listen", "camera", "mic", "both")


def _base_url(host: str) -> str | None:
    address = infra.host_address(host)
    if not address:
        return None
    return f"http://{address}:{infra.SERVICE_PORTS['bot']}"


def _request_at(
    label: str,
    base_url: str,
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> object | None:
    """Shared GET/POST helper for apps/bot's control API, addressed by a
    raw base_url (fleet host or `http://127.0.0.1:<port>` for a local dev
    session -- see cli/local_bot.py) rather than always resolving one from
    a registered fleet host name. `token` is omitted from the
    Authorization header entirely when None/empty, matching apps/bot's own
    "unset BOT_CONTROL_TOKEN = unauthenticated" local-dev convention
    (services/worker/apps/bot/README.md) -- sending an empty Bearer token
    would be actively wrong, not just redundant. Returns the parsed JSON
    response, or None on any failure (unreachable host, bad token, non-2xx,
    malformed JSON) -- printed so it lands in the GUI's Activity log via
    ActionRunner's stdout/stderr capture, same convention as
    contract.fetch_object/wallet.find_cap_id. `label` is just what
    error messages are prefixed with (a fleet host name, or "local bot
    <id>")."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"bot {label}: {method} {path} failed -- HTTP {exc.code}: {detail}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"bot {label}: {method} {path} failed -- {exc}")
        return None

    if not payload:
        # e.g. DELETE /bots/:id returns 204 with no body -- treat as a
        # successful empty result rather than a JSON parse failure.
        return {}

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"bot {label}: {method} {path} returned invalid JSON -- {exc}")
        return None


def _request(
    host: str,
    method: str,
    path: str,
    body: dict | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> object | None:
    """Fleet-host variant of _request_at() -- resolves base_url/token from
    a registered host name, same behavior as before this module supported
    raw base URLs too."""
    base_url = _base_url(host)
    if base_url is None:
        print(f"bot {host}: host address not resolved yet (run infra inventory first).")
        return None
    return _request_at(host, base_url, method, path, body, infra.bot_control_token(), timeout)


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
        timeout=ROOM_ACTION_TIMEOUT_SECONDS,
    )
    return result if isinstance(result, dict) else None


def create_room(host: str, media_mode: str, mp4_path: str | None = None) -> dict | None:
    """POST /bots {roomMode: 'create', mediaMode} -- makes this bot create
    a brand new room and join it. Response includes `roomId`/`joinUrl` for
    a real user to open, and `botId` to later stop the session via
    delete_room(). Spends real gas and spawns a real ffmpeg/mediasoup
    process on the worker, same caveats as join_room()."""
    body: dict[str, str] = {"roomMode": "create", "mediaMode": media_mode}
    if mp4_path:
        body["mp4Path"] = mp4_path
    result = _request(host, "POST", "/bots", body, timeout=ROOM_ACTION_TIMEOUT_SECONDS)
    return result if isinstance(result, dict) else None


def delete_room(host: str, bot_id: str) -> dict | None:
    """DELETE /bots/:id -- stops and removes a bot session (leaves its
    room). Returns {} on success (204 has no body), None on failure."""
    return _request(host, "DELETE", f"/bots/{bot_id}")


def delete_all_sessions(host: str) -> dict | None:
    """DELETE /bots (no id) -- stops and removes EVERY session currently
    live on this bot worker in one call, e.g. leftover sessions from a
    scenario run that crashed/was interrupted mid-timeline instead of
    reaching its own bot.delete_room actions. Returns {"stopped": <count>}
    on success, None on failure."""
    result = _request(host, "DELETE", "/bots")
    return result if isinstance(result, dict) else None


def create_room_local(port: int, media_mode: str, mp4_path: str | None = None) -> dict | None:
    """create_room(), but against a local dev bot process on
    http://127.0.0.1:<port> (see cli/local_bot.py) instead of a registered
    fleet host -- no Authorization header, matching apps/bot's own
    unset-BOT_CONTROL_TOKEN local-dev convention."""
    body: dict[str, str] = {"roomMode": "create", "mediaMode": media_mode}
    if mp4_path:
        body["mp4Path"] = mp4_path
    result = _request_at(
        f"local:{port}",
        f"http://127.0.0.1:{port}",
        "POST",
        "/bots",
        body,
        timeout=ROOM_ACTION_TIMEOUT_SECONDS,
    )
    return result if isinstance(result, dict) else None


def delete_room_local(port: int, bot_id: str) -> dict | None:
    """delete_room(), but against a local dev bot process (see
    create_room_local())."""
    return _request_at(f"local:{port}", f"http://127.0.0.1:{port}", "DELETE", f"/bots/{bot_id}")


def join_room_local(port: int, room_id: str, media_mode: str) -> dict | None:
    """join_room(), but against a local dev bot process (see
    create_room_local()) -- used by `vidctl utils bot refresh <id>` to
    rejoin a session's previously-recorded room_id after its process
    crashed, instead of creating (and paying escrow gas for) a new room."""
    result = _request_at(
        f"local:{port}",
        f"http://127.0.0.1:{port}",
        "POST",
        "/bots",
        {"roomMode": "join", "roomId": room_id, "mediaMode": media_mode},
        timeout=ROOM_ACTION_TIMEOUT_SECONDS,
    )
    return result if isinstance(result, dict) else None
