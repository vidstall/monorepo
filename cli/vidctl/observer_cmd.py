from __future__ import annotations

import argparse
import sys

from .. import observer

# The user has exactly one long-lived static host in practice -- defaulting
# every subcommand's --host to it means day-to-day use never has to spell
# it out (`vidctl observer deploy` just works), while --host stays available
# for anyone who registers additional static hosts later.
DEFAULT_HOST = "baileys"
# Pushgateway/Prometheus specifically live on "bourbon" (see runtime/observer.toml's
# per-host `services` split), NOT the DEFAULT_HOST above -- that's baileys, which
# only runs grafana. Any subcommand that PUTs to the Pushgateway or queries
# Prometheus needs THIS default, or it silently hits a host with no matching
# Caddy site block for that route (TLS handshake fails outright, not a clean 404).
PUSHGATEWAY_HOST = "bourbon"


def _parse_services(raw: str | None) -> list[str] | None:
    """Comma-separated subset of observer.ALL_SERVICE_NAMES, or None (meaning
    "all 5", today's implicit default -- see add_host()/inventory.py's
    fallback) when --services wasn't passed at all."""
    if raw is None:
        return None
    names = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = [n for n in names if n not in observer.ALL_SERVICE_NAMES]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Unknown service(s): {', '.join(unknown)}. Known: {', '.join(observer.ALL_SERVICE_NAMES)}."
        )
    return names


def _add_host(args: argparse.Namespace) -> int:
    services = _parse_services(args.services)
    entry = observer.add_host(args.host, args.address, args.ssh_user, args.ssh_key, args.port, services)
    print(f"Registered observer host {args.host!r} ({args.address}), published on port {entry['port']}.")
    return 0


def _set_services(args: argparse.Namespace) -> int:
    host = observer.find_host(args.host)
    if host is None:
        print(f"Unknown observer host: {args.host}", file=sys.stderr)
        return 1
    services = _parse_services(args.services)
    assert services is not None  # --services is required on this subcommand
    observer.add_host(host["name"], host["address"], host["ssh_user"], host["ssh_key"], host.get("port"), services)
    print(f"Updated {args.host!r}'s services to: {', '.join(services)}.")
    return 0


def _remove_host(args: argparse.Namespace) -> int:
    if not observer.remove_host(args.host):
        print(f"Unknown observer host: {args.host}", file=sys.stderr)
        return 1
    print(
        f"Forgot observer host {args.host!r}. Nothing was changed on the remote "
        "host itself -- stop/remove its containers there manually if needed."
    )
    return 0


def _add_host_arg(p: argparse.ArgumentParser, default: str = DEFAULT_HOST) -> None:
    p.add_argument("--host", default=default, help=f"Observer host name. Default: {default!r}.")


def add_observer_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "observer",
        help=(
            "Deploy/manage prometheus on static, operator-owned hosts that vidctl must never "
            "create, destroy, or reboot (see cli/infra for Pulumi-managed cloud hosts)."
        ),
    )
    actions = parser.add_subparsers(dest="action", required=True)

    add_parser = actions.add_parser("add-host", help="Register a static host for `vidctl observer` commands.")
    _add_host_arg(add_parser)
    add_parser.add_argument("--address", required=True, help="IP address or hostname to SSH into.")
    add_parser.add_argument("--ssh-user", required=True, help="SSH login user, e.g. deploy.")
    add_parser.add_argument("--ssh-key", required=True, help="Path to the SSH private key, e.g. ~/.ssh/rotexai/bourbon-deploy.")
    add_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            f"Loopback-only host port prometheus is published under (never the container's own "
            f"internal 9090). Default: {observer.DEFAULT_HOST_PORT}."
        ),
    )
    add_parser.add_argument(
        "--services",
        default=None,
        help=(
            "Comma-separated subset of {" + ",".join(observer.ALL_SERVICE_NAMES) + "} this host should "
            "run -- lets weak static hosts divide the monitoring stack between them. Default: all 5 "
            "(today's colocated behavior)."
        ),
    )
    add_parser.set_defaults(handler=_add_host)

    set_services_parser = actions.add_parser(
        "set-services",
        help="Change which monitoring services a registered host runs, without re-supplying its connection info.",
    )
    _add_host_arg(set_services_parser)
    set_services_parser.add_argument(
        "--services",
        required=True,
        help="Comma-separated subset of {" + ",".join(observer.ALL_SERVICE_NAMES) + "}.",
    )
    set_services_parser.set_defaults(handler=_set_services)

    remove_parser = actions.add_parser(
        "remove-host",
        help="Forget a registered host locally. Does NOT stop/remove anything on the remote host.",
    )
    _add_host_arg(remove_parser)
    remove_parser.set_defaults(handler=_remove_host)

    deploy_parser = actions.add_parser("deploy", help="Deploy/update prometheus on an observer host.")
    _add_host_arg(deploy_parser)
    deploy_parser.set_defaults(handler=lambda args: observer.deploy(args.host))

    status_parser = actions.add_parser("status", help="Check SSH reachability of an observer host.")
    _add_host_arg(status_parser)
    status_parser.set_defaults(handler=lambda args: observer.status(args.host))

    start_parser = actions.add_parser("start", help="Start the prometheus container (no-op if already running).")
    _add_host_arg(start_parser)
    start_parser.set_defaults(handler=lambda args: observer.start(args.host))

    stop_parser = actions.add_parser("stop", help="Stop the prometheus container without removing it.")
    _add_host_arg(stop_parser)
    stop_parser.set_defaults(handler=lambda args: observer.stop(args.host))

    restart_parser = actions.add_parser("restart", help="Force-restart the prometheus container.")
    _add_host_arg(restart_parser)
    restart_parser.set_defaults(handler=lambda args: observer.restart(args.host))

    destroy_parser = actions.add_parser(
        "destroy",
        help="Remove the prometheus container (docker rm). Its TSDB data directory is preserved on disk.",
    )
    _add_host_arg(destroy_parser)
    destroy_parser.set_defaults(handler=lambda args: observer.destroy(args.host))

    clean_parser = actions.add_parser(
        "clean",
        help="Remove the prometheus container AND wipe its TSDB data directory (permanent history loss).",
    )
    _add_host_arg(clean_parser)
    clean_parser.set_defaults(handler=lambda args: observer.clean(args.host))

    export_parser = actions.add_parser(
        "export-contract-state",
        help=(
            "Push wallet-pool and on-chain registration state to the observer host's Pushgateway "
            "(Contract & Chain dashboard). One-shot by default; only as fresh as the last run."
        ),
    )
    _add_host_arg(export_parser, default=PUSHGATEWAY_HOST)
    export_parser.add_argument("--env", default="devnet", help="Contract network to read. Default: devnet.")
    export_parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep re-pushing every --interval seconds instead of exiting after one push.",
    )
    export_parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Seconds between pushes when --watch is set. Default: 60.",
    )
    export_parser.set_defaults(
        handler=lambda args: observer.export_contract_state(args.env, args.host, args.watch, args.interval)
    )

    sync_client_env_parser = actions.add_parser(
        "sync-client-env",
        help=(
            "Write the registered loki host's public URL and auth token into "
            "services/client/client/.env as VITE_* vars, so the browser can push log "
            "batches directly to the observer stack instead of via a relay."
        ),
    )
    sync_client_env_parser.set_defaults(handler=lambda args: observer.sync_client_observability_env())
