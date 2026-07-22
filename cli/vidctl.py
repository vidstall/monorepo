from __future__ import annotations

import argparse
import re
import sys

from . import contract, doctor, image_bake, infra, object as object_cmd, registry, scenario, wallet
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
    add_wallet_parser(subparsers)
    add_object_parser(subparsers)
    add_scenario_parser(subparsers)
    add_utils_parser(subparsers)
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


def add_scenario_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "scenario",
        help="Declaratively manage a full compute topology from a TOML scenario file.",
    )
    actions = parser.add_subparsers(dest="action", required=True)

    apply_parser = actions.add_parser(
        "apply",
        help="Publish contract+images and reconcile instances to match a scenario file.",
    )
    apply_parser.add_argument("path", help="Path to a scenario TOML file (e.g. scenario/example.toml).")
    apply_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the scenario apply (contract publish, image publish, instance reconcile).",
    )
    apply_parser.set_defaults(handler=lambda args: scenario.apply(args.path, args.yes))

    status_parser = actions.add_parser("status", help="Show the active scenario lock and its instances' current state.")
    status_parser.set_defaults(handler=lambda args: scenario.status(args))

    destroy_parser = actions.add_parser(
        "destroy",
        help="Kill every instance owned by the active scenario and release the lock.",
    )
    destroy_parser.set_defaults(handler=lambda args: scenario.destroy(args))


def add_utils_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("utils", help="Operational utilities (golden-image baking, etc).")
    actions = parser.add_subparsers(dest="action", required=True)

    bake_parser = actions.add_parser(
        "image-bake",
        help="Bake a Docker-preinstalled golden image for one provider+region.",
    )
    bake_parser.add_argument(
        "--provider",
        required=True,
        choices=sorted(image_bake.SUPPORTED_PROVIDERS),
        help="Cloud provider to bake an image for.",
    )
    bake_parser.add_argument(
        "--region",
        required=True,
        help="Provider region/zone to bake into (e.g. us-east-1, eastus, cn-hangzhou, nyc3).",
    )
    bake_parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm provisioning a temporary VM and creating a billable cloud image.",
    )
    bake_parser.set_defaults(handler=lambda args: image_bake.bake(args.provider, args.region, args.yes))

    image_parser = actions.add_parser("image", help="Inspect baked golden images.")
    image_actions = image_parser.add_subparsers(dest="image_action", required=True)
    list_parser = image_actions.add_parser("list", help="List all baked images and their (provider, region).")
    list_parser.set_defaults(handler=lambda _args: image_bake.list_images())


def add_wallet_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("wallet", help="Inspect the operator-wallet pool (read-only; never prints secrets).")
    actions = parser.add_subparsers(dest="action", required=True)

    list_parser = actions.add_parser("list", help="List pooled wallets and free/assigned counts.")
    list_parser.add_argument(
        "--env",
        choices=["devnet", "testnet", "mainnet"],
        default=None,
        help="Restrict to one Sui env. Default: all envs with a pool file.",
    )
    list_parser.set_defaults(handler=lambda args: wallet.list_pool(args.env))

    gc_parser = actions.add_parser(
        "gc",
        help="Release wallets assigned to instances no longer present in the topology.",
    )
    gc_parser.set_defaults(handler=lambda _args: wallet.gc())


def add_object_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("object", help="Publish static sites (e.g. the frontend) to object storage.")
    actions = parser.add_subparsers(dest="action", required=True)

    publish = actions.add_parser("publish", help="Build and upload a static site to object storage.")
    add_object_selection(publish)
    publish.set_defaults(handler=lambda args: object_cmd.publish(args.name, args.object, args.provider))

    delete = actions.add_parser("delete", help="Delete an object-storage site.")
    add_object_selection(delete)
    delete.add_argument("--yes", action="store_true", help="Confirm destructive object-storage deletion.")
    delete.set_defaults(handler=lambda args: object_cmd.delete(args.name, args.object, args.provider, args.yes))


def add_object_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True, help="Topology object name (e.g. bucket identity).")
    parser.add_argument("--object", required=True, choices=sorted(object_cmd.OBJECT_TYPES), help="Object type to publish.")
    parser.add_argument("--provider", required=True, choices=sorted(object_cmd.PROVIDERS), help="Object-storage provider.")


MAX_SERVICE_COUNT = 25

