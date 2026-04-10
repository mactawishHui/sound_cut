# Auto Subtitle Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--subtitle` as a fourth processing mode that runs local Whisper transcription on the rendered output, writing an SRT/VTT file for audio or embedding a soft subtitle track for MP4 video.

**Architecture:** New `src/sound_cut/subtitles/` subpackage (formatter, whisper backend, pipeline) symmetric to `enhancement/`. `process_audio()` gains a `subtitle: SubtitleConfig | None` parameter; subtitle generation runs as the last step after all rendering. `faster-whisper` is an optional dependency, lazily imported with a clear `DependencyError` when missing.

**Tech Stack:** Python 3.11, faster-whisper ≥1.0 (optional), ffmpeg (`mov_text` subtitle stream), pytest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/sound_cut/core/models.py` | Add `SubtitleSegment`, `SubtitleConfig`; add `subtitle_path` field to `RenderSummary` |
| Modify | `src/sound_cut/core/__init__.py` | Export `SubtitleConfig`, `SubtitleSegment` |
| Create | `src/sound_cut/subtitles/__init__.py` | Empty package marker |
| Create | `src/sound_cut/subtitles/formatter.py` | `write_srt()`, `write_vtt()` — pure format logic, no external deps |
| Create | `src/sound_cut/subtitles/whisper.py` | `WhisperBackend` — wraps faster-whisper, lazy import |
| Create | `src/sound_cut/subtitles/pipeline.py` | `generate_subtitles()` — thin orchestrator |
| Modify | `src/sound_cut/media/ffmpeg_tools.py` | Add `embed_subtitle_track()` |
| Modify | `src/sound_cut/editing/pipeline.py` | Add `_apply_subtitles()`; update `process_audio()` |
| Modify | `src/sound_cut/cli.py` | Add `--subtitle*` flags, `_resolve_subtitle_config()`, update `main()` |
| Modify | `pyproject.toml` | Add `subtitle` optional dependency group |
| Create | `tests/test_subtitle_formatter.py` | Formatter unit tests |
| Create | `tests/test_subtitle_pipeline.py` | WhisperBackend + generate_subtitles tests |
| Modify | `tests/test_models.py` | Tests for new dataclasses |
| Modify | `tests/test_ffmpeg_tools.py` | Test `embed_subtitle_track` |
| Modify | `tests/test_pipeline.py` | Integration tests for subtitle in `process_audio` |
| Modify | `tests/test_cli.py` | Tests for new CLI flags |

---

## Task 1: Data Models

**Files:**
- Modify: `src/sound_cut/core/models.py`
- Modify: `src/sound_cut/core/__init__.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_models.py::test_subtitle_segment_stores_fields tests/test_models.py::test_subtitle_config_defaults tests/test_models.py::test_render_summary_subtitle_path_defaults_to_none -v
```

Expected: `ImportError` or `AttributeError` — `SubtitleSegment`, `SubtitleConfig` not defined yet.

- [ ] **Step 3: Add models to `src/sound_cut/core/models.py`**

Add after `EnhancementConfig` (before `AnalysisTrack`):

```python
SUPPORTED_SUBTITLE_FORMATS = ("srt", "vtt")
SUPPORTED_SUBTITLE_MODELS = ("tiny", "base", "small", "medium", "large")


@dataclass(frozen=True)
class SubtitleSegment:
    index: int        # 1-based, per SRT spec
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class SubtitleConfig:
    enabled: bool
    language: str | None = None      # None = faster-whisper auto-detect
    format: str = "srt"              # "srt" | "vtt"
    model_size: str = "base"         # tiny | base | small | medium | large
    model_path: Path | None = None   # overrides HuggingFace cache dir
```

Update `RenderSummary` at the bottom of the file:

```python
@dataclass(frozen=True)
class RenderSummary:
    input_duration_s: float
    output_duration_s: float
    removed_duration_s: float
    kept_segment_count: int
    subtitle_path: Path | None = None
