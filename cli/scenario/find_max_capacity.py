"""Capacity search: sweep bots-per-room (single-room mode) or room-count
(max-rooms mode) upward until end-to-end quality crosses the 400ms
threshold, per the "Quality/capacity/failover evaluation harness" plan.

Per the locked decisions: quality is END-TO-END latency (see
eval_quality.py), and each calibration step fully re-provisions the fleet
(`vidctl scenario apply` + `run` + `destroy`) rather than reusing one
applied topology across the sweep -- slower, but gives each step a clean,
independent measurement with no leftover state from the previous step's
load. This module drives that same apply/run/destroy cycle `vidctl
scenario` already exposes, just called as a loop instead of by hand.

Two phases: a linear step-up to find *some* step that fails the threshold,
then a binary-search refinement between the last passing and first failing
step to tighten the reported ceiling without re-running every intermediate
value.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from . import gen_eval_scenarios
from .apply import apply, destroy
from .eval_quality import avg_end_to_end_ms, latest_run_dir, max_end_to_end_ms
from .run import run

Mode = Literal["single-room", "max-rooms"]


def _run_step(
    *,
    mode: Mode,
    value: int,
    base: Path,
    out_dir: Path,
    hold_seconds: int,
    metric: str,
    threshold_ms: float,
) -> dict[str, Any]:
    rooms, bots_per_room = (1, value) if mode == "single-room" else (value, 2)
    out_path = out_dir / f"step-{value:03d}.toml"
    generated = gen_eval_scenarios.generate(
        base_path=base,
        out_path=out_path,
        name=None,
        rooms=rooms,
        bots_per_room=bots_per_room,
        kill_fraction=0.0,
        kill_at="+120s",
        hold_seconds=hold_seconds,
        seed=1,
    )

    step: dict[str, Any] = {"value": value, "rooms": rooms, "bots_per_room": bots_per_room, "scenario": str(generated)}
    try:
        if apply(str(generated), yes=True) != 0:
            step["error"] = "apply failed"
            return step
        if run(str(generated), yes=True, fast=False, report=True) != 0:
            step["error"] = "run failed"
            return step

        scenario_name = generated.stem
        run_dir = latest_run_dir(scenario_name)
        if run_dir is None:
            step["error"] = "no run directory found after run"
            return step

        value_ms = avg_end_to_end_ms(run_dir) if metric == "avg" else max_end_to_end_ms(run_dir)
        step["quality_ms"] = value_ms
        step["metric"] = metric
        step["run_dir"] = str(run_dir)
        step["passed"] = value_ms is not None and value_ms <= threshold_ms
    finally:
        destroy(None)

    return step


def search(
    *,
    mode: Mode,
    base: Path,
    out_dir: Path,
    start: int,
    step_size: int,
    threshold_ms: float,
    metric: str,
    hold_seconds: int,
    max_steps: int = 20,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []

    current = start
    last_pass: int | None = None
    first_fail: int | None = None
    for _ in range(max_steps):
        result = _run_step(
            mode=mode, value=current, base=base, out_dir=out_dir,
            hold_seconds=hold_seconds, metric=metric, threshold_ms=threshold_ms,
        )
        history.append(result)
        print(f"step={current}: {result}")
        if result.get("error") or not result.get("passed", False):
            first_fail = current
            break
        last_pass = current
        current += step_size

    if last_pass is not None and first_fail is not None:
        low, high = last_pass, first_fail
        while high - low > 1:
            mid = (low + high) // 2
            result = _run_step(
                mode=mode, value=mid, base=base, out_dir=out_dir,
                hold_seconds=hold_seconds, metric=metric, threshold_ms=threshold_ms,
            )
            history.append(result)
            print(f"refine={mid}: {result}")
            if result.get("error") or not result.get("passed", False):
                high = mid
            else:
                low = mid

    summary = {
        "mode": mode,
        "metric": metric,
        "threshold_ms": threshold_ms,
        "max_passing": last_pass,
        "first_failing": first_fail,
        "history": history,
    }
    (out_dir / "capacity_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=["single-room", "max-rooms"])
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--start", type=int, default=3)
    parser.add_argument("--step", type=int, default=3, dest="step_size")
    parser.add_argument("--threshold-ms", type=float, default=400.0)
    parser.add_argument("--metric", choices=["avg", "max"], default="avg")
    parser.add_argument("--hold-seconds", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=20)
    args = parser.parse_args(argv)

    if not args.base.exists():
        print(f"find_max_capacity: base scenario {args.base} not found.", file=sys.stderr)
        return 2

    summary = search(
        mode=args.mode, base=args.base, out_dir=args.out_dir, start=args.start,
        step_size=args.step_size, threshold_ms=args.threshold_ms, metric=args.metric,
        hold_seconds=args.hold_seconds, max_steps=args.max_steps,
    )
    print(f"\nMax passing {args.mode} value: {summary['max_passing']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
