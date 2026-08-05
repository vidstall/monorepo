from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from ..observer.grafana_render import capture_dashboard_images
from .actions import run_actions
from .lock import read_lock
from .metrics_sampler import INTERVAL_SECONDS, MetricsSampler
from .report import generate_report
from .spec import load_scenario
from .system_log import SystemLog, backfill_action_snapshots, record_snapshot_event


def run(path_str: str | None, yes: bool, fast: bool = False, report: bool = True) -> int:
    if not yes:
        print("Refusing to run a scenario's actions without --yes.", file=sys.stderr)
        return 2

    if path_str is None:
        active = read_lock()
        if active is None or active.get("status") != "active" or not active.get("scenario_path"):
            print(
                "Refusing to run: no scenario path given and no scenario is currently active "
                "(run 'vidctl scenario apply' first).",
                file=sys.stderr,
            )
            return 1
        path_str = str(active["scenario_path"])
        print(f"No scenario path given; using currently active scenario: {path_str}")

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
    # Generated ONCE, before either SystemLog or MetricsSampler is
    # constructed, so both trees land under the exact same <run_timestamp>
    # -- representing the moment `scenario run` was invoked, not whenever
    # each object happened to get constructed a few dozen ms (or, for the
    # sampler's first tick, a full INTERVAL_SECONDS) later.
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    system_log = SystemLog(scenario_path_display, env, path.stem, run_timestamp=run_timestamp)
    print(f"Logging system status for this run to: {system_log.run_dir}")
    record_snapshot_event(system_log, env, "run_start")

    metrics_sampler = MetricsSampler(env, run_timestamp=run_timestamp, room_provider_key=path.stem)
    metrics_sampler.start()
    print(
        f"Capturing live metrics every {INTERVAL_SECONDS}s "
        f"under {system_log.run_dir} (room/user) and logs/<provider>/{metrics_sampler.run_timestamp}/ (infra/worker)"
    )
    run_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if fast:
        print(
            "--fast: skipping per-action markers entirely (no before/after/during_action events, "
            "and nothing to backfill at run end) -- room/user quality metrics are unaffected. Since "
            "per-action telemetry no longer queries live during the run either way (see "
            "backfill_action_snapshots), --fast now only saves the run-end historical batch pass, "
            "not any in-run overhead."
        )
    try:
        return run_actions(scenario, env, system_log=None if fast else system_log)
    finally:
        record_snapshot_event(system_log, env, "run_end")
        # Every before_action/after_action/during_action marker recorded
        # during the run was cheap (identity + timestamp, no Prometheus
        # query -- see record_action_marker()'s doc); this is the single
        # bounded batch pass that fetches each one's historical telemetry
        # now that the scripted timeline is done and there's nothing left
        # to block. A --fast run has no markers to backfill at all (system_log
        # was None throughout run_actions), so this is a fast no-op there.
        backfilled = backfill_action_snapshots(system_log, env)
        if backfilled:
            print(f"Backfilled historical telemetry for {backfilled} action marker(s).")
        metrics_sampler.stop()
        run_end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        img_dir = system_log.run_dir / "img"
        try:
            captured = capture_dashboard_images(run_start_ms, run_end_ms, img_dir)
        except Exception as exc:  # noqa: BLE001 - image capture must never fail the run
            print(f"Warning: Grafana panel capture failed: {exc}", file=sys.stderr)
        else:
            print(f"Captured {captured} Grafana panel image(s) to {img_dir}")

        if report:
            try:
                generate_report(system_log, env, run_start_ms, run_end_ms, img_dir)
            except Exception as exc:  # noqa: BLE001 - report generation must never fail the run
                print(f"Warning: report generation failed: {exc}", file=sys.stderr)