_SERVICE_TOKEN_RE = re.compile(r"^(?P<count>[0-9]*)(?P<service>[a-zA-Z][a-zA-Z0-9-]*)$")


def parse_service_tokens(raw: str) -> list[tuple[str, int]] | None:
    """Parse a comma-separated --service string into an ordered list of
    (service, instance_index) pairs, expanding an optional leading integer
    count prefix per token (e.g. "5cp-daemon" -> 5 instances of cp-daemon,
    indices 1..5; no prefix defaults to a single instance, index 1).

    Returns None (after printing an error to stderr) on any malformed token,
    unknown service, zero count, or a count above MAX_SERVICE_COUNT (a typo
    guard -- e.g. "50cp-daemon" instead of "5cp-daemon,..." would otherwise
    silently provision 50 real cloud instances)."""
    pairs: list[tuple[str, int]] = []
    for token in (t.strip() for t in raw.split(",")):
        if not token:
            continue
        match = _SERVICE_TOKEN_RE.match(token)
        if not match:
            print(f"Malformed --service token: '{token}'", file=sys.stderr)
            return None
        count_str, service = match.group("count"), match.group("service")
        count = int(count_str) if count_str else 1
        if count == 0:
            print(f"Service count must be at least 1: '{token}'", file=sys.stderr)
            return None
        if count > MAX_SERVICE_COUNT:
            print(
                f"Service count {count} in '{token}' exceeds the safety limit of "
                f"{MAX_SERVICE_COUNT} (likely a typo, e.g. '50cp-daemon' instead of "
                "'5cp-daemon,...'). Pass a smaller count if this is intentional.",
                file=sys.stderr,
            )
            return None
        if service not in DOCKER_SERVICES:
            print(f"Unknown service(s): {service}", file=sys.stderr)
            return None
        pairs.extend((service, index) for index in range(1, count + 1))
    return pairs


def run_lifecycle_action(action: str, args: argparse.Namespace) -> int:
    """Expand --service (with optional per-token count prefixes, e.g.
    "5cp-daemon,relay") into an ordered list of (service, instance_index)
    pairs and run `action` once per pair, in order, stopping at the first
    failure. Each pair still goes through the exact same infra.control()
    call a single-service invocation would make -- running
    `--service relay,signaling` (or `2cp-daemon`) is equivalent to (and just
    a shorthand for) separate single-service/single-instance calls sharing
    the same --name, which is what actually colocates them on one instance
    (see program.py's group-by-name merge)."""
    guard_code = scenario.guard_manual_infra(action)
    if guard_code is not None:
        return guard_code
    pairs = parse_service_tokens(args.service)
    if pairs is None:
        return 2
    for service, instance_index in pairs:
        code = infra.control(
            action,
            args.name,
            service,
            args.provider,
            getattr(args, "yes", False),
            getattr(args, "find_instance_type", False),
            getattr(args, "all_region", False),
            getattr(args, "size", None),
            instance_index,
        )
        if code != 0:
            if len(pairs) > 1:
                label = service if instance_index == 1 else f"{service}-{instance_index}"
                print(f"'{action}' failed for service '{label}'; stopping.", file=sys.stderr)
            return code
    return 0


def add_lifecycle_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    for action, help_text in (
        ("start", "Start a topology service through Pulumi."),
        ("pause", "Stop a topology service through Pulumi."),
        ("restart", "Restart a topology service through Pulumi."),
        ("kill", "Delete a topology service through Pulumi."),
    ):
        parser = subparsers.add_parser(action, help=help_text)
        parser.add_argument("--name", required=True, help="Topology instance name to control.")
        parser.add_argument(
            "--service",
            required=True,
            help=(
                "Service type(s) hosted by the instance. Comma-separate to colocate "
                "multiple services on one --name (e.g. relay,signaling). Prefix a token "
                "with an integer to run that many instances of it (e.g. 5cp-daemon,relay "
                "= 5 cp-daemon instances + 1 relay); no prefix defaults to 1. "
                f"Choices: {', '.join(sorted(DOCKER_SERVICES))}."
            ),
        )
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
            parser.add_argument(
                "--size",
                help=(
                    "VM size/SKU override (e.g. s-4vcpu-8gb). Persists on the topology row. "
                    "When colocating multiple services under the same --name, pass a matching "
                    "--size on every call sharing that name."
                ),
            )
        parser.set_defaults(
            handler=lambda args, selected_action=action: run_lifecycle_action(selected_action, args)
        )

