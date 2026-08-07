"""Sync the observer stack's browser-facing endpoints/tokens into
services/client/client/.env as VITE_* vars -- what lets the browser push
relay-down-hint metrics and clientLog batches directly to Pushgateway/Loki
instead of proxying through a relay (see the approved "Browser reports
client-awareness directly to Prometheus/Loki" plan). Explicit subcommand
(`vidctl observer sync-client-env`), not auto-wired into `scenario apply` --
it depends on the observer host(s) already being registered/deployed, which
happens independently of a contract publish.
"""

from __future__ import annotations

import sys

from .config import find_host_running


def sync_client_observability_env() -> int:
    from .. import context, infra
    from .secrets import loki_auth_token

    pushgateway_host = find_host_running("pushgateway")
    loki_host = find_host_running("loki")
    if pushgateway_host is None and loki_host is None:
        print(
            "sync-client-env: no registered observer host runs pushgateway or loki -- "
            "nothing to sync. Register one with `vidctl observer add-host` first.",
            file=sys.stderr,
        )
        return 1

    mapping: dict[str, str] = {}
    if pushgateway_host is not None:
        dashed = str(pushgateway_host["address"]).replace(".", "-")
        mapping["VITE_PUSHGATEWAY_URL"] = f"https://pushgateway.{dashed}.sslip.io"
        mapping["VITE_METRICS_AUTH_TOKEN"] = infra.metrics_auth_token()
    if loki_host is not None:
        dashed = str(loki_host["address"]).replace(".", "-")
        mapping["VITE_LOKI_URL"] = f"https://loki.{dashed}.sslip.io"
        mapping["VITE_LOKI_AUTH_TOKEN"] = loki_auth_token()

    if context.sync_env_keys(context.CLIENT_ENV_PATH, mapping):
        print(f"Synced observability endpoints -> {context.CLIENT_ENV_PATH}")
        return 0
    print(
        f"Note: {context.CLIENT_ENV_PATH} not found; skipping client env sync "
        f"(copy {context.CLIENT_ENV_PATH.name}.example to {context.CLIENT_ENV_PATH.name} first).",
        file=sys.stderr,
    )
    return 1