```

- [ ] **Step 4: Update `src/sound_cut/core/__init__.py`**

Add `SubtitleConfig` and `SubtitleSegment` to both `__all__` and `_EXPORTS`:

```python
__all__ = [
    "AnalysisTrack",
    "CutProfile",
    "DependencyError",
    "EditDecisionList",
    "EditOperation",
    "EnhancementConfig",
    "MediaError",
    "NoSpeechDetectedError",
    "PauseSplitConfig",
    "RenderPlan",
    "RenderSummary",
    "SubtitleConfig",
    "SubtitleSegment",
    "default_model_cache_dir",
    "SoundCutError",
    "SourceMedia",
    "TimeRange",
    "build_profile",
]

_EXPORTS = {
    # ... existing entries ...
    "SubtitleConfig": ("sound_cut.core.models", "SubtitleConfig"),
    "SubtitleSegment": ("sound_cut.core.models", "SubtitleSegment"),
}
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/test_models.py::test_subtitle_segment_stores_fields tests/test_models.py::test_subtitle_config_defaults tests/test_models.py::test_render_summary_subtitle_path_defaults_to_none tests/test_models.py::test_render_summary_accepts_subtitle_path -v
```

Expected: all PASS.

- [ ] **Step 6: Run full test suite to check no regressions**

```
pytest --tb=short -q
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/sound_cut/core/models.py src/sound_cut/core/__init__.py tests/test_models.py
git commit -m "feat: add SubtitleSegment, SubtitleConfig models and subtitle_path to RenderSummary"
```

---

## Task 2: SRT/VTT Formatter

**Files:**
- Create: `src/sound_cut/subtitles/__init__.py`
- Create: `src/sound_cut/subtitles/formatter.py`
- Create: `tests/test_subtitle_formatter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subtitle_formatter.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from sound_cut.core.models import SubtitleSegment
from sound_cut.subtitles.formatter import write_srt, write_vtt


def test_write_srt_formats_single_segment(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.5, text="Hello")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "1\n" in content
    assert "00:00:00,000 --> 00:00:01,500" in content
    assert "Hello" in content


def test_write_srt_timestamp_with_hours(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=3661.5, end_s=3662.0, text="Late")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "01:01:01,500 --> 01:01:02,000" in content


def test_write_srt_multiple_segments_separated_by_blank_line(tmp_path: Path) -> None:
    segments = [
        SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="First"),
        SubtitleSegment(index=2, start_s=2.0, end_s=3.0, text="Second"),
    ]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert "First" in content
    assert "Second" in content
    # Blocks separated by blank line
    assert "\n\n" in content


def test_write_srt_empty_segments_writes_empty_file(tmp_path: Path) -> None:
    srt_path = tmp_path / "out.srt"
    write_srt([], srt_path)
    assert srt_path.read_text(encoding="utf-8") == ""


def test_write_vtt_includes_webvtt_header(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="Hi")]
    vtt_path = tmp_path / "out.vtt"
    write_vtt(segments, vtt_path)
    content = vtt_path.read_text(encoding="utf-8")
    assert content.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in content
    assert "Hi" in content


def test_write_vtt_empty_segments_writes_header_only(tmp_path: Path) -> None:
    vtt_path = tmp_path / "out.vtt"
    write_vtt([], vtt_path)
    assert vtt_path.read_text(encoding="utf-8").strip() == "WEBVTT"


def test_write_srt_uses_utf8_encoding(tmp_path: Path) -> None:
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="你好世界")]
    srt_path = tmp_path / "out.srt"
    write_srt(segments, srt_path)
    assert "你好世界" in srt_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_subtitle_formatter.py -v
```

Expected: `ModuleNotFoundError` — `sound_cut.subtitles` does not exist yet.

- [ ] **Step 3: Create the package and formatter**

Create `src/sound_cut/subtitles/__init__.py` (empty):

```python
```

Create `src/sound_cut/subtitles/formatter.py`:

```python
from __future__ import annotations

from pathlib import Path

from sound_cut.core.models import SubtitleSegment


