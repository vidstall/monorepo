from __future__ import annotations

import argparse

from .. import image_bake, local_bot, worker_status


def add_utils_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("utils", help="Operational utilities (golden-image baking, etc).")
    actions = parser.add_subparsers(dest="action", required=True)

    bake_parser = actions.add_parser(
        "image-bake",
        help="Bake a Docker-preinstalled golden image for one provider+region.",
    )
    bake_parser.add_argument(
        "--provider",
        required=True,
        choices=sorted(image_bake.SUPPORTED_PROVIDERS),
        help="Cloud provider to bake an image for.",
    )
    bake_parser.add_argument(
        "--region",
        required=True,
        help="Provider region/zone to bake into (e.g. us-east-1, eastus, cn-hangzhou, nyc3).",
    )
    bake_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm provisioning a temporary VM and creating a billable cloud image.",
    )
    bake_parser.set_defaults(handler=lambda args: image_bake.bake(args.provider, args.region, args.yes))

    image_parser = actions.add_parser("image", help="Inspect baked golden images.")
    image_actions = image_parser.add_subparsers(dest="image_action", required=True)
    list_parser = image_actions.add_parser("list", help="List all baked images and their (provider, region).")
    list_parser.set_defaults(handler=lambda _args: image_bake.list_images())

    bot_parser = actions.add_parser(
        "bot", help="Run apps/bot dev-server session(s) on this machine (not the cloud fleet)."
    )
    bot_actions = bot_parser.add_subparsers(dest="bot_action", required=True)

    bot_start_parser = bot_actions.add_parser(
        "start", help="Start a local bot session that creates a room and streams into it."
    )
    bot_start_parser.add_argument("id", type=int, help="Local session id, counting from 1.")
    bot_start_parser.set_defaults(handler=lambda args: local_bot.start(args.id))

    bot_stop_parser = bot_actions.add_parser("stop", help="Stop a local bot session.")
    bot_stop_parser.add_argument("id", type=int, help="Local session id, counting from 1.")
    bot_stop_parser.set_defaults(handler=lambda args: local_bot.stop(args.id))

    bot_refresh_parser = bot_actions.add_parser(
        "refresh",
        help=(
            "Revive a crashed local bot session -- restarts the process and rejoins its "
            "existing room instead of creating a new one. No-op if already running."
        ),
    )
    bot_refresh_parser.add_argument("id", type=int, help="Local session id, counting from 1.")
    bot_refresh_parser.set_defaults(handler=lambda args: local_bot.refresh(args.id))

    bot_list_parser = bot_actions.add_parser("list", help="List local bot sessions.")
    bot_list_parser.set_defaults(handler=lambda _args: local_bot.list_bots())

    bot_log_parser = bot_actions.add_parser("log", help="Show a local bot session's log file.")
    bot_log_parser.add_argument("id", type=int, help="Local session id, counting from 1.")
    bot_log_parser.add_argument(
        "-n", "--lines", type=int, default=100, help="Number of trailing lines to show (default: 100)."
    )
    bot_log_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow the log file as it grows (like `tail -f`)."
    )
    bot_log_parser.set_defaults(handler=lambda args: local_bot.log(args.id, lines=args.lines, follow=args.follow))

    worker_parser = actions.add_parser("worker", help="Inspect a deployed fleet worker.")
    worker_actions = worker_parser.add_subparsers(dest="worker_action", required=True)

    worker_status_parser = worker_actions.add_parser(
        "status", help="SSH into a worker's host and show its Docker container status, resource usage, and recent logs."
    )
    worker_status_parser.add_argument(
        "hostname",
        help=(
            "The worker's public identifier, e.g. "
            "45-79-134-247.sslip.io/akamai-004/relay-1 (or the legacy "
            "akamai-003-relay-1.96-126-106-95.sslip.io form)."
        ),
    )
    worker_status_parser.set_defaults(handler=lambda args: worker_status.status(args.hostname))

    worker_start_parser = worker_actions.add_parser("start", help="docker start a worker's container.")
    worker_start_parser.add_argument(
        "hostname",
        help=(
            "The worker's public identifier, e.g. "
            "45-79-134-247.sslip.io/akamai-004/relay-1 (or the legacy "
            "akamai-003-relay-1.96-126-106-95.sslip.io form)."
        ),
    )
    worker_start_parser.set_defaults(handler=lambda args: worker_status.start(args.hostname))

    worker_stop_parser = worker_actions.add_parser("stop", help="docker stop a worker's container.")
    worker_stop_parser.add_argument(
        "hostname",
        help=(
            "The worker's public identifier, e.g. "
            "45-79-134-247.sslip.io/akamai-004/relay-1 (or the legacy "
            "akamai-003-relay-1.96-126-106-95.sslip.io form)."
        ),
    )
    worker_stop_parser.set_defaults(handler=lambda args: worker_status.stop(args.hostname))
