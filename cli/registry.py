from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .context import (
    DOCKER_SERVICES,
    REGISTRY_SECRETS_DIR,
    command_env,
    git_short_sha,
    read_env_file,
    run,
)

DEFAULT_PROVIDER = "alibaba"


@dataclass(frozen=True)
class RegistryConfig:
    provider: str
    prefix: str
    username: str | None = None
    password: str | None = None


def registry_prefix() -> str | None:
    value = command_env().get("ALICLOUD_CR_REGISTRY", "").strip().rstrip("/")
    return value or None


def validate_provider(provider: str) -> str:
    value = provider.strip()
    if not value or value != Path(value).name:
        raise ValueError("Registry provider must be a secrets/registry env-file basename.")
    return value


def registry_env_path(provider: str) -> Path:
    return REGISTRY_SECRETS_DIR / f"{validate_provider(provider)}.env"


def provider_config(provider: str = DEFAULT_PROVIDER, *, require_credentials: bool = False) -> RegistryConfig:
    provider = validate_provider(provider)
    path = registry_env_path(provider)
    if path.exists():
        values = read_env_file(path)
        prefix = values.get("REGISTRY_PREFIX", "").strip().rstrip("/")
        username = values.get("REGISTRY_USERNAME", "").strip() or None
        password = values.get("REGISTRY_PASSWORD", "").strip() or None
        if not prefix:
            raise ValueError(f"REGISTRY_PREFIX is missing in {path}.")
        if require_credentials and (not username or not password):
            raise ValueError(f"REGISTRY_USERNAME and REGISTRY_PASSWORD are required in {path}.")
        return RegistryConfig(provider=provider, prefix=prefix, username=username, password=password)

    if provider == DEFAULT_PROVIDER:
        env = command_env()
        prefix = env.get("ALICLOUD_CR_REGISTRY", "").strip().rstrip("/")
        username = env.get("ALICLOUD_CR_USERNAME", "").strip() or None
        password = env.get("ALICLOUD_CR_PASSWORD", "").strip() or None
        if prefix:
            if require_credentials and (not username or not password):
                raise ValueError("ALICLOUD_CR_USERNAME and ALICLOUD_CR_PASSWORD are required.")
            return RegistryConfig(provider=provider, prefix=prefix, username=username, password=password)

    raise ValueError(f"Registry provider config not found: {path}")


def registry_host(prefix: str) -> str:
    return prefix.split("/", 1)[0]


def docker_auth_exists(host: str) -> bool:
    config_path = Path.home() / ".docker" / "config.json"
    if not config_path.exists():
        return False
    try:
        payload = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    auths = payload.get("auths", {})
    if not isinstance(auths, dict):
        return False
    candidates = {host, f"https://{host}", f"http://{host}"}
    if host == "docker.io":
        candidates.add("https://index.docker.io/v1/")
    return any(candidate in auths for candidate in candidates)


def selected_services(service: str | None, all_services: bool) -> list[str]:
    if all_services:
        return list(DOCKER_SERVICES)
    if service:
        return [service]
    raise ValueError("Select a service with --service or all services with --all.")


def image_name(service: str, tag: str, provider: str | None = None) -> str:
    prefix = provider_config(provider).prefix if provider else registry_prefix()
    if not prefix:
        raise ValueError("ALICLOUD_CR_REGISTRY is missing.")
    return f"{prefix}/{service}:{tag}"


def login(provider: str = DEFAULT_PROVIDER) -> int:
    try:
        config = provider_config(provider, require_credentials=True)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return docker_login(config)


def ensure_login(provider: str) -> int:
    try:
        config = provider_config(provider)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if docker_auth_exists(registry_host(config.prefix)):
        return 0
    if not config.username or not config.password:
        print(
            f"REGISTRY_USERNAME and REGISTRY_PASSWORD are required in {registry_env_path(config.provider)}.",
            file=sys.stderr,
        )
        return 1
    return docker_login(config)


def docker_login(config: RegistryConfig) -> int:
    return run(
        ["docker", "login", registry_host(config.prefix), "--username", config.username, "--password-stdin"],
        input_text=f"{config.password}\n",
    )


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


def each_service(
    action: str,
    service: str | None,
    all_services: bool,
    tag: str | None,
    provider: str | None = None,
) -> int:
    try:
        services = selected_services(service, all_services)
        resolved_tag = tag or git_short_sha()
        for name in services:
            context = DOCKER_SERVICES[name]
            image = image_name(name, resolved_tag, provider)
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
