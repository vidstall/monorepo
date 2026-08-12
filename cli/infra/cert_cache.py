"""Backup/restore Caddy's TLS cert storage across VM teardown/reprovision.

Why this exists: Caddy auto-provisions Let's Encrypt certs for
`<ip-dashed>.sslip.io` hostnames (see reverse_proxy.yml/Caddyfile.j2), and
cloud providers recycle IPs from a small pool -- a "new" VM launch can land
on an IP that already burned Let's Encrypt's "5 certs per exact identifier
per 168h" rate limit within the last week (confirmed live: `docker logs
xaisen-caddy` showing `HTTP 429 ... too many certificates (5) already
issued for this exact set of identifiers`). Let's Encrypt's rate limit is
keyed purely on the hostname string, with no notion of "this is a
different VM now" -- so the only way to avoid re-tripping it on IP reuse is
to keep the ALREADY-ISSUED cert around ourselves and hand it back to Caddy
before it ever asks the ACME server again.

Caddy's cert storage (`/data` inside its container) is a plain bind mount
to `{{ xaisen_services_root }}/runtime/caddy/data` on the VM's own disk
(reverse_proxy.yml:63) -- `/opt/xaisen` is that variable's default for
scenario-managed workers (IaC/ansible/inventory/group_vars/all/main.yml).
This module copies that whole directory to/from a local cache keyed by
(provider, resolved IP) via plain `scp`/`ssh` subprocess calls, following
the same pattern already used by inventory.py's `registry_status()` --
there's no SSH/SCP abstraction layer in this codebase to build on top of.

Deliberately does NOT parse certmagic's internal directory layout for the
copy itself (whole-directory scp instead) -- only the expiry check below
needs to locate an actual `.crt` file, via a name-filtered glob rather than
a hardcoded path, so this survives Caddy/certmagic layout changes across
versions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ._constants import CERT_CACHE_ROOT

REMOTE_CADDY_DATA_DIR = "/opt/xaisen/runtime/caddy/data"
SSH_TIMEOUT_SECONDS = 8
SCP_TIMEOUT_SECONDS = 60


def _ssh_base(key_path: Path) -> list[str]:
    return ["-o", "StrictHostKeyChecking=no", "-o", f"ConnectTimeout={SSH_TIMEOUT_SECONDS}", "-i", str(key_path)]


def _resolve_target(host: str) -> tuple[str, str, Path] | None:
    """(address, ssh_user, key_path), or None if any piece isn't resolvable
    yet -- callers treat that as "nothing to do", not an error."""
    from .. import infra

    address = infra.host_address(host)
    if not address:
        return None
    key_path = infra.SSH_KEY_ROOT / host / "id_ed25519"
    if not key_path.exists():
        return None
    return address, infra.host_ssh_user(host), key_path


def backup_caddy_cert(host: str, provider: str) -> None:
    """Best-effort: scp the about-to-be-destroyed VM's Caddy /data dir to
    the local cache. Called from control.py right before the `kill` action's
    `pulumi_up()` call, while the VM is still live and its SSH key hasn't
    been cleaned up yet. Must NEVER raise or block the actual destroy --
    every failure mode here is print-and-continue, matching this codebase's
    established warn-and-continue convention (report.py, metrics_sampler.py)."""
    target = _resolve_target(host)
    if target is None:
        return
    address, user, key_path = target

    dest_dir = CERT_CACHE_ROOT / provider / address
    dest_data = dest_dir / "data"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # scp -r into an EXISTING destination directory nests the source
        # under it (dest_data/data/... instead of dest_data/...) -- cp/scp
        # only flattens source-into-destination when the destination didn't
        # already exist. Since the same (provider, address) can legitimately
        # get backed up more than once (an IP can cycle through kill/relaunch
        # more than once), a stale dest_data from an EARLIER backup at this
        # exact address would silently nest on every repeat backup,
        # compounding one extra `data/` layer each time -- confirmed live:
        # every cache entry that had been backed up more than once had this
        # doubled-up layout, which then made restore_caddy_cert() place the
        # restored files one directory too deep on the new VM for Caddy's
        # FileStorage (rooted at the container's bare /data) to ever find,
        # silently defeating the whole point of this module (Caddy fell
        # through to ACME every time despite a valid cached cert existing).
        # Clearing dest_data first makes this call idempotent regardless of
        # scp's directory-existence-dependent copy semantics.
        shutil.rmtree(dest_data, ignore_errors=True)
        subprocess.run(
            ["scp", "-r", *_ssh_base(key_path), f"{user}@{address}:{REMOTE_CADDY_DATA_DIR}", str(dest_data)],
            capture_output=True,
            text=True,
            timeout=SCP_TIMEOUT_SECONDS,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"cert_cache: backup for {provider}/{address} failed (continuing destroy anyway) -- {exc}", file=sys.stderr)
        return

    (dest_dir / "backed_up_at.json").write_text(
        json.dumps({"host": host, "provider": provider, "address": address, "backed_up_at": datetime.now(timezone.utc).isoformat()}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"cert_cache: backed up Caddy cert data for {provider}/{address} to {dest_data}")


def _cert_candidates(data_dir: Path, address: str) -> list[Path]:
    dashed = address.replace(".", "-")
    all_crts = list(data_dir.rglob("*.crt"))
    matching = [p for p in all_crts if dashed in p.name]
    return matching or all_crts


def _cert_still_valid(crt_path: Path) -> bool:
    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(crt_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return False

    line = result.stdout.strip()  # "notAfter=Jan  1 00:00:00 2027 GMT"
    if not line.startswith("notAfter="):
        return False
    try:
        not_after = datetime.strptime(line[len("notAfter=") :], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return not_after > datetime.now(timezone.utc)


def restore_caddy_cert(host: str, provider: str) -> bool:
    """Best-effort: if a cached, still-valid cert exists for this NEW VM's
    resolved IP, scp it onto the VM's Caddy /data dir BEFORE Ansible's
    configure() ever starts the Caddy container -- so Caddy finds a valid
    cert on disk at startup and skips ACME issuance entirely (no Caddy-side
    config change needed for this; certmagic already checks storage before
    requesting a new cert). Returns True iff a restore actually happened.
    Same never-block guarantee as backup_caddy_cert(): every failure mode
    here just falls through to Caddy's normal ACME path, never blocks
    `apply`."""
    target = _resolve_target(host)
    if target is None:
        return False
    address, user, key_path = target

    data_dir = CERT_CACHE_ROOT / provider / address / "data"
    if not data_dir.is_dir():
        return False

    candidates = _cert_candidates(data_dir, address)
    if not candidates:
        print(f"cert_cache: cache for {provider}/{address} has no .crt files -- skipping restore.")
        return False
    if not all(_cert_still_valid(c) for c in candidates):
        print(f"cert_cache: cached cert for {provider}/{address} is expired or unreadable -- skipping restore.")
        return False

    try:
        subprocess.run(
            ["ssh", *_ssh_base(key_path), f"{user}@{address}", f"mkdir -p {REMOTE_CADDY_DATA_DIR}"],
            capture_output=True,
            text=True,
            timeout=SSH_TIMEOUT_SECONDS + 5,
            check=True,
        )
        subprocess.run(
            ["scp", "-r", *_ssh_base(key_path), f"{data_dir}/.", f"{user}@{address}:{REMOTE_CADDY_DATA_DIR}/"],
            capture_output=True,
            text=True,
            timeout=SCP_TIMEOUT_SECONDS,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"cert_cache: restore for {provider}/{address} failed (Caddy will fall back to ACME) -- {exc}", file=sys.stderr)
        return False

    print(f"cert_cache: restored cached Caddy cert for {provider}/{address} -- Caddy should skip ACME on startup.")
    return True
