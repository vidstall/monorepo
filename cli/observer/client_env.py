"""Sync the observer stack's browser-facing Loki/Pushgateway endpoints+tokens
into services/client/client/.env as VITE_* vars -- what lets the browser push
clientLog batches and call-quality metrics directly to Loki/Prometheus
instead of proxying through a relay (lib/log.ts, lib/metrics-push.ts).

NOT exposed as its own `vidctl observer` subcommand -- the operator workflow
here only ever touches the frontend via `scenario apply` or `object publish`,
so this is called automatically, best-effort, from both of those instead:
`scenario apply` (cli/scenario/apply.py's _sync_client_observability_env)
and a frontend `object publish` (cli/object.py's
_sync_client_observability_env_before_build, right before its `pnpm build`).
Both call sites no-op silently when no observer host is registered yet --
the sync is a testbed-observability nicety, not a functional requirement of
either a scenario apply or a frontend publish.
"""

from __future__ import annotations

import sys

from .config import find_host_running


def sync_client_observability_env() -> int:
    from .. import context
    from ..context import read_env_file
    from .secrets import loki_auth_token

    loki_host = find_host_running("loki")
    if loki_host is None:
        print(
            "client-env-sync: no registered observer host runs loki -- "
            "nothing to sync. Register one with `vidctl observer add-host` first.",
            file=sys.stderr,
        )
        return 1

    dashed = str(loki_host["address"]).replace(".", "-")
    mapping = {
        "VITE_LOKI_URL": f"https://loki.{dashed}.sslip.io",
        "VITE_LOKI_AUTH_TOKEN": loki_auth_token(),
    }

    # Pushgateway shares xaisen_metrics_auth_token with the rest of the fleet's
    # metrics surface (see observer-caddyfile.j2) -- that token is generated/
    # persisted by cli/infra/secrets.py's metrics_auth_token(), NOT this module
    # (cli/observer deliberately stays decoupled from cli/infra, see
    # secrets.py's module docstring), so read it straight from its persistence
    # file (secrets/services/monitoring.env) rather than importing infra.
    pushgateway_host = find_host_running("pushgateway")
    if pushgateway_host is not None:
        pg_dashed = str(pushgateway_host["address"]).replace(".", "-")
        metrics_token = read_env_file(context.SERVICE_SECRETS_DIR / "monitoring.env").get(
            "METRICS_AUTH_TOKEN", ""
        )
        if metrics_token:
            mapping["VITE_PUSHGATEWAY_URL"] = f"https://pushgateway.{pg_dashed}.sslip.io"
            mapping["VITE_METRICS_AUTH_TOKEN"] = metrics_token
        else:
            print(
                "client-env-sync: pushgateway host registered but no "
                "METRICS_AUTH_TOKEN persisted yet (run infra deploy first) -- "
                "skipping VITE_PUSHGATEWAY_URL/VITE_METRICS_AUTH_TOKEN.",
                file=sys.stderr,
            )
    else:
        print(
            "client-env-sync: no registered observer host runs pushgateway -- "
            "skipping VITE_PUSHGATEWAY_URL/VITE_METRICS_AUTH_TOKEN.",
            file=sys.stderr,
        )

    if context.sync_env_keys(context.CLIENT_ENV_PATH, mapping):
        print(f"Synced observability endpoints -> {context.CLIENT_ENV_PATH}")
        return 0
    print(
        f"Note: {context.CLIENT_ENV_PATH} not found; skipping client env sync "
        f"(copy {context.CLIENT_ENV_PATH.name}.example to {context.CLIENT_ENV_PATH.name} first).",
        file=sys.stderr,
    )
    return 1
