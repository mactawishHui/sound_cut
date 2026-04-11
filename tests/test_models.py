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


from sound_cut.core.models import SubtitleConfig, SubtitleSegment, RenderSummary


def test_subtitle_segment_stores_fields() -> None:
    seg = SubtitleSegment(index=1, start_s=0.0, end_s=1.5, text="Hello")
    assert seg.index == 1
    assert seg.start_s == 0.0
    assert seg.end_s == 1.5
    assert seg.text == "Hello"


def test_subtitle_config_defaults() -> None:
    config = SubtitleConfig(enabled=True)
    assert config.language is None
    assert config.format == "srt"
    assert config.model_size == "base"
    assert config.model_path is None


def test_subtitle_config_disabled_by_default_fields() -> None:
    config = SubtitleConfig(enabled=False)
    assert config.enabled is False


def test_render_summary_subtitle_path_defaults_to_none() -> None:
    summary = RenderSummary(
        input_duration_s=10.0,
        output_duration_s=8.0,
        removed_duration_s=2.0,
        kept_segment_count=3,
    )
    assert summary.subtitle_path is None


def test_render_summary_accepts_subtitle_path(tmp_path) -> None:
    from pathlib import Path
    srt = tmp_path / "output.srt"
    summary = RenderSummary(
        input_duration_s=10.0,
        output_duration_s=8.0,
        removed_duration_s=2.0,
        kept_segment_count=3,
        subtitle_path=srt,
    )
    assert summary.subtitle_path == srt
