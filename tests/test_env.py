from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli.env as env_mod


class EnvTests(unittest.TestCase):
    def test_load_env_file_supports_quotes_exports_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "runtime.env"
            env_file.write_text(
                "\n".join(
                    [
                        "# ignored",
                        "export A=one",
                        "B='two words'",
                        'C="three words"',
                        "ignored",
                    ]
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                env_mod.load_env_file(env_file),
                {"A": "one", "B": "two words", "C": "three words"},
            )

    def test_build_env_loads_runtime_and_contract_network_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "secrets" / "cloud").mkdir(parents=True)
            (root / "secrets" / "contract").mkdir(parents=True)
            (root / "secrets" / "cloud" / "alibaba-cloud.env").write_text("CLOUD=ok\n", encoding="utf-8")
            (root / "secrets" / "runtime.env").write_text("CONTRACT_NETWORK=testnet\nRUNTIME=ok\n", encoding="utf-8")
            (root / "secrets" / "contract.env").write_text("CONTRACT_PACKAGE_ID=legacy\n", encoding="utf-8")
            (root / "secrets" / "contract" / "testnet.env").write_text(
                "CONTRACT_PACKAGE_ID=network\nCONTRACT_REGISTRY_OBJECT_ID=registry\n",
                encoding="utf-8",
            )

            with patch.object(env_mod, "REPO_ROOT", root), patch.object(
                env_mod, "RUNTIME_ENV_FILE", root / "secrets" / "runtime.env"
            ), patch.object(env_mod, "CONTRACT_ENV_FILE", root / "secrets" / "contract.env"), patch.object(
                env_mod, "CONTRACT_ENV_DIR", root / "secrets" / "contract"
            ), patch.dict(os.environ, {}, clear=True):
                env = env_mod.build_env("alibaba-cloud")

            self.assertEqual(env["CLOUD"], "ok")
            self.assertEqual(env["RUNTIME"], "ok")
            self.assertEqual(env["CONTRACT_NETWORK"], "testnet")
            self.assertEqual(env["SUI_NETWORK"], "testnet")
            self.assertEqual(env["CONTRACT_PACKAGE_ID"], "network")
            self.assertEqual(env["CONTRACT_REGISTRY_OBJECT_ID"], "registry")


if __name__ == "__main__":
    unittest.main()
