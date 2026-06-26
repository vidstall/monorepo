from __future__ import annotations

import argparse
from pathlib import Path

from cli.config import CONTRACT_NETWORK_CHOICES, CONTRACT_PACKAGE_PATH, PROVIDER_CHOICES
from cli.contract import cmd_deploy_contract, cmd_init_contract, cmd_update_contract
from cli.infra import cmd_build_images, cmd_deploy, cmd_inventory, cmd_purge, cmd_setup_registry
from cli.scenario import cmd_run_scenario
from cli.status import cmd_infra_status, cmd_status


def add_infra_shape(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--testbed-name", default="depin-testbed")
    parser.add_argument("--node-registry-contract-id", default=None)
    parser.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    parser.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    parser.add_argument("--coordinator-nodes", type=int, default=1)


def _add_infra_group(subparsers: argparse._SubParsersAction) -> None:
    infra = subparsers.add_parser("infra", help="Infrastructure lifecycle commands")
    infra.set_defaults(func=cmd_infra_status)
    infra.add_argument(
        "--provider",
        default=None,
        help="Comma-separated providers to show (default: all). e.g. alibaba-cloud,aws",
    )
    infra_sub = infra.add_subparsers(dest="subcommand")

    status_p = infra_sub.add_parser("status", help="Show deployment status (default when no subcommand given)")
    status_p.add_argument("--provider", default=None,
                          help="Comma-separated providers (default: all). e.g. alibaba-cloud,aws")
    status_p.set_defaults(func=cmd_infra_status)

    deploy = infra_sub.add_parser("deploy", help="Apply Terraform, configure Docker with Ansible")
    deploy.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    deploy.add_argument("--deploy-contract", action="store_true", default=False,
                        help="Publish and initialize the Sui contract before running Ansible")
    deploy.add_argument("--contract-network", default="testnet", choices=CONTRACT_NETWORK_CHOICES)
    add_infra_shape(deploy)
    deploy.set_defaults(func=cmd_deploy)

    purge = infra_sub.add_parser("purge", help="Destroy infrastructure and clean all local state")
    purge.add_argument("--provider", required=True, choices=(*PROVIDER_CHOICES, "all"),
                       help="Purge one provider or every provider.")
    add_infra_shape(purge)
    purge.add_argument("--auto-approve", action="store_true", default=True)
    purge.set_defaults(func=cmd_purge)

    inventory = infra_sub.add_parser("inventory", help="Render Ansible inventory from Terraform output")
    inventory.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    add_infra_shape(inventory)
    inventory.set_defaults(func=cmd_inventory)

    build = infra_sub.add_parser("build", help="Build Docker images locally and optionally push to a registry")
    registry_group = build.add_mutually_exclusive_group(required=True)
    registry_group.add_argument("--registry",
                                help="Explicit Docker registry prefix (e.g. docker.io/myuser, ghcr.io/org)")
    registry_group.add_argument("--provider", choices=PROVIDER_CHOICES,
                                help="Cloud provider — reads registry URL from its secrets file")
    build.add_argument("--tag", default="latest")
    build.add_argument("--platform", default="linux/amd64")
    build.add_argument("--push", action="store_true", default=False)
    build.set_defaults(func=cmd_build_images)

    registry = infra_sub.add_parser("registry", help="Create a container registry for the given provider")
    registry.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    registry.add_argument("--namespace", default="xaisen")
    registry.set_defaults(func=cmd_setup_registry)


def _add_contract_group(subparsers: argparse._SubParsersAction) -> None:
    contract = subparsers.add_parser("contract", help="Sui smart contract lifecycle commands")
    contract_sub = contract.add_subparsers(dest="subcommand")
    contract_sub.required = True

    deploy = contract_sub.add_parser("deploy", help="Publish the Move package to the Sui network")
    deploy.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    deploy.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    deploy.add_argument("--gas-budget", type=int, default=1_000_000_000)
    deploy.add_argument("--gas-coin", dest="gas_coins", action="append", default=[],
                        help="Explicit gas coin object ID; repeatable.")
    deploy.set_defaults(func=cmd_deploy_contract)

    init = contract_sub.add_parser("init", help="Create the shared registry object after publishing")
    init.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    init.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    init.add_argument("--gas-budget", type=int, default=100_000_000)
    init.add_argument("--gas-coin", dest="gas_coins", action="append", default=[],
                      help="Explicit gas coin object ID; repeatable.")
    init.set_defaults(func=cmd_init_contract)

    update = contract_sub.add_parser("update", help="Upgrade an existing contract package")
    update.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    update.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    update.add_argument("--gas-budget", type=int, default=1_000_000_000)
    update.add_argument("--gas-coin", dest="gas_coins", action="append", default=[],
                        help="Explicit gas coin object ID; repeatable.")
    update.add_argument("--skip-verify-compatibility", action="store_true")
    update.set_defaults(func=cmd_update_contract)


def _add_testbed_group(subparsers: argparse._SubParsersAction) -> None:
    from cli.testbed import cmd_testbed_clean, cmd_testbed_list, cmd_testbed_results

    testbed = subparsers.add_parser("testbed", help="Run and manage E2E test scenarios")
    testbed_sub = testbed.add_subparsers(dest="subcommand")
    testbed_sub.required = True

    run = testbed_sub.add_parser("run", help="Execute a scenario script")
    run.add_argument("scenario", help="Path to scenario Python script")
    run.add_argument("--provider", default="alibaba-cloud", choices=PROVIDER_CHOICES)
    run.add_argument("--deploy-contract", action="store_true", default=False)
    run.add_argument("--contract-network", default="testnet", choices=CONTRACT_NETWORK_CHOICES)
    run.add_argument("--teardown", action="store_true", default=False)
    run.add_argument("--dry-run", action="store_true", default=False)
    run.add_argument("--output", help="Path to write JSON benchmark report")
    add_infra_shape(run)
    run.set_defaults(func=cmd_run_scenario)

    list_cmd = testbed_sub.add_parser("list", help="List available scenario scripts")
    list_cmd.set_defaults(func=cmd_testbed_list)

    clean = testbed_sub.add_parser("clean", help="Delete benchmark artifacts")
    clean.set_defaults(func=cmd_testbed_clean)

    results = testbed_sub.add_parser("results", help="Show the most recent benchmark report")
    results.set_defaults(func=cmd_testbed_results)


def _add_observe_group(subparsers: argparse._SubParsersAction) -> None:
    from cli.observe import cmd_observe_rooms, cmd_observe_stub, cmd_observe_workers

    observe = subparsers.add_parser("observe", help="Inspect live on-chain and node state")
    observe_sub = observe.add_subparsers(dest="subcommand")
    observe_sub.required = True

    workers = observe_sub.add_parser("workers", help="List registered workers from on-chain registry")
    workers.add_argument("--network", default="testnet", choices=CONTRACT_NETWORK_CHOICES)
    workers.set_defaults(func=cmd_observe_workers)

    rooms = observe_sub.add_parser("rooms", help="Show active room rentals from on-chain registry")
    rooms.add_argument("--network", default="testnet", choices=CONTRACT_NETWORK_CHOICES)
    rooms.set_defaults(func=cmd_observe_rooms)

    for name, help_text in [
        ("logs",    "Tail logs from deployed nodes (requires active deployment)"),
        ("metrics", "Show node metrics (requires active deployment)"),
        ("health",  "Ping all infrastructure layers"),
    ]:
        p = observe_sub.add_parser(name, help=help_text)
        p.set_defaults(func=cmd_observe_stub, subcommand=name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vidctl.py",
        description="vidctl — xaisen testbed CLI. Run with no args to see current status.",
    )
    parser.set_defaults(func=cmd_status)

    subparsers = parser.add_subparsers(dest="group")

    status_p = subparsers.add_parser("status", help="Show current deployment and contract status")
    status_p.set_defaults(func=cmd_status)

    _add_infra_group(subparsers)
    _add_contract_group(subparsers)
    _add_testbed_group(subparsers)
    _add_observe_group(subparsers)

    return parser.parse_args()
