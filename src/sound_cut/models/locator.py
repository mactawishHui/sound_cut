from __future__ import annotations

from pathlib import Path

from sound_cut.core.paths import default_model_cache_dir

from .registry import MODEL_REGISTRY


def locate_model_dir(backend: str, explicit_model_path: Path | None = None) -> Path:
    if explicit_model_path is not None:
        return explicit_model_path

    try:
        relative_dir = MODEL_REGISTRY[backend]["relative_dir"]
    except KeyError as exc:
        raise ValueError(f"unsupported enhancement backend: {backend}") from exc

    return default_model_cache_dir() / relative_dir

