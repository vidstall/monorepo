#!/usr/bin/env python3
"""Generates the DVConf thesis test-matrix scenario TOML files.

Standalone script (not wired into `vidctl`) -- see
docs/superpowers/specs (plan `refactored-meandering-summit.md`) for the
full design rationale. Produces 18 files under `scenario/test/` from 3
shared placement helpers instead of 18 hand-written TOMLs, so every file
stays internally consistent with the account-side provider caps below
(none of which cli/scenario/spec.py or the Pulumi provider modules
enforce in code -- this generator is the only thing policing them):

- DigitalOcean: hard cap of 3 `s-4vcpu-8gb` instances.
- Azure: hard cap of 4 vCPU per region -> 2 `Standard_D2als_v7` (2vCPU)
  instances per region, spread across as many regions as possible.
- Akamai: no stated cap, `g6-standard-4` -- the "fill to target" provider.
- Akamai's firewall module only opens a fixed RTC/pipe port range for
  worker_index=1 (unlike DO/Azure, which offset per replica) -- never
  colocate a 2nd `relay` replica on one Akamai host.
- worker.leave/worker.join (pause/restart) currently only work for
  `--provider alibaba/akamai` -- all [[actions]] worker.leave/worker.join
  entries below target Akamai.

Usage:
    python scenario/generate_test_matrix.py [--out-dir DIR] [--tier TIER] [--check]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.infra import toml_value  # noqa: E402
from cli.scenario.spec import load_scenario  # noqa: E402

OUT_DIR = ROOT / "scenario" / "test"
ENV = "devnet"

# ---------------------------------------------------------------------------
# Provider allocation
# ---------------------------------------------------------------------------

DO_MAX_INSTANCES = 3
DO_SIZE = "s-4vcpu-8gb"
DO_REGION = "nyc3"

AZURE_INSTANCES_PER_REGION = 2  # 4 vCPU/region cap / 2 vCPU per Standard_D2als_v7
AZURE_SIZE = "Standard_D2als_v7"
AZURE_REGIONS = ["eastus", "westus2", "centralus", "westeurope"]

AKAMAI_SIZE = "g6-standard-4"
AKAMAI_REGION = "us-east"

# Canonical per-host role density, generalizing the pattern already used in
# scenario/example/{digitalocean,akamai,azure}.toml. Akamai's relay count
# stays at 1 (firewall gotcha above); cp-daemon/validator-daemon carry no
# RTC ports so they're safe to double up for extra density.
DO_MIX = ["signaling", "relay", "cp-daemon", "validator-daemon"] * 2  # 8/host
AZURE_MIX = ["signaling", "relay", "cp-daemon", "validator-daemon"]  # 4/host (half vCPU)
AKAMAI_MIX = ["signaling", "relay", "cp-daemon", "cp-daemon", "validator-daemon"]  # 5/host


@dataclass
class HostSlot:
    host_id: str
    provider: str
    region: str
    size: str


class ProviderAllocator:
    """Deterministically allocates hosts DigitalOcean -> Azure -> Akamai,
    respecting each provider's account-side cap. DO fills first (small hard
    cap, cheap/fast), Azure spreads across as many regions as possible,
    Akamai absorbs everything else (no stated cap). A single instance is
    shared across every placement call for one generated file, so the
    global host-id counter guarantees uniqueness across providers within
    that file (loader-enforced uniqueness is only per (host, service,
    provider, worker_index) -- global host-id uniqueness across providers
    is a convention this allocator exists to uphold)."""

    def __init__(self) -> None:
        self._next_host_id = 1
        self._do_used = 0
        self._azure_region_idx = 0
        self._azure_used_in_region = 0

    def _new_host_id(self) -> str:
        host_id = f"{self._next_host_id:03d}"
        self._next_host_id += 1
        return host_id

    def allocate_host(self) -> HostSlot:
        if self._do_used < DO_MAX_INSTANCES:
            self._do_used += 1
            return HostSlot(self._new_host_id(), "digitalocean", DO_REGION, DO_SIZE)
        if self._azure_region_idx < len(AZURE_REGIONS):
            region = AZURE_REGIONS[self._azure_region_idx]
            self._azure_used_in_region += 1
            if self._azure_used_in_region >= AZURE_INSTANCES_PER_REGION:
                self._azure_region_idx += 1
                self._azure_used_in_region = 0
            return HostSlot(self._new_host_id(), "azure", region, AZURE_SIZE)
        return HostSlot(self._new_host_id(), "akamai", AKAMAI_REGION, AKAMAI_SIZE)

    def new_akamai_host(self) -> HostSlot:
        """Forces a fresh host onto Akamai, bypassing DO/Azure priority --
        used for validator-headroom and worker-join scale-out hosts, both
        of which need worker.leave/worker.join support (alibaba/akamai
        only), regardless of what the capped priority order would
        otherwise hand out next."""
        return HostSlot(self._new_host_id(), "akamai", AKAMAI_REGION, AKAMAI_SIZE)


# ---------------------------------------------------------------------------
# Worker-row construction
# ---------------------------------------------------------------------------


def _build_host_workers(slot: HostSlot, service_counts: Counter) -> list[dict[str, Any]]:
    if slot.provider == "akamai" and service_counts.get("relay", 0) > 1:
        raise ValueError(
            f"host {slot.host_id}: Akamai's firewall module only opens a fixed "
            "RTC/pipe port range for worker_index=1 -- a 2nd relay replica on "
            "one Akamai host would be silently firewalled off. Refusing to "
            "generate this scenario."
        )
    rows: list[dict[str, Any]] = []
    for service, count in service_counts.items():
        for worker_index in range(1, count + 1):
            rows.append(
                {
                    "host": slot.host_id,
                    "service": service,
                    "provider": slot.provider,
                    "worker_index": worker_index,
                    "size": slot.size,
                    "region": slot.region,
                }
            )
    return rows


def distribute_role_mix(allocator: ProviderAllocator, total_workers: int) -> list[dict[str, Any]]:
    """Places `total_workers` signaling/relay/cp-daemon/validator-daemon
    workers (excluding bot hosts, placed separately) across hosts allocated
    DO -> Azure -> Akamai. Each host fills to its provider's canonical mix
    density; the last, possibly partial, host takes only as many of its
    mix's roles as needed to reach the exact total -- a deliberate
    simplification (front-of-list bias toward signaling/relay on a partial
    host) since exact per-role balance on one leftover host doesn't matter
    for what this axis measures (topology/registry/quorum-bootstrap
    scaling, not per-role capacity)."""
    mixes = {"digitalocean": DO_MIX, "azure": AZURE_MIX, "akamai": AKAMAI_MIX}
    workers: list[dict[str, Any]] = []
    remaining = total_workers
    while remaining > 0:
        slot = allocator.allocate_host()
        mix = mixes[slot.provider]
        take = mix[: min(len(mix), remaining)]
        rows = _build_host_workers(slot, Counter(take))
        workers.extend(rows)
        remaining -= len(rows)
    return workers


def place_bot_hosts(allocator: ProviderAllocator, count: int) -> list[dict[str, Any]]:
    """One dedicated host per bot instance -- never colocated with other
    roles, per the scenario/example/*.toml convention (the bot's HTTP
    control API is reached directly at a single host)."""
    rows: list[dict[str, Any]] = []
    for _ in range(count):
        slot = allocator.allocate_host()
        rows.extend(_build_host_workers(slot, Counter({"bot": 1})))
    return rows


def add_validator_headroom(allocator: ProviderAllocator, leave_count: int, margin: int = 3) -> list[dict[str, Any]]:
    """Extra validator-daemon replicas on a dedicated fresh Akamai host, so
    live validators stay comfortably above the 2/3-of-registered quorum
    threshold even after the chaos timeline's worker.leave actions (quorum
    counts ALL registered-active validators, live or not -- see
    scenario/example/akamai.toml's comment on this exact concern)."""
    slot = allocator.new_akamai_host()
    return _build_host_workers(slot, Counter({"validator-daemon": leave_count + margin}))


def _first_worker(workers: list[dict[str, Any]], provider: str, service: str) -> dict[str, Any] | None:
    for row in workers:
        if row["provider"] == provider and row["service"] == service:
            return row
    return None


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def build_chaos_actions(workers: list[dict[str, Any]], bot_host: str) -> list[dict[str, Any]]:
    target = _first_worker(workers, "akamai", "relay") or _first_worker(workers, "akamai", "cp-daemon")
    if target is None:
        raise ValueError("chaos scenario needs at least one Akamai relay/cp-daemon worker to leave/rejoin")
    return [
        {"type": "bot.create_room", "id": "room1", "timestamp": "+10s", "host": bot_host, "media_mode": "both"},
        {
            "type": "worker.leave",
            "timestamp": "+30s",
            "host": target["host"],
            "service": target["service"],
            "provider": "akamai",
            "worker_index": target["worker_index"],
        },
        # `host` deliberately omitted -- prefer pool-reuse of the worker
        # paused above (recovery), not fresh provisioning.
        {"type": "worker.join", "timestamp": "+2m", "service": target["service"], "provider": "akamai"},
        {"type": "bot.delete_room", "timestamp": "+5m", "host": bot_host, "bot_id": "$room1.botId"},
    ]


def build_join_scaleout_actions(allocator: ProviderAllocator) -> list[dict[str, Any]]:
    slot = allocator.new_akamai_host()
    return [
        {
            # `host` explicitly set to a fresh, never-declared-in-[[workers]]
            # id, unlike the chaos scenario's worker.join -- there is
            # nothing paused to reuse here, so this forces genuine new
            # provisioning: testing a validator-daemon joining the
            # already-running network/contract, not a recovery.
            "type": "worker.join",
            "timestamp": "+30s",
            "service": "validator-daemon",
            "provider": "akamai",
            "host": slot.host_id,
            "size": slot.size,
            "region": slot.region,
        }
    ]


# ---------------------------------------------------------------------------
# Scenario generators (one per tier)
# ---------------------------------------------------------------------------

ScenarioDoc = tuple[str, list[dict[str, Any]], list[dict[str, Any]]]


def generate_topology_scale(total_workers: int, name_override: str | None = None) -> ScenarioDoc:
    """Tier 1 (and tier 5, smoke, via name_override): minimal load (1 bot
    host, nominally 1 room) -- isolates topology/registry/quorum-bootstrap
    scaling from media load."""
    allocator = ProviderAllocator()
    workers = distribute_role_mix(allocator, total_workers)
    workers += place_bot_hosts(allocator, 1)
    name = name_override or f"topology-scale-{total_workers:03d}w"
    return name, workers, []


def generate_room_botmix_scale(room_target: int, fixed_topology_workers: int = 200) -> ScenarioDoc:
    """Tier 2: room/bot-host scale. bot_hosts = ceil(room_target/5)
    (empirically ~5 concurrent rooms/bot-host, not a coded limit).
    Intentionally deviates from the single-bot-host convention used
    elsewhere -- this axis specifically measures bot-host/room scaling."""
    allocator = ProviderAllocator()
    workers = distribute_role_mix(allocator, fixed_topology_workers)
    bot_hosts = ceil(room_target / 5)
    workers += place_bot_hosts(allocator, bot_hosts)
    name = f"room-scale-{room_target:03d}r-{bot_hosts:02d}bh"
    return name, workers, []


def generate_chaos_worker_cycle(topology_workers: int, room_target: int) -> ScenarioDoc:
    """Tier 3: fault tolerance. Base placement + derived bot hosts +
    validator headroom, then a bot.create_room -> worker.leave ->
    worker.join -> bot.delete_room timeline against an Akamai worker."""
    allocator = ProviderAllocator()
    workers = distribute_role_mix(allocator, topology_workers)
    bot_hosts = ceil(room_target / 5)
    workers += place_bot_hosts(allocator, bot_hosts)
    workers += add_validator_headroom(allocator, leave_count=1, margin=3)
    bot_row = next(row for row in workers if row["service"] == "bot")
    actions = build_chaos_actions(workers, bot_row["host"])
    name = f"chaos-cycle-{topology_workers:03d}w-{room_target:03d}r"
    return name, workers, actions


def generate_worker_join_scaleout(topology_workers: int, room_target: int) -> ScenarioDoc:
    """Tier 4: worker/validator scale-out. Same base placement as tier 3,
    but no validator headroom (nothing is being removed) and no prior
    worker.leave -- a single worker.join adds genuinely new capacity."""
    allocator = ProviderAllocator()
    workers = distribute_role_mix(allocator, topology_workers)
    bot_hosts = ceil(room_target / 5)
    workers += place_bot_hosts(allocator, bot_hosts)
    actions = build_join_scaleout_actions(allocator)
    name = f"worker-join-scaleout-{topology_workers:03d}w-{room_target:03d}r"
    return name, workers, actions


# ---------------------------------------------------------------------------
# Self-checks, rendering, and orchestration
# ---------------------------------------------------------------------------


def _self_check(name: str, workers: list[dict[str, Any]]) -> None:
    do_hosts: set[str] = set()
    azure_hosts_by_region: dict[str, set[str]] = {}
    akamai_relay_replicas: Counter = Counter()
    host_provider: dict[str, str] = {}
    for row in workers:
        host, provider = row["host"], row["provider"]
        prior = host_provider.get(host)
        if prior is not None and prior != provider:
            raise AssertionError(f"{name}: host id {host!r} reused across providers {prior!r}/{provider!r}")
        host_provider[host] = provider
        if provider == "digitalocean":
            do_hosts.add(host)
        elif provider == "azure":
            azure_hosts_by_region.setdefault(row["region"], set()).add(host)
        elif provider == "akamai" and row["service"] == "relay":
            akamai_relay_replicas[host] += 1
    if len(do_hosts) > DO_MAX_INSTANCES:
        raise AssertionError(f"{name}: DigitalOcean host count {len(do_hosts)} exceeds cap {DO_MAX_INSTANCES}")
    for region, hosts in azure_hosts_by_region.items():
        if len(hosts) > AZURE_INSTANCES_PER_REGION:
            raise AssertionError(f"{name}: Azure region {region!r} host count {len(hosts)} exceeds cap {AZURE_INSTANCES_PER_REGION}")
    for host, count in akamai_relay_replicas.items():
        if count > 1:
            raise AssertionError(f"{name}: Akamai host {host!r} has {count} relay replicas")


def _print_summary(name: str, workers: list[dict[str, Any]]) -> None:
    hosts_by_provider: dict[str, set[str]] = {}
    regions_by_provider: dict[str, set[str]] = {}
    for row in workers:
        hosts_by_provider.setdefault(row["provider"], set()).add(row["host"])
        regions_by_provider.setdefault(row["provider"], set()).add(row["region"])
    parts = []
    for provider in ("digitalocean", "azure", "akamai"):
        hosts = hosts_by_provider.get(provider, set())
        regions = regions_by_provider.get(provider, set())
        parts.append(f"{provider}={len(hosts)}({len(regions)}rgn)")
    print(f"  {name}: {len(workers)} workers | " + ", ".join(parts))


def _render_toml(name: str, header: str, workers: list[dict[str, Any]], actions: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    if header:
        lines.append(header.rstrip())
        lines.append("")
    lines.append(f"name = {toml_value(name)}")
    lines.append(f"env = {toml_value(ENV)}")
    lines.append("")
    lines.append("[registry]")
    lines.append('provider = "digitalocean"')
    lines.append(f"tag = {toml_value(name)}")
    lines.append("")
    for row in workers:
        lines.append("[[workers]]")
        for key in ("host", "service", "provider", "worker_index", "size", "region"):
            value = row.get(key)
            if value is None:
                continue
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    for row in actions:
        lines.append("[[actions]]")
        for key, value in row.items():
            if value is None:
                continue
            lines.append(f"{key} = {toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _write(out_dir: Path, name: str, header: str, workers: list[dict[str, Any]], actions: list[dict[str, Any]]) -> Path:
    _self_check(name, workers)
    text = _render_toml(name, header, workers, actions)
    path = out_dir / f"{name}.toml"
    path.write_text(text, encoding="utf-8")
    _print_summary(name, workers)
    return path


def build_smoke(out_dir: Path) -> list[Path]:
    name, workers, actions = generate_topology_scale(10, name_override="smoke-baseline")
    header = (
        "# Smoke/e2e baseline -- fastest, cheapest scenario to re-run after any\n"
        "# code change, before spending time/money on the larger tiers below."
    )
    return [_write(out_dir, name, header, workers, actions)]


def build_topology(out_dir: Path) -> list[Path]:
    paths = []
    for total in (10, 20, 50, 100, 200):
        name, workers, actions = generate_topology_scale(total)
        header = (
            f"# Topology/infra scale axis: {total} total signaling/relay/cp-daemon/\n"
            "# validator-daemon workers, minimal load (1 bot host, nominally 1 room).\n"
            "# Isolates registry/quorum-bootstrap/deploy scaling from media load."
        )
        paths.append(_write(out_dir, name, header, workers, actions))
    return paths


def build_rooms(out_dir: Path) -> list[Path]:
    paths = []
    for rooms in (1, 5, 10, 30, 50, 100, 200, 300):
        name, workers, actions = generate_room_botmix_scale(rooms)
        bot_hosts = ceil(rooms / 5)
        header = (
            f"# Room/bot-host scale axis: {rooms} target concurrent rooms ->\n"
            f"# bot_hosts = ceil({rooms}/5) = {bot_hosts} dedicated bot hosts (empirically\n"
            "# ~5 concurrent rooms/bot-host, not a coded limit). Topology fixed at 200\n"
            "# workers so infra isn't the bottleneck being measured.\n"
            "#\n"
            "# NOTE: intentionally deviates from the single-bot-host convention used in\n"
            "# scenario/example/*.toml -- this axis specifically measures bot-host/room\n"
            "# scaling, so multiple dedicated bot hosts are provisioned on purpose."
        )
        paths.append(_write(out_dir, name, header, workers, actions))
    return paths


def build_chaos(out_dir: Path) -> list[Path]:
    paths = []
    for topo, rooms in ((100, 50), (200, 300)):
        name, workers, actions = generate_chaos_worker_cycle(topo, rooms)
        header = (
            "# Fault tolerance: a bot creates a room, an Akamai relay/cp-daemon worker\n"
            "# leaves (paused) at +30s, rejoins via pool-reuse at +2m, room is torn down\n"
            "# at +5m. Extra validator-daemon headroom is added so live validators stay\n"
            "# above 2/3-of-registered quorum even after the leave.\n"
            "# worker.leave/worker.join currently only work for --provider alibaba/akamai,\n"
            "# hence the Akamai target."
        )
        paths.append(_write(out_dir, name, header, workers, actions))
    return paths


def build_join(out_dir: Path) -> list[Path]:
    paths = []
    for topo, rooms in ((100, 50), (200, 300)):
        name, workers, actions = generate_worker_join_scaleout(topo, rooms)
        header = (
            "# Worker/validator scale-out: a brand-new validator-daemon worker joins\n"
            "# the already-running network at +30s. Unlike the chaos-cycle scenario's\n"
            "# worker.join (host omitted -> reclaims a paused pool worker), this one's\n"
            "# `host` is explicitly a fresh id never declared in [[workers]], forcing\n"
            "# genuine new provisioning -- there is nothing paused to reuse here."
        )
        paths.append(_write(out_dir, name, header, workers, actions))
    return paths


TIER_BUILDERS = {
    "smoke": build_smoke,
    "topology": build_topology,
    "rooms": build_rooms,
    "chaos": build_chaos,
    "join": build_join,
}


def _check_generated(paths: list[Path]) -> None:
    ok = True
    for path in sorted(paths):
        try:
            doc = load_scenario(path)
        except ValueError as exc:
            ok = False
            print(f"FAIL {path.name}: {exc}", file=sys.stderr)
            continue
        print(f"OK   {path.name}: {len(doc['workers'])} workers, {len(doc['actions'])} actions")
    if not ok:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--tier", choices=[*TIER_BUILDERS.keys(), "all"], default="all")
    parser.add_argument("--check", action="store_true", help="round-trip every generated file through cli.scenario.spec.load_scenario")
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    tiers = TIER_BUILDERS.keys() if args.tier == "all" else [args.tier]

    paths: list[Path] = []
    for tier in tiers:
        print(f"[{tier}]")
        paths.extend(TIER_BUILDERS[tier](args.out_dir))

    print(f"\nWrote {len(paths)} scenario file(s) to {args.out_dir}")

    if args.check:
        print("\nValidating via cli.scenario.spec.load_scenario ...")
        _check_generated(paths)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
