from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import context, observer


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


if __name__ == "__main__":
    unittest.main()
