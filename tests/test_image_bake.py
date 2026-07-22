from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import image_bake, infra
from cli.vidctl import build_parser


class ImagesTomlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.images_toml = Path(self.temp.name) / "images.toml"
        self.patch = patch.object(image_bake, "RUNTIME_IMAGES_TOML", self.images_toml)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(image_bake.read_runtime_images(), {})

    def test_round_trip(self) -> None:
        image_bake.write_runtime_image("digitalocean", "nyc3", "12345", base_image="ubuntu-22.04", docker_version="24.0.5")
        images = image_bake.read_runtime_images()
        key = image_bake.image_key("digitalocean", "nyc3")
        self.assertIn(key, images)
        self.assertEqual(images[key].image_id, "12345")
        self.assertEqual(images[key].docker_version, "24.0.5")

    def test_write_preserves_existing_entries(self) -> None:
        image_bake.write_runtime_image("aws", "us-east-1", "ami-1", base_image="ubuntu-22.04")
        image_bake.write_runtime_image("gcp", "global", "proj/img-1", base_image="ubuntu-22.04")
        images = image_bake.read_runtime_images()
        self.assertEqual(len(images), 2)
        self.assertEqual(images[image_bake.image_key("aws", "us-east-1")].image_id, "ami-1")
        self.assertEqual(images[image_bake.image_key("gcp", "global")].image_id, "proj/img-1")

    def test_lookup_exact_match(self) -> None:
        image_bake.write_runtime_image("digitalocean", "nyc3", "img-1", base_image="ubuntu-22.04")
        self.assertEqual(image_bake.lookup_image("digitalocean", "nyc3"), "img-1")
        self.assertIsNone(image_bake.lookup_image("digitalocean", "sfo3"))

    def test_lookup_gcp_is_always_global(self) -> None:
        image_bake.write_runtime_image("gcp", "global", "proj/img-1", base_image="ubuntu-22.04")
        self.assertEqual(image_bake.lookup_image("gcp", "us-central1-a"), "proj/img-1")
        self.assertEqual(image_bake.lookup_image("gcp", "europe-west1-b"), "proj/img-1")

    def test_lookup_akamai_falls_back_to_any_region(self) -> None:
        image_bake.write_runtime_image("akamai", "us-east", "private/111", base_image="ubuntu-22.04")
        self.assertEqual(image_bake.lookup_image("akamai", "eu-west"), "private/111")

    def test_lookup_akamai_prefers_exact_region(self) -> None:
        image_bake.write_runtime_image("akamai", "us-east", "private/111", base_image="ubuntu-22.04")
        image_bake.write_runtime_image("akamai", "eu-west", "private/222", base_image="ubuntu-22.04")
        self.assertEqual(image_bake.lookup_image("akamai", "eu-west"), "private/222")


class ProviderCliEnvTests(unittest.TestCase):
    def test_aliases_digitalocean_token_for_doctl(self) -> None:
        with patch.object(image_bake, "command_env", return_value={"DIGITALOCEAN_TOKEN": "tok"}):
            env = image_bake.provider_cli_env()
        self.assertEqual(env["DIGITALOCEAN_ACCESS_TOKEN"], "tok")

    def test_aliases_linode_token_for_linode_cli(self) -> None:
        with patch.object(image_bake, "command_env", return_value={"LINODE_TOKEN": "tok"}):
            env = image_bake.provider_cli_env()
        self.assertEqual(env["LINODE_CLI_TOKEN"], "tok")

    def test_does_not_override_explicit_alias_value(self) -> None:
        with patch.object(
            image_bake,
            "command_env",
            return_value={"DIGITALOCEAN_TOKEN": "old", "DIGITALOCEAN_ACCESS_TOKEN": "explicit"},
        ):
            env = image_bake.provider_cli_env()
        self.assertEqual(env["DIGITALOCEAN_ACCESS_TOKEN"], "explicit")


