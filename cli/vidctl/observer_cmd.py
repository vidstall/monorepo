from __future__ import annotations

import argparse
import sys

from .. import observer

# The user has exactly one long-lived static host in practice -- defaulting
# every subcommand's --host to it means day-to-day use never has to spell
# it out (`vidctl observer deploy` just works), while --host stays available
# for anyone who registers additional static hosts later.
DEFAULT_HOST = "bourbon"


def _add_host(args: argparse.Namespace) -> int:
    entry = observer.add_host(args.host, args.address, args.ssh_user, args.ssh_key, args.port)
    print(f"Registered observer host {args.host!r} ({args.address}), published on port {entry['port']}.")
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


def _add_host_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host", default=DEFAULT_HOST, help=f"Observer host name. Default: {DEFAULT_HOST!r}.")


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
    add_parser.set_defaults(handler=_add_host)

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
    _add_host_arg(export_parser)
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
