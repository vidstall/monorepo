from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from cli.config import REPO_ROOT

SCENARIO_DIR = REPO_ROOT / "scenario"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"


def cmd_testbed_list(args: argparse.Namespace) -> None:
    scripts = sorted(SCENARIO_DIR.glob("*.py"))
    if not scripts:
        print("No scenario scripts found in scenario/")
        return

    rows: list[tuple[str, str]] = []
    for path in scripts:
        name = path.stem
        description = ""
        spec = importlib.util.spec_from_file_location(f"_scenario_{name}", path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                description = getattr(mod, "DESCRIPTION", "") or ""
                name = getattr(mod, "NAME", name) or name
            except Exception:
                pass
        rows.append((name, description))

    name_w = max(len(r[0]) for r in rows)
    print(f"{'SCENARIO':<{name_w}}  DESCRIPTION")
    print("-" * (name_w + 2 + 60))
    for n, d in rows:
        print(f"{n:<{name_w}}  {d}")


def cmd_testbed_clean(args: argparse.Namespace) -> None:
    if not ARTIFACTS_DIR.exists():
        print("artifacts/ does not exist — nothing to clean")
        return
    import shutil
    removed = 0
    for item in ARTIFACTS_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        removed += 1
    print(f"Removed {removed} item(s) from {ARTIFACTS_DIR}")


def cmd_testbed_results(args: argparse.Namespace) -> None:
    if not ARTIFACTS_DIR.exists():
        print("No artifacts directory found — run a scenario first")
        return
    reports = sorted(ARTIFACTS_DIR.glob("**/*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        print("No JSON benchmark reports found in artifacts/")
        return
    latest = reports[0]
    print(f"Report: {latest}\n")
    data = json.loads(latest.read_text(encoding="utf-8"))
    print(json.dumps(data, indent=2))
