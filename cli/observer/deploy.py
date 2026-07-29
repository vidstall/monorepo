from __future__ import annotations

import sys
from typing import Any

from ..context import PINNED_IMAGES
from .config import read_hosts
from .inventory import write_inventory
from .secrets import grafana_admin_password, tempo_auth_token


def _tempo_ingest_url(host: dict[str, Any]) -> str:
    """The public URL the fleet's OTEL_EXPORTER_OTLP_ENDPOINT should point
    at -- same sslip.io-on-a-bare-IP trick the fleet's own Caddyfile.j2
    already uses for TLS (works for ANY public IP, not just Pulumi-created
    ones). Matches observer-caddyfile.j2's hostname exactly."""
    dashed = str(host["address"]).replace(".", "-")
    return f"https://tempo.{dashed}.sslip.io/v1/traces"


def _grafana_url(host: dict[str, Any]) -> str:
    """The public URL for this host's Grafana UI -- same sslip.io trick,
    matching observer-caddyfile.j2's grafana site block's hostname. Links
    straight at the provisioned "Xaisen Fleet" dashboard (fixed uid
    "xaisen-fleet", see grafana-dashboard-provider.yml.j2 +
    xaisen-fleet-dashboard.json.j2), not Grafana's bare landing page."""
    dashed = str(host["address"]).replace(".", "-")
    return f"https://grafana.{dashed}.sslip.io/d/xaisen-fleet/xaisen-fleet"


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
        "xaisen_grafana_admin_password": grafana_admin_password(),
        "xaisen_container_state": "started",
    }
    code = infra.ansible_playbook("site.yml", extra_vars=extra_vars, host_limit=host_limit)

    if code == 0:
        targeted = [h for h in hosts if host is None or h.get("name") == host]
        for entry in targeted:
            print(
                f"Tempo trace ingest for {entry['name']!r}: {_tempo_ingest_url(entry)} "
                f"(Authorization: Bearer <token from secrets/services/observer-tempo.env>)"
            )
            print(
                f"Grafana for {entry['name']!r}: {_grafana_url(entry)} "
                f"(login: admin / <password from secrets/services/observer-grafana.env>)"
            )
    return code