class WaitForSshTests(unittest.TestCase):
    def test_succeeds_immediately(self) -> None:
        with patch.object(image_bake, "run_capture", return_value=(0, "", "")) as run_capture_fn:
            ok = image_bake.wait_for_ssh("203.0.113.10", Path("/tmp/key"), attempts=5, delay_seconds=0)
        self.assertTrue(ok)
        run_capture_fn.assert_called_once()

    def test_retries_then_succeeds(self) -> None:
        with patch.object(image_bake, "run_capture", side_effect=[(1, "", "refused"), (1, "", "refused"), (0, "", "")]):
            ok = image_bake.wait_for_ssh("203.0.113.10", Path("/tmp/key"), attempts=5, delay_seconds=0)
        self.assertTrue(ok)

    def test_gives_up_after_attempts_exhausted(self) -> None:
        with patch.object(image_bake, "run_capture", return_value=(1, "", "refused")) as run_capture_fn:
            ok = image_bake.wait_for_ssh("203.0.113.10", Path("/tmp/key"), attempts=3, delay_seconds=0)
        self.assertFalse(ok)
        self.assertEqual(run_capture_fn.call_count, 3)


class ProviderValidationTests(unittest.TestCase):
    def test_supported_providers(self) -> None:
        for provider in ("aws", "gcp", "azure", "alibaba", "digitalocean", "upcloud", "akamai"):
            self.assertIsNone(image_bake.provider_error(provider))

    def test_tencent_and_cloudflare_rejected(self) -> None:
        self.assertIsNotNone(image_bake.provider_error("tencent"))
        self.assertIsNotNone(image_bake.provider_error("cloudflare"))


class ResolveBakeRegionTests(unittest.TestCase):
    def test_explicit_region_wins(self) -> None:
        self.assertEqual(image_bake.resolve_bake_region("digitalocean", "sfo3"), "sfo3")

    def test_falls_back_to_default(self) -> None:
        self.assertEqual(image_bake.resolve_bake_region("digitalocean", None), "nyc3")

    def test_all_supported_providers_have_a_default(self) -> None:
        for provider in image_bake.SUPPORTED_PROVIDERS:
            self.assertTrue(image_bake.resolve_bake_region(provider, None))


class EnsureImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.images_toml = Path(self.temp.name) / "images.toml"
        self.patch = patch.object(image_bake, "RUNTIME_IMAGES_TOML", self.images_toml)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_noop_for_unsupported_provider(self) -> None:
        with patch.object(image_bake, "bake") as bake_fn:
            ok, error = image_bake.ensure_image("tencent", None)
        self.assertTrue(ok)
        self.assertEqual(error, "")
        bake_fn.assert_not_called()

    def test_noop_when_image_already_exists(self) -> None:
        image_bake.write_runtime_image("digitalocean", "nyc3", "img-1", base_image="ubuntu-22.04")
        with patch.object(image_bake, "bake") as bake_fn:
            ok, error = image_bake.ensure_image("digitalocean", None)
        self.assertTrue(ok)
        self.assertEqual(error, "")
        bake_fn.assert_not_called()

    def test_bakes_when_missing(self) -> None:
        with patch.object(image_bake, "bake", return_value=0) as bake_fn:
            ok, error = image_bake.ensure_image("digitalocean", None)
        self.assertTrue(ok)
        bake_fn.assert_called_once_with("digitalocean", "nyc3", True)

    def test_reports_failure_when_bake_fails(self) -> None:
        with patch.object(image_bake, "bake", return_value=1):
            ok, error = image_bake.ensure_image("digitalocean", None)
        self.assertFalse(ok)
        self.assertIn("digitalocean:nyc3", error)


class ParserTests(unittest.TestCase):
    def test_image_bake_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["utils", "image-bake", "--provider", "aws", "--region", "us-east-1", "--yes"])
        self.assertEqual(args.provider, "aws")
        self.assertEqual(args.region, "us-east-1")
        self.assertTrue(args.yes)

    def test_image_bake_rejects_tencent_at_parse_time(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["utils", "image-bake", "--provider", "tencent", "--region", "x", "--yes"])

    def test_image_list_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["utils", "image", "list"])
        self.assertEqual(args.image_action, "list")


class BakeOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.topology = self.root / "runtime" / "topology.toml"
        self.history = self.root / "runtime" / "history.toml"
        self.images_toml = self.root / "runtime" / "images.toml"

        self.patches = [
            patch.object(infra, "RUNTIME_TOPOLOGY_TOML", self.topology),
            patch.object(infra, "RUNTIME_HISTORY_TOML", self.history),
            patch.object(image_bake, "RUNTIME_IMAGES_TOML", self.images_toml),
            patch.object(infra, "command_env", return_value={"DIGITALOCEAN_TOKEN": "token"}),
            patch.object(infra, "pulumi_up", return_value=0),
            patch.object(infra, "inventory", return_value=0),
            patch.object(infra, "instance_address", return_value="203.0.113.10"),
            patch.object(infra, "persist_vm_resolution", return_value=None),
            patch.object(infra, "GENERATED_INVENTORY", self.root / "runtime" / "hosts.generated.yml"),
            patch.object(image_bake, "wait_for_ssh", return_value=True),
            patch.object(image_bake, "ssh_run", return_value=(0, "Docker version 24.0.5, build abc", "")),
            patch.object(
                image_bake,
                "_stop_and_create_image",
                return_value=(True, "snap-12345", ""),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def read_topology(self) -> dict:
        return infra.read_topology()

    def test_bake_without_yes_is_refused(self) -> None:
        code = image_bake.bake("digitalocean", "nyc3", False)
        self.assertEqual(code, 2)
        self.assertFalse(self.topology.exists())

    def test_bake_unsupported_provider_rejected(self) -> None:
        code = image_bake.bake("tencent", "ap-guangzhou", True)
        self.assertEqual(code, 2)

    def test_bake_missing_credentials_rejected(self) -> None:
        with patch.object(infra, "command_env", return_value={}):
            code = image_bake.bake("digitalocean", "nyc3", True)
        self.assertEqual(code, 1)

    def test_successful_bake_records_image_and_tears_down(self) -> None:
        code = image_bake.bake("digitalocean", "nyc3", True)
        self.assertEqual(code, 0)

        images = image_bake.read_runtime_images()
        key = image_bake.image_key("digitalocean", "nyc3")
        self.assertIn(key, images)
        self.assertEqual(images[key].image_id, "snap-12345")
        self.assertEqual(images[key].docker_version, "24.0.5")

        # Bake VM's topology row must be gone after a successful run.
        topology = self.read_topology()
        bake_rows = [i for i in topology["instances"] if i.get("service") == image_bake.BAKE_SERVICE]
        self.assertEqual(bake_rows, [])

    def test_pulumi_up_failure_removes_topology_row(self) -> None:
        with patch.object(infra, "pulumi_up", return_value=1):
            code = image_bake.bake("digitalocean", "nyc3", True)
        self.assertNotEqual(code, 0)
        topology = self.read_topology()
        bake_rows = [i for i in topology["instances"] if i.get("service") == image_bake.BAKE_SERVICE]
        self.assertEqual(bake_rows, [])

    def test_ssh_never_ready_leaves_vm_for_inspection(self) -> None:
        with (
            patch.object(image_bake, "wait_for_ssh", return_value=False) as wait_for_ssh_fn,
            patch.object(image_bake, "ssh_run") as ssh_run_fn,
        ):
            code = image_bake.bake("digitalocean", "nyc3", True)
        self.assertNotEqual(code, 0)
        wait_for_ssh_fn.assert_called_once()
        ssh_run_fn.assert_not_called()
        topology = self.read_topology()
        bake_rows = [i for i in topology["instances"] if i.get("service") == image_bake.BAKE_SERVICE]
        self.assertEqual(len(bake_rows), 1)
        self.assertEqual(image_bake.read_runtime_images(), {})

    def test_bootstrap_failure_leaves_vm_for_inspection(self) -> None:
        with patch.object(image_bake, "ssh_run", return_value=(1, "", "apt-get failed")):
            code = image_bake.bake("digitalocean", "nyc3", True)
        self.assertNotEqual(code, 0)
        topology = self.read_topology()
        bake_rows = [i for i in topology["instances"] if i.get("service") == image_bake.BAKE_SERVICE]
        self.assertEqual(len(bake_rows), 1)
        self.assertEqual(image_bake.read_runtime_images(), {})

    def test_image_creation_failure_leaves_vm_for_inspection(self) -> None:
        with patch.object(image_bake, "_stop_and_create_image", return_value=(False, "", "snapshot failed")):
            code = image_bake.bake("digitalocean", "nyc3", True)
        self.assertNotEqual(code, 0)
        topology = self.read_topology()
        bake_rows = [i for i in topology["instances"] if i.get("service") == image_bake.BAKE_SERVICE]
        self.assertEqual(len(bake_rows), 1)
        self.assertEqual(image_bake.read_runtime_images(), {})


if __name__ == "__main__":
    unittest.main()
