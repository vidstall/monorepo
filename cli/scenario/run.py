from __future__ import annotations

import sys
from pathlib import Path

from .actions import run_actions
from .lock import read_lock
from .metrics_sampler import INTERVAL_SECONDS, MetricsSampler
from .spec import load_scenario
from .system_log import SystemLog, record_snapshot_event


def run(path_str: str, yes: bool) -> int:
    if not yes:
        print("Refusing to run a scenario's actions without --yes.", file=sys.stderr)
        return 2

    path = Path(path_str)
    try:
        scenario = load_scenario(path)
    except ValueError as exc:
        print(f"Invalid scenario file: {exc}", file=sys.stderr)
        return 2

    scenario_path_display = str(path.resolve())
    lock = read_lock()
    if lock is None or lock.get("status") != "active" or lock.get("scenario_path") != scenario_path_display:
        held = f"'{lock.get('scenario_path')}' (status={lock.get('status')})" if lock else "none"
        print(
            f"Refusing to run '{scenario_path_display}': it must be the currently active scenario "
            f"(run 'vidctl scenario apply' first). Currently active: {held}.",
            file=sys.stderr,
        )
        return 1

    env = scenario["env"]
    system_log = SystemLog(scenario_path_display, env, path.stem)
    print(f"Logging system status for this run to: {system_log.run_dir}")
    record_snapshot_event(system_log, env, "run_start")

    metrics_sampler = MetricsSampler(env)
    metrics_sampler.start()
    print(
        f"Capturing live metrics every {INTERVAL_SECONDS}s "
        f"under data/metrics/<provider>/{metrics_sampler.run_timestamp}/"
    )
    try:
        return run_actions(scenario, env, system_log=system_log)
    finally:
        record_snapshot_event(system_log, env, "run_end")
        metrics_sampler.stop()
