from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import read_hosts
from .inventory import ALL_SERVICE_NAMES
from .query import query
from .secrets import grafana_admin_password

REQUEST_TIMEOUT_SECONDS = 30
PANEL_WIDTH = 1000
PANEL_HEIGHT = 500

# `scenario run --mini-log`'s reduced-resolution capture -- the renderer's
# per-panel cost scales with pixel count, and mini-log's whole point is a
# fast run-end pass, not full-fidelity images for a report nobody's zooming
# into. Roughly a quarter the pixels of the default size while staying
# legible as a thumbnail.
MINI_PANEL_WIDTH = 480
MINI_PANEL_HEIGHT = 240

# Dashboards deliberately excluded from per-run panel capture: both are
# fleet/chain-wide snapshots (contract state, wallet pool, high-level fleet
# counts) that don't change meaningfully within the span of one scenario
# run and have no per-run template variable (room/peer/host) to scope them
# to -- capturing them every run is pure render-time waste. Matched by
# dashboard JSON `uid` (== filename stem for every file under
# files/dashboards/ today).
EXCLUDED_DASHBOARD_UIDS = {"contract-chain", "overview"}

_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Optional `{...}` label-matcher clause after the metric name (dropped, not
# evaluated) -- some variables filter on an earlier variable's selection,
# e.g. peer-quality.json's $peer: label_values(dvconf_relay_peer_latency_ms
# {roomId=~"$room"}, peerId). Without the `(?:\{[^}]*\})?` this simply
# failed to match at all for any such variable, silently resolving to []
# and falling back to the literal string "All" -- which matches no real
# peerId, so every $peer-scoped panel (e.g. every bot's quality/Is-Bot
# panel) rendered empty. Dropping rather than applying the matcher means
# this pulls live values ACROSS all rooms, not just the selected one -- an
# over-broad but non-empty resolution; still correct in the common
# single-room-at-a-time case this harness runs.
_LABEL_VALUES_RE = re.compile(r"label_values\(\s*(\w+)(?:\{[^}]*\})?\s*,\s*(\w+)\s*\)")


def _grafana_host() -> dict | None:
    """Same pattern as query.py's _prometheus_host() -- whichever registered
    observer host runs grafana (there's at most one)."""
    for host in read_hosts():
        if "grafana" in (host.get("services") or ALL_SERVICE_NAMES):
            return host
    return None


def _grafana_base_url(host: dict) -> str:
    dashed = str(host["address"]).replace(".", "-")
    return f"https://grafana.{dashed}.sslip.io"


def _dashboards_dir() -> Path:
    from .. import context

    return context.ANSIBLE_DIR / "roles" / "docker_service" / "files" / "dashboards"


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-") or "panel"


def enumerate_panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a dashboard JSON's top-level panels: -- Grafana nests a
    collapsed row's own panels under that row panel's "panels" key rather
    than as top-level siblings, so a naive top-level-only walk misses them.
    Row panels themselves are never independently renderable (no real
    visualization) and are dropped once their children are pulled out; a
    non-collapsed row's children are already top-level siblings and pass
    through untouched."""
    panels: list[dict[str, Any]] = []
    for panel in dashboard.get("panels", []) or []:
        if panel.get("type") == "row":
            panels.extend(panel.get("panels", []) or [])
        else:
            panels.append(panel)
    return panels


def _resolve_variable_values(variable: dict[str, Any], at_time: float | None) -> list[str]:
    """Resolves a dashboard template variable's values straight from
    Prometheus rather than hardcoding a metric/label per variable name --
    each `type: query` variable's own `query.query` string is already a
    `label_values(<metric>, <label>)` expression (see e.g.
    infrastructure.json's $host or rooms.json's $room), so parsing that
    string and reusing this package's query.py::query() (same broad-query-
    then-pull-the-label pattern as discover_active_peers()) stays correct
    even if a dashboard's variable definition changes.

    `at_time` (unix seconds, passed straight through to query()'s own
    `at_time`) matters a lot here: capture_dashboard_images() always runs
    AFTER the scenario's own bot.delete_room actions already tore the room
    down, so a plain "now" instant query (at_time=None) finds ZERO live
    peers for a room that just finished -- every variable then silently
    falls back to the literal "All" below, which is why panel capture used
    to render only one empty "All" variant instead of one per real
    room/peer even after the regex fix that made $peer parseable at all.
    Passing a timestamp from inside the run's own window (the caller uses
    its midpoint) queries Prometheus's history instead of its current
    state, so a since-ended room/peer still resolves. Empty list if the
    variable isn't a query type, doesn't match the label_values() shape, or
    the query returns no samples even at that past instant."""
    if variable.get("type") != "query":
        return []
    raw_query = (variable.get("query") or {}).get("query") if isinstance(variable.get("query"), dict) else variable.get("query")
    match = _LABEL_VALUES_RE.search(str(raw_query or ""))
    if match is None:
        return []
    metric, label = match.group(1), match.group(2)
    result = query(metric, at_time=at_time)
    if not result:
        return []
    values = {str(labels[label]) for entry in result if (labels := entry.get("metric") or {}) and label in labels}
    return sorted(values)


def _enumerate_variants(dashboard: dict[str, Any], at_time: float | None) -> list[tuple[str, dict[str, str]]]:
    """(variant_slug, {var_name: value}) pairs to render this dashboard
    once per value (as of `at_time`, see _resolve_variable_values) of each
    of its template variables -- e.g. infrastructure.json's $host produces
    one variant per instance label live at that instant. A dashboard with
    no template variables (contract-chain, overview, workers) or one whose
    variable resolves to no values even at `at_time` renders exactly once,
    under "all", matching prior behavior (no var-* param, or
    var-<name>=All respectively)."""
    variables = [v for v in (dashboard.get("templating") or {}).get("list", []) or [] if v.get("type") == "query"]
    if not variables:
        return [("all", {})]

    per_variable: list[tuple[str, list[str]]] = []
    for variable in variables:
        name = variable["name"]
        values = _resolve_variable_values(variable, at_time)
        per_variable.append((name, values if values else ["All"]))

    variants: list[tuple[str, dict[str, str]]] = [("", {})]
    for name, values in per_variable:
        variants = [
            (f"{slug}-{_slug(value)}" if slug else _slug(value), {**params, name: value})
            for slug, params in variants
            for value in values
        ]
    return variants


def _render_panel_png(
    base_url: str,
    auth_header: str,
    dashboard: dict[str, Any],
    panel: dict[str, Any],
    from_ms: int,
    to_ms: int,
    variant_params: dict[str, str],
    width: int = PANEL_WIDTH,
    height: int = PANEL_HEIGHT,
) -> bytes:
    uid = dashboard["uid"]
    params = [
        ("panelId", panel["id"]),
        ("width", width),
        ("height", height),
        ("from", from_ms),
        ("to", to_ms),
        ("tz", "UTC"),
        *[(f"var-{name}", value) for name, value in variant_params.items()],
    ]
    query_string = urllib.parse.urlencode(params)
    url = f"{base_url}/render/d-solo/{uid}/{uid}?{query_string}"
    request = urllib.request.Request(url, headers={"Authorization": auth_header})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def post_annotation(time_ms: int, tags: list[str], text: str) -> bool:
    """Posts a native Grafana annotation (a point-in-time vertical marker +
    hover text, rendered on every panel of any dashboard whose `annotations`
    list has a matching tag-filtered query -- see overview.json) via
    Grafana's own /api/annotations, reusing the same Basic-Auth admin
    credential capture_dashboard_images() already uses for the render API.
    No `dashboardUID`/`panelId` -- a plain tag-filtered global annotation,
    so any dashboard can pick it up by tag without re-posting.

    Best-effort/non-fatal, matching this module's convention: no registered
    grafana host, an unreachable API, or a non-2xx response all just print a
    warning to stderr and return False -- callers (scenario actions) must
    never fail or slow down because Grafana happened to be unreachable."""
    host = _grafana_host()
    if host is None:
        print("grafana_render: no observer host currently runs grafana, skipping annotation.", file=sys.stderr)
        return False

    base_url = _grafana_base_url(host)
    auth_header = "Basic " + base64.b64encode(f"admin:{grafana_admin_password()}".encode()).decode()
    body = json.dumps({"time": time_ms, "tags": tags, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/annotations",
        data=body,
        headers={"Authorization": auth_header, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"grafana_render: failed to post annotation {text!r}: {exc}", file=sys.stderr)
        return False


def capture_dashboard_images(
    from_ms: int, to_ms: int, dest_dir: Path, width: int = PANEL_WIDTH, height: int = PANEL_HEIGHT
) -> int:
    """Renders one PNG per panel (across every dashboard under
    files/dashboards/, including panels nested in collapsed rows) via
    Grafana's native render API (/render/d-solo/<uid>/<uid>?panelId=...),
    backed by the xaisen-grafana-renderer sidecar (monitoring_config.yml).
    `width`/`height` default to the full-size PANEL_WIDTH/PANEL_HEIGHT --
    pass MINI_PANEL_WIDTH/MINI_PANEL_HEIGHT for `scenario run --mini-log`'s
    faster, lower-resolution capture. Saves into dest_dir (logs/<scenario_name>/<run_timestamp>/img/), grouped
    one subfolder per dashboard and, within that, one subfolder per resolved
    template-variable variant: img/<dashboard-uid>/<variant>/<panel-id>-
    <panel-title-slug>.png. Entirely
    best-effort and defensive, matching MetricsSampler/SystemLog's
    convention: no registered grafana host, an unreachable renderer, or one
    bad panel must never fail (or even slow down the exit of) a scenario
    run -- only ever printed to stderr. Returns the number of panels
    successfully captured.

    Variable resolution (which rooms/peers/hosts to render a variant for) is
    pinned to this run's own MIDPOINT timestamp, not "now" -- this function
    is only ever called from run.py's `finally` block, i.e. strictly AFTER
    the scenario's own bot.delete_room actions already ended the room being
    measured, so a "now" query would always find it gone. The midpoint
    (rather than e.g. from_ms) is a deliberate margin against
    join_stagger_seconds pushing a room/peer's true start a little past
    from_ms -- see _resolve_variable_values()'s docstring for the failure
    this avoids."""
    at_time = (from_ms + to_ms) / 2 / 1000
    host = _grafana_host()
    if host is None:
        print("grafana_render: no observer host currently runs grafana, skipping panel capture.", file=sys.stderr)
        return 0

    base_url = _grafana_base_url(host)
    auth_header = "Basic " + base64.b64encode(f"admin:{grafana_admin_password()}".encode()).decode()

    dashboards_dir = _dashboards_dir()
    dashboard_files = sorted(dashboards_dir.glob("*.json"))
    if not dashboard_files:
        print(f"grafana_render: no dashboard JSON files found under {dashboards_dir}.", file=sys.stderr)
        return 0

    included_count = sum(1 for f in dashboard_files if f.stem not in EXCLUDED_DASHBOARD_UIDS)
    print(f"grafana_render: capturing panels from {included_count} dashboard(s) (excluding {sorted(EXCLUDED_DASHBOARD_UIDS)}) -- this can take a while, no per-panel output otherwise.")
    captured = 0
    for dashboard_file in dashboard_files:
        try:
            dashboard = json.loads(dashboard_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"grafana_render: failed to read {dashboard_file}: {exc}", file=sys.stderr)
            continue

        if dashboard.get("uid") in EXCLUDED_DASHBOARD_UIDS:
            continue

        # One subfolder per dashboard (img/<dashboard-uid>/<variant>/<panel-id>-
        # <title>.png) rather than flattening every dashboard's panels into one
        # directory -- panel ids are only unique WITHIN a dashboard, and a flat
        # layout made it hard to tell which dashboard a given PNG came from at
        # a glance. Variant subfolder further disambiguates the same panel
        # rendered per template-variable value (e.g. per host, per room).
        dashboard_dir = dest_dir / dashboard["uid"]
        panels = enumerate_panels(dashboard)
        variants = _enumerate_variants(dashboard, at_time)
        print(f"grafana_render: {dashboard.get('title', dashboard['uid'])} ({dashboard['uid']}): {len(panels)} panel(s) x {len(variants)} variant(s) = {len(panels) * len(variants)} render(s)")

        for variant_slug, variant_params in variants:
            variant_dir = dashboard_dir / variant_slug
            variant_dir.mkdir(parents=True, exist_ok=True)

            variant_captured = 0
            for panel in panels:
                title = _slug(str(panel.get("title", f"panel-{panel.get('id')}")))
                try:
                    png = _render_panel_png(
                        base_url, auth_header, dashboard, panel, from_ms, to_ms, variant_params, width, height
                    )
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
                    print(
                        f"grafana_render: failed to render {dashboard['uid']} panel {panel.get('id')} ({title}) "
                        f"variant {variant_slug!r}: {exc}",
                        file=sys.stderr,
                    )
                    continue
                path = variant_dir / f"{panel['id']}-{title}.png"
                path.write_bytes(png)
                captured += 1
                variant_captured += 1

            print(f"  {dashboard['uid']}/{variant_slug}: {variant_captured}/{len(panels)} captured (total so far: {captured})")

    print(f"grafana_render: done -- {captured} panel(s) captured.")
    return captured
