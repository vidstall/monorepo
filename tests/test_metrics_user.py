from __future__ import annotations

import re
import unittest
from pathlib import Path

from cli.observer import metrics_user

REPO_ROOT = Path(__file__).resolve().parent.parent
RELAY_METRICS_SERVER_TS = (
    REPO_ROOT / "services" / "worker" / "apps" / "relay" / "src" / "metrics-server-types.ts"
)


def _relay_peer_quality_field_names() -> set[str]:
    """Extract the `PeerQualitySample` field names straight out of
    metrics-server-types.ts's `PEER_QUALITY_METRIC_INFO` object literal -- the
    single source of truth for every dvconf_relay_peer_* gauge (see that
    file's own docstring). Regex-based since this is a Python test reading
    a TypeScript source file, not a real TS parser -- good enough to catch
    a field being added/removed on the relay side without a matching
    _SAMPLE_FIELD_METRICS entry, which is exactly the class of bug (a
    silently-omitted avSyncDriftMs mapping) this test guards against.
    """
    text = RELAY_METRICS_SERVER_TS.read_text()
    marker = "export const PEER_QUALITY_METRIC_INFO"
    start = text.index(marker)
    end = text.index("\n};", start)
    body = text[start:end]
    return set(re.findall(r"^\s{2}(\w+):\s*\{", body, flags=re.MULTILINE))



class MetricsUserFieldMappingTests(unittest.TestCase):
    def test_sample_field_metrics_covers_every_relay_peer_quality_field(self) -> None:
        """cli.observer.metrics_user._SAMPLE_FIELD_METRICS must have an entry
        for every field the relay actually gauges -- a missing entry means
        that field silently never reaches the per-user observability log
        (collect_user_sample), exactly what happened to avSyncDriftMs."""
        relay_fields = _relay_peer_quality_field_names()
        self.assertTrue(relay_fields, "failed to parse any fields out of metrics-server.ts")
        self.assertEqual(relay_fields, set(metrics_user._SAMPLE_FIELD_METRICS.keys()))

    def test_sample_field_metric_names_match_dvconf_relay_peer_convention(self) -> None:
        for metric_name in metrics_user._SAMPLE_FIELD_METRICS.values():
            self.assertTrue(metric_name.startswith("dvconf_relay_peer_"), metric_name)

    def test_av_sync_drift_ms_is_mapped(self) -> None:
        self.assertEqual(
            metrics_user._SAMPLE_FIELD_METRICS.get("avSyncDriftMs"),
            "dvconf_relay_peer_av_sync_drift_ms",
        )


if __name__ == "__main__":
    unittest.main()
