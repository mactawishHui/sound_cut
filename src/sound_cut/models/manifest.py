from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = "sound-cut-model.json"


@dataclass(frozen=True)
class ModelManifest:
    backend: str
    installed: bool = True
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "backend": self.backend,
            "installed": self.installed,
        }
        if self.source is not None:
            payload["source"] = self.source
        return payload


def manifest_path(model_dir: Path) -> Path:
    return model_dir / MANIFEST_FILENAME


def write_manifest(model_dir: Path, manifest: ModelManifest) -> Path:
    path = manifest_path(model_dir)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def load_manifest(model_dir: Path) -> ModelManifest | None:
    path = manifest_path(model_dir)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text())
        backend = data["backend"]
        installed = data.get("installed", False)
        source = data.get("source")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None

    if not isinstance(backend, str):
        return None
    if not isinstance(installed, bool):
        return None
    if source is not None and not isinstance(source, str):
        return None

    return ModelManifest(
        backend=backend,
        installed=installed,
        source=source,
    )
