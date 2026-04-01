# Audio Silence Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that removes long silent gaps from single-speaker spoken audio, preserves natural-sounding speech continuity, and emits a reusable edit decision list that future video/subtitle features can share.

**Architecture:** The implementation is centered on a canonical edit decision list (EDL). Media ingestion and VAD analysis produce time-aligned speech ranges, timeline shaping converts those ranges into a reusable keep/discard model, and the audio renderer consumes that model to write the final output. Renderer smoothing uses per-segment fades rather than overlap-based crossfades so output duration remains aligned with the EDL for future synchronized video and subtitle support.

**Tech Stack:** Python 3.11+, `argparse`, `dataclasses`, `pathlib`, `subprocess`, `tempfile`, `wave`, `json`, `pytest`, `webrtcvad`, external `ffmpeg` / `ffprobe`

---

## File Structure

### Create

- `pyproject.toml`
- `src/sound_cut/__init__.py`
- `src/sound_cut/__main__.py`
- `src/sound_cut/cli.py`
- `src/sound_cut/config.py`
- `src/sound_cut/errors.py`
- `src/sound_cut/models.py`
- `src/sound_cut/ffmpeg_tools.py`
- `src/sound_cut/timeline.py`
- `src/sound_cut/vad.py`
- `src/sound_cut/render.py`
- `src/sound_cut/pipeline.py`
- `tests/conftest.py`
- `tests/helpers.py`
- `tests/test_cli.py`
- `tests/test_timeline.py`
- `tests/test_ffmpeg_tools.py`
- `tests/test_vad.py`
- `tests/test_render.py`
- `tests/test_pipeline.py`

### Responsibilities

- `src/sound_cut/config.py`: public profile defaults and CLI-tunable processing settings
- `src/sound_cut/errors.py`: domain exceptions surfaced by CLI
- `src/sound_cut/models.py`: source media, time ranges, analysis tracks, EDL, render plan, summary types
- `src/sound_cut/ffmpeg_tools.py`: `ffprobe` metadata, source normalization, segment extraction, final concat
- `src/sound_cut/timeline.py`: pure interval shaping and source-to-output timestamp mapping
- `src/sound_cut/vad.py`: WebRTC VAD wrapper that emits a reusable speech analysis track
- `src/sound_cut/render.py`: audio render plan and output writing from the EDL
- `src/sound_cut/pipeline.py`: top-level orchestration from input file to summary
- `src/sound_cut/cli.py`: argument parsing, error handling, terminal output
- `tests/helpers.py`: temporary WAV generation utilities for deterministic tests

### Preconditions

- If this directory is still not a git repository, initialize it before Task 1 commit steps:

```bash
test -d .git || git init
```

## Task 1: Bootstrap Package And CLI Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/sound_cut/__init__.py`
- Create: `src/sound_cut/__main__.py`
- Create: `src/sound_cut/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke test**

```python
# tests/test_cli.py
from pathlib import Path

from sound_cut.cli import build_parser


def test_build_parser_parses_required_arguments(tmp_path: Path) -> None:
    parser = build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav")])

    assert args.input == tmp_path / "input.wav"
    assert args.output == tmp_path / "output.wav"
    assert args.aggressiveness == "balanced"
    assert args.min_silence_ms is None
    assert args.padding_ms is None
    assert args.crossfade_ms is None
    assert args.keep_temp is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py::test_build_parser_parses_required_arguments -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sound_cut'`

- [ ] **Step 3: Write the minimal package and parser implementation**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "sound-cut"
version = "0.1.0"
description = "CLI tool for cutting long silent gaps from spoken audio"
requires-python = ">=3.11"
dependencies = [
  "webrtcvad==2.0.10",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
]

[project.scripts]
sound-cut = "sound_cut.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```python
# src/sound_cut/__init__.py
__all__ = ["__version__"]

__version__ = "0.1.0"
```

```python
# src/sound_cut/__main__.py
from sound_cut.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# src/sound_cut/cli.py
from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=int)
    parser.add_argument("--padding-ms", type=int)
    parser.add_argument("--crossfade-ms", type=int)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main() -> int:
    build_parser().parse_args()
    return 0
