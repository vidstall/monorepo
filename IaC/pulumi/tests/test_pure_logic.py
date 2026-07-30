import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.common.environment import alibaba_scan_all_regions, require_env
from app.common.regions import provider_region, provider_zone
from app.frontend.artifacts import artifact_files, content_type, object_key
from app.inventory import vm_host_entry
from app.program import _group_vm_workers

# cli/ is a separate Python project (its own venv), not normally on this
# venv's path -- imported here ONLY to guard against the exact regression
# this file's WorkerKeyTests exists for: this Pulumi program's inline
# f"{provider}-{host}-{service}-{index}" worker_key format silently
# drifting out of sync with cli/infra/topology.py::worker_identifier()
# again (see that function's own docstring + this file's WorkerKeyTests
# docstring for the fleet outage this caused).
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from cli.infra.topology import worker_identifier  # noqa: E402


class EnvironmentTests(unittest.TestCase):
    def test_require_env_rejects_missing_value(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "TOKEN is required"):
                require_env("TOKEN")

    def test_alibaba_scan_all_regions_accepts_truthy_values(self) -> None:
        for value in ("1", "true", "TRUE", "yes"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"ALIBABA_SCAN_ALL_REGIONS": value}, clear=True
            ):
                self.assertTrue(alibaba_scan_all_regions())


class RegionTests(unittest.TestCase):
    def test_instance_region_overrides_environment(self) -> None:
        with patch.dict(os.environ, {"AWS_REGION": "from-env"}, clear=True):
            self.assertEqual(provider_region("aws", {"region": "from-instance"}), "from-instance")

    def test_region_and_zone_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(provider_region("digitalocean"), "nyc3")
            self.assertEqual(provider_region("upcloud"), "fi-hel1")
            self.assertEqual(provider_region("akamai"), "us-east")
            self.assertEqual(provider_zone(), "us-central1-a")


class ArtifactTests(unittest.TestCase):
    def test_discovers_files_and_builds_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "assets" / "app.js"
            nested.parent.mkdir()
            nested.write_text("", encoding="utf-8")
            instance = {"artifact_dir": str(root)}
            self.assertEqual(artifact_files(instance), [nested])
            self.assertEqual(object_key(instance, nested), "assets/app.js")
            self.assertEqual(content_type(nested), "text/javascript")

    def test_missing_artifact_directory_is_empty(self) -> None:
        self.assertEqual(artifact_files({"artifact_dir": "/missing/xaisen-artifacts"}), [])


class WorkerKeyTests(unittest.TestCase):
    """Guards worker_key consistency: node_exporter gets a host-level
    identity (<provider>-<host>, e.g. "digitalocean-001"), and every OTHER
    service gets the full <provider>-<host>-<service>-<index> scheme --
    which MUST match cli/infra/topology.py's worker_identifier() exactly
    (cli/infra/control_fleet.py/control_batch.py/control.py key
    xaisen_operator_wallets by that exact string; a mismatch here means
    deploy_one_service.yml's wallet-write task silently misses and every
    daemon crashes on boot with "Missing keypair env var" -- confirmed by
    a real fleet outage this string format was fixed in response to)."""

    def test_grouped_colocated_host_gives_node_exporter_a_host_level_key(self) -> None:
        workers = [
            {"host": "001", "service": "relay", "provider": "digitalocean", "worker_index": 1, "desired_state": "running", "backend": "vm"},
            {"host": "001", "service": "node_exporter", "provider": "digitalocean", "worker_index": 1, "desired_state": "running", "backend": "vm"},
        ]
        _, merged = _group_vm_workers(workers)
        services = {s["service"]: s for s in merged["001"]["services"]}
        self.assertEqual(services["node_exporter"]["worker_key"], "digitalocean-001")
        # Every other service gets the full 4-part identifier, matching
        # cli/infra/topology.py::worker_identifier() exactly.
        self.assertEqual(services["relay"]["worker_key"], "digitalocean-001-relay-1")

    def test_grouped_colocated_host_disambiguates_replica_index(self) -> None:
        workers = [
            {"host": "001", "service": "relay", "provider": "digitalocean", "worker_index": 1, "desired_state": "running", "backend": "vm"},
            {"host": "001", "service": "relay", "provider": "digitalocean", "worker_index": 2, "desired_state": "running", "backend": "vm"},
        ]
        _, merged = _group_vm_workers(workers)
        keys = sorted(s["worker_key"] for s in merged["001"]["services"])
        self.assertEqual(keys, ["digitalocean-001-relay-1", "digitalocean-001-relay-2"])

    def test_fallback_single_service_gives_node_exporter_a_host_level_key(self) -> None:
        instance = {"host": "004", "service": "node_exporter", "provider": "akamai", "worker_index": 1, "port": 9100}
        resource = {"address": "1.2.3.4", "user": "root"}
        output = vm_host_entry(instance, resource, {})
        result = {}
        output.apply(lambda value: result.update(value))
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
        self.assertEqual(result["xaisen_services"][0]["worker_key"], "akamai-004")

    def test_fallback_single_service_gives_full_identifier(self) -> None:
        instance = {"host": "004", "service": "relay", "provider": "akamai", "worker_index": 2, "port": 4000}
        resource = {"address": "1.2.3.4", "user": "root"}
        output = vm_host_entry(instance, resource, {})
        result = {}
        output.apply(lambda value: result.update(value))
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
        self.assertEqual(result["xaisen_services"][0]["worker_key"], "akamai-004-relay-2")

    def test_matches_cli_infra_worker_identifier_exactly(self) -> None:
        # The actual regression: these two codebases each compute a
        # worker's identity independently and MUST agree, or
        # xaisen_operator_wallets[host][worker_key] silently misses.
        instance = {"host": "007", "service": "cp-daemon", "provider": "upcloud", "worker_index": 3, "port": 0}
        resource = {"address": "1.2.3.4", "user": "root"}
        output = vm_host_entry(instance, resource, {})
        result = {}
        output.apply(lambda value: result.update(value))
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
        self.assertEqual(
            result["xaisen_services"][0]["worker_key"],
            worker_identifier("upcloud", "007", "cp-daemon", 3),
        )


if __name__ == "__main__":
    unittest.main()
