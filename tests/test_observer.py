from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli import context, infra, observer
from cli.observer.query import query


class ObserverConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(context, "RUNTIME_OBSERVER_TOML", self.root / "runtime" / "observer.toml"),
            patch.object(context, "GENERATED_OBSERVER_INVENTORY", self.root / "ansible" / "observer.generated.yml"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_add_host_persists_and_is_readable(self) -> None:
        observer.add_host("bourbon", "161.118.232.63", "deploy", "~/.ssh/rotexai/bourbon-deploy")
        hosts = observer.read_hosts()
        self.assertEqual(len(hosts), 1)
        entry = hosts[0]
        self.assertEqual(entry["name"], "bourbon")
        self.assertEqual(entry["address"], "161.118.232.63")
        self.assertEqual(entry["ssh_user"], "deploy")
        # ~ must be expanded to a real filesystem path at write time --
        # ansible_ssh_private_key_file is never shell-expanded by Ansible.
        self.assertTrue(entry["ssh_key"].startswith("/"))
        self.assertTrue(entry["ssh_key"].endswith("/.ssh/rotexai/bourbon-deploy"))

    def test_add_host_twice_updates_in_place(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        observer.add_host("bourbon", "5.6.7.8", "deploy", "/tmp/key")
        hosts = observer.read_hosts()
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0]["address"], "5.6.7.8")

    def test_remove_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        self.assertTrue(observer.remove_host("bourbon"))
        self.assertEqual(observer.read_hosts(), [])

    def test_remove_unknown_host_returns_false(self) -> None:
        self.assertFalse(observer.remove_host("nope"))

    def test_add_host_defaults_port_and_preserves_it_on_update(self) -> None:
        entry = observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        self.assertEqual(entry["port"], observer.DEFAULT_HOST_PORT)
        observer.add_host("bourbon", "5.6.7.8", "deploy", "/tmp/key")
        self.assertEqual(observer.find_host("bourbon")["port"], observer.DEFAULT_HOST_PORT)

    def test_add_host_custom_port_is_persisted_and_overridable(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key", port=27000)
        self.assertEqual(observer.find_host("bourbon")["port"], 27000)
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        self.assertEqual(observer.find_host("bourbon")["port"], 27000)
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key", port=28000)
        self.assertEqual(observer.find_host("bourbon")["port"], 28000)

    def test_add_host_without_services_omits_the_key(self) -> None:
        # No `services` key at all when unset -- keeps runtime/observer.toml
        # unchanged for every host that doesn't use the split feature (and
        # matches inventory.py's "no key -> all 5" fallback).
        entry = observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        self.assertNotIn("services", entry)
        self.assertNotIn("services", observer.find_host("bourbon"))

    def test_add_host_services_is_persisted_and_preserved_on_update(self) -> None:
        observer.add_host("vermouth", "5.6.7.8", "deploy", "/tmp/key", services=["tempo", "loki"])
        self.assertEqual(observer.find_host("vermouth")["services"], ["tempo", "loki"])
        # Re-adding without `services` preserves the existing split, same
        # pattern as `port`.
        observer.add_host("vermouth", "9.9.9.9", "deploy", "/tmp/key")
        entry = observer.find_host("vermouth")
        self.assertEqual(entry["address"], "9.9.9.9")
        self.assertEqual(entry["services"], ["tempo", "loki"])

    def test_add_host_services_can_be_changed_on_update(self) -> None:
        observer.add_host("vermouth", "5.6.7.8", "deploy", "/tmp/key", services=["tempo", "loki"])
        observer.add_host("vermouth", "5.6.7.8", "deploy", "/tmp/key", services=["tempo"])
        self.assertEqual(observer.find_host("vermouth")["services"], ["tempo"])


class ObserverInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(context, "RUNTIME_OBSERVER_TOML", self.root / "runtime" / "observer.toml"),
            patch.object(context, "GENERATED_OBSERVER_INVENTORY", self.root / "ansible" / "observer.generated.yml"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_build_inventory_shape(self) -> None:
        observer.add_host("bourbon", "161.118.232.63", "deploy", "/home/me/.ssh/bourbon-deploy")
        data = observer.build_inventory()
        host_entry = data["all"]["children"]["xaisen"]["hosts"]["bourbon"]
        self.assertEqual(host_entry["ansible_host"], "161.118.232.63")
        self.assertEqual(host_entry["ansible_user"], "deploy")
        self.assertEqual(host_entry["ansible_ssh_private_key_file"], "/home/me/.ssh/bourbon-deploy")
        services = {s["service"]: s for s in host_entry["xaisen_services"]}
        self.assertEqual(set(services), {"prometheus", "tempo", "grafana", "pushgateway", "loki"})
        # Prometheus: container-internal port stays fixed (its own default)
        # -- only host_port (the externally published one) is
        # operator-chosen.
        self.assertEqual(services["prometheus"]["port"], 9090)
        self.assertEqual(services["prometheus"]["host_port"], observer.DEFAULT_HOST_PORT)
        self.assertEqual(services["prometheus"]["desired_state"], "running")
        # Tempo: both port and host_port stay fixed at 4318 (never exposed
        # un-proxied, so no obscurity concern like prometheus's host_port).
        self.assertEqual(services["tempo"]["port"], 4318)
        self.assertEqual(services["tempo"]["host_port"], 4318)
        self.assertEqual(services["tempo"]["desired_state"], "running")
        # Grafana: both port and host_port stay fixed at 3000, same
        # no-obscurity reasoning as tempo (reached only via the observer
        # ingress Caddy's plain proxy or an SSH tunnel, never directly).
        self.assertEqual(services["grafana"]["port"], 3000)
        self.assertEqual(services["grafana"]["host_port"], 3000)
        self.assertEqual(services["grafana"]["desired_state"], "running")
        # Pushgateway: both port and host_port stay fixed at 9091. Prometheus
        # scrapes it over the internal xaisen-net bridge by container name
        # (same host, no TLS/bearer needed); its host_port only matters for
        # an SSH-tunnel debug path, same no-obscurity reasoning as tempo.
        self.assertEqual(services["pushgateway"]["port"], 9091)
        self.assertEqual(services["pushgateway"]["host_port"], 9091)
        self.assertEqual(services["pushgateway"]["desired_state"], "running")
        # Loki: both port and host_port stay fixed at 3100, same
        # no-obscurity reasoning as tempo/pushgateway (reached only via the
        # observer ingress Caddy's Basic-Auth-gated push proxy, or an SSH
        # tunnel for direct query/debug access).
        self.assertEqual(services["loki"]["port"], 3100)
        self.assertEqual(services["loki"]["host_port"], 3100)
        self.assertEqual(services["loki"]["desired_state"], "running")

    def test_build_inventory_uses_custom_port(self) -> None:
        observer.add_host("bourbon", "161.118.232.63", "deploy", "/tmp/key", port=27000)
        data = observer.build_inventory()
        service = data["all"]["children"]["xaisen"]["hosts"]["bourbon"]["xaisen_services"][0]
        self.assertEqual(service["host_port"], 27000)
        self.assertEqual(service["port"], 9090)

    def test_write_inventory_creates_file(self) -> None:
        observer.add_host("bourbon", "161.118.232.63", "deploy", "/tmp/key")
        observer.write_inventory()
        self.assertTrue(context.GENERATED_OBSERVER_INVENTORY.exists())
        self.assertIn("bourbon", context.GENERATED_OBSERVER_INVENTORY.read_text(encoding="utf-8"))

    def test_build_inventory_filters_services_for_a_split_host(self) -> None:
        observer.add_host("bourbon", "161.118.232.63", "deploy", "/tmp/key", services=["prometheus", "grafana", "pushgateway"])
        observer.add_host("vermouth", "140.245.113.173", "deploy", "/tmp/key2", services=["tempo", "loki"])
        data = observer.build_inventory()
        hosts = data["all"]["children"]["xaisen"]["hosts"]

        bourbon_services = {s["service"] for s in hosts["bourbon"]["xaisen_services"]}
        self.assertEqual(bourbon_services, {"prometheus", "grafana", "pushgateway"})

        vermouth_services = {s["service"] for s in hosts["vermouth"]["xaisen_services"]}
        self.assertEqual(vermouth_services, {"tempo", "loki"})


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
