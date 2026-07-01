from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from cli.scenario.models import BenchmarkReport


def print_report(report: BenchmarkReport) -> None:
    print("\n" + "=" * 60)
    print(f"BENCHMARK REPORT: {report.scenario_name}")
    topo = report.topology
    vc_str = f" / {topo.vclient_nodes}vc" if topo.vclient_nodes else ""
    print(f"topology: {topo.media_nodes}m / {topo.routes_nodes}r{vc_str} / {topo.coordinator_nodes}coord")
    print(f"network: {report.topology.contract_network}")
    print(f"total duration: {report.total_duration_ms:.0f}ms")
    print("-" * 60)

    stats = report.summary()
    if not stats:
        print("(no benchmark samples recorded)")
    else:
        print("\nAGGREGATE METRICS:")
        for name, s in stats.items():
            print(f"  {name}:")
            print(f"    count={s['count']}  min={s['min_ms']}ms  avg={s['avg_ms']}ms  max={s['max_ms']}ms  p50={s['p50_ms']}ms  p95={s['p95_ms']}ms")

    if report.workers or report.clients or report.users:
        print("\nPER-ENTITY METRICS:")
        for w in report.workers.values():
            print(f"  {w.summary_line()}")
        for c in report.clients.values():
            print(f"  {c.summary_line()}")
        for u in report.users.values():
            print(f"  {u.summary_line()}")

    print("=" * 60)


def _write_report(report: BenchmarkReport, output_path: Optional[str]) -> None:
    if not output_path:
        return
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({
            "scenario": report.scenario_name,
            "topology": {
                "provider": report.topology.provider,
                "region": report.topology.region,
                "instance_type": report.topology.instance_type,
                "media_nodes": report.topology.media_nodes,
                "routes_nodes": report.topology.routes_nodes,
                "vclient_nodes": report.topology.vclient_nodes,
                "coordinator_nodes": report.topology.coordinator_nodes,
                "contract_network": report.topology.contract_network,
            },
            "total_duration_ms": report.total_duration_ms,
            "samples": [
                {
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 2),
                    "entity_id": s.entity_id,
                    "metadata": s.metadata,
                }
                for s in report.samples
            ],
            "summary": report.summary(),
            "entities": report.entity_summary(),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nreport written to {out}")
