from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import bot_client, infra
from .lock import read_lock

_SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=8"]
_HARDWARE_NETWORK_REMOTE_CMD = (
    "echo ---CPU---; nproc; "
    "echo ---MEMORY---; free -m; "
    "echo ---DISK---; df -h /; "
    "echo ---NETWORK-ADDR---; ip -br addr; "
    "echo ---NETWORK-COUNTERS---; cat /proc/net/dev; "
    "echo ---KERNEL---; uname -a"
)


def _worker_key(worker: dict[str, Any]) -> str:
    service = str(worker.get("service"))
    worker_index = int(worker.get("worker_index", 1) or 1)
    return service if worker_index == 1 else f"{service}-{worker_index}"


def _parse_cpu_section(lines: list[str]) -> dict[str, Any]:
    try:
        return {"logical_cores": int(lines[0].strip())}
    except (IndexError, ValueError) as exc:
        return {"error": str(exc)}


def _parse_memory_section(lines: list[str]) -> dict[str, Any]:
    # `free -m` header + "Mem:   total   used   free   shared  buff/cache  available"
    try:
        mem_line = next(line for line in lines if line.strip().startswith("Mem:"))
        fields = mem_line.split()
        return {
            "total_mb": int(fields[1]),
            "used_mb": int(fields[2]),
            "free_mb": int(fields[3]),
            "available_mb": int(fields[-1]),
        }
    except (StopIteration, IndexError, ValueError) as exc:
        return {"error": str(exc)}


def _parse_disk_section(lines: list[str]) -> dict[str, Any]:
    # `df -h /` header + one data row: Filesystem Size Used Avail Use% Mounted-on
    try:
        data_line = lines[1]
        fields = data_line.split()
        return {
            "filesystem": fields[0],
            "size": fields[1],
            "used": fields[2],
            "avail": fields[3],
            "use_percent": fields[4],
        }
    except (IndexError, ValueError) as exc:
        return {"error": str(exc)}


def _parse_network_addr_section(lines: list[str]) -> list[dict[str, Any]]:
    # `ip -br addr`: NAME  STATE  ADDR1 ADDR2 ...
    interfaces = []
    for line in lines:
        fields = line.split()
        if len(fields) < 2:
            continue
        interfaces.append({"name": fields[0], "state": fields[1], "addresses": fields[2:]})
    return interfaces


def _parse_network_counters_section(lines: list[str]) -> list[dict[str, Any]]:
    # /proc/net/dev: 2 header lines, then "iface: rx_bytes rx_packets rx_errs rx_drop ... tx_bytes tx_packets tx_errs tx_drop ..."
    counters = []
    for line in lines[2:]:
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        fields = rest.split()
        try:
            counters.append(
                {
                    "interface": name.strip(),
                    "rx_bytes": int(fields[0]),
                    "rx_packets": int(fields[1]),
                    "rx_errs": int(fields[2]),
                    "rx_drop": int(fields[3]),
                    "tx_bytes": int(fields[8]),
                    "tx_packets": int(fields[9]),
                    "tx_errs": int(fields[10]),
                    "tx_drop": int(fields[11]),
                }
            )
        except (IndexError, ValueError):
            continue
    return counters


def _parse_hardware_network_output(output: str) -> dict[str, Any]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("---") and line.endswith("---"):
            current = line.strip("-")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    return {
        "cpu": _parse_cpu_section(sections.get("CPU", [])),
        "memory": _parse_memory_section(sections.get("MEMORY", [])),
        "disk_root": _parse_disk_section(sections.get("DISK", [])),
        "network_addrs": _parse_network_addr_section(sections.get("NETWORK-ADDR", [])),
        "network_counters": _parse_network_counters_section(sections.get("NETWORK-COUNTERS", [])),
        "kernel": "\n".join(sections.get("KERNEL", [])).strip(),
    }


def _hardware_network_probe(ssh_user: str, key_path: Path, address: str) -> dict[str, Any]:
    """Live CPU/memory/disk/network facts for one machine (worker or
    observer host), via a single SSH call modeled directly on
    infra.registry_status()'s pattern (same ssh options, same
    unreachable-host guard). Never raises -- returns {"error": ...} for the
    whole probe, or for just the malformed section, on any failure."""
    if not address or not key_path.exists():
        return {"error": "host unreachable (no address or missing SSH key)"}
    try:
        result = subprocess.run(
            ["ssh", *_SSH_OPTS, "-i", str(key_path), f"{ssh_user}@{address}", _HARDWARE_NETWORK_REMOTE_CMD],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"error": str(exc)}

    if result.returncode != 0:
        return {"error": result.stderr.strip() or f"ssh exited {result.returncode}"}
    return _parse_hardware_network_output(result.stdout)


