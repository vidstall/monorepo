from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

# Tuned to beat Prometheus's own 15s scrape interval by ~2 orders of
# magnitude (see IaC/ansible/roles/docker_service/templates/
# prometheus.yml.j2) -- the whole point of this module is measuring
# detection latency well under a second, which the fleet's existing
# pull-based observation stack can't do.
POLL_INTERVAL_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 1.0

# Only relay's /healthz is actually reachable from outside the docker
# network today. Caddyfile.j2's `/healthz*` handle block proxies to every
# service's metrics-port server, but only relay's metrics-server.ts
# implements a /healthz route there -- cp-daemon/signaling/
# validator-daemon share metrics-prom.ts, which 404s on anything but a
# literal /metrics path. Polling one of those would just measure
# 404-response latency, not liveness, so this module refuses up front
# rather than silently producing a meaningless number for them.
SUPPORTED_SERVICES = {"relay"}


def healthz_url(host_ip: str, worker_key: str) -> str:
    dashed = host_ip.replace(".", "-")
    return f"https://{worker_key}.{dashed}.sslip.io/healthz"


def worker_healthz_url(host: str, service: str, provider: str, worker_index: int) -> str | None:
    """None if this worker's service isn't in SUPPORTED_SERVICES, or its
    host has no resolved IP yet (inventory() hasn't run) -- callers should
    skip starting a poller in either case rather than spin up a thread
    that can never produce a meaningful sample."""
    if service not in SUPPORTED_SERVICES:
        return None
    from .. import infra
    from ..infra.topology import worker_identifier

    ip = infra.host_address(host)
    if not ip:
        return None
    worker_key = worker_identifier(provider, host, service, worker_index)
    return healthz_url(ip, worker_key)


def _probe_once(url: str) -> bool:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class FastHealthPoller:
    """Tight-loop /healthz poller for scenario worker.leave/worker.join
    detection-latency measurement (see actions.py's
    container_action_confirmed_at ground truth, which this is meant to be
    diffed against). Runs on the control node -- the same machine that
    dispatches the docker stop/start SSH command -- polling every
    POLL_INTERVAL_SECONDS with a short per-request timeout, no SSH
    round-trip per sample. Records every raw sample plus the timestamp of
    the FIRST sample that flipped away from the state observed by this
    poller's very first probe (down for a worker.leave target, up for a
    worker.join target) -- that flip is the "observed_at" this measurement
    cares about. Meant to be started a few seconds before an action's
    scripted dispatch and stopped after a bounded grace window once the
    transition has been seen (or the window lapses without one)."""

    def __init__(self, url: str, poll_interval: float = POLL_INTERVAL_SECONDS) -> None:
        self._url = url
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._samples: list[dict[str, Any]] = []
        self._initial_state: bool | None = None
        self._transition_at: str | None = None

    def start(self) -> None:
        self._thread.start()

    def wait_for_transition(self, grace_seconds: float) -> None:
        """Blocks until either a transition has been recorded or
        `grace_seconds` elapses, whichever comes first -- does not stop the
        poller thread itself, so callers still need stop()."""
        deadline = time.monotonic() + grace_seconds
        while self._transition_at is None and not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self._poll_interval, remaining))

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            alive = _probe_once(self._url)
            now = datetime.now(timezone.utc).isoformat()
            self._samples.append({"timestamp": now, "alive": alive})
            if self._initial_state is None:
                self._initial_state = alive
            elif self._transition_at is None and alive != self._initial_state:
                self._transition_at = now
            self._stop.wait(self._poll_interval)

    def result(self) -> dict[str, Any]:
        return {
            "url": self._url,
            "initial_state": self._initial_state,
            "observed_at": self._transition_at,
            "sample_count": len(self._samples),
            "samples": self._samples,
        }
