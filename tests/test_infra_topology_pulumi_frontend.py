from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

from cli import infra
from cli import object as object_cmd
from cli.vidctl import build_parser

from tests.infra_topology_test_base import InfraTopologyTestCase


class PulumiFrontendTests(InfraTopologyTestCase):
    def test_frontend_publish_builds_and_runs_pulumi(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "objects": [],
            }
        )

        with (
            patch.object(
                object_cmd,
                "command_env",
                return_value={
                    "CLOUDFLARE_API_TOKEN": "token",
                    "CLOUDFLARE_ACCOUNT_ID": "account",
                    "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                },
            ),
            patch.object(object_cmd, "build_static_artifacts", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = object_cmd.publish("site-1", "frontend", "cloudflare")

        self.assertEqual(code, 0)
        build.assert_called_once_with("frontend")
        pulumi_up.assert_called_once_with("devnet", parallel=4)
        obj = self.read_topology()["objects"][0]
        self.assertEqual(obj["name"], "site-1")
        self.assertEqual(obj["service"], "frontend")
        self.assertEqual(obj["provider"], "cloudflare")
        self.assertEqual(obj["desired_state"], "running")
        self.assertEqual(obj["last_status"], "running")
        self.assertEqual(obj["bucket"], "xaisen-devnet-cloudflare-site-1")
        self.assertEqual(obj["artifact_dir"], "services/frontend/out")

    def test_frontend_publish_requires_provider_credentials_before_build(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "objects": [],
            }
        )

        with (
            patch.object(object_cmd, "command_env", return_value={}),
            patch.object(object_cmd, "build_static_artifacts", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = object_cmd.publish("site-1", "frontend", "cloudflare")

        self.assertEqual(code, 1)
        build.assert_not_called()
        pulumi_up.assert_not_called()
        self.assertIn("CLOUDFLARE_ACCOUNT_ID", self.read_history()["events"][0]["error"])

    def test_frontend_publish_failure_rolls_back_desired_state(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "objects": [
                    {
                        "name": "site-1",
                        "service": "frontend",
                        "provider": "cloudflare",
                        "backend": "object_storage",
                        "bucket": "xaisen-devnet-cloudflare-site-1",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with (
            patch.object(
                object_cmd,
                "command_env",
                return_value={
                    "CLOUDFLARE_API_TOKEN": "token",
                    "CLOUDFLARE_ACCOUNT_ID": "account",
                    "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                },
            ),
            patch.object(object_cmd, "build_static_artifacts", return_value=0) as build,
            patch.object(infra, "pulumi_up", return_value=1) as pulumi_up,
        ):
            code = object_cmd.publish("site-1", "frontend", "cloudflare")

        self.assertEqual(code, 1)
        build.assert_called_once_with("frontend")
        pulumi_up.assert_called_once_with("devnet", parallel=4)
        obj = self.read_topology()["objects"][0]
        self.assertEqual(obj["desired_state"], "stopped")
        self.assertIn("publish failed with exit code 1", obj["last_error"])

    def test_alibaba_frontend_publish_limits_pulumi_parallelism(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "objects": [],
            }
        )

        with (
            patch.object(
                object_cmd,
                "command_env",
                return_value={
                    "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                    "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                    "ALIBABA_CLOUD_REGION": "cn-hangzhou",
                },
            ),
            patch.object(object_cmd, "build_static_artifacts", return_value=0),
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = object_cmd.publish("site-1", "frontend", "alibaba")

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet", parallel=4)
        self.assertEqual(self.read_topology()["objects"][0]["region"], "cn-hangzhou")

    def test_frontend_delete_removes_object_from_topology(self) -> None:
        infra.write_topology(
            {
                "active_env": "devnet",
                "contract_env": "runtime/contract/devnet.env",
                "providers": {},
                "objects": [
                    {
                        "name": "site-1",
                        "service": "frontend",
                        "provider": "cloudflare",
                        "backend": "object_storage",
                        "bucket": "xaisen-devnet-cloudflare-site-1",
                        "desired_state": "running",
                    }
                ],
            }
        )

        with (
            patch.object(
                object_cmd,
                "command_env",
                return_value={
                    "CLOUDFLARE_API_TOKEN": "token",
                    "CLOUDFLARE_ACCOUNT_ID": "account",
                    "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                },
            ),
            patch.object(infra, "pulumi_up", return_value=0) as pulumi_up,
        ):
            code = object_cmd.delete("site-1", "frontend", "cloudflare", yes=True)

        self.assertEqual(code, 0)
        pulumi_up.assert_called_once_with("devnet")
        topology = self.read_topology()
        self.assertEqual(topology.get("objects", []), [])
        self.assertEqual(self.read_history()["events"][0]["next_status"], "deleted")

    def test_parser_accepts_cloudflare_frontend_publish_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["object", "publish", "--name", "site-1", "--object", "frontend", "--provider", "cloudflare"])

        self.assertEqual(args.command, "object")
        self.assertEqual(args.action, "publish")
        self.assertEqual(args.object, "frontend")
        self.assertEqual(args.provider, "cloudflare")
