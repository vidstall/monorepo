from __future__ import annotations

import argparse

from .. import scenario


def add_scenario_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "scenario",
        help="Declaratively manage a full compute topology from a TOML scenario file.",
    )
    actions = parser.add_subparsers(dest="action", required=True)

    apply_parser = actions.add_parser(
        "apply",
        help="Publish contract+images and reconcile workers to match a scenario file.",
    )
    apply_parser.add_argument("path", help="Path to a scenario TOML file (e.g. scenario/example.toml).")
    apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the scenario apply (contract publish, image publish, worker reconcile).",
    )
    apply_parser.add_argument(
        "--rebake",
        action="store_true",
        help=(
            "Force a fresh golden image bake for every (provider, region) this scenario needs, even if one "
            "already exists -- use after `vidctl registry publish` so the rebaked image's pre-pulled app "
            "images aren't stale relative to what's about to be deployed."
        ),
    )
    apply_parser.set_defaults(handler=lambda args: scenario.apply(args.path, args.yes, args.rebake))

    run_parser = actions.add_parser(
        "run",
        help="Run a scenario's [[actions]] timeline (bot room lifecycle, worker join/leave) against the active scenario.",
    )
    run_parser.add_argument("path", help="Path to a scenario TOML file (e.g. scenario/example.toml).")
    run_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm running the scenario's actions timeline.",
    )
    run_parser.set_defaults(handler=lambda args: scenario.run(args.path, args.yes))

    status_parser = actions.add_parser("status", help="Show the active scenario lock and its workers' current state.")
    status_parser.set_defaults(handler=lambda args: scenario.status(args))

    destroy_parser = actions.add_parser(
        "destroy",
        help="Kill every worker owned by the active scenario and release the lock.",
    )
    destroy_parser.set_defaults(handler=lambda args: scenario.destroy(args))
