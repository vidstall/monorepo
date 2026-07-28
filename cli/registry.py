from __future__ import annotations

import hashlib
import subprocess
import sys
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .context import (
    ANSIBLE_DIR,
    DOCKER_SERVICES,
    DOCKERFILES,
    REGISTRY_SECRETS_DIR,
    RUNTIME_REGISTRY_TOML,
    command_env,
    git_short_sha,
    read_env_file,
    run,
)

DEPLOYED_TAGS_YAML = ANSIBLE_DIR / "vars" / "deployed_tags.generated.yml"
DEPLOYED_DIGESTS_YAML = ANSIBLE_DIR / "vars" / "deployed_digests.generated.yml"

DEFAULT_PROVIDER = "alibaba"

# The Xaisen fleet (ECS/EC2/Droplet/etc.) is x86_64; build for that explicitly
# so images built on arm64 dev machines (e.g. Apple Silicon) still run on the
# deployed hosts instead of crash-looping with "exec format error".
TARGET_PLATFORM = "linux/amd64"

# Each service's build/push is independent (own Dockerfile, own context, own
# registry path) -- run them concurrently instead of one-at-a-time. Capped
# rather than unbounded so a full `--all` build doesn't try to run every
# service's docker build simultaneously and thrash a laptop's CPU/disk.
MAX_PARALLEL_DOCKER_JOBS = 4

_deployed_tag_write_lock = threading.Lock()


@dataclass(frozen=True)
class RegistryConfig:
    provider: str
    prefix: str
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class RegistryState:
    provider: str
    host: str
    prefix: str
    images: dict[str, str]
    deployed: dict[str, str]
    digests: dict[str, str]


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


def selected_services(service: str | None, all_services: bool) -> list[str]:
    if all_services:
        return list(DOCKER_SERVICES)
    if service:
        return [service]
    raise ValueError("Select a service with --service or all services with --all.")


def runtime_images(prefix: str) -> dict[str, str]:
    return {service: f"{prefix}/{service}" for service in sorted(DOCKER_SERVICES)}


def _load_registry_toml() -> dict:
    if not RUNTIME_REGISTRY_TOML.exists():
        return {}
    try:
        return tomllib.loads(RUNTIME_REGISTRY_TOML.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def existing_deployed_tags() -> dict[str, str]:
    deployed = _load_registry_toml().get("deployed")
    return {str(k): str(v) for k, v in deployed.items()} if isinstance(deployed, dict) else {}


def existing_deployed_digests() -> dict[str, str]:
    digests = _load_registry_toml().get("deployed_digest")
    return {str(k): str(v) for k, v in digests.items()} if isinstance(digests, dict) else {}


def existing_built_hashes() -> dict[str, str]:
    hashes = _load_registry_toml().get("built_hash")
    return {str(k): str(v) for k, v in hashes.items()} if isinstance(hashes, dict) else {}


def write_runtime_registry(config: RegistryConfig) -> None:
    RUNTIME_REGISTRY_TOML.parent.mkdir(parents=True, exist_ok=True)
    _rewrite_registry_toml(config, existing_deployed_tags(), existing_deployed_digests(), existing_built_hashes())


def _rewrite_registry_toml(
    config: RegistryConfig, deployed: dict[str, str], digests: dict[str, str], built_hashes: dict[str, str]
) -> None:
    lines = [
        "# generated by vidctl",
        "# selected registry provider and image repositories",
        f'provider = "{config.provider}"',
        f'registry_host = "{registry_host(config.prefix)}"',
        f'registry_prefix = "{config.prefix}"',
        "",
        "[images]",
    ]
    for service, image in runtime_images(config.prefix).items():
        lines.append(f'{service} = "{image}"')
    lines += ["", "[deployed]"]
    for service, tag in sorted(deployed.items()):
        lines.append(f'{service} = "{tag}"')
    lines += ["", "[deployed_digest]"]
    for service, digest in sorted(digests.items()):
        lines.append(f'{service} = "{digest}"')
    lines += ["", "[built_hash]"]
    for service, content_hash in sorted(built_hashes.items()):
        lines.append(f'{service} = "{content_hash}"')
    RUNTIME_REGISTRY_TOML.write_text("\n".join(lines) + "\n")


def _rewrite_locked(deployed: dict[str, str], digests: dict[str, str], built_hashes: dict[str, str]) -> None:
    """Shared by write_deployed_tag()/write_built_hash(): both touch the same
    runtime/registry.toml, so each must rewrite ALL three data sections
    (reading the other two fresh) rather than only its own, or one writer
    would clobber the other's just-written section."""
    data = _load_registry_toml()
    provider = str(data.get("provider", ""))
    prefix = str(data.get("registry_prefix", ""))
    if provider and prefix:
        _rewrite_registry_toml(RegistryConfig(provider=provider, prefix=prefix), deployed, digests, built_hashes)


def image_digest(image_with_tag: str) -> str:
    """Digest actually pushed for `image_with_tag`, read back from the local
    Docker image cache right after a successful push (so it reflects exactly
    what the registry now serves for that tag, not a stale prior pull)."""
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{index .RepoDigests 0}}", image_with_tag],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def write_deployed_tag(service: str, tag: str, digest: str = "") -> None:
    # Guards the shared runtime/registry.toml + deployed_tags.generated.yml/
    # deployed_digests.generated.yml read-modify-write against concurrent
    # callers (each_service() now runs per-service push jobs in a thread
    # pool) -- without this, two threads racing the read-modify-write would
    # clobber each other's tag/digest entry.
    with _deployed_tag_write_lock:
        _write_deployed_tag_locked(service, tag, digest)


