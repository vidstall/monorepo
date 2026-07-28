from __future__ import annotations

import sys

from ..context import PINNED_IMAGES
from .config import find_host, set_desired_state
from .inventory import write_inventory
from .secrets import grafana_admin_password, tempo_auth_token


def _require_host(host: str) -> bool:
    if find_host(host) is None:
        print(f"Unknown observer host: {host}", file=sys.stderr)
        return False
    return True


def _site_extra_vars(container_state: str) -> dict:
    # Deferred self-import: metrics_auth_token is patched by tests as a flat
    # cli.infra attribute -- looking it up through the package at call time
    # is what makes that patch take effect here.
    from .. import infra

    return {
        "xaisen_pinned_images": dict(PINNED_IMAGES),
        "xaisen_metrics_auth_token": infra.metrics_auth_token(),
        "xaisen_tempo_auth_token": tempo_auth_token(),
        "xaisen_grafana_admin_password": grafana_admin_password(),
        "xaisen_container_state": container_state,
    }


def start(host: str) -> int:
    """(Re)start the prometheus container -- desired_state="running", then
    site.yml's docker_container `state:` (keyed off xaisen_services'
    desired_state) brings it up. Same effect as `deploy()`, but doesn't
    require re-explaining that a plain deploy already starts things."""
    from .. import infra

    if not _require_host(host):
        return 1
    set_desired_state(host, "running")
    write_inventory()
    return infra.ansible_playbook("site.yml", extra_vars=_site_extra_vars("started"), host_limit=host)


def stop(host: str) -> int:
    """Stop the prometheus container without removing it (docker stop, not
    docker rm) -- desired_state="stopped" flips docker_container's `state:`
    to "stopped" on the next site.yml run."""
    from .. import infra

    if not _require_host(host):
        return 1
    set_desired_state(host, "stopped")
    write_inventory()
    return infra.ansible_playbook("site.yml", extra_vars=_site_extra_vars("started"), host_limit=host)


def restart(host: str) -> int:
    """Force-restart the running container (xaisen_container_state=
    "restarted" flips deploy_one_service.yml's `restart:` condition true
    even when nothing else changed)."""
    from .. import infra

    if not _require_host(host):
        return 1
    set_desired_state(host, "running")
    write_inventory()
    return infra.ansible_playbook("site.yml", extra_vars=_site_extra_vars("restarted"), host_limit=host)


def destroy(host: str) -> int:
    """Remove the prometheus container (docker rm) but leave its bind-mounted
    TSDB data directory on disk -- see observer_destroy.yml. Never touches
    the host/VM itself."""
    from .. import infra

    if not _require_host(host):
        return 1
    write_inventory()
    return infra.ansible_playbook("observer_destroy.yml", host_limit=host)


def clean(host: str) -> int:
    """Remove the prometheus container AND wipe its data directory -- see
    observer_clean.yml. Never touches the host/VM itself."""
    from .. import infra

    if not _require_host(host):
        return 1
    write_inventory()
    return infra.ansible_playbook("observer_clean.yml", host_limit=host)
