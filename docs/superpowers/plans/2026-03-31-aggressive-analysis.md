# Aggressive Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second-pass internal pause splitter for the `dense` profile so it can cut more aggressively inside overly broad VAD speech envelopes without regressing semantic retention.

**Architecture:** Keep the current WebRTC VAD collector as the coarse speech envelope. Add a new pause-splitting analysis helper that inspects long `dense`-mode speech envelopes using short-window energy on the normalized analysis WAV and returns refined speech sub-ranges. `balanced` and `natural` continue to use the current VAD-only path unchanged.

**Tech Stack:** Python 3.11, `wave`, `math`, `dataclasses`, `pytest`, existing `ffmpeg` normalization pipeline, existing `webrtcvad`

---

## File Structure

### Create

- `src/sound_cut/pause_splitter.py`
- `tests/test_pause_splitter.py`

### Modify

- `src/sound_cut/config.py`
- `src/sound_cut/models.py`
- `src/sound_cut/pipeline.py`
- `tests/test_pipeline.py`

### Responsibilities

- `src/sound_cut/pause_splitter.py`: second-pass splitting of long speech envelopes based on short-window RMS valleys
- `src/sound_cut/config.py`: profile settings for enabling and tuning the pause splitter
- `src/sound_cut/models.py`: optional immutable config model for pause-splitting settings
- `src/sound_cut/pipeline.py`: apply the pause splitter only for `dense`
- `tests/test_pause_splitter.py`: unit coverage for splitting and non-splitting rules
- `tests/test_pipeline.py`: integration coverage that `dense` refines broad envelopes while `balanced` does not

## Task 1: Add Pause Splitter Config And Core Unit Tests

**Files:**
- Create: `src/sound_cut/pause_splitter.py`
- Create: `tests/test_pause_splitter.py`
- Modify: `src/sound_cut/models.py`
- Modify: `src/sound_cut/config.py`

- [ ] **Step 1: Write the failing pause splitter tests**

```python
# tests/test_pause_splitter.py
from pathlib import Path

from sound_cut.models import PauseSplitConfig, TimeRange
from sound_cut.pause_splitter import refine_speech_ranges
from tests.helpers import silence_samples, tone_samples, write_pcm_wave


def test_refine_speech_ranges_splits_long_envelope_around_internal_pause(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.30)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.5),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=180,
            context_ms=150,
        ),
    )

    assert ranges == (
        TimeRange(0.0, 0.60),
        TimeRange(0.90, 1.50),
    )


def test_refine_speech_ranges_does_not_split_when_pause_is_too_short(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
        + silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.09)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.29),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=180,
            context_ms=150,
        ),
    )

    assert ranges == (TimeRange(0.0, 1.29),)


def test_refine_speech_ranges_does_not_split_when_gap_is_too_close_to_edge(tmp_path: Path) -> None:
    wav_path = tmp_path / "analysis.wav"
    sample_rate_hz = 16_000
    samples = (
        silence_samples(sample_rate_hz=sample_rate_hz, duration_s=0.18)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.50)
        + tone_samples(sample_rate_hz=sample_rate_hz, duration_s=0.60)
    )
    write_pcm_wave(wav_path, sample_rate_hz=sample_rate_hz, samples=samples)

    ranges = refine_speech_ranges(
        wav_path,
        coarse_ranges=(TimeRange(0.0, 1.28),),
        config=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.0,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=150,
            context_ms=200,
        ),
    )

    assert ranges == (TimeRange(0.0, 1.28),)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pause_splitter.py -q
```

Expected:

- FAIL with missing `PauseSplitConfig` and `refine_speech_ranges`

- [ ] **Step 3: Write the minimal config model and pause splitter implementation**

```python
# src/sound_cut/models.py
from dataclasses import dataclass


@dataclass(frozen=True)
class PauseSplitConfig:
    enabled: bool
    min_envelope_s: float
    window_ms: int
    low_energy_ratio: float
    min_pause_ms: int
    context_ms: int
```

