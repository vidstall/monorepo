from __future__ import annotations

import argparse
from pathlib import Path

from cli.config import CONTRACT_NETWORK_CHOICES, CONTRACT_PACKAGE_PATH, PROVIDER_CHOICES
from cli.contract import cmd_deploy_contract, cmd_init_contract, cmd_update_contract
from cli.infra import (
    cmd_deploy,
    cmd_inventory,
    cmd_purge,
    cmd_registry_build,
    cmd_registry_init,
    cmd_registry_list,
    cmd_registry_purge,
)
from cli.scenario import cmd_launch
from cli.status import cmd_infra_status, cmd_status


def add_infra_shape(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--testbed-name", default="depin-testbed")
    parser.add_argument("--node-registry-contract-id", default=None)
    parser.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    parser.add_argument("--dist-nodes", dest="dist_nodes", type=int, default=1)
    parser.add_argument("--vclient-nodes", dest="vclient_nodes", type=int, default=0)
    parser.add_argument("--coordinator-nodes", type=int, default=1)


def _add_infra_group(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    infra = subparsers.add_parser("infra", help="Infrastructure lifecycle commands")
    infra.set_defaults(func=cmd_infra_status)
    infra.add_argument(
        "--provider",
        default=None,
        help="Comma-separated providers (default: all), e.g. alibaba-cloud,aws",
    )
    infra_sub = infra.add_subparsers(dest="subcommand")

    status_p = infra_sub.add_parser("status", help="Show deployment status")
    status_p.add_argument("--provider", default=None, help="Comma-separated providers (default: all)")
    status_p.set_defaults(func=cmd_infra_status)

    deploy = infra_sub.add_parser("deploy", help="Apply Terraform, configure Docker with Ansible")
    deploy.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    deploy.add_argument(
        "--deploy-contract",
        action="store_true",
        default=False,
        help="Publish and initialize the Sui contract before running Ansible",
    )
    deploy.add_argument("--contract-network", default="testnet", choices=CONTRACT_NETWORK_CHOICES)
    add_infra_shape(deploy)
    deploy.set_defaults(func=cmd_deploy)

    purge = infra_sub.add_parser("purge", help="Destroy infrastructure and clean all local state")
    purge.add_argument("--provider", required=True, choices=(*PROVIDER_CHOICES, "all"))
    add_infra_shape(purge)
    purge.add_argument("--auto-approve", action="store_true", default=True)
    purge.set_defaults(func=cmd_purge)

    inventory = infra_sub.add_parser("inventory", help="Render Ansible inventory from Terraform output")
    inventory.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    add_infra_shape(inventory)
    inventory.set_defaults(func=cmd_inventory)

    registry = infra_sub.add_parser("registry", help="Container registry lifecycle commands")
    registry_sub = registry.add_subparsers(dest="registry_command")
    registry_sub.required = True

    registry_init = registry_sub.add_parser("init", help="Create or update the provider container registry")
    registry_init.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    registry_init.add_argument("--namespace", default="xaisen")
    registry_init.set_defaults(func=cmd_registry_init)

    registry_build = registry_sub.add_parser("build", help="Build images and push them to the provider registry")
    registry_build.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    registry_build.add_argument("--tag", default="latest")
    registry_build.add_argument("--platform", default="linux/amd64")
    registry_build.set_defaults(func=cmd_registry_build)

    registry_purge = registry_sub.add_parser("purge", help="Destroy only the provider container registry")
    registry_purge.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    registry_purge.set_defaults(func=cmd_registry_purge)

    registry_list = registry_sub.add_parser("list", help="Show provider registry configuration")
    registry_list.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    registry_list.set_defaults(func=cmd_registry_list)


def _add_contract_group(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    contract = subparsers.add_parser("contract", help="Sui smart contract lifecycle commands")
    contract_sub = contract.add_subparsers(dest="subcommand")
    contract_sub.required = True

    deploy = contract_sub.add_parser("deploy", help="Publish the Move package to the Sui network")
    deploy.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    deploy.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    deploy.add_argument("--gas-budget", type=int, default=500_000_000)
    deploy.add_argument("--gas-coin", dest="gas_coins", action="append", default=[], help="Explicit gas coin object ID; repeatable.")
    deploy.set_defaults(func=cmd_deploy_contract)

    init = contract_sub.add_parser("init", help="Initialize registry object for a published package")
    init.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    init.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    init.add_argument("--gas-budget", type=int, default=100_000_000)
    init.add_argument("--gas-coin", dest="gas_coins", action="append", default=[], help="Explicit gas coin object ID; repeatable.")
    init.set_defaults(func=cmd_init_contract)

    update = contract_sub.add_parser("update", help="Upgrade an existing published package")
    update.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    update.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    update.add_argument("--gas-budget", type=int, default=1_000_000_000)
    update.add_argument("--gas-coin", dest="gas_coins", action="append", default=[], help="Explicit gas coin object ID; repeatable.")
    update.add_argument("--skip-verify-compatibility", action="store_true")
    update.set_defaults(func=cmd_update_contract)


def _add_launch_command(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    launch = subparsers.add_parser("launch", help="Run a scenario: provision infra, deploy contract, benchmark, teardown")
    launch.add_argument("scenario", nargs="?", help="Path to scenario .py file (omit to list available scenarios)")
    launch.add_argument("--dry-run", action="store_true", default=False, help="Print steps without executing real infra or contract calls")
    launch.add_argument("--no-teardown", action="store_true", default=False, help="Keep infrastructure running after scenario completes")
    launch.add_argument("--output", help="Write benchmark report JSON to this path")
    launch.add_argument("--list", action="store_true", default=False, help="List available scenarios")
    launch.add_argument("--skip-build", action="store_true", default=False, help="Skip docker image build and push (sets --no-registry-init --no-registry-build)")
    launch.add_argument("--update-contract", action="store_true", default=False, help="Upgrade the on-chain contract before running the scenario (useful when infra is already deployed)")
    launch.add_argument("--registry-init", action=argparse.BooleanOptionalAction, default=None, help="Override scenario registry initialization")
    launch.add_argument("--registry-build", action=argparse.BooleanOptionalAction, default=None, help="Override scenario registry image build/push")
    launch.add_argument("--registry-namespace", help="Override scenario registry namespace")
    launch.add_argument("--registry-tag", help="Override scenario registry image tag")
    launch.add_argument("--registry-platform", help="Override scenario registry build platform")
    launch.set_defaults(func=cmd_launch)


def _add_observe_group(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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
        ("logs", "Tail logs from deployed nodes (requires active deployment)"),
        ("metrics", "Fetch node metrics (requires active deployment)"),
        ("health", "Ping all infrastructure layers"),
    ]:
        p = observe_sub.add_parser(name, help=help_text)
        p.set_defaults(func=cmd_observe_stub, subcommand=name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vidctl.py", description="vidctl")
    parser.set_defaults(func=cmd_status)
    subparsers = parser.add_subparsers(dest="group")

    status_p = subparsers.add_parser("status", help="Show current deployment and contract status")
    status_p.set_defaults(func=cmd_status)

    _add_infra_group(subparsers)
    _add_contract_group(subparsers)
    _add_launch_command(subparsers)
    _add_observe_group(subparsers)

    return parser.parse_args()
