from __future__ import annotations

from typing import Any

# See metrics_worker.py's top-of-file comment: import the query function
# directly from its submodule to sidestep __init__.py's package-level
# shadowing of the `query` attribute.
from .query import query

# Exactly the 17 fields relay's metrics-server.ts stores per (roomId,
# peerId) -- see services/worker/apps/relay/src/metrics-server.ts
# REQUIRED_SAMPLE_FIELDS/PeerQualitySample, confirmed against the client's
# real POST /stats/report payload (services/client/client/src/pages/
# RoomPage.tsx). One dvconf_relay_peer_<snake_case> gauge per field.
_SAMPLE_FIELD_METRICS = {
    "latencyMs": "dvconf_relay_peer_latency_ms",
    "packetLoss": "dvconf_relay_peer_packet_loss",
    "jitterMs": "dvconf_relay_peer_jitter_ms",
    "bitrateUpKbps": "dvconf_relay_peer_bitrate_up_kbps",
    "bitrateDownKbps": "dvconf_relay_peer_bitrate_down_kbps",
    "resolutionWidth": "dvconf_relay_peer_resolution_width",
    "resolutionHeight": "dvconf_relay_peer_resolution_height",
    "framerate": "dvconf_relay_peer_framerate",
    "packetReorderingRate": "dvconf_relay_peer_packet_reordering_rate",
    "encodeLatencyMs": "dvconf_relay_peer_encode_latency_ms",
    "decodeLatencyMs": "dvconf_relay_peer_decode_latency_ms",
    "freezeCount": "dvconf_relay_peer_freeze_count",
    "pauseCount": "dvconf_relay_peer_pause_count",
    "connectionSetupMs": "dvconf_relay_peer_connection_setup_ms",
    "iceSuccess": "dvconf_relay_peer_ice_success",
    "reconnectMs": "dvconf_relay_peer_reconnect_ms",
    "avSyncDriftMs": "dvconf_relay_peer_av_sync_drift_ms",
}


def collect_user_sample(room_id: str, peer_id: str) -> dict[str, Any] | None:
    """The real `sample` block for one (roomId, peerId) -- the only part of
    the hand-written user/<peer_id>.json fixture with a live data source.
    `audio`/`video`/`av_sync`/`client_local`/`quality_score` have no live
    source (browser getStats() fields beyond this 16-field sample are never
    extracted/transmitted anywhere in this codebase; quality_score is a
    derived E-model computation, not a stored metric) and are intentionally
    omitted here rather than null-filled -- see plan's "Known gaps". None
    if the query fails or this peer has no current samples at all."""
    result = query(f'{{__name__=~"dvconf_relay_peer_.*", roomId="{room_id}", peerId="{peer_id}"}}')
    if not result:
        return None

    by_name: dict[str, float] = {}
    for entry in result:
        labels = dict(entry.get("metric") or {})
        name = labels.get("__name__", "")
        value = entry.get("value")
        if not name or not isinstance(value, list) or len(value) != 2:
            continue
        try:
            by_name[name] = float(value[1])
        except (TypeError, ValueError):
            continue

    sample = {field: by_name.get(metric_name) for field, metric_name in _SAMPLE_FIELD_METRICS.items()}
    if all(value is None for value in sample.values()):
        return None
    return sample
