from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.scenario.spec import load_scenario
from scenario import generate_test_matrix as gen


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class GeneratorPlacementTests(unittest.TestCase):
    """Unit tests for the shared allocator/placement helpers, independent of
    file I/O -- these are the invariants the whole test matrix depends on."""

    def test_do_cap_enforced(self) -> None:
        allocator = gen.ProviderAllocator()
        workers = gen.distribute_role_mix(allocator, gen.DO_MAX_INSTANCES * len(gen.DO_MIX) + 1)
        do_hosts = {w["host"] for w in workers if w["provider"] == "digitalocean"}
        self.assertLessEqual(len(do_hosts), gen.DO_MAX_INSTANCES)

    def test_azure_spreads_across_regions_at_two_per_region(self) -> None:
        allocator = gen.ProviderAllocator()
        # Force past DO's cap so Azure placement kicks in.
        gen.distribute_role_mix(allocator, gen.DO_MAX_INSTANCES * len(gen.DO_MIX))
        workers = gen.distribute_role_mix(
            allocator, len(gen.AZURE_MIX) * len(gen.AZURE_REGIONS) * gen.AZURE_INSTANCES_PER_REGION
        )
        azure_hosts_by_region: dict[str, set[str]] = {}
        for row in workers:
            if row["provider"] == "azure":
                azure_hosts_by_region.setdefault(row["region"], set()).add(row["host"])
        self.assertEqual(set(azure_hosts_by_region), set(gen.AZURE_REGIONS))
        for hosts in azure_hosts_by_region.values():
            self.assertLessEqual(len(hosts), gen.AZURE_INSTANCES_PER_REGION)

    def test_akamai_relay_never_doubled_on_one_host(self) -> None:
        # A single Akamai host's canonical mix already has relay=1; verify
        # the guard actually raises if a caller ever tries to force two.
        slot = gen.HostSlot("099", "akamai", gen.AKAMAI_REGION, gen.AKAMAI_SIZE)
        from collections import Counter

        with self.assertRaises(ValueError):
            gen._build_host_workers(slot, Counter({"relay": 2}))

    def test_global_host_id_unique_across_providers_in_one_scenario(self) -> None:
        allocator = gen.ProviderAllocator()
        workers = gen.distribute_role_mix(allocator, 300)
        host_provider: dict[str, str] = {}
        for row in workers:
            host, provider = row["host"], row["provider"]
            if host in host_provider:
                self.assertEqual(host_provider[host], provider, f"host {host} reused across providers")
            host_provider[host] = provider


class ChaosVsJoinSemanticsTests(unittest.TestCase):
    """The single most important behavioral distinction in the matrix:
    chaos's worker.join reclaims a paused pool worker (host omitted);
    join-scaleout's worker.join provisions genuinely new capacity (host
    explicit and never declared in [[workers]])."""

    def test_chaos_join_action_omits_host(self) -> None:
        _, workers, actions = gen.generate_chaos_worker_cycle(100, 50)
        join_actions = [a for a in actions if a["type"] == "worker.join"]
        self.assertEqual(len(join_actions), 1)
        self.assertNotIn("host", join_actions[0])

    def test_join_scaleout_action_requires_fresh_host(self) -> None:
        _, workers, actions = gen.generate_worker_join_scaleout(100, 50)
        join_actions = [a for a in actions if a["type"] == "worker.join"]
        self.assertEqual(len(join_actions), 1)
        join_host = join_actions[0].get("host")
        self.assertIsNotNone(join_host)
        declared_hosts = {w["host"] for w in workers}
        self.assertNotIn(join_host, declared_hosts)

    def test_chaos_has_validator_headroom_join_scaleout_does_not(self) -> None:
        _, chaos_workers, _ = gen.generate_chaos_worker_cycle(100, 50)
        _, join_workers, _ = gen.generate_worker_join_scaleout(100, 50)
        chaos_validators = sum(1 for w in chaos_workers if w["service"] == "validator-daemon")
        join_validators = sum(1 for w in join_workers if w["service"] == "validator-daemon")
        # Same base topology (100 workers, 50 rooms) -- chaos adds a
        # dedicated headroom host on top, join-scaleout doesn't.
        self.assertGreater(chaos_validators, join_validators)


class GeneratedFileRoundTripTests(unittest.TestCase):
    """Writes a representative subset (not all 18, to keep this fast) to a
    temp dir and round-trips each through the real loader."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_doc(self, name: str, workers: list, actions: list) -> Path:
        text = gen._render_toml(name, "", workers, actions)
        path = self.out_dir / f"{name}.toml"
        _write(path, text)
        return path

    def test_topology_scale_010w_round_trips(self) -> None:
        name, workers, actions = gen.generate_topology_scale(10)
        path = self._write_doc(name, workers, actions)
        doc = load_scenario(path)
        self.assertEqual(doc["env"], "devnet")
        bot_rows = [w for w in doc["workers"] if w["service"] == "bot"]
        self.assertEqual(len(bot_rows), 1)

    def test_room_scale_300r_60bh_round_trips_and_derives_bot_hosts(self) -> None:
        name, workers, actions = gen.generate_room_botmix_scale(300)
        path = self._write_doc(name, workers, actions)
        doc = load_scenario(path)
        bot_rows = [w for w in doc["workers"] if w["service"] == "bot"]
        self.assertEqual(len(bot_rows), 60)

    def test_chaos_cycle_200w_300r_round_trips(self) -> None:
        name, workers, actions = gen.generate_chaos_worker_cycle(200, 300)
        path = self._write_doc(name, workers, actions)
        doc = load_scenario(path)
        self.assertEqual(len(doc["actions"]), 4)
        types = [a["type"] for a in doc["actions"]]
        self.assertEqual(
            types,
            ["bot.create_room", "worker.leave", "worker.join", "bot.delete_room"],
        )

    def test_worker_join_scaleout_100w_050r_round_trips(self) -> None:
        name, workers, actions = gen.generate_worker_join_scaleout(100, 50)
        path = self._write_doc(name, workers, actions)
        doc = load_scenario(path)
        self.assertEqual(len(doc["actions"]), 1)
        self.assertEqual(doc["actions"][0]["type"], "worker.join")
        self.assertEqual(doc["actions"][0]["provider"], "akamai")


if __name__ == "__main__":
    unittest.main()
