from __future__ import annotations

import sys
from typing import Any

from ..context import PINNED_IMAGES
from .config import read_hosts
from .inventory import ALL_SERVICE_NAMES, write_inventory
from .secrets import grafana_admin_password, loki_auth_token, tempo_auth_token


def _tempo_ingest_url(host: dict[str, Any]) -> str:
    """The public URL the fleet's OTEL_EXPORTER_OTLP_ENDPOINT should point
    at -- same sslip.io-on-a-bare-IP trick the fleet's own Caddyfile.j2
    already uses for TLS (works for ANY public IP, not just Pulumi-created
    ones). Matches observer-caddyfile.j2's hostname exactly."""
    dashed = str(host["address"]).replace(".", "-")
    return f"https://tempo.{dashed}.sslip.io/v1/traces"


def _loki_ingest_url(host: dict[str, Any]) -> str:
    """The public URL every fleet VM's Docker `loki` logging driver should
    push to -- same sslip.io trick as tempo's ingest, matching observer-
    caddyfile.j2's loki site block hostname. This is what an operator
    copies into secrets/services/loki.env's LOKI_PUSH_URL (see
    cli/infra/secrets.py::loki_shipping_vars()) -- cli/infra stays
    decoupled from cli/observer, so this URL isn't wired through
    automatically, same manual bridge step tempo's OTEL endpoint already
    requires."""
    dashed = str(host["address"]).replace(".", "-")
    return f"https://loki.{dashed}.sslip.io/loki/api/v1/push"


def _grafana_url(host: dict[str, Any]) -> str:
    """The public URL for this host's Grafana UI -- same sslip.io trick,
    matching observer-caddyfile.j2's grafana site block's hostname. Links
    straight at the "Overview" dashboard (fixed uid "overview", see
    IaC/ansible/roles/docker_service/files/dashboards/overview.json), the
    pane-of-glass entry point into the other 5 dashboards -- not Grafana's
    bare landing page."""
    dashed = str(host["address"]).replace(".", "-")
    return f"https://grafana.{dashed}.sslip.io/d/overview/overview"


def deploy(host: str | None = None) -> int:
    """Deploy prometheus onto one (or every) registered static observer
    host. Deliberately does NOT call pulumi_up, checkout a wallet, or touch
    topology.toml -- this module never provisions/destroys/reboots
    anything, it only configures a host that already exists and is already
    reachable over SSH."""
    # Deferred self-import: ansible_playbook/metrics_auth_token are patched
    # by tests as flat cli.infra attributes -- looking them up through the
    # package at call time (cli/infra's own established convention) is what
    # makes those patches take effect here.
    from .. import infra

    hosts = read_hosts()
    if not hosts:
        print("No observer hosts registered. Run `vidctl observer add-host` first.", file=sys.stderr)
        return 1
    if host is not None and not any(h.get("name") == host for h in hosts):
        print(f"Unknown observer host: {host}", file=sys.stderr)
        return 1

    write_inventory()

    # `--limit` must be scoped to exactly the registered observer host(s) --
    # site.yml's play targets the whole `xaisen` Ansible group, which also
    # contains every Pulumi-managed fleet host merged in from
    # hosts.generated.yml. Passing host=None must mean "every observer
    # host", never "the whole fleet too".
    host_limit = host if host is not None else ",".join(str(h["name"]) for h in hosts)

    extra_vars = {
        "xaisen_pinned_images": dict(PINNED_IMAGES),
        "xaisen_metrics_auth_token": infra.metrics_auth_token(),
        "xaisen_tempo_auth_token": tempo_auth_token(),
        "xaisen_loki_auth_token": loki_auth_token(),
        "xaisen_grafana_admin_password": grafana_admin_password(),
        "xaisen_container_state": "started",
    }
    code = infra.ansible_playbook("site.yml", extra_vars=extra_vars, host_limit=host_limit)

    if code == 0:
        targeted = [h for h in hosts if host is None or h.get("name") == host]
        for entry in targeted:
            # Only print a service's URL for hosts that actually run it --
            # once a host's `services` is a subset (see inventory.py's
            # per-host split, e.g. bourbon/vermouth dividing the stack),
            # printing all 3 unconditionally would show ingest/login URLs
            # for services that aren't actually running on that host.
            services = entry.get("services") or ALL_SERVICE_NAMES
            if "tempo" in services:
                print(
                    f"Tempo trace ingest for {entry['name']!r}: {_tempo_ingest_url(entry)} "
                    f"(Authorization: Bearer <token from secrets/services/observer-tempo.env>)"
                )
            if "loki" in services:
                print(
                    f"Loki log ingest for {entry['name']!r}: {_loki_ingest_url(entry)} "
                    f"(Basic auth, username 'xaisen', password from secrets/services/observer-loki.env -- "
                    f"copy this URL/token into secrets/services/loki.env as LOKI_PUSH_URL/LOKI_AUTH_TOKEN "
                    f"to enable fleet-wide log shipping via cli/infra)"
                )
            if "grafana" in services:
                print(
                    f"Grafana for {entry['name']!r}: {_grafana_url(entry)} "
                    f"(login: admin / <password from secrets/services/observer-grafana.env>)"
                )
    return code