```python
# src/sound_cut/config.py
from sound_cut.models import PauseSplitConfig


@dataclass(frozen=True)
class CutProfile:
    name: str
    vad_mode: int
    merge_gap_ms: int
    min_silence_ms: int
    padding_ms: int
    crossfade_ms: int
    pause_split: PauseSplitConfig


_DISABLED_SPLIT = PauseSplitConfig(
    enabled=False,
    min_envelope_s=999.0,
    window_ms=30,
    low_energy_ratio=0.0,
    min_pause_ms=999_999,
    context_ms=0,
)

_PROFILES = {
    "natural": CutProfile(..., pause_split=_DISABLED_SPLIT),
    "balanced": CutProfile(..., pause_split=_DISABLED_SPLIT),
    "dense": CutProfile(
        ...,
        pause_split=PauseSplitConfig(
            enabled=True,
            min_envelope_s=1.2,
            window_ms=30,
            low_energy_ratio=0.12,
            min_pause_ms=150,
            context_ms=180,
        ),
    ),
}
```

```python
# src/sound_cut/pause_splitter.py
from __future__ import annotations

import math
import wave
from pathlib import Path

from sound_cut.models import PauseSplitConfig, TimeRange


def refine_speech_ranges(
    wav_path: Path,
    *,
    coarse_ranges: tuple[TimeRange, ...],
    config: PauseSplitConfig,
) -> tuple[TimeRange, ...]:
    if not config.enabled or not coarse_ranges:
        return coarse_ranges

    with wave.open(str(wav_path), "rb") as handle:
        sample_rate_hz = handle.getframerate()
        samples = handle.readframes(handle.getnframes())

    frame_count = len(samples) // 2
    pcm = memoryview(samples).cast("h")
    window_frames = max(1, int(sample_rate_hz * config.window_ms / 1000))
    context_windows = max(1, math.ceil(config.context_ms / config.window_ms))
    min_pause_windows = max(1, math.ceil(config.min_pause_ms / config.window_ms))

    refined: list[TimeRange] = []
    for coarse_range in coarse_ranges:
        if coarse_range.duration_s < config.min_envelope_s:
            refined.append(coarse_range)
            continue

        start_frame = int(coarse_range.start_s * sample_rate_hz)
        end_frame = min(frame_count, int(coarse_range.end_s * sample_rate_hz))
        energies: list[float] = []
        for index in range(start_frame, end_frame, window_frames):
            chunk = pcm[index : min(end_frame, index + window_frames)]
            if not chunk:
                break
            rms = math.sqrt(sum(sample * sample for sample in chunk) / len(chunk))
            energies.append(rms)

        peak = max(energies, default=0.0)
        if peak <= 0:
            refined.append(coarse_range)
            continue

        threshold = peak * config.low_energy_ratio
        low_start = None
        chosen_gap = None
        for index, energy in enumerate(energies):
            if energy <= threshold and low_start is None:
                low_start = index
            elif energy > threshold and low_start is not None:
                if index - low_start >= min_pause_windows:
                    chosen_gap = (low_start, index)
                    break
                low_start = None
        if chosen_gap is None and low_start is not None and len(energies) - low_start >= min_pause_windows:
            chosen_gap = (low_start, len(energies))

        if chosen_gap is None:
            refined.append(coarse_range)
            continue

        gap_start, gap_end = chosen_gap
        if gap_start < context_windows or len(energies) - gap_end < context_windows:
            refined.append(coarse_range)
            continue

        split_start_s = coarse_range.start_s + gap_start * config.window_ms / 1000
        split_end_s = coarse_range.start_s + gap_end * config.window_ms / 1000
        refined.append(TimeRange(coarse_range.start_s, split_start_s))
        refined.append(TimeRange(split_end_s, coarse_range.end_s))

    return tuple(item for item in refined if item.duration_s > 0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pause_splitter.py -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/models.py src/sound_cut/config.py src/sound_cut/pause_splitter.py tests/test_pause_splitter.py
git commit -m "feat: add dense pause splitter analysis"
```

## Task 2: Apply Pause Splitter Only In Dense Pipeline

**Files:**
- Modify: `src/sound_cut/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing pipeline integration tests**

```python
# tests/test_pipeline.py
from dataclasses import replace

