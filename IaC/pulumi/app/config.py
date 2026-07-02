from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPOLOGY_PATH = ROOT / "runtime" / "topology.toml"
FRONTEND_ARTIFACT_ROOT = ROOT / "services" / "frontend" / "out"
OBJECT_STORAGE_SERVICE = "frontend"
