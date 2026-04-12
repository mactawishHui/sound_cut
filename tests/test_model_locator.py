from __future__ import annotations

from pathlib import Path

import pytest

import sound_cut.models.locator as locator


def test_locate_model_dir_prefers_explicit_model_path(tmp_path: Path) -> None:
    explicit = tmp_path / "models" / "deepfilternet3"
    explicit.mkdir(parents=True)

    resolved = locator.locate_model_dir("deepfilternet3", explicit)

    assert resolved == explicit


def test_locate_model_dir_uses_backend_specific_default_cache_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(locator, "default_model_cache_dir", lambda: tmp_path / "cache")

    resolved = locator.locate_model_dir("demucs-vocals")

    assert resolved == tmp_path / "cache" / "demucs-vocals"
