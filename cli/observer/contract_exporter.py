from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

# Same 4-role split MinerStore actually tracks on-chain (see
# services/contract/sources/miner/miner_store.move's cp_miners/relay_miners/
# validator_miners/user_miners VecSet<ID> fields) -- keyed
# here by the plain role name used everywhere else in this CLI (wallet pool
# entries' registered_role, deploy_one_service.yml's service branches).
_MINER_STORE_ROLE_FIELDS = {
    "cp-daemon": "cp_miners",
    "relay": "relay_miners",
    "validator-daemon": "validator_miners",
    "user": "user_miners",
}

_JOB_NAME = "contract_state"


def _wallet_pool_role_and_status(entry: dict) -> tuple[str, str]:
    """Split (role, status) for dvconf_wallet_pool_count's two labels --
    independent dimensions, unlike cli/gui/pages/contract_page/render.py's
    _chart_status_key() (a single conflated string built for that GUI's own
    pie-chart bucketing, not reused here since that module pulls in flet,
    which this exporter -- runs headless, no GUI -- has no reason to
    depend on). `status` is one of assigned/idle/free/retired; `role` is
    the registered role, or "unassigned" if this wallet has never been
    checked out for one."""
    role = entry.get("registered_role") or "unassigned"
    if entry.get("retired"):
        return role, "retired"
    if entry.get("assigned_host"):
        return role, "assigned"
    if entry.get("registered_role"):
        return role, "idle"
    return role, "free"


def collect_contract_state(env: str) -> list[tuple[str, dict[str, str], float]]:
    """Gather wallet-pool + on-chain registration + contract metadata into a
    flat list of (metric_name, labels, value) gauge samples. Best-effort per
    section -- a failed on-chain read (chain unreachable, object not yet
    created) only drops that section's samples, it never aborts the whole
    export, matching this CLI's existing warn-and-continue convention (see
    cli/wallet/chain_ops.py's faucet_if_needed)."""
    from .. import contract as contract_cli
    from .. import wallet as wallet_cli

    samples: list[tuple[str, dict[str, str], float]] = []

    try:
        wallets = wallet_cli.pool_status(env).get(env, [])
    except Exception as exc:  # noqa: BLE001 - one failed section must not abort the export
        print(f"Warning: could not read wallet pool for [{env}]: {exc}", file=sys.stderr)
        wallets = []
    pool_counts: dict[tuple[str, str], int] = {}
    for entry in wallets:
        key = _wallet_pool_role_and_status(entry)
        pool_counts[key] = pool_counts.get(key, 0) + 1
        # Monitoring-redesign gap #3: per-wallet gas balance. `last_balance_mist` is
        # already populated on every pool entry by chain_ops.py's checkout/faucet
        # flow -- this is only as fresh as the last checkout/faucet check, never
        # live-polled (an accepted tradeoff, not a bug).
        samples.append((
            "dvconf_wallet_balance_mist",
            {"alias": str(entry.get("alias", "")), "address": str(entry.get("address", ""))},
            float(entry.get("last_balance_mist") or 0),
        ))
    for (role, status), count in pool_counts.items():
        samples.append(("dvconf_wallet_pool_count", {"role": role, "status": status}, float(count)))

    deployment = contract_cli.load_deployment(env)
    published = bool(deployment.get("CONTRACT_PACKAGE_ID"))
    samples.append(("dvconf_contract_published", {}, 1.0 if published else 0.0))
    if published:
        samples.append((
            "dvconf_contract_package_info",
            {
                "package_id": deployment.get("CONTRACT_PACKAGE_ID", ""),
                "chain_id": deployment.get("CONTRACT_CHAIN_ID", ""),
            },
            1.0,
        ))

    miner_store_id = deployment.get("MINER_STORE_ID", "")
    if miner_store_id:
        fields = contract_cli.fetch_object(miner_store_id)
        if fields is None:
            print(f"Warning: could not fetch MinerStore {miner_store_id} for [{env}]; skipping registration counts.", file=sys.stderr)
        else:
            for role, field_name in _MINER_STORE_ROLE_FIELDS.items():
                vec_set = fields.get(field_name) or {}
                contents = vec_set.get("contents") if isinstance(vec_set, dict) else None
                if contents is None:
                    continue
                samples.append(("dvconf_onchain_registered_count", {"role": role}, float(len(contents))))
    elif published:
        print(f"Warning: no MINER_STORE_ID on file for [{env}]; skipping registration counts.", file=sys.stderr)

    # UserRegistry is a SEPARATE object from MinerStore -- it tracks actual
    # app users who called user_registry::register_user() (see
    # services/client's useNetworkStats.ts, which reads this same
    # total_users field via devInspect), not the "user" bucket of
    # MinerStore's role VecSets above (that one only ever fills from
    # miner_store::register(), which no client-side code path calls -- it
    # stays 0 regardless of how many real users connect). Exposed as its own
    # metric name rather than folded into dvconf_onchain_registered_count's
    # role label, since conflating the two was exactly the confusion this
    # was added to fix.
    user_registry_id = deployment.get("USER_REGISTRY_ID", "")
    if user_registry_id:
        fields = contract_cli.fetch_object(user_registry_id)
        if fields is None:
            print(f"Warning: could not fetch UserRegistry {user_registry_id} for [{env}]; skipping registered-user count.", file=sys.stderr)
        else:
            total_users = fields.get("total_users")
            if total_users is not None:
                samples.append(("dvconf_registered_users_total", {}, float(total_users)))
    elif published:
        print(f"Warning: no USER_REGISTRY_ID on file for [{env}]; skipping registered-user count.", file=sys.stderr)

    return samples


