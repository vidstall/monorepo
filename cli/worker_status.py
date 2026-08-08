"""`vidctl utils worker status <hostname>` -- SSH into a deployed worker VM
and show the Docker state of one worker's container: ps/inspect summary,
a resource snapshot, and recent logs.

Takes the same public hostname a browser/relay client would use (e.g.
`akamai-003-signaling-1.96-126-106-95.sslip.io`, built by
worker_env.yml/Caddyfile.j2 as `<worker_key>.<ip-with-dashes>.sslip.io`) so
an operator can paste a URL straight out of Grafana/logs without having to
separately know the host id or SSH details. `<worker_key>` is
`<provider>-<host>-<service>-<index>` (see topology.py's worker_identifier(),
the one-directional builder this module's parse_worker_hostname() reverses),
and the container it maps to is always named `xaisen-<worker_key>` (see
run_container.yml).
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

from . import infra

SSH_TIMEOUT_SECONDS = 25
SSH_CONNECT_TIMEOUT_SECONDS = 8
LOG_TAIL_LINES = 40

_HOST_ID_RE = re.compile(r"^\d{3,}$")


@dataclass
class WorkerRef:
    provider: str
    host: str
    service: str
    index: int
    worker_key: str

    @property
    def container_name(self) -> str:
        return f"xaisen-{self.worker_key}"


def parse_worker_hostname(hostname: str) -> WorkerRef | None:
    """Reverse worker_identifier(): pull `<provider>-<host>-<service>-<index>`
    back out of a full sslip.io hostname (or a bare worker key, for
    convenience). Service names may themselves contain dashes (cp-daemon,
    validator-daemon), so `index` and `provider`/`host` are peeled off the
    two ends first and everything left in the middle is the service name.
    Returns None on anything that doesn't parse -- callers print their own
    usage-appropriate error rather than this raising.
    """
    worker_key = hostname.split(".", 1)[0]
    parts = worker_key.split("-")
    if len(parts) < 4:
        return None

    provider, host = parts[0], parts[1]
    index_str = parts[-1]
    service = "-".join(parts[2:-1])

    if provider not in infra.PROVIDERS:
        return None
    if not _HOST_ID_RE.match(host):
        return None
    if not index_str.isdigit():
        return None
    if service not in infra.DOCKER_SERVICES:
        return None

    return WorkerRef(
        provider=provider,
        host=host,
        service=service,
        index=int(index_str),
        worker_key=worker_key,
    )


def _run_ssh(host: str, address: str, user: str, remote_command: str) -> subprocess.CompletedProcess[str] | None:
    key_path = infra.SSH_KEY_ROOT / host / "id_ed25519"
    if not key_path.exists():
        return None
    try:
        return subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}",
                "-i", str(key_path),
                f"{user}@{address}",
                remote_command,
            ],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def _docker_status_command(container_name: str) -> str:
    # Chained with `;` (not `&&`) so a not-found container still shows the
    # `docker ps` line (which reports its absence) instead of aborting the
    # whole probe on the first failing subcommand.
    ps_format = "table {{.Names}}\\t{{.Status}}\\t{{.Image}}\\t{{.Ports}}"
    inspect_format = (
        "Status: {{.State.Status}}"
        "  Health: {{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}"
        "  Restarts: {{.RestartCount}}"
        "  StartedAt: {{.State.StartedAt}}"
    )
    return (
        f"echo '=== docker ps ==='; "
        f"docker ps -a --filter name=^/{container_name}$ --format '{ps_format}'; "
        f"echo; echo '=== container state ==='; "
        f"docker inspect {container_name} --format '{inspect_format}' 2>&1; "
        f"echo; echo '=== resource snapshot ==='; "
        f"docker stats --no-stream {container_name} 2>&1; "
        f"echo; echo '=== last {LOG_TAIL_LINES} log lines ==='; "
        f"docker logs --tail {LOG_TAIL_LINES} {container_name} 2>&1"
    )


def status(hostname: str) -> int:
    ref = parse_worker_hostname(hostname)
    if ref is None:
        print(
            f"Could not parse '{hostname}' as a worker hostname. Expected "
            "<provider>-<host>-<service>-<index>[.<ip-with-dashes>.sslip.io], "
            "e.g. akamai-003-signaling-1.96-126-106-95.sslip.io.",
            file=sys.stderr,
        )
        return 2

    address = infra.host_address(ref.host)
    if not address:
        message = (
            f"No address on record for host {ref.host} -- run `vidctl infra inventory` "
            "first, or check the host is actually provisioned."
        )
        print(message, file=sys.stderr)
        infra.record_history(
            "utils worker status",
            service=ref.service,
            provider=ref.provider,
            resource_id=ref.container_name,
            result_for_code=1,
            error=message,
        )
        return 1

    user = infra.host_ssh_user(ref.host)
    result = _run_ssh(ref.host, address, user, _docker_status_command(ref.container_name))
    if result is None:
        message = f"Could not SSH to {ref.host} ({address}) -- missing key or connection failed."
        print(message, file=sys.stderr)
        infra.record_history(
            "utils worker status",
            service=ref.service,
            provider=ref.provider,
            resource_id=ref.container_name,
            result_for_code=1,
            error=message,
        )
        return 1

    print(f"{ref.container_name} @ {ref.provider} host {ref.host} ({address})")
    print()
    print(result.stdout.rstrip())
    if result.stderr.strip():
        print()
        print(result.stderr.rstrip(), file=sys.stderr)

    infra.record_history(
        "utils worker status",
        service=ref.service,
        provider=ref.provider,
        resource_id=ref.container_name,
        result_for_code=0 if result.returncode == 0 else 1,
    )
    return 0 if result.returncode == 0 else 1


def start(hostname: str) -> int:
    """`docker start` a single worker's container. Thin wrapper over
    infra.toggle_container's ansible fast-path (skips site.yml's
    common/docker_service roles -- only valid when the container already
    exists with correct config from an earlier `vidctl scenario apply`)."""
    return _toggle(hostname, "start")


def stop(hostname: str) -> int:
    """`docker stop` a single worker's container. See start()'s docstring."""
    return _toggle(hostname, "stop")


def _toggle(hostname: str, action: str) -> int:
    ref = parse_worker_hostname(hostname)
    if ref is None:
        print(
            f"Could not parse '{hostname}' as a worker hostname. Expected "
            "<provider>-<host>-<service>-<index>[.<ip-with-dashes>.sslip.io], "
            "e.g. akamai-003-signaling-1.96-126-106-95.sslip.io.",
            file=sys.stderr,
        )
        return 2

    print(f"{ref.container_name} @ {ref.provider} host {ref.host}: docker {action}...")
    # toggle_container() already calls infra.record_history() itself -- no
    # separate call needed here (unlike status(), which does its own raw SSH
    # and has no such built-in bookkeeping).
    code = infra.toggle_container(host_limit=ref.host, container_name=ref.container_name, action=action)
    if code == 0:
        print(f"{ref.container_name}: {action} succeeded.")
    else:
        print(f"{ref.container_name}: {action} failed (exit {code}) -- see ansible output above.", file=sys.stderr)
    return code
