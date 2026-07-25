from __future__ import annotations

import argparse

from .. import contract


def add_contract_env(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env",
        choices=["devnet", "testnet", "mainnet"],
        default="devnet",
        help="Sui Move build environment. Default: devnet.",
    )


def add_contract_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("contract", help="Manage the Sui smart contract.")
    actions = parser.add_subparsers(dest="action", required=True)

    build = actions.add_parser("build", help="Build the Sui Move package.")
    add_contract_env(build)
    build.set_defaults(handler=lambda args: contract.build(args.env))

    test = actions.add_parser("test", help="Run Sui Move tests.")
    add_contract_env(test)
    test.set_defaults(handler=lambda args: contract.test(args.env))

    check = actions.add_parser("check", help="Build and test the Sui Move package.")
    add_contract_env(check)
    check.set_defaults(handler=lambda args: contract.check(args.env))

    publish = actions.add_parser("publish", help="Publish or dry-run publish the Sui package.")
    add_contract_env(publish)
    publish.add_argument("--dry-run", action="store_true", help="Build a publish transaction without executing it.")
    publish.add_argument("--yes", action="store_true", help="Allow an on-chain publish transaction.")
    publish.add_argument("--gas-budget", help="Gas budget in MIST.")
    publish.add_argument(
        "--create-registry-if-missing",
        action="store_true",
        help="Create a fresh shared registry when upgrading a package with no saved registry object ID.",
    )
    publish.add_argument(
        "--force",
        action="store_true",
        help=(
            "Force a fresh publish (new package + new shared registry), ignoring/clearing any "
            "existing published state for this environment. Existing on-chain worker/stake data is "
            "NOT migrated. Use when local source has diverged from what's deployed on-chain (e.g. a "
            "module was renamed/removed) and a normal upgrade is rejected as incompatible."
        ),
    )
    publish.set_defaults(
        handler=lambda args: contract.publish(
            args.env,
            args.dry_run,
            args.yes,
            args.gas_budget,
            args.create_registry_if_missing,
            args.force,
        )
    )
