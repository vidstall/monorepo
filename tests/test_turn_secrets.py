from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import infra, registry


class TurnSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(infra, "SERVICE_SECRETS_DIR", self.root / "secrets" / "services")]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_turn_static_secret_generates_once_and_persists(self) -> None:
        first = infra.turn_static_secret()
        second = infra.turn_static_secret()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (infra.SERVICE_SECRETS_DIR / "turn.env").read_text(encoding="utf-8")
        self.assertIn(f"TURN_STATIC_SECRET={first}", contents)

    def test_turn_rpc_token_generates_once_and_persists(self) -> None:
        first = infra.turn_rpc_token()
        second = infra.turn_rpc_token()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (infra.SERVICE_SECRETS_DIR / "turn.env").read_text(encoding="utf-8")
        self.assertIn(f"TURN_RPC_TOKEN={first}", contents)

    def test_static_secret_and_rpc_token_are_independent_keys_in_the_shared_file(self) -> None:
        secret = infra.turn_static_secret()
        token = infra.turn_rpc_token()
        self.assertNotEqual(secret, token)
        contents = (infra.SERVICE_SECRETS_DIR / "turn.env").read_text(encoding="utf-8")
        self.assertIn(f"TURN_STATIC_SECRET={secret}", contents)
        self.assertIn(f"TURN_RPC_TOKEN={token}", contents)
        # Re-reading each key later must not disturb the other.
        self.assertEqual(infra.turn_static_secret(), secret)
        self.assertEqual(infra.turn_rpc_token(), token)


class DockerDeployExtraVarsTurnTests(unittest.TestCase):
    """xaisen_turn_static_secret/xaisen_turn_rpc_token must reach every
    docker_deploy_extra_vars() return path -- run_container.yml's TURN
    combine()s (see run_container.yml) are unconditionally referenced, so a
    missing key here means every ansible apply undefined-variables out."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(infra, "SERVICE_SECRETS_DIR", self.root / "secrets" / "services")]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_turn_vars_present_on_the_no_registry_early_return_path(self) -> None:
        with patch.object(registry, "read_runtime_registry", side_effect=ValueError("no provider logged in")):
            extra_vars = infra.docker_deploy_extra_vars()
        self.assertTrue(extra_vars["xaisen_turn_static_secret"])
        self.assertTrue(extra_vars["xaisen_turn_rpc_token"])

    def test_turn_vars_match_the_persisted_secrets_file(self) -> None:
        with patch.object(registry, "read_runtime_registry", side_effect=ValueError("no provider logged in")):
            extra_vars = infra.docker_deploy_extra_vars()
        self.assertEqual(extra_vars["xaisen_turn_static_secret"], infra.turn_static_secret())
        self.assertEqual(extra_vars["xaisen_turn_rpc_token"], infra.turn_rpc_token())


if __name__ == "__main__":
    unittest.main()