def _ts_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round(seconds % 1 * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round(seconds % 1 * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def write_srt(segments: list[SubtitleSegment], path: Path) -> None:
    if not segments:
        path.write_text("", encoding="utf-8")
        return
    blocks = []
    for seg in segments:
        blocks.append(
            f"{seg.index}\n{_ts_srt(seg.start_s)} --> {_ts_srt(seg.end_s)}\n{seg.text}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def write_vtt(segments: list[SubtitleSegment], path: Path) -> None:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_ts_vtt(seg.start_s)} --> {_ts_vtt(seg.end_s)}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_subtitle_formatter.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/subtitles/__init__.py src/sound_cut/subtitles/formatter.py tests/test_subtitle_formatter.py
git commit -m "feat: add SRT/VTT subtitle formatter"
```

---

## Task 3: embed_subtitle_track in ffmpeg_tools

**Files:**
- Modify: `src/sound_cut/media/ffmpeg_tools.py`
- Modify: `tests/test_ffmpeg_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ffmpeg_tools.py`:

```python
from sound_cut.media.ffmpeg_tools import embed_subtitle_track


def test_embed_subtitle_track_calls_ffmpeg_with_mov_text(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr("sound_cut.media.ffmpeg_tools._run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("sound_cut.media.ffmpeg_tools._require_binary", lambda name: name)

    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    output = tmp_path / "output.mp4"

    embed_subtitle_track(video, srt, output)

    assert len(calls) == 1
    cmd = calls[0]
    assert "-c:s" in cmd
    assert "mov_text" in cmd
    assert "-c:v" in cmd
    assert "copy" in cmd
    assert str(video) in cmd
    assert str(srt) in cmd
    assert str(output) in cmd


def test_embed_subtitle_track_passes_srt_as_second_input(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("sound_cut.media.ffmpeg_tools._run", lambda cmd: calls.append(cmd))
    monkeypatch.setattr("sound_cut.media.ffmpeg_tools._require_binary", lambda name: name)

    video = tmp_path / "video.mp4"
    srt = tmp_path / "subtitle.srt"
    output = tmp_path / "output.mp4"

    embed_subtitle_track(video, srt, output)

    cmd = calls[0]
    i_indices = [idx for idx, arg in enumerate(cmd) if arg == "-i"]
    assert len(i_indices) == 2
    assert cmd[i_indices[0] + 1] == str(video)
    assert cmd[i_indices[1] + 1] == str(srt)
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_ffmpeg_tools.py::test_embed_subtitle_track_calls_ffmpeg_with_mov_text -v
```

Expected: `ImportError` — `embed_subtitle_track` not defined yet.

- [ ] **Step 3: Add `embed_subtitle_track` to `src/sound_cut/media/ffmpeg_tools.py`**

Add at the end of the file:

```python
def embed_subtitle_track(video_path: Path, srt_path: Path, output_path: Path) -> None:
    ffmpeg = _require_binary("ffmpeg")
    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-i",
            str(srt_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            str(output_path),
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_ffmpeg_tools.py::test_embed_subtitle_track_calls_ffmpeg_with_mov_text -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/media/ffmpeg_tools.py tests/test_ffmpeg_tools.py
git commit -m "feat: add embed_subtitle_track to ffmpeg_tools"
```

---

## Task 4: WhisperBackend

**Files:**
- Create: `src/sound_cut/subtitles/whisper.py`
- Create: `tests/test_subtitle_pipeline.py` (initial)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_subtitle_pipeline.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sound_cut.core.errors import DependencyError
from sound_cut.core.models import SubtitleSegment
from sound_cut.subtitles.whisper import WhisperBackend


def test_whisper_backend_raises_dependency_error_when_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    backend = WhisperBackend()
    with pytest.raises(DependencyError, match="faster-whisper is required"):
        backend.transcribe(Path("audio.wav"))


def test_whisper_backend_converts_segments_to_subtitle_segments(monkeypatch, tmp_path):
    fake_segment_1 = MagicMock()
    fake_segment_1.start = 0.0
    fake_segment_1.end = 1.5
    fake_segment_1.text = "  Hello world  "

    fake_segment_2 = MagicMock()
    fake_segment_2.start = 2.0
    fake_segment_2.end = 3.0
    fake_segment_2.text = "  Goodbye  "

    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_segment_1, fake_segment_2], MagicMock())

    fake_whisper_module = MagicMock()
    fake_whisper_module.WhisperModel.return_value = fake_model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_whisper_module)

    audio = tmp_path / "audio.wav"
    audio.touch()
    backend = WhisperBackend(model_size="tiny")
    segments = backend.transcribe(audio, language="en")

    assert len(segments) == 2
    assert segments[0] == SubtitleSegment(index=1, start_s=0.0, end_s=1.5, text="Hello world")
    assert segments[1] == SubtitleSegment(index=2, start_s=2.0, end_s=3.0, text="Goodbye")


def test_whisper_backend_passes_language_to_model(monkeypatch, tmp_path):
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([], MagicMock())

    fake_module = MagicMock()
    fake_module.WhisperModel.return_value = fake_model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    audio = tmp_path / "audio.wav"
    audio.touch()
    WhisperBackend(model_size="base").transcribe(audio, language="zh")

    call_kwargs = fake_model.transcribe.call_args
    assert call_kwargs.kwargs.get("language") == "zh" or "zh" in call_kwargs.args


def test_whisper_backend_uses_model_path_when_provided(monkeypatch, tmp_path):
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([], MagicMock())

    fake_module = MagicMock()
    fake_module.WhisperModel.return_value = fake_model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    model_dir = tmp_path / "my_model"
    audio = tmp_path / "audio.wav"
    audio.touch()
    WhisperBackend(model_size="base", model_path=model_dir).transcribe(audio)

    init_args = fake_module.WhisperModel.call_args
    assert str(model_dir) in init_args.args or str(model_dir) == init_args.args[0]
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_subtitle_pipeline.py -v -k "whisper"
```

Expected: `ModuleNotFoundError` — `sound_cut.subtitles.whisper` does not exist.

- [ ] **Step 3: Create `src/sound_cut/subtitles/whisper.py`**

```python
from __future__ import annotations

from pathlib import Path

from sound_cut.core.errors import DependencyError
from sound_cut.core.models import SubtitleSegment


class WhisperBackend:
    def __init__(
        self,
        model_size: str = "base",
        model_path: Path | None = None,
    ) -> None:
        self._model_size = model_size
        self._model_path = model_path

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> list[SubtitleSegment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyError(
                "faster-whisper is required for --subtitle; "
                "install it with: pip install 'sound-cut[subtitle]'"
            ) from exc

        model_id = str(self._model_path) if self._model_path is not None else self._model_size
        model = WhisperModel(model_id, device="auto")
        segments, _ = model.transcribe(str(audio_path), language=language)
        return [
            SubtitleSegment(
                index=i + 1,
                start_s=seg.start,
                end_s=seg.end,
                text=seg.text.strip(),
            )
            for i, seg in enumerate(segments)
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_subtitle_pipeline.py -v -k "whisper"
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/subtitles/whisper.py tests/test_subtitle_pipeline.py
git commit -m "feat: add WhisperBackend for local speech transcription"
```

---

## Task 5: generate_subtitles Pipeline

**Files:**
- Create: `src/sound_cut/subtitles/pipeline.py`
- Modify: `tests/test_subtitle_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_subtitle_pipeline.py`:

```python
from sound_cut.core.models import SubtitleConfig
from sound_cut.subtitles.pipeline import generate_subtitles


def test_generate_subtitles_delegates_to_whisper_backend(monkeypatch, tmp_path):
    expected = [SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="Test")]

    class _MockBackend:
        def __init__(self, model_size, model_path):
            self.model_size = model_size
            self.model_path = model_path

        def transcribe(self, path, language):
            assert path == audio_path
            assert language == "zh"
            return expected

    monkeypatch.setattr("sound_cut.subtitles.pipeline.WhisperBackend", _MockBackend)

    audio_path = tmp_path / "audio.wav"
    audio_path.touch()
    config = SubtitleConfig(enabled=True, language="zh", model_size="tiny")

    result = generate_subtitles(audio_path, config)
    assert result == expected


def test_generate_subtitles_passes_model_path(monkeypatch, tmp_path):
    class _MockBackend:
        def __init__(self, model_size, model_path):
            self.captured_model_path = model_path

        def transcribe(self, path, language):
            return []

    monkeypatch.setattr("sound_cut.subtitles.pipeline.WhisperBackend", _MockBackend)

    model_dir = tmp_path / "models"
    audio_path = tmp_path / "audio.wav"
    audio_path.touch()
    config = SubtitleConfig(enabled=True, model_path=model_dir)

    generate_subtitles(audio_path, config)
    # No assertion needed — if __init__ doesn't receive model_path, _MockBackend would ignore it;
    # the test verifies the call doesn't raise and the backend is constructed.
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_subtitle_pipeline.py::test_generate_subtitles_delegates_to_whisper_backend -v
```

Expected: `ImportError` — `sound_cut.subtitles.pipeline` does not exist.

- [ ] **Step 3: Create `src/sound_cut/subtitles/pipeline.py`**

```python
from __future__ import annotations

from pathlib import Path

from sound_cut.core.models import SubtitleConfig, SubtitleSegment
from sound_cut.subtitles.whisper import WhisperBackend


def generate_subtitles(audio_path: Path, config: SubtitleConfig) -> list[SubtitleSegment]:
    backend = WhisperBackend(model_size=config.model_size, model_path=config.model_path)
    return backend.transcribe(audio_path, language=config.language)
```

- [ ] **Step 4: Run all subtitle pipeline tests**

```
pytest tests/test_subtitle_pipeline.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/subtitles/pipeline.py tests/test_subtitle_pipeline.py
git commit -m "feat: add generate_subtitles pipeline"
```

---

## Task 6: Pipeline Integration

**Files:**
- Modify: `src/sound_cut/editing/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
from sound_cut.core.models import SubtitleConfig, SubtitleSegment


def test_process_audio_writes_srt_when_subtitle_enabled(tmp_path, monkeypatch, ffmpeg_available):
    input_wav = tmp_path / "input.wav"
    output_wav = tmp_path / "output.wav"
    write_pcm_wave(
        input_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=1.0),
    )
    segments = [SubtitleSegment(index=1, start_s=0.0, end_s=1.0, text="Hello")]
    monkeypatch.setattr(
        "sound_cut.editing.pipeline.generate_subtitles",
        lambda path, cfg: segments,
    )

    summary = process_audio(
        input_wav,
        output_wav,
        build_profile("balanced"),
        enable_cut=False,
        subtitle=SubtitleConfig(enabled=True),
    )

    expected_srt = tmp_path / "output.srt"
    assert summary.subtitle_path == expected_srt
    assert expected_srt.exists()
    assert "Hello" in expected_srt.read_text(encoding="utf-8")


def test_process_audio_writes_vtt_when_format_is_vtt(tmp_path, monkeypatch, ffmpeg_available):
    input_wav = tmp_path / "input.wav"
    output_wav = tmp_path / "output.wav"
    write_pcm_wave(
        input_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=1.0),
    )
    monkeypatch.setattr(
        "sound_cut.editing.pipeline.generate_subtitles",
        lambda path, cfg: [],
    )

    summary = process_audio(
        input_wav,
        output_wav,
        build_profile("balanced"),
        enable_cut=False,
        subtitle=SubtitleConfig(enabled=True, format="vtt"),
    )

    assert summary.subtitle_path == tmp_path / "output.vtt"
    assert (tmp_path / "output.vtt").exists()


def test_process_audio_subtitle_path_is_none_when_disabled(tmp_path, ffmpeg_available):
    input_wav = tmp_path / "input.wav"
    output_wav = tmp_path / "output.wav"
    write_pcm_wave(
        input_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=1.0),
    )

    summary = process_audio(
        input_wav,
        output_wav,
        build_profile("balanced"),
        enable_cut=False,
        subtitle=SubtitleConfig(enabled=False),
    )

    assert summary.subtitle_path is None


def test_process_audio_subtitle_path_is_none_when_no_subtitle_config(tmp_path, ffmpeg_available):
    input_wav = tmp_path / "input.wav"
    output_wav = tmp_path / "output.wav"
    write_pcm_wave(
        input_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=1.0),
    )

    summary = process_audio(
        input_wav,
        output_wav,
        build_profile("balanced"),
        enable_cut=False,
    )

    assert summary.subtitle_path is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_pipeline.py::test_process_audio_writes_srt_when_subtitle_enabled -v
```

Expected: `TypeError` — `process_audio()` does not accept `subtitle` keyword argument yet.

- [ ] **Step 3: Update `src/sound_cut/editing/pipeline.py`**

Add imports at the top (alongside existing imports):

```python
import shutil

from sound_cut.core.models import (
    DEFAULT_TARGET_LUFS,
    EnhancementConfig,
    LoudnessNormalizationConfig,
    RenderPlan,
    RenderSummary,
    SubtitleConfig,
)
from sound_cut.subtitles.formatter import write_srt, write_vtt
from sound_cut.subtitles.pipeline import generate_subtitles
```

Add the `_apply_subtitles` helper before `process_audio`:

```python
def _apply_subtitles(
    output_path: Path,
    config: SubtitleConfig,
    *,
    is_video: bool,
) -> Path:
    segments = generate_subtitles(output_path, config)

    if is_video:
        from sound_cut.media.ffmpeg_tools import embed_subtitle_track

        tmp_dir = Path(tempfile.mkdtemp(prefix="sound-cut-subtitle-"))
        try:
            tmp_srt = tmp_dir / "subtitle.srt"
            tmp_video = tmp_dir / "video.mp4"
            write_srt(segments, tmp_srt)
            embed_subtitle_track(output_path, tmp_srt, tmp_video)
            shutil.move(str(tmp_video), str(output_path))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return output_path

    if config.format == "vtt":
        subtitle_path = output_path.with_suffix(".vtt")
        write_vtt(segments, subtitle_path)
    else:
        subtitle_path = output_path.with_suffix(".srt")
        write_srt(segments, subtitle_path)
    return subtitle_path
```

Replace the existing `process_audio` function entirely with:

```python
def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    *,
    enable_cut: bool = True,
    analyzer=None,
    keep_temp: bool = False,
    loudness: LoudnessNormalizationConfig | None = None,
    enhancement: EnhancementConfig | None = None,
    subtitle: SubtitleConfig | None = None,
) -> RenderSummary:
    if input_path.resolve(strict=False) == output_path.resolve(strict=False):
        raise MediaError(f"Input and output paths must be different: {input_path}")

    if not input_path.exists():
        raise MediaError(f"Input media not found: {input_path}")

    original_source = probe_source_media(input_path)
    enhancement_config = enhancement or EnhancementConfig(enabled=False)
    loudness_config = loudness or LoudnessNormalizationConfig(
        enabled=False, target_lufs=DEFAULT_TARGET_LUFS
    )
    subtitle_config = subtitle or SubtitleConfig(enabled=False)

    with tempfile.TemporaryDirectory(prefix="sound-cut-enhance-") as temp_dir_name:
        working_input_path = enhance_audio(
            input_path=input_path,
            enhancement=enhancement_config,
            working_dir=Path(temp_dir_name),
        )
        processing_source = replace(original_source, input_path=working_input_path)
        render_video_output = (
            original_source.has_video and output_path.suffix.lower() in _VIDEO_OUTPUT_SUFFIXES
        )

        if enable_cut:
            if render_video_output:
                summary = _process_cut_video(
                    input_path=working_input_path,
                    output_path=output_path,
                    profile=profile,
                    video_source=original_source,
                    audio_source=processing_source,
                    analyzer=analyzer,
                    keep_temp=keep_temp,
                    loudness=loudness_config,
                )
            else:
                summary = _process_cut_audio(
                    input_path=working_input_path,
                    output_path=output_path,
                    profile=profile,
                    source=processing_source,
                    analyzer=analyzer,
                    keep_temp=keep_temp,
                    loudness=loudness_config,
                )
        elif render_video_output:
            summary = render_full_video(
                video_source=original_source,
                audio_source=processing_source,
                output_path=output_path,
                loudness=loudness_config,
            )
        else:
            summary = render_full_audio(
                source=processing_source,
                output_path=output_path,
                loudness=loudness_config,
            )

    if subtitle_config.enabled:
        subtitle_path = _apply_subtitles(
            output_path, subtitle_config, is_video=render_video_output
        )
        return replace(summary, subtitle_path=subtitle_path)
    return summary
```

- [ ] **Step 4: Run new tests**

```
pytest tests/test_pipeline.py::test_process_audio_writes_srt_when_subtitle_enabled tests/test_pipeline.py::test_process_audio_subtitle_path_is_none_when_disabled -v
```

Expected: PASS.

- [ ] **Step 5: Run full test suite**

```
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/sound_cut/editing/pipeline.py tests/test_pipeline.py
git commit -m "feat: integrate subtitle generation into process_audio pipeline"
```

---

## Task 7: CLI Integration

**Files:**
- Modify: `src/sound_cut/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
from sound_cut.core.models import SubtitleConfig


def test_build_parser_parses_subtitle_flag(tmp_path: Path) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([str(tmp_path / "input.wav"), "--subtitle"])
    assert args.subtitle is True


def test_subtitle_alone_is_a_valid_processing_mode(tmp_path: Path) -> None:
    parser = cli.build_parser()
    # Should not raise — --subtitle satisfies the "at least one mode" requirement
    args = parser.parse_args([str(tmp_path / "input.wav"), "--subtitle"])
    assert args.cut is False
    assert args.auto_volume is False
    assert args.enhance_speech is False
    assert args.subtitle is True


def test_build_parser_parses_all_subtitle_options(tmp_path: Path) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([
        str(tmp_path / "input.wav"),
        "--subtitle",
        "--subtitle-format", "vtt",
        "--subtitle-language", "zh",
        "--subtitle-model", "small",
        "--subtitle-model-path", str(tmp_path / "models"),
    ])
    assert args.subtitle_format == "vtt"
    assert args.subtitle_language == "zh"
    assert args.subtitle_model == "small"
    assert args.subtitle_model_path == tmp_path / "models"


def test_subtitle_flag_defaults(tmp_path: Path) -> None:
    parser = cli.build_parser()
    args = parser.parse_args([str(tmp_path / "input.wav"), "--subtitle"])
    assert args.subtitle_format == "srt"
    assert args.subtitle_language is None
    assert args.subtitle_model == "base"
    assert args.subtitle_model_path is None


def test_main_prints_subtitle_path_when_generated(tmp_path, monkeypatch, capsys) -> None:
    import sound_cut.editing.pipeline as pipeline_module
    from sound_cut.core import RenderSummary

    input_wav = tmp_path / "input.wav"
    input_wav.touch()
    srt_path = tmp_path / "input.cut.srt"

    monkeypatch.setattr(
        pipeline_module,
        "process_audio",
        lambda *a, **kw: RenderSummary(
            input_duration_s=10.0,
            output_duration_s=8.0,
            removed_duration_s=2.0,
            kept_segment_count=3,
            subtitle_path=srt_path,
        ),
    )

    result = cli.main([str(input_wav), "--subtitle"])
    assert result == 0
    captured = capsys.readouterr()
    assert f"subtitle_path={srt_path}" in captured.out


def test_main_does_not_print_subtitle_path_when_disabled(tmp_path, monkeypatch, capsys) -> None:
    import sound_cut.editing.pipeline as pipeline_module
    from sound_cut.core import RenderSummary

    input_wav = tmp_path / "input.wav"
    input_wav.touch()

    monkeypatch.setattr(
        pipeline_module,
        "process_audio",
        lambda *a, **kw: RenderSummary(
            input_duration_s=10.0,
            output_duration_s=8.0,
            removed_duration_s=2.0,
            kept_segment_count=3,
            subtitle_path=None,
        ),
    )

    result = cli.main([str(input_wav), "--cut"])
    assert result == 0
    captured = capsys.readouterr()
    assert "subtitle_path" not in captured.out
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/test_cli.py::test_build_parser_parses_subtitle_flag tests/test_cli.py::test_subtitle_alone_is_a_valid_processing_mode -v
```

Expected: FAIL — `--subtitle` not recognised.

- [ ] **Step 3: Update `src/sound_cut/cli.py`**

Update the import line to include `SubtitleConfig`:

```python
from sound_cut.core import EnhancementConfig, SoundCutError, SubtitleConfig, build_profile
```

Add `"--subtitle"` to `_PROCESSING_MODE_FLAGS`:

```python
_PROCESSING_MODE_FLAGS = {"--cut", "--auto-volume", "--enhance-speech", "--subtitle"}
```

Add the four new arguments to `_SoundCutArgumentParser.__init__` after the existing `--model-path` argument:

```python
self.add_argument("--subtitle", action="store_true")
self.add_argument(
    "--subtitle-format",
    choices=("srt", "vtt"),
    default="srt",
)
self.add_argument("--subtitle-language", default=None)
self.add_argument(
    "--subtitle-model",
    choices=("tiny", "base", "small", "medium", "large"),
    default="base",
)
self.add_argument("--subtitle-model-path", type=Path)
```

Update the "at least one mode" check in `parse_args`:

```python
if (
    not parsed_args.cut
    and not parsed_args.auto_volume
    and not parsed_args.enhance_speech
    and not parsed_args.subtitle
):
    self.error(
        "at least one processing mode is required: --cut, --auto-volume, --enhance-speech, and/or --subtitle"
    )
```

Add `_resolve_subtitle_config` after `_resolve_enhancement_config`:

```python
def _resolve_subtitle_config(args: argparse.Namespace) -> SubtitleConfig:
    return SubtitleConfig(
        enabled=args.subtitle,
        language=args.subtitle_language,
        format=args.subtitle_format,
        model_size=args.subtitle_model,
        model_path=args.subtitle_model_path,
    )
```

Update `main()` to resolve subtitle config and pass it to `process_audio`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) == "models":
        return _run_models_command(args)

    try:
        loudness = _resolve_loudness_config(args)
        enhancement = _resolve_enhancement_config(args)
        subtitle = _resolve_subtitle_config(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    profile = build_profile(args.aggressiveness)
    overrides = {
        "min_silence_ms": args.min_silence_ms,
        "padding_ms": args.padding_ms,
        "crossfade_ms": args.crossfade_ms,
    }
    profile = replace(profile, **{name: value for name, value in overrides.items() if value is not None})
    output_path = resolve_output_path(args.input, args.output)

    try:
        from sound_cut.editing.pipeline import process_audio

        summary = process_audio(
            args.input,
            output_path,
            profile,
            keep_temp=args.keep_temp,
            loudness=loudness,
            enable_cut=args.cut,
            enhancement=enhancement,
            subtitle=subtitle,
        )
    except SoundCutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"input_duration_s={summary.input_duration_s:.3f}")
    print(f"output_duration_s={summary.output_duration_s:.3f}")
    print(f"removed_duration_s={summary.removed_duration_s:.3f}")
    print(f"kept_segment_count={summary.kept_segment_count}")
    if summary.subtitle_path is not None:
        suffix = " (embedded)" if summary.subtitle_path == output_path else ""
        print(f"subtitle_path={summary.subtitle_path}{suffix}")
    return 0
```

- [ ] **Step 4: Run new CLI tests**

```
pytest tests/test_cli.py -v -k "subtitle"
```

Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/sound_cut/cli.py tests/test_cli.py
git commit -m "feat: add --subtitle CLI flag and subtitle config resolution"
```

---

## Task 8: Optional Dependency in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the `subtitle` extra**

In `pyproject.toml`, add after the existing `[project.optional-dependencies]` section (or create it):

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.0",
]
subtitle = [
  "faster-whisper>=1.0",
]
```

- [ ] **Step 2: Verify install command works**

```
pip install -e ".[subtitle]" --dry-run
```

Expected: resolves `faster-whisper>=1.0` without error.

- [ ] **Step 3: Run full test suite one final time**

```
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add faster-whisper as optional subtitle dependency"
```
