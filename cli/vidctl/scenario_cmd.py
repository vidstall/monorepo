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
    apply_parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help=(
            "Path to a scenario TOML file (e.g. scenario/example.toml). If omitted, reuses the "
            "previously applied scenario's path."
        ),
    )
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
    apply_parser.add_argument(
        "--force-contract",
        action="store_true",
        help=(
            "Force a fresh contract publish instead of an upgrade, even if a prior deployment is on record -- "
            "use when the recorded package/upgrade-cap is stale or out of sync with what's actually on-chain "
            "(e.g. PackageIDDoesNotMatch). Overrides [contract].force in the scenario file."
        ),
    )
    apply_parser.set_defaults(
        handler=lambda args: scenario.apply(args.path, args.yes, args.rebake, args.force_contract)
    )

    run_parser = actions.add_parser(
        "run",
        help="Run a scenario's [[actions]] timeline (bot room lifecycle, worker join/leave) against the active scenario.",
    )
    run_parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help=(
            "Path to a scenario TOML file (e.g. scenario/example.toml). If omitted, uses the "
            "currently active scenario."
        ),
    )
    run_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm running the scenario's actions timeline.",
    )
    run_parser.add_argument(
        "--fast",
        action="store_true",
        help=(
            "Skip per-action system-wide telemetry entirely (no before/after/during_action markers, "
            "and nothing to backfill from Prometheus at run end). Per-action telemetry never queries "
            "live during the run either way (it's reconstructed from Prometheus history in one batch "
            "pass at run end), so --fast only saves that end-of-run batch pass, not any in-run "
            "overhead. Room/user quality metrics are unaffected."
        ),
    )
    run_parser.set_defaults(handler=lambda args: scenario.run(args.path, args.yes, args.fast))

    status_parser = actions.add_parser("status", help="Show the active scenario lock and its workers' current state.")
    status_parser.set_defaults(handler=lambda args: scenario.status(args))

    destroy_parser = actions.add_parser(
        "destroy",
        help="Kill every worker owned by the active scenario and release the lock.",
    )
    destroy_parser.set_defaults(handler=lambda args: scenario.destroy(args))
