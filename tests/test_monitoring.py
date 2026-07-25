from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import infra, scenario


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class ScenarioPinnedImageTests(unittest.TestCase):
    def test_load_scenario_accepts_prometheus_and_grafana_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            _write(
                path,
                """
name = "monitoring-demo"
env = "devnet"

[[workers]]
host = "node-1"
service = "prometheus"
provider = "digitalocean"

[[workers]]
host = "node-1"
service = "grafana"
provider = "digitalocean"
""",
            )
            data = scenario.load_scenario(path)
            services = {w["service"] for w in data["workers"]}
            self.assertEqual(services, {"prometheus", "grafana"})

    def test_load_scenario_still_rejects_unknown_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            _write(
                path,
                """
name = "bad"
env = "devnet"

[[workers]]
host = "node-1"
service = "not-a-real-service"
provider = "digitalocean"
""",
            )
            with self.assertRaises(ValueError):
                scenario.load_scenario(path)


class MonitoringSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(infra, "SERVICE_SECRETS_DIR", self.root / "secrets" / "services"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_grafana_admin_password_generates_once_and_persists(self) -> None:
        first = infra.grafana_admin_password()
        second = infra.grafana_admin_password()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (infra.SERVICE_SECRETS_DIR / "grafana.env").read_text(encoding="utf-8")
        self.assertIn(f"GF_SECURITY_ADMIN_PASSWORD={first}", contents)

    def test_metrics_auth_token_generates_once_and_persists(self) -> None:
        first = infra.metrics_auth_token()
        second = infra.metrics_auth_token()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (infra.SERVICE_SECRETS_DIR / "monitoring.env").read_text(encoding="utf-8")
        self.assertIn(f"METRICS_AUTH_TOKEN={first}", contents)

    def test_grafana_and_metrics_secrets_are_independent(self) -> None:
        password = infra.grafana_admin_password()
        token = infra.metrics_auth_token()
        self.assertNotEqual(password, token)


if __name__ == "__main__":
    unittest.main()
