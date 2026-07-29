from __future__ import annotations

import sys
from pathlib import Path

from .actions import run_actions
from .lock import read_lock
from .spec import load_scenario


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

    return run_actions(scenario, scenario["env"])