def _worker_snapshot(worker: dict[str, Any]) -> dict[str, Any]:
    """One worker's full detail: every topology field plus a live registry
    check, a live hardware/network probe, and (bot workers only) live
    bot/room session state. Each network call is wrapped independently so
    one bad host never blanks the rest of this worker's data, let alone the
    whole snapshot."""
    host = str(worker.get("host"))
    snapshot = dict(worker)

    address = ""
    try:
        address = infra.host_address(host)
        snapshot["registry_status"] = infra.registry_status(host, _worker_key(worker), address)
    except Exception as exc:  # noqa: BLE001 - one host's SSH probe must not sink the snapshot
        snapshot["registry_status"] = {"error": str(exc)}

    try:
        key_path = infra.SSH_KEY_ROOT / host / "id_ed25519"
        snapshot["hardware_network"] = _hardware_network_probe("root", key_path, address)
    except Exception as exc:  # noqa: BLE001
        snapshot["hardware_network"] = {"error": str(exc)}

    if worker.get("service") == "bot":
        try:
            sessions = bot_client.list_sessions(host)
            snapshot["bot_sessions"] = sessions if sessions is not None else {"error": "no response"}
        except Exception as exc:  # noqa: BLE001
            snapshot["bot_sessions"] = {"error": str(exc)}

    return snapshot


def _all_workers(env: str) -> list[dict[str, Any]]:
    # runtime/topology.toml is a single global file (every env's workers
    # live in the same flat "workers" array, each carrying its own "env"
    # field) -- `env` here only seeds ensure_topology()'s bookkeeping if the
    # file doesn't exist yet, it never filters what's returned. Unlike
    # cli.scenario.status._active_workers_for_env, this deliberately does
    # NOT filter by env or drop desired_state == "deleted": the system-status
    # log is meant to cover every worker the whole system knows about, not
    # just the current scenario's live set.
    topology = infra.ensure_topology(env)
    return list(topology.get("workers", []))


def _workers_snapshot(env: str) -> list[dict[str, Any]]:
    try:
        workers = _all_workers(env)
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]
    if not workers:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(workers))) as pool:
        return list(pool.map(_worker_snapshot, workers))


def _observer_host_snapshot(host: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(host)
    try:
        key_path = Path(str(host.get("ssh_key", "")))
        snapshot["hardware_network"] = _hardware_network_probe(
            str(host.get("ssh_user") or "root"), key_path, str(host.get("address") or "")
        )
    except Exception as exc:  # noqa: BLE001
        snapshot["hardware_network"] = {"error": str(exc)}
    return snapshot


def _observer_hosts_snapshot() -> list[dict[str, Any]]:
    try:
        from .. import observer

        hosts = observer.read_hosts()
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]
    if not hosts:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(hosts))) as pool:
        return list(pool.map(_observer_host_snapshot, hosts))


_RELAY_QUALITY_QUERY = '{__name__=~"dvconf_relay_peer_.*|dvconf_rtc_.*"}'


def _relay_quality_snapshot() -> list[dict[str, Any]] | dict[str, str]:
    """Client-reported (dvconf_relay_peer_*) and server-observed
    (dvconf_rtc_*) per-peer WebRTC quality gauges, fetched in a single
    Prometheus instant query via cli.observer.query() -- reuses that
    module's existing auth/observer-host-lookup/JSON-parsing rather than
    scraping each relay worker's /metrics/prom directly. Best-effort: no
    observer host running prometheus, or any query failure, becomes
    {"error": ...} rather than raising, same as every other section here."""
    try:
        from .. import observer

        result = observer.query(_RELAY_QUALITY_QUERY)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    if result is None:
        return {"error": "prometheus query failed or no observer host runs prometheus"}

    samples: list[dict[str, Any]] = []
    for entry in result:
        labels = dict(entry.get("metric") or {})
        metric_name = labels.pop("__name__", "unknown")
        value = entry.get("value")
        if not isinstance(value, list) or len(value) != 2:
            continue
        try:
            numeric_value = float(value[1])
        except (TypeError, ValueError):
            continue
        samples.append({"metric": metric_name, "labels": labels, "value": numeric_value})
    return samples


def _contract_state_snapshot(env: str) -> list[dict[str, Any]] | dict[str, str]:
    try:
        from ..observer.contract_exporter import collect_contract_state

        samples = collect_contract_state(env)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return [{"metric": name, "labels": labels, "value": value} for name, labels, value in samples]


def _lock_snapshot() -> dict[str, Any] | None:
    try:
        return read_lock()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def capture_system_snapshot(env: str) -> dict[str, Any]:
    """Best-effort, maximum-detail snapshot of the whole system at this
    instant: the active scenario lock, every worker the system knows about
    across every env and desired_state (with live registry status, a live
    hardware/network probe, and for bot workers, live room/bot session
    state), every registered observer/monitoring host (with the same
    hardware/network probe), client-reported and server-observed per-peer
    WebRTC quality metrics from Prometheus (dvconf_relay_peer_*/dvconf_rtc_*),
    and on-chain contract/wallet-pool state for `env`. Every section fails
    independently (an {"error": ...} dict in its
    place) rather than raising, matching this CLI's existing warn-and-continue
    convention (see apply.py's observer refresh/push helpers) -- this makes
    it safe to call repeatedly from a background sampler thread without
    extra guarding."""
    return {
        "captured_at": infra.timestamp(),
        "env": env,
        "lock": _lock_snapshot(),
        "workers": _workers_snapshot(env),
        "observer_hosts": _observer_hosts_snapshot(),
        "relay_quality": _relay_quality_snapshot(),
        "contract_state": _contract_state_snapshot(env),
    }
