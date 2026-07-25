from __future__ import annotations

import sys

from ..context import PULUMI_DIR
from .history import record_history
from .topology import active_stack, ensure_topology
from .validation import validate_network


def init(env_name: str | None = None) -> int:
    # Deferred self-import: command_env/select_or_create_stack/
    # RUNTIME_TOPOLOGY_TOML are patched by tests as flat cli.infra
    # attributes -- looking them up through the package at call time is
    # what makes those patches take effect here.
    from .. import infra

    stack = validate_network(env_name or infra.command_env().get("PULUMI_STACK", "dev"))
    topology = ensure_topology(stack)
    code = infra.select_or_create_stack(stack)
    record_history(
        command="infra init",
        env=stack,
        result="success" if code == 0 else "failure",
        exit_code=code,
    )
    if code == 0:
        print(f"Initialized topology {infra.RUNTIME_TOPOLOGY_TOML} for {topology['active_env']}")
    return code


def preview() -> int:
    from .. import infra

    stack = active_stack()
    code = infra.run(["pulumi", "preview", "--stack", stack], cwd=PULUMI_DIR)
    record_history("infra preview", env=stack, result_for_code=code)
    return code


def apply(yes: bool) -> int:
    from .. import infra

    stack = active_stack()
    if not yes:
        code = 2
        message = "Refusing to apply infrastructure without --yes."
        print(message, file=sys.stderr)
        record_history("infra apply", env=stack, result_for_code=code, error=message)
        return code

    code = infra.pulumi_up(stack)
    if code == 0:
        code = infra.inventory()
    record_history("infra apply", env=stack, result_for_code=code)
    return code


def deploy(yes: bool) -> int:
    from .. import infra

    if not yes:
        message = "Refusing to deploy infrastructure without --yes."
        print(message, file=sys.stderr)
        record_history("infra deploy", env=active_stack(), result_for_code=2, error=message)
        return 2
    code = infra.apply(yes=True)
    if code == 0:
        code = infra.configure()
    record_history("infra deploy", env=active_stack(), result_for_code=code)
    return code