```

- [ ] **Step 4: Install dependencies and run the test to verify it passes**

Run: `python3 -m pip install -e ".[dev]"`
Expected: editable install completes and includes `webrtcvad`

Run: `python3 -m pytest tests/test_cli.py::test_build_parser_parses_required_arguments -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
test -d .git || git init
git add pyproject.toml src/sound_cut/__init__.py src/sound_cut/__main__.py src/sound_cut/cli.py tests/test_cli.py
git commit -m "chore: bootstrap sound cut cli package"
```

## Task 2: Add Core Models, Profiles, And Timeline Logic

**Files:**
- Create: `src/sound_cut/config.py`
- Create: `src/sound_cut/errors.py`
- Create: `src/sound_cut/models.py`
- Create: `src/sound_cut/timeline.py`
- Create: `tests/test_timeline.py`

- [ ] **Step 1: Write the failing interval-shaping tests**

```python
# tests/test_timeline.py
from sound_cut.config import build_profile
from sound_cut.models import TimeRange
from sound_cut.timeline import build_edit_decision_list, kept_ranges, source_to_output_time


def test_build_edit_decision_list_keeps_short_pause_and_drops_long_pause() -> None:
    profile = build_profile("balanced")
    speech_ranges = (
        TimeRange(0.50, 1.00),
        TimeRange(1.18, 1.50),
        TimeRange(2.60, 3.20),
    )

    edl = build_edit_decision_list(
        duration_s=4.00,
        speech_ranges=speech_ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )

    assert kept_ranges(edl) == (
        TimeRange(0.40, 1.60),
        TimeRange(2.50, 3.30),
    )


def test_source_to_output_time_remaps_kept_ranges() -> None:
    profile = build_profile("balanced")
    speech_ranges = (
        TimeRange(0.50, 1.00),
        TimeRange(2.50, 3.00),
    )

    edl = build_edit_decision_list(
        duration_s=4.00,
        speech_ranges=speech_ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )

    assert source_to_output_time(edl, 0.60) == 0.20
    assert source_to_output_time(edl, 2.60) == 0.90
    assert source_to_output_time(edl, 1.70) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_timeline.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbol errors for `build_profile`, `TimeRange`, and timeline functions

- [ ] **Step 3: Write the minimal models, profile defaults, errors, and timeline implementation**

```python
# src/sound_cut/config.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CutProfile:
    name: str
    vad_mode: int
    merge_gap_ms: int
    min_silence_ms: int
    padding_ms: int
    crossfade_ms: int


_PROFILES = {
    "natural": CutProfile("natural", vad_mode=1, merge_gap_ms=180, min_silence_ms=700, padding_ms=120, crossfade_ms=12),
    "balanced": CutProfile("balanced", vad_mode=2, merge_gap_ms=200, min_silence_ms=550, padding_ms=100, crossfade_ms=10),
    "dense": CutProfile("dense", vad_mode=3, merge_gap_ms=220, min_silence_ms=380, padding_ms=80, crossfade_ms=8),
}


def build_profile(name: str) -> CutProfile:
    return _PROFILES[name]
```

```python
# src/sound_cut/errors.py
class SoundCutError(Exception):
    """Base exception for expected CLI-facing failures."""


class DependencyError(SoundCutError):
    """Raised when ffmpeg or ffprobe is unavailable."""


class MediaError(SoundCutError):
    """Raised when input media cannot be read or written."""


class NoSpeechDetectedError(SoundCutError):
    """Raised when the analyzer finds no usable speech."""
```

```python
# src/sound_cut/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, order=True)
class TimeRange:
    start_s: float
    end_s: float

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError("end_s must be >= start_s")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class SourceMedia:
    input_path: Path
    duration_s: float
    audio_codec: str | None
    sample_rate_hz: int | None
    channels: int | None
    has_video: bool = False


@dataclass(frozen=True)
class AnalysisTrack:
    name: str
    ranges: tuple[TimeRange, ...]
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EditOperation:
    action: Literal["keep", "discard"]
    range: TimeRange
    reason: str | None = None


@dataclass(frozen=True)
class EditDecisionList:
    operations: tuple[EditOperation, ...]


@dataclass(frozen=True)
class RenderPlan:
    source: SourceMedia
    edl: EditDecisionList
    output_path: Path
    target: Literal["audio"]
    crossfade_ms: int


@dataclass(frozen=True)
class RenderSummary:
    input_duration_s: float
    output_duration_s: float
    removed_duration_s: float
    kept_segment_count: int
```

