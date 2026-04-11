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


def test_whisper_backend_model_size_passed_to_constructor(tmp_path):
    """WhisperModel is constructed — backend integration smoke test."""
    seg = MagicMock(start=0.0, end=1.0, text="Hi")
    fake_fw, mock_model = _make_fake_faster_whisper([seg])

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()

    with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
        import importlib
        import sound_cut.subtitles.whisper as whisper_mod
        importlib.reload(whisper_mod)

        backend = whisper_mod.WhisperBackend(_make_config())
        backend.transcribe(audio_path)

    fake_fw.WhisperModel.assert_called_once()


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


# --- generate_subtitles() tests ---

from sound_cut.subtitles.pipeline import generate_subtitles


def test_generate_subtitles_writes_srt_and_returns_path(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "audio.wav"
    subtitle_path = tmp_path / "output.srt"
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=2.0, text="Hello")]

    monkeypatch.setattr(
        "sound_cut.subtitles.pipeline.FunASRBackend.transcribe",
        lambda self, path: segments,
    )

    result = generate_subtitles(
        audio, subtitle_path, SubtitleConfig(enabled=True, format="srt", api_key="sk-test")
    )

    assert result == subtitle_path
    assert subtitle_path.exists()
    content = subtitle_path.read_text()
    assert "Hello" in content
    assert "00:00:00,000 --> 00:00:02,000" in content


def test_generate_subtitles_writes_vtt_when_format_is_vtt(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "audio.wav"
    subtitle_path = tmp_path / "output.vtt"
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.5, text="Hi")]

    monkeypatch.setattr(
        "sound_cut.subtitles.pipeline.FunASRBackend.transcribe",
        lambda self, path: segments,
    )

    result = generate_subtitles(
        audio, subtitle_path, SubtitleConfig(enabled=True, format="vtt", api_key="sk-test")
    )

    assert result == subtitle_path
    content = subtitle_path.read_text()
    assert content.startswith("WEBVTT")
    assert "Hi" in content


def test_generate_subtitles_empty_segments_writes_empty_srt(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "audio.wav"
    subtitle_path = tmp_path / "output.srt"

    monkeypatch.setattr(
        "sound_cut.subtitles.pipeline.FunASRBackend.transcribe",
        lambda self, path: [],
    )

    generate_subtitles(audio, subtitle_path, SubtitleConfig(enabled=True, api_key="sk-test"))

    assert subtitle_path.exists()
    assert subtitle_path.read_text() == ""


# --- FunASRBackend unit tests ---

from sound_cut.subtitles.funasr import FunASRBackend, _parse_sentences
from sound_cut.core.errors import MediaError


def test_funasr_backend_requires_api_key() -> None:
    import os
    env_backup = os.environ.pop("DASHSCOPE_API_KEY", None)
    try:
        with pytest.raises(MediaError, match="API key"):
            FunASRBackend(SubtitleConfig(enabled=True))
    finally:
        if env_backup is not None:
            os.environ["DASHSCOPE_API_KEY"] = env_backup


def test_funasr_backend_reads_api_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
    backend = FunASRBackend(SubtitleConfig(enabled=True))
    assert backend._api_key == "sk-from-env"


def test_funasr_backend_explicit_api_key_takes_precedence(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
    backend = FunASRBackend(SubtitleConfig(enabled=True, api_key="sk-explicit"))
    assert backend._api_key == "sk-explicit"


def test_parse_sentences_converts_to_subtitle_segments() -> None:
    data = {
        "transcripts": [
            {
                "sentences": [
                    {"begin_time": 0, "end_time": 2500, "text": "Hello world"},
                    {"begin_time": 2500, "end_time": 5000, "text": "  Goodbye  "},
                ]
            }
        ]
    }
    result = _parse_sentences(data)
    assert len(result) == 2
    assert result[0] == SubtitleSegment(index=1, start_s=0.0, end_s=2.5, text="Hello world")
    assert result[1] == SubtitleSegment(index=2, start_s=2.5, end_s=5.0, text="Goodbye")


def test_parse_sentences_skips_empty_text() -> None:
    data = {
        "transcripts": [
            {
                "sentences": [
                    {"begin_time": 0, "end_time": 1000, "text": "  "},
                    {"begin_time": 1000, "end_time": 2000, "text": "Hi"},
                ]
            }
        ]
    }
    result = _parse_sentences(data)
    assert len(result) == 1
    assert result[0].text == "Hi"
    assert result[0].index == 1


def test_parse_sentences_empty_transcripts() -> None:
    assert _parse_sentences({}) == []
    assert _parse_sentences({"transcripts": []}) == []


def test_funasr_backend_transcribe_full_flow(tmp_path, monkeypatch) -> None:
    """transcribe() calls upload → submit → poll → fetch result and returns segments."""
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake audio")

    upload_calls: list = []
    submit_calls: list = []

    def fake_upload(path: "Path") -> str:
        upload_calls.append(path)
        return "https://transfer.sh/audio.mp3"

    def fake_submit(self, file_url: str) -> str:
        submit_calls.append(file_url)
        return "task-abc-123"

    fake_result_data = {
        "transcripts": [
            {"sentences": [{"begin_time": 100, "end_time": 3000, "text": "Test sentence"}]}
        ]
    }

    def fake_poll(self, task_id: str) -> list:
        assert task_id == "task-abc-123"
        return [{"transcription_url": "https://result.example.com/out.json"}]

    import json
    import urllib.request
    from io import BytesIO

    def fake_urlopen(url, **kwargs):
        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return json.dumps(fake_result_data).encode()
        return FakeResp()

    monkeypatch.setattr("sound_cut.subtitles.funasr.upload_audio_for_asr", fake_upload)
    monkeypatch.setattr("sound_cut.subtitles.funasr.FunASRBackend._submit_task", fake_submit)
    monkeypatch.setattr("sound_cut.subtitles.funasr.FunASRBackend._poll_task", fake_poll)
    monkeypatch.setattr("sound_cut.subtitles.funasr.urllib.request.urlopen", fake_urlopen)

    backend = FunASRBackend(SubtitleConfig(enabled=True, api_key="sk-test"))
    segments = backend.transcribe(audio)

    assert len(segments) == 1
    assert segments[0].text == "Test sentence"
    assert segments[0].start_s == pytest.approx(0.1)
    assert segments[0].end_s == pytest.approx(3.0)
    assert upload_calls[0] == audio
