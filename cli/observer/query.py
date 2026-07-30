from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .config import read_hosts
from .inventory import ALL_SERVICE_NAMES

REQUEST_TIMEOUT_SECONDS = 6


def _prometheus_host() -> dict | None:
    """Whichever registered observer host runs prometheus -- there's at
    most one under the current CLI (no two hosts are ever given the same
    service, see cli/vidctl/observer_cmd.py's add-host/set-services), so
    the first match is the only one that matters."""
    for host in read_hosts():
        if "prometheus" in (host.get("services") or ALL_SERVICE_NAMES):
            return host
    return None


def _prometheus_query_url(host: dict) -> str:
    dashed = str(host["address"]).replace(".", "-")
    return f"https://prometheus-query.{dashed}.sslip.io/api/v1/query"


def query(promql: str) -> list[dict] | None:
    """Instant-query Prometheus's /api/v1/query over the bearer-gated
    "prometheus-query" Caddy route (see observer-caddyfile.j2) -- the only
    reachable path from an operator's machine, since Prometheus's own port
    is loopback-only on the observer host (see inventory.py's port
    comments). Returns the raw `data.result` vector (a list of
    {"metric": {...labels}, "value": [timestamp, "stringValue"]} entries),
    or None on any failure (no prometheus host registered, unreachable,
    non-2xx, malformed JSON, or a non-"success" Prometheus response)."""
    # Deferred self-import: metrics_auth_token is patched by tests as a flat
    # cli.infra attribute -- looking it up through the package at call time
    # is what makes that patch take effect here.
    from .. import infra

    host = _prometheus_host()
    if host is None:
        print("query: no observer host currently runs prometheus.")
        return None

    url = f"{_prometheus_query_url(host)}?{urllib.parse.urlencode({'query': promql})}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {infra.metrics_auth_token()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"query: {promql!r} failed -- HTTP {exc.code}: {detail}")
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"query: {promql!r} failed -- {exc}")
        return None

    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"query: {promql!r} returned invalid JSON -- {exc}")
        return None

    if not isinstance(body, dict) or body.get("status") != "success":
        print(f"query: {promql!r} returned a non-success response -- {body}")
        return None

    data = body.get("data") or {}
    result = data.get("result")
    return result if isinstance(result, list) else None


def room_participant_counts() -> dict[str, int] | None:
    """{roomId: current participant count} for every room Prometheus has a
    dvconf_room_participants sample for -- the signaling service's live
    gauge (services/worker/apps/signaling/src/rooms.ts), scraped fleet-wide
    (see prometheus.yml.j2's xaisen-signaling job). Rooms with zero current
    participants aren't in this dict at all (the gauge is removed, not set
    to 0, when a room empties -- see RoomManager.leave()); callers should
    treat a missing roomId as 0, not omit it."""
    result = query("dvconf_room_participants")
    if result is None:
        return None
    counts: dict[str, int] = {}
    for entry in result:
        room_id = str((entry.get("metric") or {}).get("roomId", ""))
        value = entry.get("value")
        if not room_id or not isinstance(value, list) or len(value) != 2:
            continue
        try:
            counts[room_id] = int(float(value[1]))
        except (TypeError, ValueError):
            continue
    return counts
