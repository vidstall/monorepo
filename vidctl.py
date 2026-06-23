#!/usr/bin/env python3
from __future__ import annotations

import shlex
import subprocess
import sys

from cli.parser import parse_args


def main() -> int:
    args = parse_args()
    try:
        args.func(args)
    except subprocess.CalledProcessError as exc:
        print(
            f"Command failed with exit code {exc.returncode}: {shlex.join(exc.cmd)}",
            file=sys.stderr,
        )
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
