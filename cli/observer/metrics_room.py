from __future__ import annotations

from typing import Any

# See metrics_worker.py's top-of-file comment: import the query function
# directly from its submodule to sidestep __init__.py's package-level
# shadowing of the `query` attribute.
from .query import query


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _sum_or_none(values: list[float]) -> float | None:
    return sum(values) if values else None


def collect_room_peer_quality(room_id: str) -> dict[str, Any]:
    """Aggregate this room's dvconf_relay_peer_*/dvconf_rtc_* gauges across
    every peer currently in it -- the same broad-regex-query-then-reshape
    pattern as cli.scenario.system_status._relay_quality_snapshot(), scoped
    to one roomId via PromQL label matching instead of pulled fleet-wide.
    Mirrors the field shape already established for
    worker/relay-001.json's `peer_quality`/`rtc_quality_server_observed`
    blocks, so room-level and relay-level fixtures stay comparable.

    dvconf_rtc_* now carries a `kind` (audio/video) label (see
    rtc-quality-metrics.ts) -- rtc_quality_server_observed is split per kind
    below so audio and video quality can actually be told apart and compared
    (e.g. to see one running hotter/laggier than the other), rather than a
    single flat average that silently favored whichever kind's getStats()
    happened to resolve last on the relay each tick (the bug this
    per-kind split replaces)."""
    result = query(f'{{__name__=~"dvconf_relay_peer_.*|dvconf_rtc_.*", roomId="{room_id}"}}')

    by_metric: dict[str, list[float]] = {}
    by_metric_kind: dict[str, dict[str, list[float]]] = {}
    if result:
        for entry in result:
            labels = dict(entry.get("metric") or {})
            name = labels.pop("__name__", "")
            kind = labels.get("kind")
            value = entry.get("value")
            if not name or not isinstance(value, list) or len(value) != 2:
                continue
            try:
                parsed = float(value[1])
            except (TypeError, ValueError):
                continue
            by_metric.setdefault(name, []).append(parsed)
            if kind:
                by_metric_kind.setdefault(kind, {}).setdefault(name, []).append(parsed)

    def _rtc_quality_for(kind_values: dict[str, list[float]]) -> dict[str, float | None]:
        return {
            "avg_jitter_ms": _avg(kind_values.get("dvconf_rtc_jitter_ms", [])),
            "avg_packet_loss_ratio": _avg(kind_values.get("dvconf_rtc_packet_loss_ratio", [])),
            "avg_bitrate_kbps": _avg(kind_values.get("dvconf_rtc_bitrate_kbps", [])),
            "avg_rtt_ms": _avg(kind_values.get("dvconf_rtc_rtt_ms", [])),
        }

    return {
        "peer_quality": {
            "avg_latency_ms": _avg(by_metric.get("dvconf_relay_peer_latency_ms", [])),
            "avg_packet_loss": _avg(by_metric.get("dvconf_relay_peer_packet_loss", [])),
            "avg_jitter_ms": _avg(by_metric.get("dvconf_relay_peer_jitter_ms", [])),
            "avg_bitrate_up_kbps": _avg(by_metric.get("dvconf_relay_peer_bitrate_up_kbps", [])),
            "avg_bitrate_down_kbps": _avg(by_metric.get("dvconf_relay_peer_bitrate_down_kbps", [])),
            "freeze_count_total": _sum_or_none(by_metric.get("dvconf_relay_peer_freeze_count", [])),
            "pause_count_total": _sum_or_none(by_metric.get("dvconf_relay_peer_pause_count", [])),
            "avg_connection_setup_ms": _avg(by_metric.get("dvconf_relay_peer_connection_setup_ms", [])),
            "ice_success_rate": _avg(by_metric.get("dvconf_relay_peer_ice_success", [])),
            "avg_av_sync_drift_ms": _avg(by_metric.get("dvconf_relay_peer_av_sync_drift_ms", [])),
        },
        "rtc_quality_server_observed": {
            "audio": _rtc_quality_for(by_metric_kind.get("audio", {})),
            "video": _rtc_quality_for(by_metric_kind.get("video", {})),
        },
        # participants.peers[].has_*_producer/e2ee_session_key_established
        # and audio_top_k: relay's in-memory RoomState/PeerState
        # (apps/relay/src/room-handler.ts) isn't exposed via Prometheus or
        # any HTTP endpoint today -- intentionally omitted, not fabricated.
        # See plan's "Known gaps"; a relay roster endpoint would close this,
        # explicitly out of scope for this pass.
    }


def collect_room_identity(room_id: str) -> dict[str, Any]:
    """RoomInfo/RoomEscrow on-chain identity fields, via the same
    contract_cli.fetch_object() path cli.observer.contract_exporter uses
    for MinerStore. `room_id` must be the room's on-chain Sui object ID --
    if the scenario/bot layer's app-level room ID string differs from the
    object ID, this needs a lookup step not yet wired (flagged in the plan
    as needing verification); until then this best-effort call returns
    {"error": ...} the same way any other unreachable/invalid object ID
    would, rather than raising."""
    from .. import contract as contract_cli

    fields = contract_cli.fetch_object(room_id)
    if fields is None:
        return {"error": f"could not fetch on-chain RoomInfo for {room_id}"}
    return {
        "room_id": room_id,
        "creator": fields.get("creator"),
        "status": fields.get("status"),
        "relay_mode": fields.get("relay_mode"),
        "created_at": fields.get("created_at"),
        "closed_at": fields.get("closed_at"),
        "expected_participants": fields.get("expected_participants"),
        "verified_score": fields.get("verified_score"),
        "consensus_reached": fields.get("consensus_reached"),
        "standby_relay_id": fields.get("standby_relay_id"),
    }
