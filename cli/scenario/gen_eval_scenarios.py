"""Generate an evaluation scenario TOML from a base topology file, per the
"Quality/capacity/failover evaluation harness" plan.

`spec.py`'s scenario schema has no declarative "N bots / M rooms" knob --
every bot session is one explicit `[[actions]]` row (see spec.py's module
comment and actions.py's `_bot_create_room`/`_bot_join_room`). This module
is the generator that turns (rooms, bots_per_room, kill_fraction) into that
action list, reusing the base file's `[contract]`/`[registry]`/
`[[frontends]]`/`[[workers]]` topology as-is so infra/credentials aren't
hand-duplicated per generated scenario.

Chaos kill selection happens HERE, at generation time, as a plain seeded
`random.sample()` over the base topology's `[[workers]]` -- deliberately NOT
a new scenario-engine action type. The existing `worker.leave` action
already does exactly what a chaos-kill needs for one target (see
actions.py's `_worker_leave`: blocking `docker stop` via
`infra.control("pause", ..., docker_only=True)`, bracketed with a real
`container_action_confirmed_at` timestamp) -- picking targets in Python
before any TOML is written keeps `spec.py`'s action-type enum and
`actions.py`'s dispatcher completely untouched.

Everything this generator decides -- which workers get killed, when, with
what rooms/bots/seed -- ends up as plain `[[actions]]` rows in the ONE
output TOML; there is no sidecar file and no separate result-computing
script. The TOML is the single source of truth for what to run; reading
back what happened (quality, failover recovery/downtime, etc.) goes
through the Grafana observation system that `vidctl scenario run` already
feeds (system_log/metrics_sampler + the dashboards under
IaC/ansible/roles/docker_service/files/dashboards/), not a bespoke reader.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path
from typing import Any

import tomllib

from .spec import parse_timestamp

# Services eligible to be chaos-killed. Deliberately excludes "bot" (the
# scenario's own instrumentation -- killing it would sever the test's
# ability to create/join/delete rooms at all) and "node_exporter" (host
# metrics sidecar, not a system-under-test node; spec.py adds these
# implicitly and a hand-written base file shouldn't declare them either).
KILLABLE_SERVICES = ("relay", "cp-daemon", "validator-daemon")

# Per-room join stagger: how many seconds apart each bot after the first
# joins its room, so N simultaneous joins don't land as one instantaneous
# spike that would skew the quality numbers this harness exists to measure.
DEFAULT_JOIN_STAGGER_SECONDS = 3
# How many seconds apart each room's OWN creation is offset from the next
# room's, for the same reason (max-rooms scenarios especially).
DEFAULT_ROOM_STAGGER_SECONDS = 2


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    return _toml_string(str(value))


def _dump_table_body(table: dict[str, Any]) -> list[str]:
    return [f"{key} = {_toml_scalar(value)}" for key, value in table.items() if value is not None]


def _dump_array_of_tables(name: str, rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        lines.append(f"[[{name}]]")
        lines.extend(_dump_table_body(row))
        lines.append("")
    return lines


def render_scenario_toml(
    name: str,
    env: str,
    contract: dict[str, Any],
    registry: dict[str, Any],
    frontends: list[dict[str, Any]],
    workers: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> str:
    lines = [f"name = {_toml_string(name)}", f"env = {_toml_string(env)}", ""]
    if contract:
        lines.append("[contract]")
        lines.extend(_dump_table_body(contract))
        lines.append("")
    if registry:
        lines.append("[registry]")
        lines.extend(_dump_table_body(registry))
        lines.append("")
    lines.extend(_dump_array_of_tables("frontends", frontends))
    lines.extend(_dump_array_of_tables("workers", workers))
    lines.extend(_dump_array_of_tables("actions", actions))
    return "\n".join(lines).rstrip() + "\n"


def _find_bot_host(workers: list[dict[str, Any]]) -> str:
    for worker in workers:
        if worker.get("service") == "bot":
            return str(worker["host"])
    raise ValueError("Base topology has no [[workers]] entry with service = \"bot\" -- can't drive any room actions.")


def _select_kill_targets(
    workers: list[dict[str, Any]], fraction: float, seed: int
) -> list[dict[str, Any]]:
    pool = [w for w in workers if w.get("service") in KILLABLE_SERVICES]
    count = math.ceil(fraction * len(pool))
    return random.Random(seed).sample(pool, count) if count > 0 else []


def build_actions(
    *,
    bot_host: str,
    rooms: int,
    bots_per_room: int,
    hold_seconds: int,
    room_stagger_seconds: int,
    join_stagger_seconds: int,
    kill_targets: list[dict[str, Any]],
    kill_at: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for room_index in range(rooms):
        room_id_ref = f"room{room_index}"
        create_offset = room_index * room_stagger_seconds
        actions.append(
            {
                "id": room_id_ref,
                "type": "bot.create_room",
                "timestamp": f"+{create_offset}s",
                "host": bot_host,
                "media_mode": "both",
            }
        )
        join_ids: list[str] = []
        for bot_index in range(1, bots_per_room):
            join_id = f"{room_id_ref}join{bot_index}"
            join_ids.append(join_id)
            actions.append(
                {
                    "id": join_id,
                    "type": "bot.join_room",
                    "timestamp": f"+{create_offset + bot_index * join_stagger_seconds}s",
                    "host": bot_host,
                    "room_id": f"${room_id_ref}.roomId",
                    "media_mode": "both",
                }
            )

    for target in kill_targets:
        actions.append(
            {
                "type": "worker.leave",
                "timestamp": kill_at,
                "host": target["host"],
                "service": target["service"],
                "provider": target["provider"],
                "worker_index": target.get("worker_index", 1),
            }
        )

    for room_index in range(rooms):
        room_id_ref = f"room{room_index}"
        actions.append(
            {
                "type": "bot.delete_room",
                "timestamp": f"+{hold_seconds}s",
                "host": bot_host,
                "bot_id": f"${room_id_ref}.botId",
            }
        )
        for bot_index in range(1, bots_per_room):
            actions.append(
                {
                    "type": "bot.delete_room",
                    "timestamp": f"+{hold_seconds}s",
                    "host": bot_host,
                    "bot_id": f"${room_id_ref}join{bot_index}.botId",
                }
            )

    # Actions above are built per-room (room0's create+joins, then room1's,
    # ...), but with >1 room and a room_stagger_seconds smaller than a
    # room's own join spread, a later room's EARLIER-timestamped create can
    # land after an earlier room's LATER-timestamped join in this list --
    # e.g. room1 create=+2s appended after room0 join2=+6s. The scenario
    # engine requires non-decreasing timestamps in FILE order (it sleeps
    # forward only -- see spec.py's load_scenario() ordering warning and
    # actions.py's run_actions(), which never sorts), so re-sort by parsed
    # offset here. Stable sort preserves this function's within-timestamp
    # relative ordering (e.g. a room's create still precedes its own joins
    # when they legitimately share a timestamp).
    actions.sort(key=lambda a: parse_timestamp(a["timestamp"]))
    return actions


def generate(
    *,
    base_path: Path,
    out_path: Path,
    name: str | None,
    rooms: int,
    bots_per_room: int,
    kill_fraction: float,
    kill_at: str,
    hold_seconds: int,
    seed: int,
    join_stagger_seconds: int = DEFAULT_JOIN_STAGGER_SECONDS,
    room_stagger_seconds: int = DEFAULT_ROOM_STAGGER_SECONDS,
) -> Path:
    parse_timestamp(kill_at)  # raises ValueError on malformed input, same rules spec.py enforces

    base = tomllib.loads(base_path.read_text(encoding="utf-8"))
    env = str(base.get("env") or "")
    if not env:
        raise ValueError(f"Base scenario {base_path} has no top-level 'env'.")
    workers = list(base.get("workers", []))
    bot_host = _find_bot_host(workers)

    kill_targets = _select_kill_targets(workers, kill_fraction, seed) if kill_fraction > 0 else []
    actions = build_actions(
        bot_host=bot_host,
        rooms=rooms,
        bots_per_room=bots_per_room,
        hold_seconds=hold_seconds,
        room_stagger_seconds=room_stagger_seconds,
        join_stagger_seconds=join_stagger_seconds,
        kill_targets=kill_targets,
        kill_at=kill_at,
    )

    scenario_name = name or f"{base_path.stem}-eval-r{rooms}-b{bots_per_room}-k{kill_fraction:g}"
    toml_text = render_scenario_toml(
        scenario_name, env, dict(base.get("contract", {})), dict(base.get("registry", {})),
        list(base.get("frontends", [])), workers, actions,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(toml_text, encoding="utf-8")

    print(f"Wrote {out_path}")
    if kill_targets:
        print(f"  ({len(kill_targets)} chaos-kill target(s) selected with seed={seed}, baked into its worker.leave actions)")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="Base scenario TOML to clone infra topology from.")
    parser.add_argument("--out", required=True, type=Path, help="Path to write the generated scenario TOML.")
    parser.add_argument("--name", default=None, help="Scenario name override (default: derived from args).")
    parser.add_argument("--rooms", type=int, default=1)
    parser.add_argument("--bots-per-room", type=int, default=3)
    parser.add_argument("--kill-fraction", type=float, default=0.0, help="0.0-1.0, e.g. 0.4 for 40%% random node-down.")
    parser.add_argument("--kill-at", default="+120s", help="Scenario-relative timestamp for the chaos kill, e.g. +120s.")
    parser.add_argument("--hold-seconds", type=int, default=300, help="How long rooms stay open before cleanup.")
    parser.add_argument("--seed", type=int, default=1, help="Chaos-kill selection seed (reproducibility).")
    args = parser.parse_args(argv)

    try:
        generate(
            base_path=args.base,
            out_path=args.out,
            name=args.name,
            rooms=args.rooms,
            bots_per_room=args.bots_per_room,
            kill_fraction=args.kill_fraction,
            kill_at=args.kill_at,
            hold_seconds=args.hold_seconds,
            seed=args.seed,
        )
    except ValueError as exc:
        print(f"gen_eval_scenarios: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