def format_prometheus_text(samples: list[tuple[str, dict[str, str], float]]) -> str:
    """Prometheus text-exposition format (version 0.0.4), same shape
    services/worker/packages/shared/src/metrics-prom.ts's pushToGateway()
    builds -- one HELP/TYPE pair per distinct metric name, then one sample
    line per (labels, value)."""
    seen_names: set[str] = set()
    lines: list[str] = []
    for name, labels, value in samples:
        if name not in seen_names:
            seen_names.add(name)
            lines.append(f"# HELP {name} dvconf contract/wallet state, pushed by `vidctl observer export-contract-state`.")
            lines.append(f"# TYPE {name} gauge")
        if labels:
            label_str = ",".join(f'{key}="{val.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"' for key, val in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def push_contract_state(env: str, host: str = "bourbon") -> int:
    """Compute the current snapshot and PUT it to the observer host's
    Pushgateway, under job=contract_state/instance=<env> (see
    observer-caddyfile.j2's bearer-gated pushgateway.<ip>.sslip.io site
    block -- same route/auth the TS eval scripts' pushToGateway() already
    uses). Returns 0 on a successful push, 1 if the push itself failed
    (an empty/missing host, unreachable gateway, or non-2xx response) --
    a section-level read failure above only drops that section's samples,
    it does not fail the push."""
    from .. import infra
    from .config import find_host

    host_entry = find_host(host)
    if host_entry is None:
        print(f"Unknown observer host: {host}", file=sys.stderr)
        return 1

    samples = collect_contract_state(env)
    body = format_prometheus_text(samples)

    dashed = str(host_entry["address"]).replace(".", "-")
    url = f"https://pushgateway.{dashed}.sslip.io/metrics/job/{_JOB_NAME}/instance/{env}"
    token = infra.metrics_auth_token()

    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        method="PUT",
        headers={
            "content-type": "text/plain; version=0.0.4",
            "authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        print(f"Warning: pushing contract state to {url} failed: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Warning: pushing contract state to {url} failed: {exc.reason}", file=sys.stderr)
        return 1

    if status_code >= 300:
        print(f"Warning: pushing contract state to {url} failed: HTTP {status_code}", file=sys.stderr)
        return 1

    print(f"Pushed {len(samples)} contract-state sample(s) for [{env}] to {url}.")
    return 0


def export_contract_state(env: str, host: str = "bourbon", watch: bool = False, interval: int = 60) -> int:
    """CLI entrypoint for `vidctl observer export-contract-state`. One-shot
    by default (push once and exit, same shape as the existing eval
    scripts' single Pushgateway push); --watch re-pushes every `interval`
    seconds instead of exiting, for a continuously-fresher (rather than
    only as-fresh-as-the-last-manual-run) Contract & Chain dashboard."""
    if not watch:
        return push_contract_state(env, host)

    code = 0
    try:
        while True:
            code = push_contract_state(env, host)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return code
