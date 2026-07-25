from __future__ import annotations

import argparse
import re
import sys

from .. import infra, scenario
from ..context import DOCKER_SERVICES

MAX_SERVICE_COUNT = 25

_SERVICE_TOKEN_RE = re.compile(r"^(?P<count>[0-9]*)(?P<service>[a-zA-Z][a-zA-Z0-9-]*)$")


def parse_service_tokens(raw: str) -> list[tuple[str, int]] | None:
    """Parse a comma-separated --service string into an ordered list of
    (service, worker_index) pairs, expanding an optional leading integer
    count prefix per token (e.g. "5cp-daemon" -> 5 workers of cp-daemon,
    indices 1..5; no prefix defaults to a single worker, index 1).

    Returns None (after printing an error to stderr) on any malformed token,
    unknown service, zero count, or a count above MAX_SERVICE_COUNT (a typo
    guard -- e.g. "50cp-daemon" instead of "5cp-daemon,..." would otherwise
    silently provision 50 real cloud workers)."""
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
    "5cp-daemon,relay") into an ordered list of (service, worker_index)
    pairs and run `action` once per pair, in order, stopping at the first
    failure. Each pair still goes through the exact same infra.control()
    call a single-service invocation would make -- running
    `--service relay,signaling` (or `2cp-daemon`) is equivalent to (and just
    a shorthand for) separate single-service/single-worker calls sharing
    the same --host, which is what actually colocates them on one worker
    (see program.py's group-by-host merge)."""
    guard_code = scenario.guard_manual_infra(action)
    if guard_code is not None:
        return guard_code
    pairs = parse_service_tokens(args.service)
    if pairs is None:
        return 2
    for service, worker_index in pairs:
        code = infra.control(
            action,
            args.host,
            service,
            args.provider,
            getattr(args, "yes", False),
            getattr(args, "find_instance_type", False),
            getattr(args, "all_region", False),
            getattr(args, "size", None),
            worker_index,
        )
        if code != 0:
            if len(pairs) > 1:
                label = service if worker_index == 1 else f"{service}-{worker_index}"
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
        parser.add_argument("--host", required=True, help="Topology host name to control.")
        parser.add_argument(
            "--service",
            required=True,
            help=(
                "Service type(s) hosted by the worker. Comma-separate to colocate "
                "multiple services on one --host (e.g. relay,signaling). Prefix a token "
                "with an integer to run that many workers of it (e.g. 5cp-daemon,relay "
                "= 5 cp-daemon workers + 1 relay); no prefix defaults to 1. "
                f"Choices: {', '.join(sorted(DOCKER_SERVICES))}."
            ),
        )
        parser.add_argument("--provider", required=True, choices=sorted(infra.PROVIDERS), help="Cloud provider for the topology worker.")
        if action == "kill":
            parser.add_argument("--yes", action="store_true", help="Confirm destructive worker deletion.")
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
                    "When colocating multiple services under the same --host, pass a matching "
                    "--size on every call sharing that host."
                ),
            )
        parser.set_defaults(
            handler=lambda args, selected_action=action: run_lifecycle_action(selected_action, args)
        )
