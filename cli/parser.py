from __future__ import annotations

import argparse
from pathlib import Path

from cli.config import CONTRACT_NETWORK_CHOICES, CONTRACT_PACKAGE_PATH, PROVIDER_CHOICES
from cli.contract import cmd_deploy_contract, cmd_init_contract, cmd_update_contract
from cli.infra import cmd_deploy, cmd_destroy, cmd_inventory
from cli.scenario import cmd_run_scenario


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
    deploy.add_argument("--deploy-contract", action="store_true", default=False,
                        help="Publish and initialize the Sui contract before running Ansible")
    deploy.add_argument("--contract-network", default="testnet", choices=CONTRACT_NETWORK_CHOICES,
                        help="Sui network for contract deployment (default: testnet)")
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

    update_contract = subparsers.add_parser(
        "update-contract",
        help="Upgrade an existing Sui contract package using the stored UpgradeCap",
    )
    update_contract.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    update_contract.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
    update_contract.add_argument("--gas-budget", type=int, default=1_000_000_000)
    update_contract.add_argument(
        "--gas-coin",
        dest="gas_coins",
        action="append",
        default=[],
        help="Explicit gas coin object ID to use for upgrade; repeatable.",
    )
    update_contract.add_argument(
        "--skip-verify-compatibility",
        action="store_true",
        help="Pass through to Sui CLI; only use when you intentionally bypass upgrade compatibility checks.",
    )
    update_contract.set_defaults(func=cmd_update_contract)

    init_contract = subparsers.add_parser(
        "init-contract",
        help="Create the shared SUI registry object for a published contract",
    )
    init_contract.add_argument("--network", required=True, choices=CONTRACT_NETWORK_CHOICES)
    init_contract.add_argument("--package-path", type=Path, default=CONTRACT_PACKAGE_PATH)
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

    run_scenario = subparsers.add_parser("run-scenario", help="Execute a scenario script")
    run_scenario.add_argument("scenario", help="Path to scenario Python script")
    run_scenario.add_argument("--provider", default="alibaba-cloud", choices=PROVIDER_CHOICES)
    run_scenario.add_argument("--deploy-contract", action="store_true", default=False,
                              help="Publish and initialize the Sui contract if deploying")
    run_scenario.add_argument("--contract-network", default="testnet", choices=CONTRACT_NETWORK_CHOICES)
    run_scenario.add_argument("--teardown", action="store_true", default=False,
                              help="Destroy infrastructure after scenario completes")
    run_scenario.add_argument("--dry-run", action="store_true", default=False,
                              help="Print steps without executing Sui transactions or API calls")
    run_scenario.add_argument("--output", help="Path to write JSON benchmark report")
    add_infra_shape(run_scenario)
    run_scenario.set_defaults(func=cmd_run_scenario)

    return parser.parse_args()
