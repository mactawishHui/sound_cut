# Compressed Delivery Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the final exported audio follow the input format by default and use compressed delivery formats so output size stays near the same order of magnitude as the original file.

**Architecture:** Keep the current cut/render pipeline rendering internally to WAV for correctness, then add a delivery-export step that converts the internal WAV into the final user-facing format based on the explicit output suffix or inferred input suffix. `cli.py` owns output-path inference, `render.py` owns the internal WAV render, and `ffmpeg_tools.py` owns final codec selection and export.

**Tech Stack:** Python 3.11, `argparse`, `pathlib`, `tempfile`, `shutil`, `pytest`, `ffmpeg`, `ffprobe`

---

## File Structure

### Modify

- `src/sound_cut/cli.py`
- `src/sound_cut/models.py`
- `src/sound_cut/ffmpeg_tools.py`
- `src/sound_cut/render.py`
- `tests/test_cli.py`
- `tests/test_ffmpeg_tools.py`
- `tests/test_render.py`

### Responsibilities

- `src/sound_cut/cli.py`: infer default output path when omitted and preserve explicit output suffix behavior
- `src/sound_cut/models.py`: carry delivery-path/format intent cleanly in render models
- `src/sound_cut/ffmpeg_tools.py`: choose final export codec from suffix and transcode internal WAV to delivery format
- `src/sound_cut/render.py`: render to internal WAV, then hand off to delivery export
- `tests/test_cli.py`: verify inferred output paths and explicit output handling
- `tests/test_ffmpeg_tools.py`: verify suffix-to-codec/export behavior
- `tests/test_render.py`: verify final delivery outputs exist, use the requested format, preserve duration, and avoid WAV-only behavior

## Task 1: Add CLI Output Inference And Delivery Intent Model

**Files:**
- Modify: `src/sound_cut/cli.py`
- Modify: `src/sound_cut/models.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
# tests/test_cli.py
from pathlib import Path

from sound_cut.cli import build_parser, resolve_output_path


def test_resolve_output_path_defaults_to_input_suffix_when_output_is_omitted(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"

    resolved = resolve_output_path(input_path, None)

    assert resolved == tmp_path / "sample.cut.mp3"


def test_resolve_output_path_uses_explicit_output_path_when_provided(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"
    explicit = tmp_path / "custom.m4a"

    resolved = resolve_output_path(input_path, explicit)

    assert resolved == explicit


def test_build_parser_output_is_optional(tmp_path: Path) -> None:
    parser = build_parser()

    args = parser.parse_args([str(tmp_path / "input.mp3")])

    assert args.output is None
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py::test_resolve_output_path_defaults_to_input_suffix_when_output_is_omitted tests/test_cli.py::test_resolve_output_path_uses_explicit_output_path_when_provided tests/test_cli.py::test_build_parser_output_is_optional -q
```

Expected:

- FAIL because `resolve_output_path` does not exist and `-o` is still required

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/models.py
@dataclass(frozen=True)
class RenderPlan:
    source: SourceMedia
    edl: EditDecisionList
    output_path: Path
    target: Literal["audio"]
    crossfade_ms: int
```

```python
# src/sound_cut/cli.py
from pathlib import Path


_SUPPORTED_DELIVERY_SUFFIXES = {".mp3", ".m4a", ".wav"}


