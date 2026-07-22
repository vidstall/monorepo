import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.common.environment import alibaba_scan_all_regions, require_env
from app.common.regions import provider_region, provider_zone
from app.frontend.artifacts import artifact_files, content_type, object_key


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


if __name__ == "__main__":
    unittest.main()
