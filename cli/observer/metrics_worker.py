from __future__ import annotations

from typing import Any

# `cli.observer.query` (the submodule) is shadowed at package level by
# `cli/observer/__init__.py`'s `from .query import query, ...` re-export --
# `cli.observer.query` as an attribute resolves to that function, not the
# module. Importing names directly from the submodule's own dotted path
# sidesteps that shadowing.
from .query import query, room_participant_counts


def _reshape(result: list[dict] | None) -> dict[str, dict[str, Any]]:
    """{metric_name: {label_key: value}} from a raw Prometheus vector --
    the shared reshape used by every per-role collector below, mirroring
    cli.scenario.system_status._relay_quality_snapshot()'s pattern but
    keyed by metric name for direct per-field lookup instead of a flat
    sample list."""
    out: dict[str, dict[str, Any]] = {}
    if not result:
        return out
    for entry in result:
        labels = dict(entry.get("metric") or {})
        name = labels.pop("__name__", "unknown")
        value = entry.get("value")
        if not isinstance(value, list) or len(value) != 2:
            continue
        try:
            numeric = float(value[1])
        except (TypeError, ValueError):
            continue
        label_key = ",".join(f"{k}={v}" for k, v in sorted(labels.items())) or "_"
        out.setdefault(name, {})[label_key] = numeric
    return out


def _single(metrics: dict[str, dict[str, Any]], name: str) -> float | None:
    values = metrics.get(name, {})
    return next(iter(values.values()), None)


def _relay_application() -> dict[str, Any]:
    result = query(
        '{__name__=~"dvconf_relay_worker_died_total|dvconf_relay_worker_ru_.*|'
        'dvconf_relay_active_sessions|dvconf_relay_room_count|'
        'dvconf_relay_bytes_forwarded_total|dvconf_failover_.*"}'
    )
    metrics = _reshape(result)
    return {
        "worker_died_total": _single(metrics, "dvconf_relay_worker_died_total"),
        "active_sessions": _single(metrics, "dvconf_relay_active_sessions"),
        "room_count": _single(metrics, "dvconf_relay_room_count"),
        "bytes_forwarded_total": _single(metrics, "dvconf_relay_bytes_forwarded_total"),
        "workers": {
            "ru_utime_ms": metrics.get("dvconf_relay_worker_ru_utime_ms", {}),
            "ru_stime_ms": metrics.get("dvconf_relay_worker_ru_stime_ms", {}),
            "ru_maxrss_kb": metrics.get("dvconf_relay_worker_ru_maxrss_kb", {}),
        },
        "failover_events_by_phase": metrics.get("dvconf_failover_events_total", {}),
        "failover_avg_duration_seconds_by_phase": metrics.get("dvconf_failover_duration_seconds", {}),
        # peer_quality/rtc_quality_server_observed are room-scoped, not
        # relay-instance-scoped -- dvconf_relay_peer_*/dvconf_rtc_* carry
        # roomId/peerId labels, not a relay-instance label to filter "this
        # relay only". See cli/observer/metrics_room.py for the room-scoped
        # aggregate instead (plan's "Known gaps").
    }


def _bot_application(instance_filter: str | None = None, at_time: float | None = None) -> dict[str, Any]:
    filter_clause = f", {instance_filter}" if instance_filter else ""
    result = query(f'{{__name__=~"dvconf_active_sessions|dvconf_bot_.*"{filter_clause}}}', at_time=at_time)
    metrics = _reshape(result)
    return {
        "sessions_active": _single(metrics, "dvconf_active_sessions"),
        "sessions_total": _single(metrics, "dvconf_bot_sessions_total"),
        "session_errors_total": _single(metrics, "dvconf_bot_session_errors_total"),
        "join_phase_avg_seconds": metrics.get("dvconf_bot_join_phase_seconds", {}),
        "ffmpeg_respawns_total": metrics.get("dvconf_bot_ffmpeg_respawns_total", {}),
        "ffmpeg_stderr_lines_total": metrics.get("dvconf_bot_ffmpeg_stderr_lines_total", {}),
        "frame_drops_total": metrics.get("dvconf_bot_frame_drops_total", {}),
        "underruns_total": metrics.get("dvconf_bot_underruns_total", {}),
    }


def registration_status(instance_filter: str, at_time: float | None = None) -> bool | None:
    """Whether one worker instance is currently registered on-chain, per its
    self-reported dvconf_registered gauge (services/worker/packages/shared/
    src/metrics-prom.ts's createRegistrationGauge, set right after each
    app's ensureRegistered() call resolves) -- replaces the old SSH-grepped
    `docker logs | grep 'operator address|node_id=|bootstrap failed'` check
    (cli/infra/inventory.py's registry_status()). None if no series matched
    (host not yet redeployed with the gauge, or the query failed), not an
    exception -- same convention as every other collector in this module.
    `at_time`: see query()'s doc -- historical point-in-time lookup instead
    of "now"."""
    result = query(f'{{__name__="dvconf_registered", {instance_filter}}}', at_time=at_time)
    metrics = _reshape(result)
    value = _single(metrics, "dvconf_registered")
    return None if value is None else bool(value)


