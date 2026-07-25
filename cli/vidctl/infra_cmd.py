from __future__ import annotations

import argparse

from .. import infra, scenario
from .contract_cmd import add_contract_env
from .lifecycle_cmd import add_lifecycle_parsers


def _infra_init(args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("init")
    if guard_code is not None:
        return guard_code
    return infra.init(args.env)


def _infra_preview(_args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("preview")
    if guard_code is not None:
        return guard_code
    return infra.preview()


def _infra_apply(args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("apply")
    if guard_code is not None:
        return guard_code
    return infra.apply(args.yes)


def _infra_inventory(_args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("inventory")
    if guard_code is not None:
        return guard_code
    return infra.inventory()


def _infra_ping(_args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("ping")
    if guard_code is not None:
        return guard_code
    return infra.ping()


def _infra_configure(_args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("configure")
    if guard_code is not None:
        return guard_code
    return infra.configure()


def _infra_deploy(args: argparse.Namespace) -> int:
    guard_code = scenario.guard_manual_infra("deploy")
    if guard_code is not None:
        return guard_code
    return infra.deploy(args.yes)


def add_infra_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("infra", help="Manage Pulumi infrastructure, topology, and Ansible host configuration.")
    actions = parser.add_subparsers(dest="action", required=True)

    init = actions.add_parser("init", help="Create or update runtime topology and ensure the Pulumi stack exists.")
    add_contract_env(init)
    init.set_defaults(handler=_infra_init)

    preview = actions.add_parser("preview", help="Preview infrastructure changes.")
    preview.set_defaults(handler=_infra_preview)

    apply_parser = actions.add_parser("apply", help="Apply infrastructure changes and regenerate inventory.")
    apply_parser.add_argument("--yes", action="store_true", help="Confirm infrastructure changes.")
    apply_parser.set_defaults(handler=_infra_apply)

    inventory = actions.add_parser("inventory", help="Generate Ansible inventory from Pulumi outputs.")
    inventory.set_defaults(handler=_infra_inventory)

    ping = actions.add_parser("ping", help="Run the Ansible connectivity playbook.")
    ping.set_defaults(handler=_infra_ping)

    configure = actions.add_parser("configure", help="Run the Ansible site configuration playbook.")
    configure.set_defaults(handler=_infra_configure)

    deploy = actions.add_parser("deploy", help="Apply infrastructure and configure hosts.")
    deploy.add_argument("--yes", action="store_true", help="Confirm infrastructure deployment.")
    deploy.set_defaults(handler=_infra_deploy)

    add_lifecycle_parsers(actions)
