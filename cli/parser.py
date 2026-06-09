from __future__ import annotations

import argparse
from pathlib import Path

from cli.config import CONTRACT_NETWORK_CHOICES, CONTRACT_PACKAGE_PATH, PROVIDER_CHOICES
from cli.contract import cmd_deploy_contract, cmd_init_contract
from cli.infra import cmd_deploy, cmd_destroy, cmd_inventory


def add_infra_shape(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--testbed-name", default="depin-testbed")
    parser.add_argument("--node-registry-contract-id", default=None)
    parser.add_argument("--worker-nodes", "--livekit-nodes", dest="worker_nodes", type=int, default=1)
    parser.add_argument("--client-nodes", "--meet-nodes", dest="client_nodes", type=int, default=1)
    parser.add_argument("--coordinator-nodes", type=int, default=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vidctl.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy = subparsers.add_parser("deploy", help="Apply Terraform, configure Docker with Ansible")
    deploy.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    add_infra_shape(deploy)
    deploy.set_defaults(func=cmd_deploy)

    deploy_contract = subparsers.add_parser(
        "deploy-contract",
        help="Switch a Sui environment, build the Move package, and publish the contract",
    )
    deploy_contract.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    deploy_contract.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    deploy_contract.set_defaults(func=cmd_deploy_contract)
    deploy_contract.add_argument("--gas-budget", type=int, default=1_000_000_000)
    deploy_contract.add_argument(
        "--gas-coin",
        dest="gas_coins",
        action="append",
        default=[],
        help="Explicit gas coin object ID to use for publish; repeatable.",
    )

    init_contract = subparsers.add_parser(
        "init-contract",
        help="Create the shared SUI registry object for a published contract",
    )
    init_contract.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    init_contract.add_argument("--gas-budget", type=int, default=100_000_000)
    init_contract.add_argument(
        "--gas-coin",
        dest="gas_coins",
        action="append",
        default=[],
        help="Explicit gas coin object ID to use for registry initialization; repeatable.",
    )
    init_contract.set_defaults(func=cmd_init_contract)

    destroy = subparsers.add_parser("destroy", help="Tear down Terraform-managed infrastructure")
    destroy.add_argument(
        "--provider",
        required=True,
        choices=(*PROVIDER_CHOICES, "all"),
        help="Destroy one provider or every provider.",
    )
    add_infra_shape(destroy)
    destroy.add_argument("--auto-approve", action="store_true", default=True)
    destroy.set_defaults(func=cmd_destroy)

    inventory = subparsers.add_parser("inventory", help="Render Ansible inventory from Terraform output")
    inventory.add_argument("--provider", required=True, choices=PROVIDER_CHOICES)
    add_infra_shape(inventory)
    inventory.set_defaults(func=cmd_inventory)

    return parser.parse_args()
