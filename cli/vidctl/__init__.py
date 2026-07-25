from __future__ import annotations

import argparse

from .. import doctor
from ..context import bootstrap
from .contract_cmd import add_contract_parser
from .infra_cmd import add_infra_parser
from .misc_cmd import add_gui_parser, add_object_parser, add_registry_parser
from .scenario_cmd import add_scenario_parser
from .utils_cmd import add_utils_parser
from .wallet_cmd import add_wallet_parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    return args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vidctl", description="Manage Xaisen infrastructure, contract, and registry workflows.")
    subparsers = parser.add_subparsers(dest="command")

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Install local IaC control dependencies.")
    bootstrap_parser.set_defaults(handler=lambda _args: bootstrap())

    doctor_parser = subparsers.add_parser("doctor", help="Check local tools, credentials, and control-plane readiness.")
    doctor_parser.set_defaults(handler=lambda _args: doctor.run())

    add_contract_parser(subparsers)
    add_registry_parser(subparsers)
    add_infra_parser(subparsers)
    add_wallet_parser(subparsers)
    add_object_parser(subparsers)
    add_scenario_parser(subparsers)
    add_utils_parser(subparsers)
    add_gui_parser(subparsers)
    return parser