def resolve_output_path(input_path: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path

    suffix = input_path.suffix.lower()
    if suffix not in _SUPPORTED_DELIVERY_SUFFIXES:
        suffix = ".m4a"
    return input_path.with_name(f"{input_path.stem}.cut{suffix}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    ...
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = resolve_output_path(args.input, args.output)
    ...
    summary = process_audio(args.input, output_path, profile, keep_temp=args.keep_temp)
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py::test_resolve_output_path_defaults_to_input_suffix_when_output_is_omitted tests/test_cli.py::test_resolve_output_path_uses_explicit_output_path_when_provided tests/test_cli.py::test_build_parser_output_is_optional -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/cli.py src/sound_cut/models.py tests/test_cli.py
git commit -m "feat: infer compressed delivery output paths"
```

## Task 2: Add Final Delivery Export Helpers

**Files:**
- Modify: `src/sound_cut/ffmpeg_tools.py`
- Modify: `tests/test_ffmpeg_tools.py`

- [ ] **Step 1: Write the failing ffmpeg export tests**

```python
# tests/test_ffmpeg_tools.py
from pathlib import Path

import pytest

from sound_cut.errors import MediaError
from sound_cut.ffmpeg_tools import delivery_codec_for_suffix, export_delivery_audio
from tests.helpers import tone_samples, write_pcm_wave


def test_delivery_codec_for_suffix_maps_supported_formats() -> None:
    assert delivery_codec_for_suffix(".mp3") == ("libmp3lame", "128k")
    assert delivery_codec_for_suffix(".m4a") == ("aac", "128k")
    assert delivery_codec_for_suffix(".wav") == ("pcm_s16le", None)


def test_delivery_codec_for_suffix_rejects_unsupported_formats() -> None:
    with pytest.raises(MediaError, match="Unsupported output format"):
        delivery_codec_for_suffix(".ogg")


def test_export_delivery_audio_writes_mp3_output(tmp_path: Path, ffmpeg_available) -> None:
    source_wav = tmp_path / "source.wav"
    output_mp3 = tmp_path / "output.mp3"
    write_pcm_wave(
        source_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=0.50),
    )

    export_delivery_audio(source_wav, output_mp3)

    assert output_mp3.exists()
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_delivery_codec_for_suffix_maps_supported_formats tests/test_ffmpeg_tools.py::test_delivery_codec_for_suffix_rejects_unsupported_formats tests/test_ffmpeg_tools.py::test_export_delivery_audio_writes_mp3_output -q
```

Expected:

- FAIL because delivery codec/export helpers do not exist

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/ffmpeg_tools.py
def delivery_codec_for_suffix(suffix: str) -> tuple[str, str | None]:
    suffix = suffix.lower()
    mapping = {
        ".mp3": ("libmp3lame", "128k"),
        ".m4a": ("aac", "128k"),
        ".wav": ("pcm_s16le", None),
    }
    try:
        return mapping[suffix]
    except KeyError as exc:
        raise MediaError(f"Unsupported output format: {suffix}") from exc


def export_delivery_audio(source_wav_path: Path, output_path: Path) -> None:
    ffmpeg = _require_binary("ffmpeg")
    codec, bitrate = delivery_codec_for_suffix(output_path.suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source_wav_path),
        "-c:a",
        codec,
    ]
    if bitrate is not None:
        command.extend(["-b:a", bitrate])
    if output_path.suffix.lower() == ".m4a":
        command.extend(["-f", "ipod"])
    elif output_path.suffix.lower() == ".wav":
        command.extend(["-f", "wav"])
    command.append(str(output_path))
    _run(command)
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_delivery_codec_for_suffix_maps_supported_formats tests/test_ffmpeg_tools.py::test_delivery_codec_for_suffix_rejects_unsupported_formats tests/test_ffmpeg_tools.py::test_export_delivery_audio_writes_mp3_output -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/ffmpeg_tools.py tests/test_ffmpeg_tools.py
git commit -m "feat: add compressed delivery export helpers"
```

## Task 3: Render Internally To WAV And Export Final Delivery Format

**Files:**
- Modify: `src/sound_cut/render.py`
- Modify: `tests/test_render.py`

- [ ] **Step 1: Write the failing render tests**

```python
# tests/test_render.py
from sound_cut.ffmpeg_tools import probe_source_media


def test_render_audio_from_edl_writes_mp3_delivery_output(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.mp3"
    samples = (
        tone_samples(sample_rate_hz=16_000, duration_s=0.50)
        + silence_samples(sample_rate_hz=16_000, duration_s=0.50)
        + tone_samples(sample_rate_hz=16_000, duration_s=0.50)
    )
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=samples)
    source = SourceMedia(
        input_path=input_path,
        duration_s=1.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        has_video=False,
    )
    plan = RenderPlan(
        source=source,
        edl=EditDecisionList(
            operations=(
                EditOperation("keep", TimeRange(0.0, 0.5), "speech"),
                EditOperation("keep", TimeRange(1.0, 1.5), "speech"),
            )
        ),
        output_path=output_path,
        target="audio",
        crossfade_ms=10,
    )

    summary = render_audio_from_edl(plan)
    exported = probe_source_media(output_path)

    assert output_path.exists()
    assert exported.audio_codec == "mp3"
    assert summary.output_duration_s == pytest.approx(exported.duration_s, abs=0.05)
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_render.py::test_render_audio_from_edl_writes_mp3_delivery_output -q
```

Expected:

- FAIL because render currently rejects non-WAV output

- [ ] **Step 3: Write the minimal render/export implementation**

```python
# src/sound_cut/render.py
from sound_cut.ffmpeg_tools import _require_binary, _run, export_delivery_audio


def render_audio_from_edl(plan: RenderPlan) -> RenderSummary:
    ffmpeg = _require_binary("ffmpeg")
    input_path = plan.source.input_path
    output_path = plan.output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ...
    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_output_path = temp_dir / "rendered.wav"
        ...
        if not ranges:
            _write_empty_wave(
                internal_output_path,
                sample_rate_hz=plan.source.sample_rate_hz or 44_100,
                channels=plan.source.channels or 1,
            )
        elif len(segment_paths) == 1:
            shutil.copyfile(segment_paths[0], internal_output_path)
        else:
            ...
            command.extend([... , str(internal_output_path)])
            _run(command)

        if output_path.suffix.lower() == ".wav":
            shutil.copyfile(internal_output_path, output_path)
        else:
            export_delivery_audio(internal_output_path, output_path)

    output_duration_s = probe_source_media(output_path).duration_s
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_render.py::test_render_audio_from_edl_writes_mp3_delivery_output -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/render.py tests/test_render.py
git commit -m "feat: export compressed delivery audio formats"
```

## Task 4: Full Verification And Real MP3 Size Check

**Files:**
- No new production files expected

- [ ] **Step 1: Run the full automated test suite**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q
```

Expected:

- all tests pass

- [ ] **Step 2: Run the real-file validation using inferred compressed output**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m sound_cut '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3' --aggressiveness dense
```

Expected:

- output path inferred as `/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3`
- command succeeds

- [ ] **Step 3: Verify final format, duration, and size are compressed**

Run:

```bash
ls -lh '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3' '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3'
```

Expected:

- output file exists
- output file size is in compressed-audio scale, not WAV scale

Run:

```bash
PATH=/opt/homebrew/bin:$PATH ffprobe -v error -show_entries stream=codec_name -of default=nk=1:nw=1 '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3'
```

Expected:

- prints `mp3`

Run:

```bash
PATH=/opt/homebrew/bin:$PATH ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3'
```

Expected:

- prints a duration close to the rendered summary duration

- [ ] **Step 4: Commit**

```bash
git add src/sound_cut/cli.py src/sound_cut/models.py src/sound_cut/ffmpeg_tools.py src/sound_cut/render.py tests/test_cli.py tests/test_ffmpeg_tools.py tests/test_render.py
git commit -m "feat: follow input format for compressed delivery output"
```
