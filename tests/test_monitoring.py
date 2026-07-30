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
    def test_load_scenario_accepts_prometheus_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            _write(
                path,
                """
name = "monitoring-demo"
env = "devnet"

[[workers]]
host = "001"
service = "prometheus"
provider = "digitalocean"
""",
            )
            data = scenario.load_scenario(path)
            services = {w["service"] for w in data["workers"]}
            # node_exporter is auto-injected once per host regardless of
            # which service(s) are declared there (see load_scenario()).
            self.assertEqual(services, {"prometheus", "node_exporter"})

    def test_load_scenario_accepts_grafana_worker(self) -> None:
        # Grafana is a pinned upstream image (cli/context.py PINNED_IMAGES),
        # same as prometheus/tempo -- syntactically valid here, but rejected
        # at runtime by infra.control() (see
        # test_infra_topology.py::test_grafana_start_is_rejected_in_favor_of_vidctl_observer),
        # since it's only ever deployed via `vidctl observer`, never a
        # disposable scenario worker.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            _write(
                path,
                """
name = "monitoring-demo"
env = "devnet"

[[workers]]
host = "001"
service = "grafana"
provider = "digitalocean"
""",
            )
            data = scenario.load_scenario(path)
            services = {w["service"] for w in data["workers"]}
            # node_exporter is auto-injected once per host regardless of
            # which service(s) are declared there (see load_scenario()).
            self.assertEqual(services, {"grafana", "node_exporter"})

    def test_load_scenario_accepts_loki_worker(self) -> None:
        # Loki is a pinned upstream image (cli/context.py PINNED_IMAGES),
        # same as prometheus/tempo/grafana -- syntactically valid here, but
        # rejected at runtime by infra.control() (see
        # test_infra_topology.py::test_loki_start_is_rejected_in_favor_of_vidctl_observer),
        # since it's only ever deployed via `vidctl observer`, never a
        # disposable scenario worker.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            _write(
                path,
                """
name = "monitoring-demo"
env = "devnet"

[[workers]]
host = "001"
service = "loki"
provider = "digitalocean"
""",
            )
            data = scenario.load_scenario(path)
            services = {w["service"] for w in data["workers"]}
            # node_exporter is auto-injected once per host regardless of
            # which service(s) are declared there (see load_scenario()).
            self.assertEqual(services, {"loki", "node_exporter"})

    def test_load_scenario_still_rejects_unknown_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            _write(
                path,
                """
name = "bad"
env = "devnet"

[[workers]]
host = "001"
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

    def test_metrics_auth_token_generates_once_and_persists(self) -> None:
        first = infra.metrics_auth_token()
        second = infra.metrics_auth_token()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (infra.SERVICE_SECRETS_DIR / "monitoring.env").read_text(encoding="utf-8")
        self.assertIn(f"METRICS_AUTH_TOKEN={first}", contents)

    def test_otel_exporter_vars_empty_when_unseeded(self) -> None:
        self.assertEqual(infra.otel_exporter_vars(), {})

    def test_otel_exporter_vars_reads_seeded_file(self) -> None:
        path = infra.SERVICE_SECRETS_DIR / "otel.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "OTEL_EXPORTER_OTLP_ENDPOINT=https://tempo.1-2-3-4.sslip.io/v1/traces\n"
            "OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20tok\n",
            encoding="utf-8",
        )
        self.assertEqual(
            infra.otel_exporter_vars(),
            {
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://tempo.1-2-3-4.sslip.io/v1/traces",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20tok",
            },
        )

    def test_otel_exporter_vars_ignores_headers_without_endpoint(self) -> None:
        path = infra.SERVICE_SECRETS_DIR / "otel.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20tok\n", encoding="utf-8")
        self.assertEqual(infra.otel_exporter_vars(), {})

    def test_loki_shipping_vars_empty_when_unseeded(self) -> None:
        self.assertEqual(infra.loki_shipping_vars(), {})

    def test_loki_shipping_vars_reads_seeded_file(self) -> None:
        path = infra.SERVICE_SECRETS_DIR / "loki.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "LOKI_PUSH_URL=https://loki.1-2-3-4.sslip.io/loki/api/v1/push\n"
            "LOKI_AUTH_TOKEN=tok123\n",
            encoding="utf-8",
        )
        self.assertEqual(
            infra.loki_shipping_vars(),
            {
                "LOKI_PUSH_URL": "https://loki.1-2-3-4.sslip.io/loki/api/v1/push",
                "LOKI_AUTH_TOKEN": "tok123",
            },
        )

    def test_loki_shipping_vars_ignores_token_without_url(self) -> None:
        path = infra.SERVICE_SECRETS_DIR / "loki.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("LOKI_AUTH_TOKEN=tok123\n", encoding="utf-8")
        self.assertEqual(infra.loki_shipping_vars(), {})


if __name__ == "__main__":
    unittest.main()
