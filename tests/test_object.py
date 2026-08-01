from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import infra, object as object_cmd


class ObjectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.topology = self.root / "runtime" / "topology.toml"
        self.history = self.root / "runtime" / "history.toml"

        self.patches = [
            patch.object(infra, "RUNTIME_TOPOLOGY_TOML", self.topology),
            patch.object(infra, "RUNTIME_HISTORY_TOML", self.history),
            patch.object(
                infra,
                "command_env",
                return_value={
                    "ALIBABA_CLOUD_ACCESS_KEY_ID": "k",
                    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "s",
                    "ALIBABA_CLOUD_REGION": "ap-southeast-1",
                },
            ),
        ]
        for item in self.patches:
            item.start()

        topology = infra.ensure_topology("devnet")
        topology.setdefault("objects", []).append(
            {
                "name": "site-2-bucket",
                "object": "frontend",
                "provider": "alibaba",
                "env": "devnet",
                "backend": "object_storage",
                "desired_state": "running",
            }
        )
        infra.write_topology(topology)

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()


PHANTOM_URN = "urn:pulumi:devnet::xaisen-iac::alicloud:oss/bucketObject:BucketObject::site-2-bucket-assets-index-DUlKSvZW.css"
HEALTHY_URN = "urn:pulumi:devnet::xaisen-iac::alicloud:oss/bucketObject:BucketObject::site-2-bucket-assets-index-DWIyhP15.js"
UNRELATED_URN = "urn:pulumi:devnet::xaisen-iac::alicloud:oss/bucketObject:BucketObject::other-object-index.css"


class FindPhantomObjectUrnsTests(unittest.TestCase):
    def test_matches_name_prefixed_urn_with_recognized_missing_message(self) -> None:
        diagnostics = [
            {
                "urn": PHANTOM_URN,
                "message": 'To get the Object: "assets/index-DUlKSvZW.css" but it is not exist in the specified bucket xaisen-devnet-alibaba-site-2-bucket.',
            },
        ]
        self.assertEqual(
            object_cmd.find_phantom_object_urns(diagnostics, "site-2-bucket"),
            [PHANTOM_URN],
        )

    def test_ignores_unrelated_object_name(self) -> None:
        diagnostics = [
            {
                "urn": UNRELATED_URN,
                "message": "but it is not exist in the specified bucket",
            },
        ]
        self.assertEqual(
            object_cmd.find_phantom_object_urns(diagnostics, "site-2-bucket"), []
        )

    def test_ignores_non_missing_error_for_same_object(self) -> None:
        diagnostics = [
            {"urn": PHANTOM_URN, "message": "AccessDenied: invalid credentials"},
        ]
        self.assertEqual(
            object_cmd.find_phantom_object_urns(diagnostics, "site-2-bucket"), []
        )


class CleanTests(ObjectTestCase):
    def test_clean_detects_and_removes_phantom_bucket_objects(self) -> None:
        diagnostics = [
            {
                "urn": PHANTOM_URN,
                "message": "but it is not exist in the specified bucket",
            },
            {
                "urn": HEALTHY_URN,
                "message": "some unrelated warning, not a missing-object error",
            },
        ]
        with (
            patch.object(infra, "pulumi_refresh_diagnostics", return_value=diagnostics),
            patch.object(infra, "pulumi_state_delete", return_value=0) as state_delete,
            patch.object(object_cmd, "refresh", return_value=0) as refresh,
        ):
            code = object_cmd.clean("site-2-bucket", "frontend", "alibaba", False)

        self.assertEqual(code, 0)
        state_delete.assert_called_once_with("devnet", PHANTOM_URN)
        refresh.assert_called_once_with("site-2-bucket", "frontend", "alibaba")

    def test_clean_dry_run_reports_without_deleting(self) -> None:
        diagnostics = [
            {
                "urn": PHANTOM_URN,
                "message": "but it is not exist in the specified bucket",
            }
        ]
        with (
            patch.object(infra, "pulumi_refresh_diagnostics", return_value=diagnostics),
            patch.object(infra, "pulumi_state_delete") as state_delete,
            patch.object(object_cmd, "refresh") as refresh,
        ):
            code = object_cmd.clean("site-2-bucket", "frontend", "alibaba", True)

        self.assertEqual(code, 0)
        state_delete.assert_not_called()
        refresh.assert_not_called()

    def test_clean_no_phantoms_still_runs_normal_refresh(self) -> None:
        with (
            patch.object(infra, "pulumi_refresh_diagnostics", return_value=[]),
            patch.object(infra, "pulumi_state_delete") as state_delete,
            patch.object(object_cmd, "refresh", return_value=0) as refresh,
        ):
            code = object_cmd.clean("site-2-bucket", "frontend", "alibaba", False)

        self.assertEqual(code, 0)
        state_delete.assert_not_called()
        refresh.assert_called_once_with("site-2-bucket", "frontend", "alibaba")

    def test_clean_aborts_if_a_state_delete_fails(self) -> None:
        diagnostics = [
            {
                "urn": PHANTOM_URN,
                "message": "but it is not exist in the specified bucket",
            }
        ]
        with (
            patch.object(infra, "pulumi_refresh_diagnostics", return_value=diagnostics),
            patch.object(infra, "pulumi_state_delete", return_value=1) as state_delete,
            patch.object(object_cmd, "refresh") as refresh,
        ):
            code = object_cmd.clean("site-2-bucket", "frontend", "alibaba", False)

        self.assertEqual(code, 1)
        state_delete.assert_called_once_with("devnet", PHANTOM_URN)
        refresh.assert_not_called()

    def test_clean_unknown_object_in_topology_fails_cleanly(self) -> None:
        with patch.object(infra, "pulumi_refresh_diagnostics") as refresh_diagnostics:
            code = object_cmd.clean("does-not-exist", "frontend", "alibaba", False)

        self.assertEqual(code, 2)
        refresh_diagnostics.assert_not_called()


if __name__ == "__main__":
    unittest.main()
