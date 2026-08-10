from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli import context, infra, observer
from cli.observer.query import query


class ObserverDeployTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(context, "RUNTIME_OBSERVER_TOML", self.root / "runtime" / "observer.toml"),
            patch.object(context, "GENERATED_OBSERVER_INVENTORY", self.root / "ansible" / "observer.generated.yml"),
            patch.object(context, "SERVICE_SECRETS_DIR", self.root / "secrets" / "services"),
            patch.object(infra, "metrics_auth_token", return_value="tok"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_deploy_without_hosts_fails_without_calling_ansible(self) -> None:
        with patch.object(infra, "ansible_playbook") as ansible_playbook:
            code = observer.deploy()
        self.assertEqual(code, 1)
        ansible_playbook.assert_not_called()

    def test_deploy_unknown_host_fails_without_calling_ansible(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        with patch.object(infra, "ansible_playbook") as ansible_playbook:
            code = observer.deploy("nope")
        self.assertEqual(code, 1)
        ansible_playbook.assert_not_called()

    def test_deploy_scopes_limit_to_observer_hosts_only(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        observer.add_host("other", "5.6.7.8", "deploy", "/tmp/key2")
        with patch.object(infra, "ansible_playbook", return_value=0) as ansible_playbook:
            code = observer.deploy()
        self.assertEqual(code, 0)
        _, kwargs = ansible_playbook.call_args
        self.assertEqual(kwargs["host_limit"], "bourbon,other")
        self.assertEqual(kwargs["extra_vars"]["xaisen_metrics_auth_token"], "tok")

    def test_deploy_single_host_limits_to_that_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        with patch.object(infra, "ansible_playbook", return_value=0) as ansible_playbook:
            code = observer.deploy("bourbon")
        self.assertEqual(code, 0)
        _, kwargs = ansible_playbook.call_args
        self.assertEqual(kwargs["host_limit"], "bourbon")

    def test_deploy_only_prints_urls_for_a_split_host_own_services(self) -> None:
        # A host whose `services` doesn't include tempo/loki/grafana must not
        # print those services' ingest/login URLs -- they're not running
        # there (see bourbon/vermouth dividing the stack).
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key", services=["prometheus", "grafana", "pushgateway"])
        observer.add_host("vermouth", "5.6.7.8", "deploy", "/tmp/key2", services=["tempo", "loki"])
        with patch.object(infra, "ansible_playbook", return_value=0):
            with patch("builtins.print") as mock_print:
                observer.deploy()
        printed = "\n".join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn("Grafana for 'bourbon'", printed)
        self.assertNotIn("Tempo trace ingest for 'bourbon'", printed)
        self.assertNotIn("Loki log ingest for 'bourbon'", printed)
        self.assertIn("Tempo trace ingest for 'vermouth'", printed)
        self.assertIn("Loki log ingest for 'vermouth'", printed)
        self.assertNotIn("Grafana for 'vermouth'", printed)

    def test_deploy_writes_otel_env_for_a_tempo_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key", services=["tempo"])
        with patch.object(infra, "ansible_playbook", return_value=0):
            observer.deploy()
        otel_env = context.SERVICE_SECRETS_DIR / "otel.env"
        self.assertTrue(otel_env.exists())
        content = otel_env.read_text(encoding="utf-8")
        self.assertIn("OTEL_EXPORTER_OTLP_ENDPOINT=https://tempo.1-2-3-4.sslip.io/v1/traces", content)
        # Same token tempo_auth_token() persisted to observer-tempo.env -- both
        # reads/writes go through the SAME (test-patched) SERVICE_SECRETS_DIR.
        tempo_secret = (context.SERVICE_SECRETS_DIR / "observer-tempo.env").read_text(encoding="utf-8")
        token = tempo_secret.strip().split("=", 1)[1]
        self.assertIn(f"OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20{token}", content)

    def test_deploy_writes_loki_env_for_a_loki_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key", services=["loki"])
        with patch.object(infra, "ansible_playbook", return_value=0):
            observer.deploy()
        loki_env = context.SERVICE_SECRETS_DIR / "loki.env"
        self.assertTrue(loki_env.exists())
        content = loki_env.read_text(encoding="utf-8")
        self.assertIn("LOKI_PUSH_URL=https://loki.1-2-3-4.sslip.io/loki/api/v1/push", content)
        loki_secret = (context.SERVICE_SECRETS_DIR / "observer-loki.env").read_text(encoding="utf-8")
        token = loki_secret.strip().split("=", 1)[1]
        self.assertIn(f"LOKI_AUTH_TOKEN={token}", content)

    def test_deploy_does_not_write_otel_or_loki_env_for_a_host_without_those_services(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key", services=["prometheus", "grafana", "pushgateway"])
        with patch.object(infra, "ansible_playbook", return_value=0):
            observer.deploy()
        self.assertFalse((context.SERVICE_SECRETS_DIR / "otel.env").exists())
        self.assertFalse((context.SERVICE_SECRETS_DIR / "loki.env").exists())


class ObserverLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(context, "RUNTIME_OBSERVER_TOML", self.root / "runtime" / "observer.toml"),
            patch.object(context, "GENERATED_OBSERVER_INVENTORY", self.root / "ansible" / "observer.generated.yml"),
            patch.object(infra, "metrics_auth_token", return_value="tok"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])
        observer.add_host("bourbon", "161.118.232.63", "deploy", "/tmp/key")

    def test_start_sets_desired_state_running_and_calls_site_yml(self) -> None:
        observer.set_desired_state("bourbon", "stopped")
        with patch.object(infra, "ansible_playbook", return_value=0) as ansible_playbook:
            code = observer.start("bourbon")
        self.assertEqual(code, 0)
        self.assertEqual(observer.find_host("bourbon")["desired_state"], "running")
        args, kwargs = ansible_playbook.call_args
        self.assertEqual(args[0], "site.yml")
        self.assertEqual(kwargs["host_limit"], "bourbon")
        self.assertEqual(kwargs["extra_vars"]["xaisen_container_state"], "started")

    def test_stop_sets_desired_state_stopped(self) -> None:
        with patch.object(infra, "ansible_playbook", return_value=0):
            code = observer.stop("bourbon")
        self.assertEqual(code, 0)
        self.assertEqual(observer.find_host("bourbon")["desired_state"], "stopped")
        data = observer.build_inventory()
        service = data["all"]["children"]["xaisen"]["hosts"]["bourbon"]["xaisen_services"][0]
        self.assertEqual(service["desired_state"], "stopped")

    def test_restart_forces_container_state_restarted(self) -> None:
        with patch.object(infra, "ansible_playbook", return_value=0) as ansible_playbook:
            code = observer.restart("bourbon")
        self.assertEqual(code, 0)
        args, kwargs = ansible_playbook.call_args
        self.assertEqual(args[0], "site.yml")
        self.assertEqual(kwargs["extra_vars"]["xaisen_container_state"], "restarted")

    def test_destroy_calls_dedicated_playbook_and_leaves_desired_state(self) -> None:
        with patch.object(infra, "ansible_playbook", return_value=0) as ansible_playbook:
            code = observer.destroy("bourbon")
        self.assertEqual(code, 0)
        args, kwargs = ansible_playbook.call_args
        self.assertEqual(args[0], "observer_destroy.yml")
        self.assertEqual(kwargs["host_limit"], "bourbon")
        self.assertEqual(observer.find_host("bourbon")["desired_state"], "running")

    def test_clean_calls_dedicated_playbook(self) -> None:
        with patch.object(infra, "ansible_playbook", return_value=0) as ansible_playbook:
            code = observer.clean("bourbon")
        self.assertEqual(code, 0)
        args, kwargs = ansible_playbook.call_args
        self.assertEqual(args[0], "observer_clean.yml")
        self.assertEqual(kwargs["host_limit"], "bourbon")

    def test_lifecycle_actions_reject_unknown_host(self) -> None:
        with patch.object(infra, "ansible_playbook") as ansible_playbook:
            self.assertEqual(observer.start("nope"), 1)
            self.assertEqual(observer.stop("nope"), 1)
            self.assertEqual(observer.restart("nope"), 1)
            self.assertEqual(observer.destroy("nope"), 1)
            self.assertEqual(observer.clean("nope"), 1)
        ansible_playbook.assert_not_called()


class ObserverSecretsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(context, "SERVICE_SECRETS_DIR", self.root / "secrets" / "services")]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_tempo_auth_token_generates_once_and_persists(self) -> None:
        first = observer.tempo_auth_token()
        second = observer.tempo_auth_token()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (context.SERVICE_SECRETS_DIR / "observer-tempo.env").read_text(encoding="utf-8")
        self.assertIn(f"TEMPO_AUTH_TOKEN={first}", contents)

    def test_grafana_admin_password_generates_once_and_persists(self) -> None:
        first = observer.grafana_admin_password()
        second = observer.grafana_admin_password()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (context.SERVICE_SECRETS_DIR / "observer-grafana.env").read_text(encoding="utf-8")
        self.assertIn(f"GF_SECURITY_ADMIN_PASSWORD={first}", contents)

    def test_loki_auth_token_generates_once_and_persists(self) -> None:
        first = observer.loki_auth_token()
        second = observer.loki_auth_token()
        self.assertTrue(first)
        self.assertEqual(first, second)
        contents = (context.SERVICE_SECRETS_DIR / "observer-loki.env").read_text(encoding="utf-8")
        self.assertIn(f"LOKI_AUTH_TOKEN={first}", contents)


class ObserverCleanPlaybookTests(unittest.TestCase):
    def test_clean_wipes_prometheus_and_tempo_data_but_not_grafanas(self) -> None:
        import yaml

        path = context.ANSIBLE_DIR / "playbooks" / "observer_clean.yml"
        play = yaml.safe_load(path.read_text(encoding="utf-8"))[0]
        tasks = {task["name"]: task for task in play["tasks"]}

        removed_containers = tasks["Remove monitoring containers"]["loop"]
        self.assertEqual(
            set(removed_containers),
            {
                "xaisen-prometheus",
                "xaisen-tempo",
                "xaisen-grafana",
                "xaisen-grafana-renderer",
                "xaisen-pushgateway",
                "xaisen-loki",
            },
        )

        wiped_data_dirs = tasks["Wipe monitoring data directories"]["loop"]
        # Grafana's container is removed above, but its data dir (dashboards,
        # logins) must survive a `vidctl scenario destroy` reset -- only
        # prometheus/tempo/loki's history is meant to be wiped.
        self.assertEqual(set(wiped_data_dirs), {"prometheus", "tempo", "loki"})
        self.assertNotIn("grafana", wiped_data_dirs)


class QueryAtTimeTests(unittest.TestCase):
    """cli.observer.query.query()'s `at_time` param -- enables
    cli.scenario.system_log.backfill_action_snapshots() to ask Prometheus
    for its historical view of the system instead of "now"."""

    def _fake_response(self, body: bytes) -> MagicMock:
        response = MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_omits_time_param_when_at_time_is_none(self) -> None:
        body = json.dumps({"status": "success", "data": {"result": []}}).encode()
        with (
            patch("cli.observer.query.read_hosts", return_value=[{"address": "1.2.3.4", "services": ["prometheus"]}]),
            patch.object(infra, "metrics_auth_token", return_value="tok"),
            patch("urllib.request.urlopen", return_value=self._fake_response(body)) as mock_urlopen,
        ):
            query("up")

        request = mock_urlopen.call_args[0][0]
        self.assertNotIn("time=", request.full_url)

    def test_includes_time_param_when_at_time_given(self) -> None:
        body = json.dumps({"status": "success", "data": {"result": []}}).encode()
        with (
            patch("cli.observer.query.read_hosts", return_value=[{"address": "1.2.3.4", "services": ["prometheus"]}]),
            patch.object(infra, "metrics_auth_token", return_value="tok"),
            patch("urllib.request.urlopen", return_value=self._fake_response(body)) as mock_urlopen,
        ):
            query("up", at_time=1700000000.0)

        request = mock_urlopen.call_args[0][0]
        self.assertIn("time=1700000000.0", request.full_url)


class GrafanaAnnotationTests(unittest.TestCase):
    """cli.observer.grafana_render.post_annotation() -- the time-event
    marker scenario worker.leave/worker.join actions post so the Grafana
    overview dashboard shows exactly when a worker was stopped/started
    (see cli.scenario.actions.py)."""

    def _fake_response(self, status: int = 200) -> MagicMock:
        response = MagicMock()
        response.status = status
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_posts_annotation_with_expected_body_and_auth(self) -> None:
        from cli.observer.grafana_render import post_annotation

        with (
            patch(
                "cli.observer.grafana_render.read_hosts",
                return_value=[{"address": "1.2.3.4", "services": ["grafana"]}],
            ),
            patch("cli.observer.grafana_render.grafana_admin_password", return_value="secret"),
            patch("urllib.request.urlopen", return_value=self._fake_response()) as mock_urlopen,
        ):
            ok = post_annotation(1700000000000, ["worker-churn", "worker.leave"], "worker.leave: relay stopped")

        self.assertTrue(ok)
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.full_url, "https://grafana.1-2-3-4.sslip.io/api/annotations")
        self.assertEqual(request.get_header("Authorization"), "Basic YWRtaW46c2VjcmV0")
        body = json.loads(request.data)
        self.assertEqual(
            body,
            {
                "time": 1700000000000,
                "tags": ["worker-churn", "worker.leave"],
                "text": "worker.leave: relay stopped",
            },
        )

    def test_returns_false_without_raising_when_no_grafana_host_registered(self) -> None:
        from cli.observer.grafana_render import post_annotation

        with patch("cli.observer.grafana_render.read_hosts", return_value=[]):
            ok = post_annotation(1700000000000, ["worker-churn"], "text")

        self.assertFalse(ok)

    def test_returns_false_without_raising_on_unreachable_grafana(self) -> None:
        import urllib.error

        from cli.observer.grafana_render import post_annotation

        with (
            patch(
                "cli.observer.grafana_render.read_hosts",
                return_value=[{"address": "1.2.3.4", "services": ["grafana"]}],
            ),
            patch("cli.observer.grafana_render.grafana_admin_password", return_value="secret"),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("unreachable")),
        ):
            ok = post_annotation(1700000000000, ["worker-churn"], "text")

        self.assertFalse(ok)


class RoomOccupancyCountsTests(unittest.TestCase):
    def test_counts_distinct_peers_per_room_including_bots(self) -> None:
        # discover_active_peers() is built on dvconf_relay_peer_*/
        # dvconf_rtc_* -- populated by both bots and browser clients (see
        # room_occupancy_counts()'s docstring) -- unlike
        # room_participant_counts()'s signaling-only gauge, which bots
        # never touch at all.
        with patch(
            "cli.observer.query.discover_active_peers",
            return_value={"room-1": {"bot-peer", "browser-peer"}, "room-2": {"bot-peer-2"}},
        ):
            counts = observer.room_occupancy_counts()

        self.assertEqual(counts, {"room-1": 2, "room-2": 1})

    def test_returns_none_when_discover_active_peers_fails(self) -> None:
        with patch("cli.observer.query.discover_active_peers", return_value=None):
            counts = observer.room_occupancy_counts()

        self.assertIsNone(counts)


if __name__ == "__main__":
    unittest.main()
