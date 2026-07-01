from __future__ import annotations

import argparse
import importlib.util
import time
from pathlib import Path
from typing import Any

from cli.scenario.models import BenchmarkReport, Scenario, Topology
from cli.scenario.report import _write_report, print_report


def load_scenario(path: Path) -> Scenario:
    spec = importlib.util.spec_from_file_location("scenario_module", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load scenario from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr in ("NAME", "DESCRIPTION", "TOPOLOGY", "run"):
        if not hasattr(module, attr):
            raise SystemExit(f"Scenario {path} missing required attribute: {attr}")

    return Scenario(
        name=module.NAME,
        description=module.DESCRIPTION,
        topology=module.TOPOLOGY,
        run=module.run,
    )


def _terraform_apply_with_topology(topo: Topology, env: Any) -> None:
    from cli.infra.terraform import provider_terraform_root, terraform_init
    from cli.process import run_command

    root = provider_terraform_root(topo.provider)
    terraform_init(topo.provider, env)

    vars = [
        "-input=false",
        "-var=testbed_name=depin-testbed",
        f"-var=media_count={topo.media_nodes}",
        f"-var=routes_count={topo.routes_nodes}",
        f"-var=vclient_count={topo.vclient_nodes}",
        f"-var=coordinator_count={topo.coordinator_nodes}",
    ]
    if topo.provider == "alibaba-cloud":
        vars.append(f"-var=alicloud_region={topo.region}")
        if topo.instance_type:
            vars.append(f"-var=alicloud_instance_type={topo.instance_type}")

    run_command(["terraform", "apply", "-auto-approve", *vars], cwd=root, env=env)


def _apply_registry_overrides(topo: Topology, args: argparse.Namespace) -> None:
    if getattr(args, "skip_build", False):
        topo.registry_init = False
        topo.registry_build = False
        return
    registry_init = getattr(args, "registry_init", None)
    registry_build = getattr(args, "registry_build", None)
    if registry_init is not None:
        topo.registry_init = registry_init
    if registry_build is not None:
        topo.registry_build = registry_build
    if getattr(args, "registry_namespace", None):
        topo.registry_namespace = args.registry_namespace
    if getattr(args, "registry_tag", None):
        topo.registry_tag = args.registry_tag
    if getattr(args, "registry_platform", None):
        topo.registry_platform = args.registry_platform


def _setup_registry(topo: Topology) -> None:
    from cli.registry import cmd_registry_init, cmd_registry_build

    if topo.registry_init:
        init_args = argparse.Namespace(provider=topo.provider, namespace=topo.registry_namespace)
        cmd_registry_init(init_args)

    if topo.registry_build:
        build_args = argparse.Namespace(
            provider=topo.provider,
            tag=topo.registry_tag,
            platform=topo.registry_platform,
        )
        cmd_registry_build(build_args)


def _setup_and_push_images(topo: Topology, env: Any) -> None:
    from cli.registry.build import cmd_build_images

    build_args = argparse.Namespace(
        provider=None,
        registry=None,
        tag="latest",
        push=False,
        platform="linux/amd64",
    )
    cmd_build_images(build_args)


def _print_launch_banner(scenario: Scenario, topo: Topology, dry_run: bool = False) -> None:
    print(f"\n{'='*60}")
    print(f"LAUNCH: {scenario.name}")
    print(f"  {scenario.description}")
    print(f"  provider:    {topo.provider}  ({topo.region})")
    if topo.instance_type:
        print(f"  instance:    {topo.instance_type}")
    vc_nodes_str = f" / {topo.vclient_nodes} vclient" if topo.vclient_nodes else ""
    print(f"  nodes:       {topo.media_nodes} media / {topo.routes_nodes} routes{vc_nodes_str} / {topo.coordinator_nodes} coordinators")
    print(f"  network:     {topo.contract_network}")
    print(f"  contract:    {'deploy+init' if topo.deploy_contract else 'use existing'}")
    print(f"  registry:    init={topo.registry_init} build={topo.registry_build} tag={topo.registry_tag}")
    print(f"  teardown:    {topo.teardown}")
    if topo.benchmark_targets:
        targets = "  ".join(f"{k}<{v}ms" for k, v in topo.benchmark_targets.items())
        print(f"  targets:     {targets}")
    if dry_run:
        print("  mode:        DRY RUN")
    print(f"{'='*60}\n")


def cmd_run_scenario(args: argparse.Namespace) -> None:
    from cli.scenario.context import ScenarioContext

    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        raise SystemExit(f"Scenario file not found: {scenario_path}")

    scenario = load_scenario(scenario_path)
    dry_run = getattr(args, "dry_run", False)
    provider = getattr(args, "provider", "alibaba-cloud")
    teardown = getattr(args, "teardown", False)

    topology = scenario.topology
    if getattr(args, "media_nodes", None) is not None:
        topology.media_nodes = args.media_nodes
    if getattr(args, "routes_nodes", None) is not None:
        topology.routes_nodes = args.routes_nodes
    if getattr(args, "coordinator_nodes", None) is not None:
        topology.coordinator_nodes = args.coordinator_nodes
    topology.provider = provider
    topology.contract_network = getattr(args, "contract_network", "devnet")

    print(f"scenario: {scenario.name}")
    print(f"  {scenario.description}")
    print(f"  topology: {topology.media_nodes} media, {topology.routes_nodes} routes, {topology.coordinator_nodes} coordinators")
    print(f"  network: {topology.contract_network}")
    print(f"  provider: {topology.provider}")
    if dry_run:
        print("  mode: DRY RUN")

    deployment = None
    if not dry_run:
        from cli.infra.discovery import is_deployed, discover, wait_for_routes

        if not is_deployed(provider):
            print("\nInfrastructure not deployed. Running deploy...")
            from cli.infra import cmd_deploy

            deploy_args = argparse.Namespace(
                provider=provider,
                deploy_contract=getattr(args, "deploy_contract", False),
                contract_network=topology.contract_network,
                testbed_name=getattr(args, "testbed_name", "depin-testbed"),
                node_registry_contract_id=getattr(args, "node_registry_contract_id", None),
                media_nodes=topology.media_nodes,
                routes_nodes=topology.routes_nodes,
                vclient_nodes=topology.vclient_nodes,
                coordinator_nodes=topology.coordinator_nodes,
            )
            try:
                cmd_deploy(deploy_args)
            except Exception as e:
                raise SystemExit(f"Deploy failed: {e}")

        deployment = discover(provider)
        print(f"  routes: {deployment.routes_url}")
        print(f"  livekit: {deployment.livekit_url}")

        print("\nWaiting for routes service...")
        wait_for_routes(deployment)
        print("  routes service ready")

    report = BenchmarkReport(scenario_name=scenario.name, topology=topology)
    ctx = ScenarioContext(topology=topology, report=report, dry_run=dry_run)
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

    if teardown and not dry_run:
        print("\nTearing down infrastructure...")
        from cli.infra import cmd_purge

        destroy_args = argparse.Namespace(
            provider=provider,
            testbed_name=getattr(args, "testbed_name", "depin-testbed"),
            node_registry_contract_id=getattr(args, "node_registry_contract_id", None),
            media_nodes=topology.media_nodes,
            routes_nodes=topology.routes_nodes,
            vclient_nodes=topology.vclient_nodes,
            coordinator_nodes=topology.coordinator_nodes,
            auto_approve=True,
        )
        cmd_purge(destroy_args)
