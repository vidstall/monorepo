from __future__ import annotations

import secrets as py_secrets
from pathlib import Path

from ..context import read_env_file


def bot_control_token() -> str:
    """Read (or generate + persist) BOT_CONTROL_TOKEN from
    secrets/services/bot.env -- the SAME file deploy_one_service.yml's
    generic per-service secrets mechanism already copies into the bot
    container as its env_file (see "Copy per-service secrets file to host").
    Generated once, on first use."""
    # Deferred self-import: SERVICE_SECRETS_DIR is patched by tests as a
    # flat cli.infra attribute -- looking it up through the package at call
    # time is what makes that patch take effect here.
    from .. import infra

    path = infra.SERVICE_SECRETS_DIR / "bot.env"
    values = read_env_file(path)
    token = values.get("BOT_CONTROL_TOKEN", "")
    if token:
        return token
    token = py_secrets.token_urlsafe(32)
    values["BOT_CONTROL_TOKEN"] = token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return token


def _read_or_generate_secret(path: Path, key: str) -> str:
    """Shared read-or-generate-and-persist helper, same shape as
    bot_control_token()'s inline logic, generalized so
    grafana_admin_password() and metrics_auth_token() below don't each
    reimplement it."""
    values = read_env_file(path)
    value = values.get(key, "")
    if value:
        return value
    value = py_secrets.token_urlsafe(32)
    values[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{k}={v}" for k, v in values.items()) + "\n",
        encoding="utf-8",
    )
    return value


def grafana_admin_password() -> str:
    """Read (or generate + persist) Grafana's real admin login password,
    from secrets/services/grafana.env -- the SAME file
    deploy_one_service.yml's generic per-service secrets mechanism copies
    into the grafana container's env_file for the `service = "grafana"`
    worker (see PINNED_IMAGES), giving it a real GF_SECURITY_ADMIN_PASSWORD.
    Used only for editing dashboards directly in Grafana's own UI, separate
    from the anonymous-viewer role embedded panels use (see
    GF_AUTH_ANONYMOUS_ENABLED in deploy_one_service.yml)."""
    from .. import infra

    return _read_or_generate_secret(infra.SERVICE_SECRETS_DIR / "grafana.env", "GF_SECURITY_ADMIN_PASSWORD")


def metrics_auth_token() -> str:
    """Read (or generate + persist) METRICS_AUTH_TOKEN -- the bearer token
    gating every worker's Prometheus-format /metrics(/prom) scrape endpoint,
    since Prometheus scrapes every host over the public sslip.io endpoints
    (no private network exists between droplets). Persisted in
    secrets/services/monitoring.env (a pure persistence file -- unlike
    grafana.env/bot.env, nothing copies it verbatim to a host; it's consumed
    as the xaisen_metrics_auth_token Ansible var, injected into
    relay/signaling/cp-daemon/validator-daemon's env and into Prometheus's
    own scrape config via prometheus.yml.j2)."""
    from .. import infra

    return _read_or_generate_secret(infra.SERVICE_SECRETS_DIR / "monitoring.env", "METRICS_AUTH_TOKEN")