from sound_cut.config import build_profile
from sound_cut.models import AnalysisTrack, TimeRange
from sound_cut.pipeline import process_audio


def test_process_audio_refines_dense_ranges_with_pause_splitter(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = (
        tone_samples(sample_rate_hz=16_000, duration_s=0.60)
        + silence_samples(sample_rate_hz=16_000, duration_s=0.30)
        + tone_samples(sample_rate_hz=16_000, duration_s=0.60)
    )
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=samples)
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 1.50),))

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("dense"), min_silence_ms=150, padding_ms=0, merge_gap_ms=0),
        analyzer=analyzer,
    )

    assert summary.kept_segment_count == 2


def test_process_audio_leaves_balanced_ranges_unmodified(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    samples = (
        tone_samples(sample_rate_hz=16_000, duration_s=0.60)
        + silence_samples(sample_rate_hz=16_000, duration_s=0.30)
        + tone_samples(sample_rate_hz=16_000, duration_s=0.60)
    )
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=samples)
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 1.50),))

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), min_silence_ms=150, padding_ms=0, merge_gap_ms=0),
        analyzer=analyzer,
    )

    assert summary.kept_segment_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py::test_process_audio_refines_dense_ranges_with_pause_splitter tests/test_pipeline.py::test_process_audio_leaves_balanced_ranges_unmodified -q
```

Expected:

- FAIL because both paths still behave identically

- [ ] **Step 3: Wire the pause splitter into the pipeline**

```python
# src/sound_cut/pipeline.py
from sound_cut.pause_splitter import refine_speech_ranges


def process_audio(...):
    ...
    if profile.pause_split.enabled:
        refined_ranges = refine_speech_ranges(
            normalized_path,
            coarse_ranges=analysis.ranges,
            config=profile.pause_split,
        )
    else:
        refined_ranges = analysis.ranges

    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=refined_ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py::test_process_audio_refines_dense_ranges_with_pause_splitter tests/test_pipeline.py::test_process_audio_leaves_balanced_ranges_unmodified -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/pipeline.py tests/test_pipeline.py
git commit -m "feat: apply pause splitting only for dense profile"
```

## Task 3: Full Verification And Real-File Regression Check

**Files:**
- No new code files expected

- [ ] **Step 1: Run the full automated test suite**

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q
```

Expected:

- all tests pass

- [ ] **Step 2: Re-run the real dense validation on the user sample**

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m sound_cut \
  '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3' \
  -o /tmp/say_my_name.next_dense.wav \
  --aggressiveness dense \
  --min-silence-ms 180 \
  --padding-ms 50 \
  --crossfade-ms 6
```

Expected:

- output duration shorter than the current `43.182333s`
- no silent tail regression

- [ ] **Step 3: Verify rendered output duration and tail energy**

```bash
PATH=/opt/homebrew/bin:$PATH ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 /tmp/say_my_name.next_dense.wav
```

Expected:

- prints a finite duration shorter than `43.182333`

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 - <<'PY'
from pathlib import Path
import wave, math, struct

path = Path('/tmp/say_my_name.next_dense.wav')
with wave.open(str(path), 'rb') as handle:
    rate = handle.getframerate()
    channels = handle.getnchannels()
    frames = handle.getnframes()
    raw = handle.readframes(frames)

samples = struct.unpack('<' + 'h' * (len(raw) // 2), raw)
channel = samples[0::channels]
window = channel[max(0, len(channel) - int(rate * 0.5)):]
rms = math.sqrt(sum(sample * sample for sample in window) / len(window))
print(rms)
PY
```

Expected:

- prints a non-zero RMS value

- [ ] **Step 4: Commit**

```bash
git status --short
```

Expected:

- no unexpected unstaged code changes beyond this feature

```bash
git add src/sound_cut/config.py src/sound_cut/models.py src/sound_cut/pipeline.py src/sound_cut/pause_splitter.py tests/test_pause_splitter.py tests/test_pipeline.py
git commit -m "feat: tighten dense analysis with internal pause splitting"
```