```python
# src/sound_cut/timeline.py
from __future__ import annotations

from sound_cut.models import EditDecisionList, EditOperation, TimeRange


def _round(value: float) -> float:
    return round(value, 3)


def _merge_ranges(ranges: tuple[TimeRange, ...], merge_gap_ms: int) -> tuple[TimeRange, ...]:
    if not ranges:
        return ()
    merge_gap_s = merge_gap_ms / 1000
    merged = [ranges[0]]
    for current in ranges[1:]:
        previous = merged[-1]
        if current.start_s - previous.end_s <= merge_gap_s:
            merged[-1] = TimeRange(previous.start_s, max(previous.end_s, current.end_s))
        else:
            merged.append(current)
    return tuple(merged)


def _pad_ranges(ranges: tuple[TimeRange, ...], duration_s: float, padding_ms: int) -> tuple[TimeRange, ...]:
    padding_s = padding_ms / 1000
    return tuple(
        TimeRange(
            start_s=max(0.0, _round(item.start_s - padding_s)),
            end_s=min(duration_s, _round(item.end_s + padding_s)),
        )
        for item in ranges
    )


def build_edit_decision_list(
    *,
    duration_s: float,
    speech_ranges: tuple[TimeRange, ...],
    padding_ms: int,
    min_silence_ms: int,
    merge_gap_ms: int,
) -> EditDecisionList:
    merged = _merge_ranges(tuple(sorted(speech_ranges)), merge_gap_ms)
    padded = _merge_ranges(_pad_ranges(merged, duration_s, padding_ms), merge_gap_ms)
    keep_ops = tuple(EditOperation("keep", item, "speech") for item in padded if item.duration_s > 0)
    return EditDecisionList(operations=keep_ops)


def kept_ranges(edl: EditDecisionList) -> tuple[TimeRange, ...]:
    return tuple(operation.range for operation in edl.operations if operation.action == "keep")


def source_to_output_time(edl: EditDecisionList, source_time_s: float) -> float | None:
    cursor = 0.0
    for keep_range in kept_ranges(edl):
        if keep_range.start_s <= source_time_s <= keep_range.end_s:
            return _round(cursor + (source_time_s - keep_range.start_s))
        cursor += keep_range.duration_s
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_timeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/config.py src/sound_cut/errors.py src/sound_cut/models.py src/sound_cut/timeline.py tests/test_timeline.py
git commit -m "feat: add timeline models and cut profiles"
```

## Task 3: Add ffprobe Metadata And Audio Normalization Adapters

**Files:**
- Create: `src/sound_cut/ffmpeg_tools.py`
- Create: `tests/conftest.py`
- Create: `tests/helpers.py`
- Create: `tests/test_ffmpeg_tools.py`

- [ ] **Step 1: Write the failing ffmpeg adapter tests**

```python
# tests/helpers.py
from __future__ import annotations

import math
import wave
from pathlib import Path


def write_pcm_wave(path: Path, *, sample_rate_hz: int, samples: list[int], channels: int = 1) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples))


def tone_samples(*, sample_rate_hz: int, duration_s: float, frequency_hz: float = 220.0, amplitude: int = 6000) -> list[int]:
    frame_count = int(sample_rate_hz * duration_s)
    return [
        int(amplitude * math.sin(2 * math.pi * frequency_hz * index / sample_rate_hz))
        for index in range(frame_count)
    ]


def silence_samples(*, sample_rate_hz: int, duration_s: float) -> list[int]:
    return [0] * int(sample_rate_hz * duration_s)
```

```python
# tests/conftest.py
from __future__ import annotations

import shutil

import pytest


@pytest.fixture(scope="session")
def ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required for integration tests")
```

```python
# tests/test_ffmpeg_tools.py
import wave

from sound_cut.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_probe_source_media_reads_basic_wave_metadata(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48000,
        samples=tone_samples(sample_rate_hz=48000, duration_s=0.5) + silence_samples(sample_rate_hz=48000, duration_s=0.5),
    )

    media = probe_source_media(input_path)

    assert media.input_path == input_path
    assert round(media.duration_s, 2) == 1.00
    assert media.sample_rate_hz == 48000
    assert media.channels == 1
    assert media.has_video is False


def test_normalize_audio_for_analysis_outputs_mono_16k_wave(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48000,
        samples=tone_samples(sample_rate_hz=48000, duration_s=0.25) + silence_samples(sample_rate_hz=48000, duration_s=0.25),
    )

    normalize_audio_for_analysis(input_path, output_path, sample_rate_hz=16000)

    with wave.open(str(output_path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16000
        assert handle.getsampwidth() == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ffmpeg_tools.py -v`
Expected: FAIL with missing module or missing symbol errors for `probe_source_media` / `normalize_audio_for_analysis`

- [ ] **Step 3: Write the minimal ffmpeg adapter implementation**

