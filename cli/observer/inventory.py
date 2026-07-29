from __future__ import annotations

from typing import Any

from .config import DEFAULT_HOST_PORT, read_hosts

# The observer host runs the whole monitoring stack: prometheus + tempo +
# grafana, colocated (same pattern DigitalOcean VMs already use for
# multi-service hosts). This mirrors the ServicePort shape Ansible's
# docker_service role already expects (see IaC/pulumi/app/models.py's
# ServicePort / vm_host_entry()'s fallback construction) -- deploy_one_
# service.yml loops over xaisen_services using these keys, plus one
# observer-only addition: `host_port` (prometheus's operator-chosen
# published port -- see deploy_one_service.yml's ports: construction).
# Tempo/grafana's ports are always loopback-only and fixed (no obscurity
# concern), since neither is ever reached directly -- tempo only through
# the observer ingress Caddy for OTLP, grafana through the same Caddy's
# plain (no bearer gate, relies on Grafana's own login) reverse proxy, or
# an SSH tunnel for either's direct/debug access.

# Tempo's OTLP/HTTP receiver always listens on this fixed port inside the
# container (set by tempo.yaml.j2) -- no obscurity concern like prometheus's
# host_port, since it's never exposed un-proxied (see deploy_one_service.yml's
# loopback-only ports: mapping and observer-caddyfile.j2's bearer-gated
# reverse proxy in front of it). Tempo's query API (3200, also fixed,
# loopback-only, SSH-tunnel-reached) is hardcoded directly in
# deploy_one_service.yml's ports: expression, the same way relay's RTC/pipe
# UDP ranges are already hardcoded there -- not worth a generic
# multi-port-per-service mechanism for a single fixed pair.
_TEMPO_OTLP_PORT = 4318

# Grafana's own default port -- fixed since it's never published un-proxied
# either (reached through observer-caddyfile.j2's plain reverse proxy, or an
# SSH tunnel), same reasoning as tempo's ports above.
_GRAFANA_PORT = 3000

# Pushgateway's own default port. Prometheus scrapes it over the internal
# xaisen-net bridge by container name (same host, no TLS/bearer needed --
# see prometheus.yml.j2's xaisen-pushgateway job), same as prometheus could
# scrape itself. Eval-harness scripts running on a dev machine (not on the
# fleet) still need a way to PUSH results in, though -- that's the one
# write path this observer host exposes externally, bearer-gated through
# observer-caddyfile.j2 reusing xaisen_metrics_auth_token, same pattern as
# tempo's OTLP ingest.
_PUSHGATEWAY_PORT = 9091


def _host_entry(host: dict[str, Any]) -> dict[str, Any]:
    desired_state = host.get("desired_state", "running")
    return {
        "ansible_host": host["address"],
        "ansible_user": host["ssh_user"],
        "ansible_ssh_private_key_file": host["ssh_key"],
        # Static hosts are operator-provisioned, not Pulumi-managed --
        # deploy_one_service.yml's ssh user typically has no sudo (e.g.
        # bourbon's), unlike cloud-init'd fleet VMs. Host vars here override
        # both site.yml's play-level `become: true` and group_vars/all's
        # `/opt/xaisen` default, redirecting everything into a directory
        # this user already owns so no privilege escalation is ever needed
        # (see IaC/ansible roles' `xaisen_provider != 'static'` guards).
        "ansible_become": False,
        "xaisen_services_root": f"/home/{host['ssh_user']}/xaisen",
        # Informational only -- nothing in the Ansible role reads this
        # singular field (xaisen_services, plural, below is what actually
        # drives deploy_one_service.yml).
        "xaisen_service": "prometheus",
        "xaisen_services": [
            {
                "service": "prometheus",
                # Prometheus's own process always listens on 9090 inside the
                # container (fixed by the upstream image) -- `host_port` is
                # the DIFFERENT, operator-chosen port it's published as on
                # the host, so nothing sits on the well-known default
                # externally (see deploy_one_service.yml's loopback-only
                # ports: mapping).
                "port": 9090,
                "host_port": host.get("port", DEFAULT_HOST_PORT),
                "desired_state": desired_state,
                "index": 1,
                "worker_key": "prometheus",
            },
            {
                "service": "tempo",
                "port": _TEMPO_OTLP_PORT,
                "host_port": _TEMPO_OTLP_PORT,
                "desired_state": desired_state,
                "index": 1,
                "worker_key": "tempo",
            },
            {
                "service": "grafana",
                "port": _GRAFANA_PORT,
                "host_port": _GRAFANA_PORT,
                "desired_state": desired_state,
                "index": 1,
                "worker_key": "grafana",
            },
            {
                "service": "pushgateway",
                "port": _PUSHGATEWAY_PORT,
                "host_port": _PUSHGATEWAY_PORT,
                "desired_state": desired_state,
                "index": 1,
                "worker_key": "pushgateway",
            },
        ],
        "xaisen_provider": "static",
        "xaisen_env": "",
        "xaisen_contract_env": "",
        "xaisen_desired_state": desired_state,
    }


def build_inventory(hosts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Shape matches hosts.generated.yml exactly (all.children.xaisen.hosts)
    so this file merges into the SAME `xaisen` Ansible group as the
    Pulumi-managed fleet -- required for prometheus.yml.j2's scrape-config
    template, which iterates `groups['xaisen']` across the WHOLE merged
    inventory (every file in ansible.cfg's `inventory =` list), not just
    whichever host --limit targets."""
    hosts = hosts if hosts is not None else read_hosts()
    return {
        "all": {
            "children": {
                "xaisen": {
                    "hosts": {host["name"]: _host_entry(host) for host in hosts if host.get("name")}
                }
            }
        }
    }


def write_inventory() -> None:
    import yaml

    from .. import context

    context.GENERATED_OBSERVER_INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    context.GENERATED_OBSERVER_INVENTORY.write_text(
        "# Generated by ./vidctl observer -- do not edit by hand\n" + yaml.safe_dump(build_inventory(), sort_keys=False),
        encoding="utf-8",
    )