def write_built_hash(service: str, content_hash: str) -> None:
    # Same shared-file race as write_deployed_tag() -- each_service() also
    # runs "build" jobs concurrently in a thread pool.
    with _deployed_tag_write_lock:
        _write_built_hash_locked(service, content_hash)


def _write_built_hash_locked(service: str, content_hash: str) -> None:
    built_hashes = existing_built_hashes()
    built_hashes[service] = content_hash
    _rewrite_locked(existing_deployed_tags(), existing_deployed_digests(), built_hashes)


def _write_deployed_tag_locked(service: str, tag: str, digest: str) -> None:
    deployed = existing_deployed_tags()
    deployed[service] = tag
    digests = existing_deployed_digests()
    if digest:
        digests[service] = digest
    else:
        digests.pop(service, None)
    _rewrite_locked(deployed, digests, existing_built_hashes())

    DEPLOYED_TAGS_YAML.parent.mkdir(parents=True, exist_ok=True)
    yaml_lines = ["# generated by vidctl - service -> currently published image tag"] + [
        f"{name}: {deployed_tag}" for name, deployed_tag in sorted(deployed.items())
    ]
    DEPLOYED_TAGS_YAML.write_text("\n".join(yaml_lines) + "\n")

    DEPLOYED_DIGESTS_YAML.parent.mkdir(parents=True, exist_ok=True)
    digest_yaml_lines = ["# generated by vidctl - service -> currently published image digest"] + [
        f"{name}: {deployed_digest}" for name, deployed_digest in sorted(digests.items())
    ]
    DEPLOYED_DIGESTS_YAML.write_text("\n".join(digest_yaml_lines) + "\n")


