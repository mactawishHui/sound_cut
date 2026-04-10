from __future__ import annotations

from pathlib import Path

import pytest

from sound_cut.core import EnhancementConfig, default_model_cache_dir


def test_enhancement_config_defaults() -> None:
    config = EnhancementConfig(enabled=False)

    assert config.enabled is False
    assert config.backend == "deepfilternet3"
    assert config.profile == "natural"
    assert config.model_path is None


@pytest.mark.parametrize(
    ("field_name", "kwargs"),
    [
        ("backend", {"backend": "unknown"}),
        ("profile", {"profile": "unknown"}),
    ],
)
def test_enhancement_config_rejects_unsupported_values(field_name: str, kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=field_name):
        EnhancementConfig(enabled=True, **kwargs)


def test_enhancement_config_accepts_requested_backend_and_profile_values() -> None:
    config = EnhancementConfig(enabled=True, backend="resemble-enhance", profile="strong")

    assert config.backend == "resemble-enhance"
    assert config.profile == "strong"


def test_enhancement_config_normalizes_model_path_to_path() -> None:
    config = EnhancementConfig(enabled=True, model_path="models/enhancer.pt")

    assert config.model_path == Path("models/enhancer.pt")



@pytest.mark.parametrize(
    ("platform_name", "expected"),
    [
        ("linux", Path.home() / ".cache" / "sound-cut" / "models"),
        ("darwin", Path.home() / ".cache" / "sound-cut" / "models"),
        ("windows", Path(r"C:\Users\test\AppData\Local") / "sound-cut" / "models"),
    ],
)
def test_default_model_cache_dir_uses_platform_conventions(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, expected: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")

    assert default_model_cache_dir(platform_name=platform_name) == expected


def test_default_model_cache_dir_windows_falls_back_without_localappdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert default_model_cache_dir(platform_name="windows") == Path.home() / "AppData" / "Local" / "sound-cut" / "models"