```python
# src/sound_cut/ffmpeg_tools.py
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from sound_cut.errors import DependencyError, MediaError
from sound_cut.models import SourceMedia


def _require_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise DependencyError(f"Required dependency '{name}' is not installed or not on PATH")
    return binary


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise MediaError(exc.stderr.strip() or exc.stdout.strip() or "ffmpeg command failed") from exc


def probe_source_media(input_path: Path) -> SourceMedia:
    ffprobe = _require_binary("ffprobe")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(input_path),
        ]
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    return SourceMedia(
        input_path=input_path,
        duration_s=float(payload["format"]["duration"]),
        audio_codec=audio_stream.get("codec_name"),
        sample_rate_hz=int(audio_stream["sample_rate"]) if audio_stream.get("sample_rate") else None,
        channels=audio_stream.get("channels"),
        has_video=video_stream is not None,
    )


def normalize_audio_for_analysis(input_path: Path, output_path: Path, *, sample_rate_hz: int) -> None:
    ffmpeg = _require_binary("ffmpeg")
    _run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate_hz),
            "-sample_fmt",
            "s16",
            str(output_path),
        ]
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ffmpeg_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/ffmpeg_tools.py tests/conftest.py tests/helpers.py tests/test_ffmpeg_tools.py
git commit -m "feat: add ffmpeg probe and normalization adapters"
```

## Task 4: Add WebRTC VAD Analyzer And Speech Track Generation

**Files:**
- Create: `src/sound_cut/vad.py`
- Create: `tests/test_vad.py`

- [ ] **Step 1: Write the failing VAD tests**

```python
# tests/test_vad.py
from sound_cut.config import build_profile
from sound_cut.models import TimeRange
from sound_cut.vad import collapse_speech_flags, frame_duration_bytes, split_frames


def test_frame_duration_bytes_matches_30ms_mono_16bit_audio() -> None:
    assert frame_duration_bytes(sample_rate_hz=16000, frame_ms=30) == 960


def test_split_frames_discards_partial_tail() -> None:
    data = b"x" * (960 * 2 + 100)

    frames = split_frames(data, sample_rate_hz=16000, frame_ms=30)

    assert len(frames) == 2
    assert all(len(frame) == 960 for frame in frames)


def test_collapse_speech_flags_converts_frames_to_ranges() -> None:
    profile = build_profile("balanced")
    flags = [False, True, True, False, False, True, True, True]

    ranges = collapse_speech_flags(flags, frame_ms=30, merge_gap_ms=profile.merge_gap_ms)

    assert ranges == (
        TimeRange(0.03, 0.09),
        TimeRange(0.15, 0.24),
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_vad.py -v`
Expected: FAIL with missing module or missing symbol errors for VAD helpers

- [ ] **Step 3: Write the minimal VAD helper and analyzer implementation**

```python
# src/sound_cut/vad.py
from __future__ import annotations

import wave
from pathlib import Path

import webrtcvad

from sound_cut.models import AnalysisTrack, TimeRange


def frame_duration_bytes(*, sample_rate_hz: int, frame_ms: int) -> int:
    return int(sample_rate_hz * (frame_ms / 1000) * 2)


def split_frames(data: bytes, *, sample_rate_hz: int, frame_ms: int) -> list[bytes]:
    frame_size = frame_duration_bytes(sample_rate_hz=sample_rate_hz, frame_ms=frame_ms)
    usable_length = len(data) - (len(data) % frame_size)
    return [data[index:index + frame_size] for index in range(0, usable_length, frame_size)]


def collapse_speech_flags(flags: list[bool], *, frame_ms: int, merge_gap_ms: int) -> tuple[TimeRange, ...]:
    ranges: list[TimeRange] = []
    start_index: int | None = None
    for index, is_speech in enumerate(flags):
        if is_speech and start_index is None:
            start_index = index
        if not is_speech and start_index is not None:
            ranges.append(TimeRange(round(start_index * frame_ms / 1000, 3), round(index * frame_ms / 1000, 3)))
            start_index = None
    if start_index is not None:
        ranges.append(TimeRange(round(start_index * frame_ms / 1000, 3), round(len(flags) * frame_ms / 1000, 3)))
    return tuple(ranges)


class WebRtcSpeechAnalyzer:
    def __init__(self, *, vad_mode: int, frame_ms: int = 30) -> None:
        self._vad = webrtcvad.Vad(vad_mode)
        self._frame_ms = frame_ms

    def analyze(self, wav_path: Path) -> AnalysisTrack:
        with wave.open(str(wav_path), "rb") as handle:
            sample_rate_hz = handle.getframerate()
            pcm = handle.readframes(handle.getnframes())
        frames = split_frames(pcm, sample_rate_hz=sample_rate_hz, frame_ms=self._frame_ms)
        flags = [self._vad.is_speech(frame, sample_rate_hz) for frame in frames]
        return AnalysisTrack(
            name="speech",
            ranges=collapse_speech_flags(flags, frame_ms=self._frame_ms, merge_gap_ms=0),
            metadata={"frame_ms": str(self._frame_ms)},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_vad.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/vad.py tests/test_vad.py
git commit -m "feat: add webrtc speech analysis helpers"
```

