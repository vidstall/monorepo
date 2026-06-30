from __future__ import annotations

import argparse
import time
from pathlib import Path

from cli.scenario.models import BenchmarkReport
from cli.scenario.report import _write_report, print_report
from cli.scenario.run import (
    _apply_registry_overrides,
    _print_launch_banner,
    _setup_and_push_images,
    _setup_registry,
    _terraform_apply_with_topology,
    load_scenario,
)


def _list_scenarios() -> None:
    from cli.config import REPO_ROOT
    scenario_dir = REPO_ROOT / "scenario"

    groups: dict[str, list[Path]] = {}
    for subdir in sorted(scenario_dir.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("_") and not subdir.name.startswith("."):
            scripts = sorted(subdir.glob("*.py"))
            if scripts:
                groups[subdir.name] = scripts
    top_level = sorted(scenario_dir.glob("*.py"))
    if top_level:
        groups["(root)"] = top_level

    if not groups:
        print("No scenario scripts found in scenario/")
        return

    print()
    for group_name, scripts in groups.items():
        print(f"  [{group_name.upper()}]")
        for path in scripts:
            try:
                s = load_scenario(path)
                t = s.topology
                teardown_flag = "teardown" if t.teardown else "persistent"
                vc_part = f"/{t.vclient_nodes}vc" if t.vclient_nodes else ""
                topo_str = (
                    f"{t.provider} | {t.worker_nodes}w/{t.dist_nodes}d{vc_part}/{t.coordinator_nodes}coord"
                    f" | {t.contract_network} | {teardown_flag}"
                )
                print(f"    {path.name:<32} {s.name:<25} {topo_str}")
                print(f"    {'':32} {s.description}")
            except Exception as e:
                print(f"    {path.name:<32} (load error: {e})")
        print()
    print(f"  Run: python3 vidctl.py launch scenario/<category>/<file>.py")


def cmd_launch(args: argparse.Namespace) -> None:
    if getattr(args, "list", False) or not getattr(args, "scenario", None):
        _list_scenarios()
        return

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise SystemExit(f"Scenario file not found: {scenario_path}")

    scenario = load_scenario(scenario_path)
    topo = scenario.topology
    dry_run = getattr(args, "dry_run", False)
    no_teardown = getattr(args, "no_teardown", False)
    _apply_registry_overrides(topo, args)

    _print_launch_banner(scenario, topo, dry_run)

    deployment = None
    if not dry_run:
        from cli.contract import cmd_deploy_contract, cmd_update_contract
        from cli.infra.discovery import discover, is_deployed, wait_for_routes
        from cli.env import build_env
        from cli.infra.inventory import ansible_playbook, render_ansible_vars, render_inventory, require_runtime_env
        from cli.infra.terraform import terraform_output

        env = build_env(topo.provider)
        if topo.registry_init or topo.registry_build:
            print("\nSetting up container registry...")
            _setup_registry(topo)
            env = build_env(topo.provider)
        if not topo.build_images:
            require_runtime_env(env)

        infra_provisioned_here = False
        _purge_args = argparse.Namespace(
            provider=topo.provider,
            auto_approve=True,
            testbed_name="depin-testbed",
            worker_nodes=topo.worker_nodes,
            dist_nodes=topo.dist_nodes,
            vclient_nodes=topo.vclient_nodes,
            coordinator_nodes=topo.coordinator_nodes,
            node_registry_contract_id=None,
        )

        if not is_deployed(topo.provider):
            print("Provisioning infrastructure from topology spec...")
            _terraform_apply_with_topology(topo, env)
            infra_provisioned_here = True

            if topo.build_images:
                print("\nSetting up container registry and building images...")
                _setup_and_push_images(topo, env)
                env = build_env(topo.provider)
                require_runtime_env(env)

            try:
                if topo.deploy_contract:
                    from cli.config import CONTRACT_PACKAGE_PATH
                    contract_args = argparse.Namespace(
                        network=topo.contract_network,
                        package_path=CONTRACT_PACKAGE_PATH,
                        gas_budget=1_000_000_000,
                        gas_coins=[],
                    )
                    cmd_deploy_contract(contract_args)
                    env = build_env(topo.provider)

                outputs = terraform_output(topo.provider, env)
                inventory_path = render_inventory(topo.provider, outputs)
                vars_path = render_ansible_vars(topo.provider, outputs, env)
                ansible_playbook(inventory_path, vars_path, env)
            except Exception as exc:
                print(f"\n[atomic] step failed — purging infrastructure to avoid partial state...")
                try:
                    from cli.infra import cmd_purge
                    cmd_purge(_purge_args)
                except Exception as purge_exc:
                    print(f"[atomic] purge also failed: {purge_exc}")
                raise SystemExit(f"Launch aborted and infrastructure purged. Original error: {exc}")
        else:
            print(f"Infrastructure already deployed for {topo.provider} — skipping provisioning.")
            if getattr(args, "update_contract", False):
                print("\nUpgrading on-chain contract...")
                from cli.config import CONTRACT_PACKAGE_PATH
                update_args = argparse.Namespace(
                    network=topo.contract_network,
                    package_path=CONTRACT_PACKAGE_PATH,
                    gas_budget=1_000_000_000,
                    gas_coins=[],
                    skip_verify_compatibility=False,
                )
                cmd_update_contract(update_args)
                env = build_env(topo.provider)

        deployment = discover(topo.provider)
        print(f"  routes:   {deployment.routes_url}")
        print(f"  livekit:  {deployment.livekit_url}")
        print("\nWaiting for routes service...")
        try:
            wait_for_routes(deployment)
        except Exception as exc:
            if infra_provisioned_here:
                print(f"\n[atomic] routes service unreachable — purging infrastructure...")
                try:
                    from cli.infra import cmd_purge
                    cmd_purge(_purge_args)
                except Exception as purge_exc:
                    print(f"[atomic] purge also failed: {purge_exc}")
            raise SystemExit(f"Routes service did not become ready: {exc}")
        print("  routes service ready\n")

    from cli.scenario.context import ScenarioContext

    report = BenchmarkReport(scenario_name=scenario.name, topology=topo)
    ctx = ScenarioContext(topology=topo, report=report, dry_run=dry_run)
    if deployment:
        ctx.set_deployment(deployment)

    report.started_at = time.time()
    try:
        scenario.run(ctx)
    except KeyboardInterrupt:
        print("\n\nscenario interrupted by user")
    finally:
        ctx.cleanup()
        report.finished_at = time.time()
        print_report(report)
        _write_report(report, getattr(args, "output", None))

    should_teardown = topo.teardown and not no_teardown
    if should_teardown and not dry_run:
        print("\nTearing down infrastructure (topology.teardown=True)...")
        from cli.infra import cmd_purge
        purge_args = argparse.Namespace(
            provider=topo.provider,
            auto_approve=True,
            testbed_name="depin-testbed",
            worker_nodes=topo.worker_nodes,
            dist_nodes=topo.dist_nodes,
            vclient_nodes=topo.vclient_nodes,
            coordinator_nodes=topo.coordinator_nodes,
            node_registry_contract_id=None,
        )
        cmd_purge(purge_args)
