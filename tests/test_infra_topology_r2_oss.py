from __future__ import annotations

import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from cli import context, infra

from tests.infra_topology_test_base import InfraTopologyTestCase


class R2OssTests(InfraTopologyTestCase):
    def test_command_env_loads_alibaba_admin_file(self) -> None:
            alibaba_env = self.root / "secrets" / "cloud" / "alibaba.env"
            alibaba_env.parent.mkdir(parents=True, exist_ok=True)
            alibaba_env.write_text(
                "ALICLOUD_ACCESS_KEY=admin-key\nALICLOUD_SECRET_KEY=admin-secret\nALICLOUD_REGION=cn-shanghai\n",
                encoding="utf-8",
            )

            with (
                patch.object(context, "ROOT", self.root),
                patch.object(context, "IAC_DIR", self.root / "IaC"),
                patch.object(context, "SECRETS_DIR", self.root / "secrets" / "cloud"),
                patch.object(context, "PULUMI_STATE_DIR", self.root / "secrets" / "pulumi-state"),
                patch.object(context, "PULUMI_PASSPHRASE_FILE", self.root / "secrets" / "pulumi-passphrase"),
                patch.object(context, "ANSIBLE_DIR", self.root / "IaC" / "ansible"),
            ):
                env = context.command_env()

            self.assertEqual(env["ALIBABA_CLOUD_ACCESS_KEY_ID"], "admin-key")
            self.assertEqual(env["ALIBABA_CLOUD_ACCESS_KEY_SECRET"], "admin-secret")
            self.assertEqual(env["ALIBABA_CLOUD_REGION"], "cn-shanghai")

    def test_cloudflare_r2_provider_skips_aws_account_lookup(self) -> None:
            captured: dict[str, dict] = {}

            class FakeProvider:
                def __init__(self, name: str, **kwargs: dict) -> None:
                    captured["provider"] = {"name": name, **kwargs}

            class FakeR2Bucket:
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    self.name = kwargs.get("name", resource_name)
                    captured["bucket"] = {"name": resource_name, **kwargs}

            fake_aws = SimpleNamespace(
                Provider=FakeProvider,
                s3=SimpleNamespace(BucketObjectv2=lambda *args, **kwargs: None),
            )
            fake_cloudflare = SimpleNamespace(R2Bucket=FakeR2Bucket)
            fake_pulumi = ModuleType("pulumi")
            fake_pulumi.Config = lambda _name: SimpleNamespace(get_object=lambda _key: None)
            fake_pulumi.warn = lambda _message: None
            fake_pulumi.export = lambda *_args, **_kwargs: None
            fake_pulumi.FileAsset = lambda path: path
            fake_pulumi.ResourceOptions = lambda **kwargs: kwargs
            fake_pulumi.InvokeOptions = lambda **kwargs: kwargs

            module_path = Path(__file__).resolve().parents[1] / "IaC" / "pulumi" / "__main__.py"
            topology_path = Path(__file__).resolve().parents[1] / "runtime" / "topology.toml"
            fake_topology = (
                'active_env = "devnet"\n'
                'contract_env = "runtime/contract/devnet.env"\n\n'
                '[[objects]]\n'
                'name = "site-1"\n'
                'service = "frontend"\n'
                'provider = "cloudflare"\n'
                'env = "devnet"\n'
                'backend = "object_storage"\n'
                'bucket = "xaisen-devnet-cloudflare-site-1"\n'
                'artifact_dir = "services/frontend/out"\n'
                'desired_state = "running"\n'
            )
            spec = importlib.util.spec_from_file_location("pulumi_main_for_test", module_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)

            with (
                patch.object(Path, "exists", lambda self: str(self) == str(topology_path)),
                patch.object(Path, "read_text", lambda self, encoding="utf-8": fake_topology if str(self) == str(topology_path) else ""),
                patch.dict(
                    sys.modules,
                    {
                        "pulumi": fake_pulumi,
                        "pulumi_aws": fake_aws,
                        "pulumi_cloudflare": fake_cloudflare,
                    },
                ),
                patch.dict(
                    "os.environ",
                    {
                        "CLOUDFLARE_API_TOKEN": "token",
                        "CLOUDFLARE_ACCOUNT_ID": "account",
                        "CLOUDFLARE_R2_ACCESS_KEY_ID": "key",
                        "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "secret",
                    },
                    clear=False,
                ),
            ):
                spec.loader.exec_module(module)

            self.assertIn("provider", captured)
            self.assertTrue(captured["provider"]["skip_requesting_account_id"])
            self.assertTrue(captured["provider"]["skip_credentials_validation"])
            self.assertTrue(captured["provider"]["skip_metadata_api_check"])
            self.assertTrue(captured["provider"]["skip_region_validation"])
            self.assertEqual(captured["provider"]["region"], "auto")

    def test_alibaba_oss_upload_inherits_bucket_acl(self) -> None:
            captured: dict[str, dict] = {}

            class FakeProvider:
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    captured["provider"] = {"resource": self, "name": resource_name, **kwargs}

            class FakeBucket:
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    self.bucket = kwargs.get("bucket", resource_name)
                    captured["bucket"] = {"name": resource_name, **kwargs}

            class FakeBucketObject:
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    captured["object"] = {"name": resource_name, **kwargs}

            class FakeBucketAcl:
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    captured["bucket_acl"] = {"name": resource_name, **kwargs}

            fake_alicloud = SimpleNamespace(
                Provider=FakeProvider,
                oss=SimpleNamespace(
                    Bucket=FakeBucket,
                    BucketAcl=FakeBucketAcl,
                    BucketObject=FakeBucketObject,
                    BucketPublicAccessBlock=FakeBucketAcl,
                ),
            )
            fake_pulumi = ModuleType("pulumi")
            fake_pulumi.Config = lambda _name: SimpleNamespace(get_object=lambda _key: None)
            fake_pulumi.warn = lambda _message: None
            fake_pulumi.export = lambda *_args, **_kwargs: None
            fake_pulumi.FileAsset = lambda path: path
            fake_pulumi.ResourceOptions = lambda **kwargs: kwargs

            module_path = Path(__file__).resolve().parents[1] / "IaC" / "pulumi" / "__main__.py"
            topology_path = Path(__file__).resolve().parents[1] / "runtime" / "topology.toml"
            fake_topology = (
                'active_env = "devnet"\n'
                'contract_env = "runtime/contract/devnet.env"\n\n'
                '[[objects]]\n'
                'name = "site-1"\n'
                'service = "frontend"\n'
                'provider = "alibaba"\n'
                'env = "devnet"\n'
                'backend = "object_storage"\n'
                'bucket = "xaisen-devnet-alibaba-site-1"\n'
                'region = "ap-southeast-1"\n'
                'artifact_dir = "services/frontend/out"\n'
                'desired_state = "running"\n'
            )
            spec = importlib.util.spec_from_file_location("pulumi_main_alibaba_for_test", module_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)

            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".html") as tmp_file:
                tmp_file.write(b"hello")
                tmp_file.flush()

                with (
                    patch.object(Path, "exists", lambda self: str(self) == str(topology_path) or str(self).endswith("services/frontend/out") or str(self).startswith(str(Path("services/frontend/out")))),
                    patch.object(Path, "read_text", lambda self, encoding="utf-8": fake_topology if str(self) == str(topology_path) else ""),
                    patch("app.frontend.artifacts.artifact_files", return_value=[Path(tmp_file.name)]),
                    patch("app.frontend.artifacts.object_key", return_value="index.html"),
                    patch.dict(
                        sys.modules,
                        {
                            "pulumi": fake_pulumi,
                            "pulumi_alicloud": fake_alicloud,
                        },
                    ),
                    patch.dict(
                        "os.environ",
                        {
                            "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                            "ALIBABA_CLOUD_REGION": "cn-hangzhou",
                        },
                        clear=False,
                    ),
                ):
                    spec.loader.exec_module(module)
                    from app.frontend.service import frontend_site_url
                    self.assertEqual(
                        frontend_site_url("alibaba", "xaisen-devnet-alibaba-site-1", {"region": "ap-southeast-1"}),
                        "https://xaisen-devnet-alibaba-site-1.oss-website-ap-southeast-1.aliyuncs.com",
                    )

            self.assertIn("object", captured)
            self.assertEqual(captured["provider"]["region"], "ap-southeast-1")
            self.assertIsInstance(captured["object"]["source"], str)
            self.assertNotIn("FileAsset", captured["object"]["source"])
            self.assertNotIn("acl", captured["bucket"])
            self.assertEqual(captured["bucket"]["tags"], {"xaisen:region": "ap-southeast-1"})
            self.assertEqual(captured["bucket_acl"]["acl"], "public-read")
            self.assertEqual(captured["object"]["acl"], "public-read")
            self.assertTrue(captured["bucket"]["opts"]["delete_before_replace"])
            self.assertEqual(captured["bucket"]["opts"]["replace_on_changes"], ["tags"])
            self.assertIs(captured["bucket"]["opts"]["provider"], captured["provider"]["resource"])
            self.assertIs(captured["bucket_acl"]["opts"]["provider"], captured["provider"]["resource"])
            self.assertIs(captured["object"]["opts"]["provider"], captured["provider"]["resource"])
            self.assertEqual(len(captured["object"]["opts"]["depends_on"]), 1)
            self.assertIsInstance(captured["object"]["opts"]["depends_on"][0], FakeBucketAcl)

    def test_alibaba_vm_maps_stopped_topology_to_ecs_power_state(self) -> None:
            captured: dict[str, dict] = {}

            class FakeResource:
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    self.id = f"{resource_name}-id"
                    self.key_pair_name = kwargs.get("key_pair_name", resource_name)
                    self.public_ip = "192.0.2.10"

            class FakeInstance(FakeResource):
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    captured["worker"] = {"name": resource_name, **kwargs}
                    super().__init__(resource_name, **kwargs)

            class FakeSecurityGroupRule(FakeResource):
                def __init__(self, resource_name: str, **kwargs: dict) -> None:
                    captured.setdefault("security_group_rules", {})[resource_name] = kwargs
                    super().__init__(resource_name, **kwargs)

            fake_alicloud = SimpleNamespace(
                Provider=FakeResource,
                get_zones=lambda **_kwargs: SimpleNamespace(ids=["cn-hangzhou-h"]),
                vpc=SimpleNamespace(Network=FakeResource, Switch=FakeResource),
                ecs=SimpleNamespace(
                    KeyPair=FakeResource,
                    SecurityGroup=FakeResource,
                    SecurityGroupRule=FakeSecurityGroupRule,
                    Instance=FakeInstance,
                    get_images=lambda **_kwargs: SimpleNamespace(images=[SimpleNamespace(id="ubuntu-image")]),
                    get_instance_types=lambda **_kwargs: SimpleNamespace(
                        instance_types=[SimpleNamespace(id="ecs.g6.large", availability_zones=["cn-hangzhou-h"])]
                    ),
                ),
            )
            fake_pulumi = ModuleType("pulumi")
            fake_pulumi.Config = lambda _name: SimpleNamespace(get_object=lambda _key: None)
            fake_pulumi.warn = lambda _message: None
            fake_pulumi.export = lambda *_args, **_kwargs: None
            fake_pulumi.ResourceOptions = lambda **kwargs: kwargs
            fake_pulumi.InvokeOptions = lambda **kwargs: kwargs

            module_path = Path(__file__).resolve().parents[1] / "IaC" / "pulumi" / "app" / "compute" / "alibaba.py"
            spec = importlib.util.spec_from_file_location("app.compute.alibaba", module_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)

            with (
                patch.object(Path, "exists", return_value=False),
                patch.dict(sys.modules, {"pulumi": fake_pulumi, "pulumi_alicloud": fake_alicloud}),
                patch.dict(
                    "os.environ",
                    {
                        "ALIBABA_CLOUD_ACCESS_KEY_ID": "key",
                        "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "secret",
                        "ALIBABA_CLOUD_REGION": "cn-hangzhou",
                    },
                    clear=False,
                ),
            ):
                spec.loader.exec_module(module)
                module.create_vm(
                    {
                        "name": "node-1",
                        "host": "node-1",
                        "service": "routes",
                        "provider": "alibaba",
                        "desired_state": "stopped",
                        "port": 3001,
                    },
                    "ssh-ed25519 test",
                )

            self.assertEqual(captured["worker"]["status"], "Stopped")
            self.assertEqual(captured["worker"]["stopped_mode"], "KeepCharging")
            self.assertEqual(captured["worker"]["availability_zone"], "cn-hangzhou-h")
            self.assertEqual(captured["security_group_rules"]["node-1-vm-sg-http"]["port_range"], "80/80")
            self.assertEqual(captured["security_group_rules"]["node-1-vm-sg-https"]["port_range"], "443/443")
            self.assertNotIn("node-1-vm-sg-port", captured["security_group_rules"])

