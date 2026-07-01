from __future__ import annotations

import sys

from .context import CONTRACT_DIR, run


def build(env: str) -> int:
    return run(["sui", "move", "--build-env", env, "build", "--path", CONTRACT_DIR])


def test(env: str) -> int:
    return run(["sui", "move", "--build-env", env, "test", "--path", CONTRACT_DIR])


def check(env: str) -> int:
    code = build(env)
    if code != 0:
        return code
    return test(env)


def publish(dry_run: bool, yes: bool, gas_budget: str | None) -> int:
    if not dry_run and not yes:
        print("Refusing to publish contract without --dry-run or --yes.", file=sys.stderr)
        return 2

    args: list[str | object] = ["sui", "client", "publish", CONTRACT_DIR]
    if dry_run:
        args.append("--dry-run")
    if gas_budget:
        args.extend(["--gas-budget", gas_budget])
    return run(args)