def read_runtime_registry() -> RegistryState:
    if not RUNTIME_REGISTRY_TOML.exists():
        raise ValueError(
            f"{RUNTIME_REGISTRY_TOML} is missing. Run ./vidctl registry login --provider <provider> first."
        )
    try:
        data = tomllib.loads(RUNTIME_REGISTRY_TOML.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{RUNTIME_REGISTRY_TOML} is invalid: {exc}") from exc

    provider = str(data.get("provider", "")).strip()
    host = str(data.get("registry_host", "")).strip()
    prefix = str(data.get("registry_prefix", "")).strip().rstrip("/")
    images = data.get("images")
    if not provider or not host or not prefix or not isinstance(images, dict):
        raise ValueError(
            f"{RUNTIME_REGISTRY_TOML} is incomplete. Run ./vidctl registry login --provider <provider> first."
        )

    resolved_images = {str(name): str(image).strip().rstrip("/") for name, image in images.items() if str(image).strip()}
    missing = sorted(set(DOCKER_SERVICES) - set(resolved_images))
    if missing:
        raise ValueError(f"{RUNTIME_REGISTRY_TOML} is missing image entries: {', '.join(missing)}.")
    deployed = data.get("deployed")
    resolved_deployed = {str(k): str(v) for k, v in deployed.items()} if isinstance(deployed, dict) else {}
    digests = data.get("deployed_digest")
    resolved_digests = {str(k): str(v) for k, v in digests.items()} if isinstance(digests, dict) else {}
    return RegistryState(
        provider=provider,
        host=host,
        prefix=prefix,
        images=resolved_images,
        deployed=resolved_deployed,
        digests=resolved_digests,
    )


def image_name(service: str, tag: str) -> str:
    state = read_runtime_registry()
    image = state.images.get(service)
    if not image:
        raise ValueError(f"{RUNTIME_REGISTRY_TOML} has no image entry for service: {service}.")
    return f"{image}:{tag}"


def login(provider: str = DEFAULT_PROVIDER) -> int:
    try:
        config = provider_config(provider, require_credentials=True)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    code = docker_login(config)
    if code == 0:
        write_runtime_registry(config)
    return code


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
    code = build(service, all_services, tag)
    if code != 0:
        return code
    return push(service, all_services, tag)


def each_service(action: str, service: str | None, all_services: bool, tag: str | None) -> int:
    try:
        services = selected_services(service, all_services)
        resolved_tag = tag or git_short_sha()
        # Resolve image names up front (single-threaded) since image_name()
        # itself reads shared registry state; each_service_job() below then
        # only touches its own service's independent build/push.
        images = {name: image_name(name, resolved_tag) for name in services}
    except KeyError as exc:
        print(f"Unknown service: {exc.args[0]}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    def run_one(name: str) -> tuple[str, int]:
        if action == "build":
            # `docker buildx build` is NOT reproducible (floating base image,
            # apt drift -- see cli/registry.py module docs) and previously
            # ran unconditionally on every single `vidctl scenario apply`,
            # which meant the pushed digest changed almost every apply even
            # with zero real source changes -- defeating the docker_container
            # role's digest-based pull-skip downstream. Skipping the actual
            # rebuild when the content hash AND the previously-built local
            # image both still match keeps the image (and therefore its
            # digest) stable across repeat no-op applies.
            content_hash = docker_context_hash(DOCKER_SERVICES[name], DOCKERFILES[name])
            if (
                content_hash
                and existing_built_hashes().get(name) == content_hash
                and _local_image_exists(images[name])
            ):
                return name, 0
            code = run_docker_action(action, images[name], DOCKER_SERVICES[name], DOCKERFILES[name])
            if code == 0:
                write_built_hash(name, content_hash)
            return name, code

        code = run_docker_action(action, images[name], DOCKER_SERVICES[name], DOCKERFILES[name])
        if code == 0 and action == "push":
            write_deployed_tag(name, resolved_tag, image_digest(images[name]))
        return name, code

    max_workers = max(1, min(len(services), MAX_PARALLEL_DOCKER_JOBS))
    failures: list[tuple[str, int]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for name, code in pool.map(run_one, services):
            if code != 0:
                failures.append((name, code))

    if failures:
        for name, code in failures:
            print(f"{action} failed for service {name} (exit {code}).", file=sys.stderr)
        return failures[0][1]
    return 0


# Mirrors services/worker/.dockerignore's exclusions (node_modules, dist,
# .env*, coverage, .git, .logs, .evidence, bench-output, *.tsbuildinfo,
# .DS_Store) -- not a full docker-ignore-pattern engine, just what this
# repo's .dockerignore actually declares, so the content hash below reflects
# exactly what `docker build` would actually see as its context.
_HASH_EXCLUDED_DIR_NAMES = {"node_modules", "dist", ".git", ".logs", ".evidence", "bench-output", "coverage"}


def _should_hash_file(relative_path: Path) -> bool:
    if any(part in _HASH_EXCLUDED_DIR_NAMES for part in relative_path.parts[:-1]):
        return False
    name = relative_path.name
    if name == ".DS_Store" or name.endswith(".tsbuildinfo"):
        return False
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return False
    return True


@lru_cache(maxsize=None)
def _hash_directory(context: Path) -> str:
    """Content hash of everything under `context` that `docker build` would
    actually see (see _should_hash_file). Several services here share the
    SAME build context (the whole pnpm workspace) -- cached per context path
    so a multi-service `--all` build/push doesn't re-walk/re-hash an
    identical few-hundred-file tree once per service."""
    digest = hashlib.sha256()
    for path in sorted(context.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(context)
        if not _should_hash_file(relative):
            continue
        digest.update(str(relative).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def docker_context_hash(context: Path, dockerfile: Path) -> str:
    """Combines the shared context hash with this service's OWN Dockerfile
    content -- stable across repeat builds of unchanged source (the actual
    property that lets each_service() skip a redundant, non-reproducible
    `docker buildx build`), and still changes if just this service's
    Dockerfile changes even when the shared context hash doesn't."""
    digest = hashlib.sha256()
    digest.update(_hash_directory(context).encode())
    digest.update(dockerfile.read_bytes())
    return digest.hexdigest()


def _local_image_exists(image_with_tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image_with_tag],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def run_docker_action(action: str, image: str, context: Path, dockerfile: Path) -> int:
    if action == "build":
        args = [
            "docker", "buildx", "build",
            "--platform", TARGET_PLATFORM,
            "--load", "-t", image,
            "-f", str(dockerfile),
            str(context),
        ]
        return run(args)
    if action == "push":
        return run(["docker", "push", image])
    print(f"Unknown registry action: {action}", file=sys.stderr)
    return 2
