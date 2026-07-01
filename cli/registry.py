from __future__ import annotations

import sys
from pathlib import Path

from .context import DOCKER_SERVICES, command_env, git_short_sha, run


def registry_prefix() -> str | None:
    value = command_env().get("ALICLOUD_CR_REGISTRY", "").strip().rstrip("/")
    return value or None


def selected_services(service: str | None, all_services: bool) -> list[str]:
    if all_services:
        return list(DOCKER_SERVICES)
    if service:
        return [service]
    raise ValueError("Select a service with --service or all services with --all.")


def image_name(service: str, tag: str) -> str:
    prefix = registry_prefix()
    if not prefix:
        raise ValueError("ALICLOUD_CR_REGISTRY is missing.")
    return f"{prefix}/{service}:{tag}"


def login() -> int:
    env = command_env()
    registry = registry_prefix()
    username = env.get("ALICLOUD_CR_USERNAME")
    password = env.get("ALICLOUD_CR_PASSWORD")
    if not registry or not username or not password:
        print("Alibaba Container Registry credentials are incomplete.", file=sys.stderr)
        return 1
    host = registry.split("/", 1)[0]
    return run(["docker", "login", host, "--username", username, "--password-stdin"], input_text=f"{password}\n")


def build(service: str | None, all_services: bool, tag: str | None) -> int:
    return each_service("build", service, all_services, tag)


def push(service: str | None, all_services: bool, tag: str | None) -> int:
    return each_service("push", service, all_services, tag)


def publish(service: str | None, all_services: bool, tag: str | None) -> int:
    code = login()
    if code != 0:
        return code
    code = build(service, all_services, tag)
    if code != 0:
        return code
    return push(service, all_services, tag)


def each_service(action: str, service: str | None, all_services: bool, tag: str | None) -> int:
    try:
        services = selected_services(service, all_services)
        resolved_tag = tag or git_short_sha()
        for name in services:
            context = DOCKER_SERVICES[name]
            image = image_name(name, resolved_tag)
            code = run_docker_action(action, image, context)
            if code != 0:
                return code
        return 0
    except KeyError as exc:
        print(f"Unknown service: {exc.args[0]}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def run_docker_action(action: str, image: str, context: Path) -> int:
    if action == "build":
        return run(["docker", "build", "-t", image, context])
    if action == "push":
        return run(["docker", "push", image])
    print(f"Unknown registry action: {action}", file=sys.stderr)
    return 2
