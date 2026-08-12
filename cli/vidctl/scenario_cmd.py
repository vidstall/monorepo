from __future__ import annotations

import argparse
from pathlib import Path

from .. import scenario
from ..scenario import find_max_capacity, gen_eval_scenarios


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
    run_parser.add_argument(
        "--no-report",
        action="store_true",
        help=(
            "Skip generating the post-run report (summary.txt, CSV export, matplotlib diagrams, and "
            "report.md under logs/<scenario_name>/<run_timestamp>/report/) that's produced by default "
            "once the run finishes."
        ),
    )
    run_parser.add_argument(
        "--mini-log",
        action="store_true",
        help=(
            "Fast run-end logging instead of the full report: captures Grafana panels at reduced "
            "resolution, and skips the CSV/chart/Markdown report pipeline entirely in favor of one "
            "condensed summary (mini_log.json/mini_log.txt under logs/<scenario_name>/<run_timestamp>/) "
            "covering per-instance cpu/ram, per-worker-role cpu/ram, and per-room session averages "
            "(latency, jitter, packet loss, bitrate up/down, frame rate, resolution, ICE success rate, "
            "relay-failover downtime, and a participants-over-time series). Overrides --no-report."
        ),
    )
    run_parser.set_defaults(
        handler=lambda args: scenario.run(args.path, args.yes, args.fast, not args.no_report, args.mini_log)
    )

    status_parser = actions.add_parser("status", help="Show the active scenario lock and its workers' current state.")
    status_parser.set_defaults(handler=lambda args: scenario.status(args))

    destroy_parser = actions.add_parser(
        "destroy",
        help="Kill every worker owned by the active scenario and release the lock.",
    )
    destroy_parser.set_defaults(handler=lambda args: scenario.destroy(args))

    clean_parser = actions.add_parser(
        "clean",
        help=(
            "Stop leftover bot sessions/rooms from a crashed or interrupted run and wipe "
            "Prometheus/Tempo history, without tearing down the active scenario's workers."
        ),
    )
    clean_parser.set_defaults(handler=lambda args: scenario.clean(args))

    _add_eval_parsers(actions)


def _add_eval_parsers(actions: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """`vidctl scenario eval-*` -- generation/sweep helpers for the
    quality/capacity evaluation harness (see cli/scenario/gen_eval_scenarios.py,
    find_max_capacity.py). Both subcommands only ever produce or apply/run
    ordinary scenario TOML files through the normal apply/run path -- they
    don't compute or report results themselves. Reading results back out
    (quality, failover recovery/downtime, etc.) goes through the Grafana
    observation system (see e.g. peer-quality.json's "Relay Failover
    Downtime" panel, infrastructure.json's node-up panels), not a
    separate script -- there used to be an eval-recovery/eval-suite pair
    that computed and reported those numbers outside that system; removed
    deliberately so results have exactly one source of truth."""

    gen_parser = actions.add_parser(
        "eval-gen",
        help="Generate an evaluation scenario TOML from a base topology file.",
    )
    gen_parser.add_argument("--base", required=True, type=Path)
    gen_parser.add_argument("--out", required=True, type=Path)
    gen_parser.add_argument("--name", default=None)
    gen_parser.add_argument("--rooms", type=int, default=1)
    gen_parser.add_argument("--bots-per-room", type=int, default=3)
    gen_parser.add_argument("--kill-fraction", type=float, default=0.0)
    gen_parser.add_argument("--kill-at", default="+120s")
    gen_parser.add_argument("--hold-seconds", type=int, default=300)
    gen_parser.add_argument("--seed", type=int, default=1)
    gen_parser.set_defaults(handler=_handle_eval_gen)

    capacity_parser = actions.add_parser(
        "eval-find-capacity",
        help="Sweep bots/room or room-count until end-to-end quality crosses the threshold (re-provisions per step).",
    )
    capacity_parser.add_argument("--mode", required=True, choices=["single-room", "max-rooms"])
    capacity_parser.add_argument("--base", required=True, type=Path)
    capacity_parser.add_argument("--out-dir", required=True, type=Path)
    capacity_parser.add_argument("--start", type=int, default=3)
    capacity_parser.add_argument("--step", type=int, default=3, dest="step_size")
    capacity_parser.add_argument("--threshold-ms", type=float, default=400.0)
    capacity_parser.add_argument("--metric", choices=["avg", "max"], default="avg")
    capacity_parser.add_argument("--hold-seconds", type=int, default=300)
    capacity_parser.set_defaults(handler=_handle_eval_find_capacity)


def _handle_eval_gen(args: argparse.Namespace) -> int:
    gen_eval_scenarios.generate(
        base_path=args.base, out_path=args.out, name=args.name, rooms=args.rooms,
        bots_per_room=args.bots_per_room, kill_fraction=args.kill_fraction, kill_at=args.kill_at,
        hold_seconds=args.hold_seconds, seed=args.seed,
    )
    return 0


def _handle_eval_find_capacity(args: argparse.Namespace) -> int:
    find_max_capacity.search(
        mode=args.mode, base=args.base, out_dir=args.out_dir, start=args.start,
        step_size=args.step_size, threshold_ms=args.threshold_ms, metric=args.metric,
        hold_seconds=args.hold_seconds,
    )
    return 0
