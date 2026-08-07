"""Small reusable Pushgateway PUT, factored out of contract_exporter.py's
push_contract_state() so other one-off samplers (worker_status.py's
stop/start event timestamps, worker_liveness.py's correlator) don't each
reinvent the PUT/auth/URL plumbing. contract_exporter.py keeps its own
inlined copy rather than being refactored onto this -- not touching a
working, already-relied-on export path for an unrelated feature.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request


def format_prometheus_text(samples: list[tuple[str, dict[str, str], float]], help_text: str) -> str:
    """Prometheus text-exposition format (version 0.0.4). One HELP/TYPE pair
    per distinct metric name, then one sample line per (labels, value)."""
    seen_names: set[str] = set()
    lines: list[str] = []
    for name, labels, value in samples:
        if name not in seen_names:
            seen_names.add(name)
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
        if labels:
            label_str = ",".join(
                f'{key}="{val.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
                for key, val in labels.items()
            )
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")
    return "\n".join(lines) + "\n"


def push_samples(
    job: str,
    instance: str,
    samples: list[tuple[str, dict[str, str], float]],
    help_text: str,
    host: str = "bourbon",
) -> int:
    """PUT `samples` to the named observer host's Pushgateway under
    job=<job>/instance=<instance>. Returns 0 on success, 1 on any failure
    (unknown host, unreachable gateway, non-2xx response) -- callers should
    treat a 1 as best-effort-dropped, not fatal, matching this CLI's
    warn-and-continue convention for observability pushes."""
    from .. import infra
    from .config import find_host

    host_entry = find_host(host)
    if host_entry is None:
        print(f"Unknown observer host: {host}", file=sys.stderr)
        return 1

    body = format_prometheus_text(samples, help_text)
    dashed = str(host_entry["address"]).replace(".", "-")
    url = f"https://pushgateway.{dashed}.sslip.io/metrics/job/{job}/instance/{instance}"
    token = infra.metrics_auth_token()

    request = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        method="PUT",
        headers={
            "content-type": "text/plain; version=0.0.4",
            "authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.status
    except urllib.error.HTTPError as exc:
        print(f"Warning: pushing to {url} failed: HTTP {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"Warning: pushing to {url} failed: {exc.reason}", file=sys.stderr)
        return 1

    if status_code >= 300:
        print(f"Warning: pushing to {url} failed: HTTP {status_code}", file=sys.stderr)
        return 1

    return 0
