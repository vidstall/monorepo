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
    bot_control_token()'s inline logic, generalized so metrics_auth_token()
    below doesn't reimplement it."""
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


def turn_static_secret() -> str:
    """Read (or generate + persist) TURN_STATIC_SECRET from
    secrets/services/turn.env -- the single coturn `--static-auth-secret`
    value shared by EVERY coturn instance across the fleet AND cp-daemon's
    TurnIssuer (which mints credentials off exactly one "current secret"
    fleet-wide, see turn-issuer.ts's issueFor()). Generated once, on first
    use, like metrics_auth_token()."""
    from .. import infra

    return _read_or_generate_secret(infra.SERVICE_SECRETS_DIR / "turn.env", "TURN_STATIC_SECRET")


def turn_rpc_token() -> str:
    """Read (or generate + persist) TURN_RPC_TOKEN from
    secrets/services/turn.env -- the bearer token gating cp-daemon's
    POST /turn/issue RPC (turn-rpc.ts; the RPC server only starts once this
    is set, see cp-issuers-wiring.ts). Shared between cp-daemon (verifies
    it) and every relay (sends it as Authorization: Bearer, see
    relay-wiring-turn.ts / turn-fetcher.ts). Same file as
    turn_static_secret() -- two independent keys, one TURN-secrets file."""
    from .. import infra

    return _read_or_generate_secret(infra.SERVICE_SECRETS_DIR / "turn.env", "TURN_RPC_TOKEN")


def otel_exporter_vars() -> dict[str, str]:
    """Read (never generate) OTEL_EXPORTER_OTLP_ENDPOINT/HEADERS from
    secrets/services/otel.env. There's nothing for `vidctl infra` to
    generate here: the actual endpoint/token belong to `vidctl observer`'s
    tempo deployment (see cli/observer/secrets.py's tempo_auth_token()) --
    `vidctl observer deploy` now writes this file itself on success
    (cli/observer/deploy.py's _write_otel_env()), keeping `cli/infra` and
    `cli/observer` decoupled (no direct import between the two packages;
    observer writes to the shared secrets path, infra only ever reads it).
    Returns {} if the file or either key is missing (e.g. `observer deploy`
    hasn't run yet), so every call site stays a graceful no-op."""
    from .. import infra

    values = read_env_file(infra.SERVICE_SECRETS_DIR / "otel.env")
    endpoint = values.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    headers = values.get("OTEL_EXPORTER_OTLP_HEADERS", "")
    if not endpoint:
        return {}
    result = {"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint}
    if headers:
        result["OTEL_EXPORTER_OTLP_HEADERS"] = headers
    return result


def loki_shipping_vars() -> dict[str, str]:
    """Read (never generate) LOKI_PUSH_URL/LOKI_AUTH_TOKEN from
    secrets/services/loki.env, same shape as otel_exporter_vars() and for
    the same reason: the actual ingest URL/token belong to `vidctl
    observer`'s loki deployment (see cli/observer/secrets.py's
    loki_auth_token()) -- `vidctl observer deploy` now writes this file
    itself on success (cli/observer/deploy.py's _write_loki_env()), keeping
    `cli/infra` and `cli/observer` decoupled (no direct import between the
    two packages). Returns {} if the file or the URL is missing (e.g.
    `observer deploy` hasn't run yet), so every call site stays a graceful
    no-op -- fleet containers simply don't get a `loki` log_driver until
    then."""
    from .. import infra

    values = read_env_file(infra.SERVICE_SECRETS_DIR / "loki.env")
    push_url = values.get("LOKI_PUSH_URL", "")
    auth_token = values.get("LOKI_AUTH_TOKEN", "")
    if not push_url:
        return {}
    result = {"LOKI_PUSH_URL": push_url}
    if auth_token:
        result["LOKI_AUTH_TOKEN"] = auth_token
    return result


def metrics_auth_token() -> str:
    """Read (or generate + persist) METRICS_AUTH_TOKEN -- the bearer token
    gating every worker's Prometheus-format /metrics(/prom) scrape endpoint,
    since Prometheus scrapes every host over the public sslip.io endpoints
    (no private network exists between droplets). Persisted in
    secrets/services/monitoring.env (a pure persistence file -- unlike
    bot.env, nothing copies it verbatim to a host; it's consumed
    as the xaisen_metrics_auth_token Ansible var, injected into
    relay/signaling/cp-daemon/validator-daemon's env and into Prometheus's
    own scrape config via prometheus.yml.j2)."""
    from .. import infra

    return _read_or_generate_secret(infra.SERVICE_SECRETS_DIR / "monitoring.env", "METRICS_AUTH_TOKEN")
