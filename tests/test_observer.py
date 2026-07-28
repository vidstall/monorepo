from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import context, infra, observer


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
        self.assertEqual(set(services), {"prometheus", "tempo", "grafana"})
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


class ObserverDeployTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
