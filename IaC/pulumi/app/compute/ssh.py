from ..config import ROOT
from ..models import TopologyInstance


def read_ssh_public_key(instance: TopologyInstance) -> str:
    key_dir = instance.get("ssh_key_dir")
    if not key_dir:
        raise ValueError(
            f"Instance {instance.get('host')} has no ssh_key_dir; "
            "the CLI should generate one before pulumi up."
        )
    path = ROOT / key_dir / "id_ed25519.pub"
    return path.read_text(encoding="utf-8").strip()
