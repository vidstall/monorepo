from __future__ import annotations

import argparse

from . import contract, doctor, infra, registry
from .context import DOCKER_SERVICES, bootstrap


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
    return parser


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
    publish.set_defaults(
        handler=lambda args: contract.publish(
            args.env,
            args.dry_run,
            args.yes,
            args.gas_budget,
            args.create_registry_if_missing,
        )
    )


def add_contract_env(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--env",
        choices=["devnet", "testnet", "mainnet"],
        default="devnet",
        help="Sui Move build environment. Default: devnet.",
    )


def add_registry_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("registry", help="Manage Docker images and registry publishing.")
    actions = parser.add_subparsers(dest="action", required=True)

    login = actions.add_parser("login", help="Log in to a Docker registry provider.")
    add_registry_provider(login)
    login.set_defaults(handler=lambda args: registry.login(args.provider))

    for action, help_text, handler in (
        ("build", "Build Docker image(s).", registry.build),
        ("push", "Push Docker image(s).", registry.push),
    ):
        item = actions.add_parser(action, help=help_text)
        add_registry_selection(item)
        item.set_defaults(handler=lambda args, selected_handler=handler: selected_handler(args.service, args.all, args.tag))

    publish = actions.add_parser("publish", help="Build and push Docker image(s).")
    add_registry_selection(publish)
    publish.set_defaults(handler=lambda args: registry.publish(args.service, args.all, args.tag))


def add_registry_selection(parser: argparse.ArgumentParser) -> None:
    service_group = parser.add_mutually_exclusive_group(required=True)
    service_group.add_argument("--service", choices=sorted(DOCKER_SERVICES), help="Service image to manage.")
    service_group.add_argument("--all", action="store_true", help="Manage every service image.")
    parser.add_argument("--tag", help="Image tag. Default: current git short SHA, or dev outside git history.")


def add_registry_provider(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        default=registry.DEFAULT_PROVIDER,
        help="Registry provider env-file basename under secrets/registry. Default: alibaba.",
    )


def add_infra_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("infra", help="Manage Pulumi infrastructure, topology, and Ansible host configuration.")
    actions = parser.add_subparsers(dest="action", required=True)

    init = actions.add_parser("init", help="Create or update runtime topology and ensure the Pulumi stack exists.")
    add_contract_env(init)
    init.set_defaults(handler=lambda args: infra.init(args.env))

    preview = actions.add_parser("preview", help="Preview infrastructure changes.")
    preview.set_defaults(handler=lambda _args: infra.preview())

    apply_parser = actions.add_parser("apply", help="Apply infrastructure changes and regenerate inventory.")
    apply_parser.add_argument("--yes", action="store_true", help="Confirm infrastructure changes.")
    apply_parser.set_defaults(handler=lambda args: infra.apply(args.yes))

    inventory = actions.add_parser("inventory", help="Generate Ansible inventory from Pulumi outputs.")
    inventory.set_defaults(handler=lambda _args: infra.inventory())

    ping = actions.add_parser("ping", help="Run the Ansible connectivity playbook.")
    ping.set_defaults(handler=lambda _args: infra.ping())

    configure = actions.add_parser("configure", help="Run the Ansible site configuration playbook.")
    configure.set_defaults(handler=lambda _args: infra.configure())

    deploy = actions.add_parser("deploy", help="Apply infrastructure and configure hosts.")
    deploy.add_argument("--yes", action="store_true", help="Confirm infrastructure deployment.")
    deploy.set_defaults(handler=lambda args: infra.deploy(args.yes))

    add_lifecycle_parsers(actions)


def add_lifecycle_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    for action, help_text in (
        ("start", "Start a topology service through Pulumi."),
        ("pause", "Stop a topology service through Pulumi."),
        ("restart", "Restart a topology service through Pulumi."),
        ("kill", "Delete a topology service through Pulumi."),
    ):
        parser = subparsers.add_parser(action, help=help_text)
        parser.add_argument("--name", required=True, help="Topology instance name to control.")
        parser.add_argument("--service", required=True, choices=sorted(DOCKER_SERVICES), help="Service type hosted by the instance.")
        parser.add_argument("--provider", required=True, choices=sorted(infra.PROVIDERS), help="Cloud provider for the topology instance.")
        if action == "kill":
            parser.add_argument("--yes", action="store_true", help="Confirm destructive instance deletion.")
        if action in {"start", "restart"}:
            parser.add_argument(
                "--find-instance-type",
                action="store_true",
                help="Force a fresh Alibaba spot instance-type/region search instead of reusing the pinned one for this service.",
            )
            parser.add_argument(
                "--all-region",
                action="store_true",
                help="Scan every Alibaba region for spot capacity instead of only the default region.",
            )
        parser.set_defaults(
            handler=lambda args, selected_action=action: infra.control(
                selected_action,
                args.name,
                args.service,
                args.provider,
                getattr(args, "yes", False),
                getattr(args, "find_instance_type", False),
                getattr(args, "all_region", False),
            )
        )
