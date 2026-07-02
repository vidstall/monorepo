from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Callable

from ..config import FRONTEND_ARTIFACT_ROOT, ROOT
from ..models import TopologyInstance


def artifact_root(instance: TopologyInstance) -> Path:
    root = ROOT / instance.get("artifact_dir", str(FRONTEND_ARTIFACT_ROOT))
    return root if root.is_absolute() else ROOT / root


def artifact_files(instance: TopologyInstance) -> list[Path]:
    root = artifact_root(instance)
    if not root.exists():
        return []
    return [path for path in root.rglob("*") if path.is_file()]


def object_key(instance: TopologyInstance, path: Path) -> str:
    return path.relative_to(artifact_root(instance)).as_posix()


def content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def upload_artifacts(
    instance: TopologyInstance,
    upload: Callable[[str, Path, str], None],
) -> int:
    count = 0
    for path in artifact_files(instance):
        upload(object_key(instance, path), path, content_type(path))
        count += 1
    return count
