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

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_LABEL_VALUES_RE = re.compile(r"label_values\(\s*(\w+)\s*,\s*(\w+)\s*\)")


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


def _resolve_variable_values(variable: dict[str, Any]) -> list[str]:
    """Resolves a dashboard template variable's live values straight from
    Prometheus rather than hardcoding a metric/label per variable name --
    each `type: query` variable's own `query.query` string is already a
    `label_values(<metric>, <label>)` expression (see e.g.
    infrastructure.json's $host or rooms.json's $room), so parsing that
    string and reusing this package's query.py::query() (same broad-query-
    then-pull-the-label pattern as discover_active_peers()) stays correct
    even if a dashboard's variable definition changes. Empty list if the
    variable isn't a query type, doesn't match the label_values() shape, or
    the query currently returns no samples (e.g. nobody live right now)."""
    if variable.get("type") != "query":
        return []
    raw_query = (variable.get("query") or {}).get("query") if isinstance(variable.get("query"), dict) else variable.get("query")
    match = _LABEL_VALUES_RE.search(str(raw_query or ""))
    if match is None:
        return []
    metric, label = match.group(1), match.group(2)
    result = query(metric)
    if not result:
        return []
    values = {str(labels[label]) for entry in result if (labels := entry.get("metric") or {}) and label in labels}
    return sorted(values)


def _enumerate_variants(dashboard: dict[str, Any]) -> list[tuple[str, dict[str, str]]]:
    """(variant_slug, {var_name: value}) pairs to render this dashboard
    once per live value of each of its template variables -- e.g.
    infrastructure.json's $host produces one variant per live instance
    label. A dashboard with no template variables (contract-chain,
    overview, workers) or one whose variable currently resolves to no live
    values renders exactly once, under "all", matching prior behavior (no
    var-* param, or var-<name>=All respectively)."""
    variables = [v for v in (dashboard.get("templating") or {}).get("list", []) or [] if v.get("type") == "query"]
    if not variables:
        return [("all", {})]

    per_variable: list[tuple[str, list[str]]] = []
    for variable in variables:
        name = variable["name"]
        values = _resolve_variable_values(variable)
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
) -> bytes:
    uid = dashboard["uid"]
    params = [
        ("panelId", panel["id"]),
        ("width", PANEL_WIDTH),
        ("height", PANEL_HEIGHT),
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


def capture_dashboard_images(from_ms: int, to_ms: int, dest_dir: Path) -> int:
    """Renders one PNG per panel (across every dashboard under
    files/dashboards/, including panels nested in collapsed rows) via
    Grafana's native render API (/render/d-solo/<uid>/<uid>?panelId=...),
    backed by the xaisen-grafana-renderer sidecar (monitoring_config.yml).
    Saves into dest_dir (logs/<scenario_name>/<run_timestamp>/img/), grouped
    one subfolder per dashboard and, within that, one subfolder per resolved
    template-variable variant: img/<dashboard-uid>/<variant>/<panel-id>-
    <panel-title-slug>.png. Entirely
    best-effort and defensive, matching MetricsSampler/SystemLog's
    convention: no registered grafana host, an unreachable renderer, or one
    bad panel must never fail (or even slow down the exit of) a scenario
    run -- only ever printed to stderr. Returns the number of panels
    successfully captured."""
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

    captured = 0
    for dashboard_file in dashboard_files:
        try:
            dashboard = json.loads(dashboard_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"grafana_render: failed to read {dashboard_file}: {exc}", file=sys.stderr)
            continue

        # One subfolder per dashboard (img/<dashboard-uid>/<variant>/<panel-id>-
        # <title>.png) rather than flattening every dashboard's panels into one
        # directory -- panel ids are only unique WITHIN a dashboard, and a flat
        # layout made it hard to tell which dashboard a given PNG came from at
        # a glance. Variant subfolder further disambiguates the same panel
        # rendered per template-variable value (e.g. per host, per room).
        dashboard_dir = dest_dir / dashboard["uid"]
        panels = enumerate_panels(dashboard)

        for variant_slug, variant_params in _enumerate_variants(dashboard):
            variant_dir = dashboard_dir / variant_slug
            variant_dir.mkdir(parents=True, exist_ok=True)

            for panel in panels:
                title = _slug(str(panel.get("title", f"panel-{panel.get('id')}")))
                try:
                    png = _render_panel_png(base_url, auth_header, dashboard, panel, from_ms, to_ms, variant_params)
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

    return captured
