from __future__ import annotations

from unittest.mock import patch

from cli import bot_client, contract, image_bake, infra, local_bot, observer, registry, scenario
from cli import object as object_cmd
from cli.vidctl import build_parser

from tests.scenario_test_base import SCENARIO_TOML, SCENARIO_TOML_ONE_INSTANCE, ScenarioTestCase

SCENARIO_TOML_WITH_BOT = (
    SCENARIO_TOML
    + """
[[workers]]
host = "002"
service = "bot"
provider = "digitalocean"
size = "s-1vcpu-1gb"
"""
)


class ApplyTests(ScenarioTestCase):
    def test_apply_ensures_image_before_starting_workers(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(image_bake, "ensure_image", return_value=(True, "")) as ensure_image:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        # SCENARIO_TOML has two digitalocean workers with no explicit
        # region -- ensure_image should be called once per unique
        # (provider, region) pair, not once per worker.
        ensure_image.assert_called_once_with("digitalocean", None, force=False)

    def test_apply_parser_rebake_flag_defaults_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["scenario", "apply", "s.toml", "--yes"])
        self.assertFalse(args.rebake)

    def test_apply_parser_rebake_flag_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["scenario", "apply", "s.toml", "--yes", "--rebake"])
        self.assertTrue(args.rebake)

    def test_apply_rebake_forces_ensure_image(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(image_bake, "ensure_image", return_value=(True, "")) as ensure_image:
            code = scenario.apply(str(path), True, rebake=True)
        self.assertEqual(code, 0)
        ensure_image.assert_called_once_with("digitalocean", None, force=True)

    def test_apply_fails_when_image_bake_fails(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(image_bake, "ensure_image", return_value=(False, "bake blew up")):
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "active")
        # The workers should still have been started despite bake failure (best-effort).
        topology = self.read_topology()
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(topology.get("workers", [])), 3)

    def test_apply_passes_explicit_region_through_to_control(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML.replace(
                '[[workers]]\nhost = "001"\nservice = "cp-daemon"',
                '[[workers]]\nhost = "001"\nservice = "cp-daemon"\nregion = "sfo3"',
            ),
        )
        with (
            patch.object(image_bake, "ensure_image", return_value=(True, "")) as ensure_image,
            patch.object(infra, "control_many_hosts", wraps=infra.control_many_hosts) as control_many_hosts_spy,
        ):
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        ensure_image.assert_any_call("digitalocean", "sfo3", force=False)
        # Both workers are colocated on node-1@digitalocean, so apply()
        # batches them through control_many_hosts() instead of calling control() once per service.
        call_args, _call_kwargs = control_many_hosts_spy.call_args
        groups = call_args[1]
        workers = groups[0][2]
        cp_daemon_row = next(r for r in workers if r["service"] == "cp-daemon")
        self.assertEqual(cp_daemon_row.get("region"), "sfo3")


    def test_apply_excludes_await_worker_from_provisioning(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML_ONE_INSTANCE
            + '\n[[workers]]\nhost = "002"\nservice = "relay"\nprovider = "digitalocean"\nawait = true\n'
            + '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            + 'host = "002"\nservice = "relay"\nprovider = "digitalocean"\n',
        )
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        topology = self.read_topology()
        hosts = {row["host"] for row in topology.get("workers", [])}
        self.assertNotIn("002", hosts)
        self.assertIn("001", hosts)

    def test_apply_does_not_kill_worker_previously_started_via_join(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML_ONE_INSTANCE)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        # Re-declare the already-running host "001" cp-daemon worker as
        # await=true (simulating a scenario file edited after the worker
        # was separately brought up e.g. via worker.join) and re-apply --
        # it must not be treated as drift and killed.
        v2 = self.write_scenario(
            "s.toml",
            SCENARIO_TOML_ONE_INSTANCE.replace(
                '[[workers]]\nhost = "001"\nservice = "cp-daemon"\nprovider = "digitalocean"\nsize = "s-1vcpu-1gb"\n',
                '[[workers]]\nhost = "001"\nservice = "cp-daemon"\nprovider = "digitalocean"\n'
                'size = "s-1vcpu-1gb"\nawait = true\n',
            )
            + '\n[[actions]]\ntype = "worker.join"\ntimestamp = "+1s"\n'
            + 'host = "001"\nservice = "cp-daemon"\nprovider = "digitalocean"\n',
        )
        code = scenario.apply(str(v2), True)
        self.assertEqual(code, 0)
        topology = self.read_topology()
        hosts = {row["host"] for row in topology.get("workers", [])}
        self.assertIn("001", hosts)

    def test_apply_creates_workers_and_locks(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        topology = self.read_topology()
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(topology["workers"]), 3)
        self.assertTrue(all(i["desired_state"] == "running" for i in topology["workers"]))

        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "active")
        self.assertEqual(lock["scenario_hash"], scenario.scenario_hash_of(path))

    def test_apply_refreshes_observer_stack_in_one_combined_call(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0) as observer_deploy:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        # observer.deploy(host=None) already covers every registered host in
        # one combined Ansible run -- apply() calls it once, not once per
        # registered host, to avoid paying a full playbook startup per host.
        observer_deploy.assert_called_once_with(None)

    def test_apply_skips_observer_refresh_when_none_registered(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy") as observer_deploy:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        observer_deploy.assert_not_called()

    def test_apply_survives_observer_refresh_failure(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", side_effect=RuntimeError("unreachable")):
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "active")

    def test_apply_pushes_contract_state_to_pushgateway_host(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            with patch.object(observer, "export_contract_state", return_value=0) as export_state:
                code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        export_state.assert_called_once_with("devnet", "bourbon")

    def test_apply_skips_contract_state_push_when_no_pushgateway_host(self) -> None:
        observer.add_host("vermouth", "1.2.3.4", "deploy", "/tmp/key", services=["tempo", "loki"])
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            with patch.object(observer, "export_contract_state") as export_state:
                code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        export_state.assert_not_called()

    def test_apply_skips_contract_state_push_when_none_registered(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "export_contract_state") as export_state:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        export_state.assert_not_called()

    def test_apply_survives_contract_state_push_failure(self) -> None:
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            with patch.object(observer, "export_contract_state", side_effect=RuntimeError("unreachable")):
                code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "active")

    def test_apply_publishes_frontends_before_registry(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        with patch.object(object_cmd, "publish", return_value=0) as publish_frontend:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        publish_frontend.assert_called_once_with("site-2-bucket", "frontend", "alibaba")

    def test_apply_frontend_failure_stops_before_registry_and_workers(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        with (
            patch.object(object_cmd, "publish", return_value=1),
            patch.object(registry, "publish") as registry_publish,
        ):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        registry_publish.assert_not_called()
        self.assertEqual(scenario.read_lock()["status"], "failed")
        # Instance reconcile never started -- topology.toml isn't even
        # created yet (only ensure_topology(), reached during reconcile,
        # would create it).
        self.assertFalse(self.topology.exists())

    def test_apply_never_calls_object_delete(self) -> None:
        path = self.write_scenario(
            "s.toml",
            SCENARIO_TOML + '\n[[frontends]]\nname = "site-2-bucket"\nprovider = "alibaba"\n',
        )
        with patch.object(object_cmd, "delete") as delete_frontend:
            self.assertEqual(scenario.apply(str(path), True), 0)
            self.assertEqual(scenario.destroy(None), 0)
        delete_frontend.assert_not_called()

    def test_destroy_stops_local_bot_sessions_before_killing_workers(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        with (
            patch.object(local_bot, "stop_all", return_value=0) as stop_all,
            patch.object(infra, "control", return_value=0) as control,
        ):
            self.assertEqual(scenario.destroy(None), 0)
        stop_all.assert_called_once_with()
        control.assert_called()

    def test_destroy_no_op_when_no_scenario_active_never_touches_local_bots(self) -> None:
        with patch.object(local_bot, "stop_all", return_value=0) as stop_all:
            self.assertEqual(scenario.destroy(None), 0)
        stop_all.assert_not_called()

    def test_clean_no_op_when_no_scenario_active(self) -> None:
        with patch.object(observer, "read_hosts", return_value=[]) as read_hosts:
            self.assertEqual(scenario.clean(None), 0)
        read_hosts.assert_not_called()

    def test_clean_stops_leftover_bot_sessions_without_killing_workers(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML_WITH_BOT)
        self.assertEqual(scenario.apply(str(path), True), 0)
        with (
            patch.object(bot_client, "delete_all_sessions", return_value={"stopped": 2}) as delete_all,
            patch.object(observer, "read_hosts", return_value=[]),
            patch.object(infra, "control") as control,
        ):
            self.assertEqual(scenario.clean(None), 0)
        delete_all.assert_called_once_with("002")
        control.assert_not_called()

    def test_clean_skips_unreachable_bot_worker(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML_WITH_BOT)
        self.assertEqual(scenario.apply(str(path), True), 0)
        with (
            patch.object(bot_client, "delete_all_sessions", return_value=None),
            patch.object(observer, "read_hosts", return_value=[]),
        ):
            self.assertEqual(scenario.clean(None), 0)

    def test_clean_redeploys_observer_stack_so_grafana_comes_back(self) -> None:
        # Regression test: clean() used to call only observer.clean() (via
        # _clean_observer_stack()), which removes the Grafana container
        # along with prometheus/tempo -- fine for destroy() (always
        # followed by an apply() that redeploys everything) but clean() has
        # no such follow-up, so the operator's dashboard would just stay
        # down. clean() must always pair the wipe with a redeploy.
        observer.add_host("bourbon", "1.2.3.4", "deploy", "/tmp/key")
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(observer, "deploy", return_value=0):
            self.assertEqual(scenario.apply(str(path), True), 0)
        with (
            patch.object(observer, "clean", return_value=0) as observer_clean,
            patch.object(observer, "deploy", return_value=0) as observer_deploy,
        ):
            self.assertEqual(scenario.clean(None), 0)
        observer_clean.assert_called_once_with("bourbon")
        observer_deploy.assert_called_once_with(None)

    def test_apply_logs_into_registry_when_provider_set(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML + '\n[registry]\nprovider = "digitalocean"\n')
        with patch.object(registry, "login", return_value=0) as login:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        login.assert_called_once_with("digitalocean")

    def test_apply_skips_registry_login_when_provider_unset(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(registry, "login", return_value=0) as login:
            code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)
        login.assert_not_called()

    def test_apply_registry_login_failure_leaves_lock_failed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML + '\n[registry]\nprovider = "digitalocean"\n')
        with patch.object(registry, "login", return_value=1):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        self.assertEqual(scenario.read_lock()["status"], "failed")

    def test_apply_without_yes_is_refused(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        code = scenario.apply(str(path), False)
        self.assertEqual(code, 2)
        self.assertIsNone(scenario.read_lock())

    def test_reapply_same_scenario_allowed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        self.assertEqual(scenario.apply(str(path), True), 0)

    def test_apply_different_scenario_while_locked_is_blocked(self) -> None:
        path_a = self.write_scenario("a.toml", SCENARIO_TOML)
        path_b = self.write_scenario("b.toml", SCENARIO_TOML_ONE_INSTANCE)
        self.assertEqual(scenario.apply(str(path_a), True), 0)
        lock_before = scenario.read_lock()

        code = scenario.apply(str(path_b), True)
        self.assertNotEqual(code, 0)
        lock_after = scenario.read_lock()
        self.assertEqual(lock_before, lock_after)

    def test_reconcile_kills_dropped_worker_and_never_touches_objects(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        self.assertEqual(scenario.apply(str(path), True), 0)
        # 2 declared + 1 auto-injected node_exporter (both rows share host "node-1").
        self.assertEqual(len(self.read_topology()["workers"]), 3)

        # Seed an [[objects]] row (frontend/object-storage) that must survive
        # every scenario apply/destroy untouched.
        topology = infra.read_topology()
        topology.setdefault("objects", []).append(
            {
                "name": "site-1-bucket",
                "object": "frontend",
                "provider": "alibaba",
                "env": "devnet",
                "backend": "object_storage",
                "desired_state": "running",
            }
        )
        infra.write_topology(topology)

        # Edit the SAME scenario path in place (drop the relay worker) and
        # re-apply it -- this is the intended drift-reconcile flow, since the
        # lock's identity check is by content hash, not path.
        self.write_scenario("s.toml", SCENARIO_TOML_ONE_INSTANCE)
        code = scenario.apply(str(path), True)
        self.assertEqual(code, 0)

        topology = self.read_topology()
        active = [i for i in topology["workers"] if i["desired_state"] != "deleted"]
        # cp-daemon (still declared) + its auto-injected node_exporter --
        # relay was dropped, along with relay's OWN auto-injected instance
        # (SCENARIO_TOML_ONE_INSTANCE only declares one host, so there's
        # only ever one node_exporter for it either way).
        self.assertEqual(len(active), 2)
        self.assertEqual({i["service"] for i in active}, {"cp-daemon", "node_exporter"})
        self.assertEqual(len(topology["objects"]), 1)
        self.assertEqual(topology["objects"][0]["name"], "site-1-bucket")

    def test_failure_mid_reconcile_leaves_lock_failed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(infra, "pulumi_up", return_value=1):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "failed")

    def test_contract_publish_failure_leaves_lock_failed(self) -> None:
        path = self.write_scenario("s.toml", SCENARIO_TOML)
        with patch.object(contract, "publish", return_value=1):
            code = scenario.apply(str(path), True)
        self.assertNotEqual(code, 0)
        lock = scenario.read_lock()
        self.assertEqual(lock["status"], "failed")