def _chain_daemon_fields(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fields shared by cp-daemon and validator-daemon -- both register the
    same chain_tx_*/chain_poll_*/role_assignment_* metrics via
    services/worker/packages/shared's registerTxMetrics/
    registerEventPollerMetrics/registerRoleAssignmentMetrics."""
    return {
        "chain_tx_avg_duration_seconds_by_method": metrics.get("dvconf_chain_tx_duration_seconds", {}),
        "chain_tx_retries_total_by_method": metrics.get("dvconf_chain_tx_retries_total", {}),
        "chain_poll_avg_duration_seconds_by_module": metrics.get("dvconf_chain_poll_duration_seconds", {}),
        "chain_poll_events_processed_total_by_module": metrics.get("dvconf_chain_events_processed_total", {}),
        "role_assignments_total": metrics.get("dvconf_role_assignments_total", {}),
        "role_assignment_wait_avg_seconds": metrics.get("dvconf_role_assignment_wait_seconds", {}),
    }


def _cp_daemon_application() -> dict[str, Any]:
    result = query(
        '{__name__=~"dvconf_role_votes_cast_total|dvconf_role_vote_latency_seconds|'
        'dvconf_chain_tx_.*|dvconf_chain_poll_.*|dvconf_role_assignment.*"}'
    )
    metrics = _reshape(result)
    return {
        "role_votes_cast_total": _single(metrics, "dvconf_role_votes_cast_total"),
        "role_vote_latency_avg_seconds": _single(metrics, "dvconf_role_vote_latency_seconds"),
        **_chain_daemon_fields(metrics),
    }


def _validator_daemon_application() -> dict[str, Any]:
    result = query(
        '{__name__=~"dvconf_active_sessions|dvconf_validator_relay_.*|dvconf_canary_.*|'
        'dvconf_chain_tx_.*|dvconf_chain_poll_.*|dvconf_role_assignment.*"}'
    )
    metrics = _reshape(result)
    return {
        "active_sessions": _single(metrics, "dvconf_active_sessions"),
        "relay_rtt_ms": metrics.get("dvconf_validator_relay_rtt_ms", {}),
        "relay_jitter_ms": metrics.get("dvconf_validator_relay_jitter_ms", {}),
        "relay_loss_bps": metrics.get("dvconf_validator_relay_loss_bps", {}),
        "canary_coverage_distinct_validators_by_relay": metrics.get(
            "dvconf_canary_coverage_distinct_validators", {}
        ),
        "canary_quorum_met_by_relay": metrics.get("dvconf_canary_quorum_met", {}),
        "canary_divergence_promoted_total": _single(metrics, "dvconf_canary_divergence_promoted_total"),
        **_chain_daemon_fields(metrics),
    }


def _signaling_application() -> dict[str, Any]:
    # Only dvconf_room_participants is confirmed real for signaling as of
    # this pass. Everything else the hand-written worker/signaling-001.json
    # fixture carries (sessions_active/max/utilization_percent/per_sec/
    # created_total/terminated_total, call_setup_time_ms/p95,
    # call_drop_rate_percent, sdp_negotiation_time_ms, ice_candidate_pairs,
    # reconnect_count) has no confirmed dvconf_* metric backing it -- do
    # not invent PromQL for those, omit rather than fabricate. See
    # services/worker/apps/signaling's actual metrics registration for a
    # follow-up verification pass before adding them here.
    counts = room_participant_counts()
    return {
        "rooms_with_participants": len(counts) if counts is not None else None,
        "total_participants_across_rooms": sum(counts.values()) if counts else None,
    }


_ROLE_COLLECTORS = {
    "relay": _relay_application,
    "bot": _bot_application,
    "cp-daemon": _cp_daemon_application,
    "validator-daemon": _validator_daemon_application,
    "signaling": _signaling_application,
}


def collect_worker_application(
    service: str, instance_filter: str | None = None, at_time: float | None = None
) -> dict[str, Any] | None:
    """One worker role's real, confirmed dvconf_* metrics, reshaped into
    the `application` block for that role's worker/<role>-<instance>.json
    entry. None for an unrecognized service; {"error": ...} (not a raised
    exception) if the underlying query fails, matching this codebase's
    warn-and-continue convention. `instance_filter` (a PromQL label matcher
    like 'instance=~".*1-2-3-4.*"', no surrounding braces) narrows the query
    to one host's series instead of collapsing the whole fleet into a single
    value -- only the "bot" collector currently accepts it (per-host active
    session count, used by cli.scenario.system_status's per-worker snapshot);
    every other role ignores it, unchanged fleet-wide behavior. `at_time`:
    see query()'s doc -- historical point-in-time lookup instead of "now";
    only meaningful for the "bot" collector for the same reason."""
    collector = _ROLE_COLLECTORS.get(service)
    if collector is None:
        return None
    try:
        if service == "bot":
            return _bot_application(instance_filter, at_time)
        return collector()
    except Exception as exc:  # noqa: BLE001 - one worker's metrics query must not sink the tick
        return {"error": str(exc)}
