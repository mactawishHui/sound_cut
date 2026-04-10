from __future__ import annotations

import shutil
from pathlib import Path

from sound_cut.models.locator import locate_model_dir
from sound_cut.models.registry import MODEL_REGISTRY

from .manifest import MANIFEST_FILENAME, ModelManifest, load_manifest, write_manifest


def install_model(backend: str, destination: Path | None = None) -> Path:
    target_dir = destination or locate_model_dir(backend)
    target_dir.mkdir(parents=True, exist_ok=True)
    already_ready = verify_model(backend, target_dir)
    write_manifest(target_dir, ModelManifest(backend=backend, installed=already_ready))
    return target_dir


def import_model(backend: str, source: Path, destination: Path | None = None) -> Path:
    source_dir = Path(source)
    if not source_dir.exists():
        raise FileNotFoundError(source_dir)
    if not source_dir.is_dir():
        raise NotADirectoryError(source_dir)

    target_dir = destination or locate_model_dir(backend)
    source_resolved = source_dir.resolve()
    target_resolved = target_dir.resolve(strict=False)
    if (
        source_resolved == target_resolved
        or source_resolved.is_relative_to(target_resolved)
        or target_resolved.is_relative_to(source_resolved)
    ):
        raise OSError(
            f"source and destination model directories must not overlap: "
            f"{source_resolved} <-> {target_resolved}"
        )
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    write_manifest(target_dir, ModelManifest(backend=backend, installed=True, source=str(source_dir)))
    return target_dir


def verify_model(backend: str, model_dir: Path | None = None) -> bool:
    target_dir = model_dir or locate_model_dir(backend)
    manifest = load_manifest(target_dir)
    if manifest is None:
        return False
    if manifest.backend != backend or manifest.installed is not True:
        return False
    return has_model_assets(backend, target_dir)


def model_install_state(backend: str, model_dir: Path | None = None) -> str:
    target_dir = model_dir or locate_model_dir(backend)
    manifest = load_manifest(target_dir)
    if manifest is None or manifest.backend != backend:
        return "missing"
    if manifest.installed is not True:
        return "prepared"
    if verify_model(backend, target_dir):
        return "installed"
    return "invalid"


def has_model_assets(backend: str, model_dir: Path) -> bool:
    asset_globs = MODEL_REGISTRY.get(backend, {}).get("asset_globs", ())
    try:
        if asset_globs:
            return any(any(model_dir.rglob(pattern)) for pattern in asset_globs)
        for path in model_dir.iterdir():
            if path.name != MANIFEST_FILENAME:
                return True
    except OSError:
        return False
    return False
