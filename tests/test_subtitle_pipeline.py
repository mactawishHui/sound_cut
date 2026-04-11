from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from sound_cut.core.errors import DependencyError
from sound_cut.core.models import SubtitleConfig, SubtitleSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> SubtitleConfig:
    defaults = dict(enabled=True)
    defaults.update(kwargs)
    return SubtitleConfig(**defaults)


def _make_fake_faster_whisper(segments):
    """Return a fake faster_whisper module whose WhisperModel yields *segments*."""
    fake_fw = ModuleType("faster_whisper")
    mock_model_instance = MagicMock()
    mock_model_instance.transcribe.return_value = (iter(segments), MagicMock())
    fake_fw.WhisperModel = MagicMock(return_value=mock_model_instance)
    return fake_fw, mock_model_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_whisper_backend_raises_dependency_error_when_faster_whisper_missing(tmp_path):
    """DependencyError is raised when faster_whisper is not installed."""
    # Remove faster_whisper from sys.modules if present, then block its import.
    sys.modules.pop("faster_whisper", None)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("No module named 'faster_whisper'")
        return real_import(name, *args, **kwargs)

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()

    # Import backend *after* patching so _require_faster_whisper sees the mock.
    with patch("builtins.__import__", side_effect=fake_import):
        # Re-import the module so it picks up the patched import.
        import importlib
        import sound_cut.subtitles.whisper as whisper_mod
        importlib.reload(whisper_mod)

        backend = whisper_mod.WhisperBackend(_make_config())
        with pytest.raises(DependencyError, match="faster-whisper is required"):
            backend.transcribe(audio_path)


def test_whisper_backend_transcribe_returns_subtitle_segments(tmp_path):
    """transcribe() returns correctly populated SubtitleSegment objects."""
    seg1 = MagicMock(start=0.0, end=2.5, text=" Hello world ")
    seg2 = MagicMock(start=2.5, end=5.0, text=" Goodbye ")
    fake_fw, mock_model = _make_fake_faster_whisper([seg1, seg2])

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        import importlib
        import sound_cut.subtitles.whisper as whisper_mod
        importlib.reload(whisper_mod)

        backend = whisper_mod.WhisperBackend(_make_config())
        result = backend.transcribe(audio_path)

    assert len(result) == 2

    assert result[0] == SubtitleSegment(index=1, start_s=0.0, end_s=2.5, text="Hello world")
    assert result[1] == SubtitleSegment(index=2, start_s=2.5, end_s=5.0, text="Goodbye")


def test_whisper_backend_passes_language_when_set(tmp_path):
    """model.transcribe() is called with language= when config.language is set."""
    seg = MagicMock(start=0.0, end=1.0, text="Hi")
    fake_fw, mock_model = _make_fake_faster_whisper([seg])

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        import importlib
        import sound_cut.subtitles.whisper as whisper_mod
        importlib.reload(whisper_mod)

        backend = whisper_mod.WhisperBackend(_make_config(language="en"))
        backend.transcribe(audio_path)

    call_kwargs = mock_model.transcribe.call_args
    assert call_kwargs.kwargs.get("language") == "en" or (
        len(call_kwargs.args) > 1 and call_kwargs.args[1] == "en"
    )


def test_whisper_backend_passes_model_path_when_set(tmp_path):
    """WhisperModel is constructed with model_size_or_path=str(model_path) when set."""
    seg = MagicMock(start=0.0, end=1.0, text="Hi")
    fake_fw, mock_model = _make_fake_faster_whisper([seg])

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()
    model_path = tmp_path / "my_model"

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        import importlib
        import sound_cut.subtitles.whisper as whisper_mod
        importlib.reload(whisper_mod)

        backend = whisper_mod.WhisperBackend(_make_config(model_path=model_path))
        backend.transcribe(audio_path)

    fake_fw.WhisperModel.assert_called_once_with(model_size_or_path=str(model_path))


def test_whisper_backend_omits_language_when_none(tmp_path):
    """language key is NOT passed to model.transcribe() when config.language is None."""
    seg = MagicMock(start=0.0, end=1.0, text="Hi")
    fake_fw, mock_model = _make_fake_faster_whisper([seg])

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        import importlib
        import sound_cut.subtitles.whisper as whisper_mod
        importlib.reload(whisper_mod)

        backend = whisper_mod.WhisperBackend(_make_config(language=None))
        backend.transcribe(audio_path)

    call_kwargs = mock_model.transcribe.call_args
    assert "language" not in call_kwargs.kwargs
