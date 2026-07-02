from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOPOLOGY_PATH = ROOT / "runtime" / "topology.toml"
FRONTEND_ARTIFACT_ROOT = ROOT / "services" / "frontend" / "out"
