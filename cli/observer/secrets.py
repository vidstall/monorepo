from __future__ import annotations

import secrets as py_secrets

from ..context import read_env_file

# Deliberately reimplemented rather than imported from cli/infra/secrets.py's
# _read_or_generate_secret -- cli/observer stays fully decoupled from
# cli/infra (it's a separate vidctl module, not a role of infra), so it
# shouldn't import infra's internals, only the generic context-level file
# helpers every module already shares.
#
# Deferred self-import (`from .. import context` inside each function, not
# `from ..context import SERVICE_SECRETS_DIR` at module scope) -- same
# convention cli/infra/secrets.py uses for `infra.SERVICE_SECRETS_DIR` --
# tests patch `context.SERVICE_SECRETS_DIR` as a module attribute, which
# only takes effect on a fresh attribute lookup at call time, not a name
# already bound at import time.


def tempo_auth_token() -> str:
    """Read (or generate + persist) the bearer token gating the observer
    ingress Caddy's reverse-proxy to tempo's OTLP/HTTP receiver (see
    IaC/ansible/roles/docker_service/templates/observer-caddyfile.j2) --
    tempo has no authentication of its own. Persisted in
    secrets/services/observer-tempo.env, generated once on first use, same
    shape as cli/infra/secrets.py's metrics_auth_token()/
    grafana_admin_password() (now-removed)."""
    from .. import context

    path = context.SERVICE_SECRETS_DIR / "observer-tempo.env"
    values = read_env_file(path)
    token = values.get("TEMPO_AUTH_TOKEN", "")
    if token:
        return token
    token = py_secrets.token_urlsafe(32)
    values["TEMPO_AUTH_TOKEN"] = token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return token


def loki_auth_token() -> str:
    """Read (or generate + persist) the token gating the observer ingress
    Caddy's reverse-proxy to loki's push API (see observer-caddyfile.j2) --
    loki has no authentication of its own, same as tempo. Unlike
    tempo_auth_token(), this is NOT sent as a Bearer header: Docker's
    `loki` logging driver can only attach credentials via HTTP Basic Auth
    embedded in the log-driver URL's userinfo (`https://xaisen:<token>@...`),
    since the driver has no way to inject a custom Authorization header. So
    this token is consumed as the Basic Auth password (fixed username
    "xaisen") both when deploy_one_service.yml builds each container's
    `loki-url` log-option and when observer-caddyfile.j2 matches the
    resulting `Authorization: Basic base64("xaisen:<token>")` header.
    Persisted in secrets/services/observer-loki.env, generated once on
    first use, same shape as tempo_auth_token()."""
    from .. import context

    path = context.SERVICE_SECRETS_DIR / "observer-loki.env"
    values = read_env_file(path)
    token = values.get("LOKI_AUTH_TOKEN", "")
    if token:
        return token
    token = py_secrets.token_urlsafe(32)
    values["LOKI_AUTH_TOKEN"] = token
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return token


def grafana_admin_password() -> str:
    """Read (or generate + persist) Grafana's admin login password, injected
    as GF_SECURITY_ADMIN_PASSWORD (see deploy_one_service.yml). Grafana is
    reached directly over its own public sslip.io endpoint (observer-
    caddyfile.j2 reverse-proxies to it with no bearer gate, unlike tempo's
    ingest) -- its own login screen is the only auth in front of it, so this
    password is the sole thing protecting it. Persisted in
    secrets/services/observer-grafana.env, generated once on first use."""
    from .. import context

    path = context.SERVICE_SECRETS_DIR / "observer-grafana.env"
    values = read_env_file(path)
    password = values.get("GF_SECURITY_ADMIN_PASSWORD", "")
    if password:
        return password
    password = py_secrets.token_urlsafe(24)
    values["GF_SECURITY_ADMIN_PASSWORD"] = password
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return password
