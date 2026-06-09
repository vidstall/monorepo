from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


def run_command(args: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> None:
    print(f"+ {shlex.join(args)}", flush=True)
    subprocess.run(args, cwd=str(cwd), env=dict(env), check=True)