## Task 5: Add Audio Renderer That Preserves EDL Duration

**Files:**
- Create: `src/sound_cut/render.py`
- Create: `tests/test_render.py`

- [ ] **Step 1: Write the failing renderer test**

```python
# tests/test_render.py
import wave

from sound_cut.models import EditDecisionList, EditOperation, RenderPlan, SourceMedia, TimeRange
from sound_cut.render import render_audio_from_edl
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_render_audio_from_edl_keeps_only_requested_ranges(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = (
        tone_samples(sample_rate_hz=16000, duration_s=0.5)
        + silence_samples(sample_rate_hz=16000, duration_s=0.5)
        + tone_samples(sample_rate_hz=16000, duration_s=0.5)
    )
    write_pcm_wave(input_path, sample_rate_hz=16000, samples=samples)
    source = SourceMedia(
        input_path=input_path,
        duration_s=1.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16000,
        channels=1,
        has_video=False,
    )
    edl = EditDecisionList(
        operations=(
            EditOperation("keep", TimeRange(0.0, 0.5), "speech"),
            EditOperation("keep", TimeRange(1.0, 1.5), "speech"),
        )
    )
    plan = RenderPlan(source=source, edl=edl, output_path=output_path, target="audio", crossfade_ms=10)

    summary = render_audio_from_edl(plan)

    with wave.open(str(output_path), "rb") as handle:
        output_duration = round(handle.getnframes() / handle.getframerate(), 2)

    assert output_duration == 1.00
    assert summary.kept_segment_count == 2
    assert round(summary.removed_duration_s, 2) == 0.50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL with missing module or missing symbol errors for `render_audio_from_edl`

- [ ] **Step 3: Write the minimal renderer implementation**

```python
# src/sound_cut/render.py
from __future__ import annotations

import tempfile
from pathlib import Path

from sound_cut.ffmpeg_tools import _require_binary, _run
from sound_cut.models import RenderPlan, RenderSummary
from sound_cut.timeline import kept_ranges


def render_audio_from_edl(plan: RenderPlan) -> RenderSummary:
    ffmpeg = _require_binary("ffmpeg")
    source = plan.source
    input_path = source.input_path
    output_path = plan.output_path
    ranges = kept_ranges(plan.edl)
    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        concat_list = temp_dir / "segments.txt"
        segment_paths: list[Path] = []
        fade_seconds = max(plan.crossfade_ms / 1000, 0.0)
        for index, item in enumerate(ranges):
            segment_path = temp_dir / f"segment-{index:03d}.wav"
            segment_paths.append(segment_path)
            filters = []
            if fade_seconds > 0 and item.duration_s > fade_seconds * 2:
                filters.append(f"afade=t=in:st=0:d={fade_seconds:.3f}")
                filters.append(f"afade=t=out:st={item.duration_s - fade_seconds:.3f}:d={fade_seconds:.3f}")
            command = [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-vn",
                "-ss",
                f"{item.start_s:.3f}",
                "-to",
                f"{item.end_s:.3f}",
            ]
            if filters:
                command.extend(["-af", ",".join(filters)])
            command.append(str(segment_path))
            _run(command)
        concat_list.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8")
        _run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(output_path),
            ]
        )
    output_duration_s = round(sum(item.duration_s for item in ranges), 3)
    return RenderSummary(
        input_duration_s=round(source.duration_s, 3),
        output_duration_s=output_duration_s,
        removed_duration_s=round(source.duration_s - output_duration_s, 3),
        kept_segment_count=len(ranges),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/render.py tests/test_render.py
git commit -m "feat: render kept audio segments from edit timeline"
```

## Task 6: Wire Pipeline, CLI Output, And End-To-End Error Handling

**Files:**
- Create: `src/sound_cut/pipeline.py`
- Modify: `src/sound_cut/cli.py`
- Create: `tests/test_pipeline.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing pipeline and CLI tests**

```python
# tests/test_pipeline.py
from pathlib import Path

from sound_cut.config import build_profile
from sound_cut.models import AnalysisTrack, TimeRange
from sound_cut.pipeline import process_audio
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


class FakeSpeechAnalyzer:
    def analyze(self, wav_path: Path) -> AnalysisTrack:
        return AnalysisTrack(
            name="speech",
            ranges=(
                TimeRange(0.0, 0.5),
                TimeRange(1.0, 1.5),
            ),
            metadata={"source": str(wav_path)},
        )


def test_process_audio_returns_summary_and_writes_output(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = (
        tone_samples(sample_rate_hz=16000, duration_s=0.5)
        + silence_samples(sample_rate_hz=16000, duration_s=0.5)
        + tone_samples(sample_rate_hz=16000, duration_s=0.5)
    )
    write_pcm_wave(input_path, sample_rate_hz=16000, samples=samples)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=build_profile("balanced"),
        analyzer=FakeSpeechAnalyzer(),
    )

    assert output_path.exists()
    assert round(summary.output_duration_s, 2) == 1.00
    assert round(summary.removed_duration_s, 2) == 0.50
    assert summary.kept_segment_count == 2
```

```python
# tests/test_cli.py
from pathlib import Path

from sound_cut.cli import build_parser, main


def test_build_parser_parses_required_arguments(tmp_path: Path) -> None:
    parser = build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav")])

    assert args.input == tmp_path / "input.wav"
    assert args.output == tmp_path / "output.wav"
    assert args.aggressiveness == "balanced"
    assert args.min_silence_ms is None
    assert args.padding_ms is None
    assert args.crossfade_ms is None
    assert args.keep_temp is False


def test_main_returns_non_zero_for_missing_input(tmp_path: Path, capsys) -> None:
    exit_code = main([str(tmp_path / "missing.wav"), "-o", str(tmp_path / "output.wav")])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "does not exist" in captured.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py tests/test_cli.py -v`
Expected: FAIL with missing module or signature errors for `process_audio` and `main(argv)`

- [ ] **Step 3: Write the minimal pipeline and CLI integration**

```python
# src/sound_cut/pipeline.py
from __future__ import annotations

import tempfile
from pathlib import Path

from sound_cut.config import CutProfile
from sound_cut.errors import MediaError, NoSpeechDetectedError
from sound_cut.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from sound_cut.models import RenderPlan, RenderSummary
from sound_cut.render import render_audio_from_edl
from sound_cut.timeline import build_edit_decision_list
from sound_cut.vad import WebRtcSpeechAnalyzer


def process_audio(
    *,
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    analyzer: object | None = None,
) -> RenderSummary:
    if not input_path.exists():
        raise MediaError(f"Input file does not exist: {input_path}")
    source = probe_source_media(input_path)
    active_analyzer = analyzer or WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
    with tempfile.TemporaryDirectory(prefix="sound-cut-analysis-") as temp_dir_name:
        normalized_path = Path(temp_dir_name) / "analysis.wav"
        normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16000)
        track = active_analyzer.analyze(normalized_path)
    if not track.ranges:
        raise NoSpeechDetectedError("No usable speech segments were detected")
    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=track.ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )
    plan = RenderPlan(
        source=source,
        edl=edl,
        output_path=output_path,
        target="audio",
        crossfade_ms=profile.crossfade_ms,
    )
    return render_audio_from_edl(plan)
```

```python
# src/sound_cut/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from sound_cut.config import build_profile
from sound_cut.errors import SoundCutError
from sound_cut.pipeline import process_audio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=int)
    parser.add_argument("--padding-ms", type=int)
    parser.add_argument("--crossfade-ms", type=int)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = build_profile(args.aggressiveness)
    if args.min_silence_ms is not None:
        profile = profile.__class__(**{**profile.__dict__, "min_silence_ms": args.min_silence_ms})
    if args.padding_ms is not None:
        profile = profile.__class__(**{**profile.__dict__, "padding_ms": args.padding_ms})
    if args.crossfade_ms is not None:
        profile = profile.__class__(**{**profile.__dict__, "crossfade_ms": args.crossfade_ms})
    try:
        summary = process_audio(
            input_path=args.input,
            output_path=args.output,
            profile=profile,
        )
    except SoundCutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"input_duration_s={summary.input_duration_s:.3f}")
    print(f"output_duration_s={summary.output_duration_s:.3f}")
    print(f"removed_duration_s={summary.removed_duration_s:.3f}")
    print(f"kept_segment_count={summary.kept_segment_count}")
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pipeline.py tests/test_cli.py -v`
Expected: PASS

Run: `python3 -m pytest -v`
Expected: PASS for all unit and integration tests

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/pipeline.py src/sound_cut/cli.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: wire end-to-end audio silence cutting pipeline"
```

## Task 7: Tighten Timeline Semantics And Future-Extension Contracts

**Files:**
- Modify: `src/sound_cut/models.py`
- Modify: `src/sound_cut/timeline.py`
- Modify: `tests/test_timeline.py`

- [ ] **Step 1: Write the failing EDL contract test**

```python
# tests/test_timeline.py
from sound_cut.config import build_profile
from sound_cut.models import TimeRange
from sound_cut.timeline import build_edit_decision_list, kept_ranges, source_to_output_time


def test_build_edit_decision_list_emits_discard_operations_for_removed_gaps() -> None:
    profile = build_profile("balanced")
    speech_ranges = (
        TimeRange(0.50, 1.00),
        TimeRange(2.50, 3.00),
    )

    edl = build_edit_decision_list(
        duration_s=4.00,
        speech_ranges=speech_ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )

    assert [operation.action for operation in edl.operations] == ["keep", "discard", "keep"]
    assert edl.operations[1].range == TimeRange(1.10, 2.40)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_timeline.py::test_build_edit_decision_list_emits_discard_operations_for_removed_gaps -v`
Expected: FAIL because the current EDL only stores keep operations

- [ ] **Step 3: Update the timeline implementation to emit a canonical keep/discard EDL**

```python
# src/sound_cut/timeline.py
from __future__ import annotations

from sound_cut.models import EditDecisionList, EditOperation, TimeRange


def _round(value: float) -> float:
    return round(value, 3)


def _merge_ranges(ranges: tuple[TimeRange, ...], merge_gap_ms: int) -> tuple[TimeRange, ...]:
    if not ranges:
        return ()
    merge_gap_s = merge_gap_ms / 1000
    merged = [ranges[0]]
    for current in ranges[1:]:
        previous = merged[-1]
        if current.start_s - previous.end_s <= merge_gap_s:
            merged[-1] = TimeRange(previous.start_s, max(previous.end_s, current.end_s))
        else:
            merged.append(current)
    return tuple(merged)


def _pad_ranges(ranges: tuple[TimeRange, ...], duration_s: float, padding_ms: int) -> tuple[TimeRange, ...]:
    padding_s = padding_ms / 1000
    return tuple(
        TimeRange(
            start_s=max(0.0, _round(item.start_s - padding_s)),
            end_s=min(duration_s, _round(item.end_s + padding_s)),
        )
        for item in ranges
    )


def build_edit_decision_list(
    *,
    duration_s: float,
    speech_ranges: tuple[TimeRange, ...],
    padding_ms: int,
    min_silence_ms: int,
    merge_gap_ms: int,
) -> EditDecisionList:
    merged = _merge_ranges(tuple(sorted(speech_ranges)), merge_gap_ms)
    padded = _merge_ranges(_pad_ranges(merged, duration_s, padding_ms), merge_gap_ms)
    operations: list[EditOperation] = []
    cursor = 0.0
    min_silence_s = min_silence_ms / 1000
    for item in padded:
        if item.start_s - cursor >= min_silence_s:
            operations.append(EditOperation("discard", TimeRange(_round(cursor), _round(item.start_s)), "long-silence"))
        operations.append(EditOperation("keep", item, "speech"))
        cursor = item.end_s
    if duration_s - cursor >= min_silence_s:
        operations.append(EditOperation("discard", TimeRange(_round(cursor), _round(duration_s)), "long-silence"))
    return EditDecisionList(operations=tuple(operations))


def kept_ranges(edl: EditDecisionList) -> tuple[TimeRange, ...]:
    return tuple(operation.range for operation in edl.operations if operation.action == "keep")


def source_to_output_time(edl: EditDecisionList, source_time_s: float) -> float | None:
    cursor = 0.0
    for operation in edl.operations:
        if operation.action == "discard":
            continue
        keep_range = operation.range
        if keep_range.start_s <= source_time_s <= keep_range.end_s:
            return _round(cursor + (source_time_s - keep_range.start_s))
        cursor += keep_range.duration_s
    return None
```

- [ ] **Step 4: Run the focused and full timeline tests to verify they pass**

Run: `python3 -m pytest tests/test_timeline.py::test_build_edit_decision_list_emits_discard_operations_for_removed_gaps -v`
Expected: PASS

Run: `python3 -m pytest tests/test_timeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/models.py src/sound_cut/timeline.py tests/test_timeline.py
git commit -m "feat: emit canonical keep discard edit decision lists"
```

## Task 8: Final Verification And Manual QA Notes

**Files:**
- Modify: `src/sound_cut/cli.py`
- Modify: `src/sound_cut/pipeline.py`

- [ ] **Step 1: Add the final CLI output assertions**

```python
# tests/test_cli.py
from pathlib import Path

from sound_cut.cli import build_parser, main


def test_main_returns_non_zero_for_missing_input(tmp_path: Path, capsys) -> None:
    exit_code = main([str(tmp_path / "missing.wav"), "-o", str(tmp_path / "output.wav")])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "does not exist" in captured.err


def test_main_prints_processing_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    from sound_cut.models import RenderSummary

    def fake_process_audio(**_kwargs) -> RenderSummary:
        return RenderSummary(
            input_duration_s=10.0,
            output_duration_s=6.2,
            removed_duration_s=3.8,
            kept_segment_count=4,
        )

    monkeypatch.setattr("sound_cut.cli.process_audio", fake_process_audio)

    exit_code = main([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav")])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "input_duration_s=10.000" in captured.out
    assert "output_duration_s=6.200" in captured.out
    assert "removed_duration_s=3.800" in captured.out
    assert "kept_segment_count=4" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py::test_main_prints_processing_summary -v`
Expected: FAIL until the current CLI output matches the summary contract exactly

- [ ] **Step 3: Adjust CLI output format and keep-temp plumbing**

```python
# src/sound_cut/pipeline.py
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sound_cut.config import CutProfile
from sound_cut.errors import MediaError, NoSpeechDetectedError
from sound_cut.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from sound_cut.models import RenderPlan, RenderSummary
from sound_cut.render import render_audio_from_edl
from sound_cut.timeline import build_edit_decision_list
from sound_cut.vad import WebRtcSpeechAnalyzer


def process_audio(
    *,
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    analyzer: object | None = None,
    keep_temp: bool = False,
) -> RenderSummary:
    if not input_path.exists():
        raise MediaError(f"Input file does not exist: {input_path}")
    source = probe_source_media(input_path)
    active_analyzer = analyzer or WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
    with tempfile.TemporaryDirectory(prefix="sound-cut-analysis-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        normalized_path = temp_dir / "analysis.wav"
        normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16000)
        track = active_analyzer.analyze(normalized_path)
        if keep_temp:
            shutil.copy2(normalized_path, output_path.with_suffix(".analysis.wav"))
    if not track.ranges:
        raise NoSpeechDetectedError("No usable speech segments were detected")
    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=track.ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )
    plan = RenderPlan(
        source=source,
        edl=edl,
        output_path=output_path,
        target="audio",
        crossfade_ms=profile.crossfade_ms,
    )
    return render_audio_from_edl(plan)
```

```python
# src/sound_cut/cli.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from sound_cut.config import build_profile
from sound_cut.errors import SoundCutError
from sound_cut.pipeline import process_audio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=int)
    parser.add_argument("--padding-ms", type=int)
    parser.add_argument("--crossfade-ms", type=int)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = build_profile(args.aggressiveness)
    if args.min_silence_ms is not None:
        profile = profile.__class__(**{**profile.__dict__, "min_silence_ms": args.min_silence_ms})
    if args.padding_ms is not None:
        profile = profile.__class__(**{**profile.__dict__, "padding_ms": args.padding_ms})
    if args.crossfade_ms is not None:
        profile = profile.__class__(**{**profile.__dict__, "crossfade_ms": args.crossfade_ms})
    try:
        summary = process_audio(
            input_path=args.input,
            output_path=args.output,
            profile=profile,
            keep_temp=args.keep_temp,
        )
    except SoundCutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"input_duration_s={summary.input_duration_s:.3f}")
    print(f"output_duration_s={summary.output_duration_s:.3f}")
    print(f"removed_duration_s={summary.removed_duration_s:.3f}")
    print(f"kept_segment_count={summary.kept_segment_count}")
    return 0
```

- [ ] **Step 4: Run final automated verification**

Run: `python3 -m pytest -v`
Expected: PASS for all tests

Run: `python3 -m sound_cut sample.wav -o sample.cut.wav`
Expected: exit code 0, summary printed, output file created

Manual QA:
- Listen for swallowed initials at cut starts.
- Listen for clipped trailing syllables.
- Listen for boundary clicks.
- Compare original and output durations.
- Confirm very short rhetorical pauses remain.

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/cli.py src/sound_cut/pipeline.py tests/test_cli.py
git commit -m "chore: finalize cli summary and verification flow"
```
