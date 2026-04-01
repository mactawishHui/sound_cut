# Adaptive Delivery Bitrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make compressed delivery outputs choose a source-aware default bitrate so file size stays closer to the original compressed input while preserving a `64k..128k` quality-first range.

**Architecture:** Extend `SourceMedia` with bitrate metadata from ffprobe, add a delivery bitrate policy helper in `ffmpeg_tools.py`, and pass the probed source media into final export so compressed outputs are no longer hard-coded to `128k`. Keep the internal WAV render pipeline unchanged and verify behavior with focused unit tests plus ffmpeg-backed integration checks.

**Tech Stack:** Python 3.11, dataclasses, pathlib, pytest, ffmpeg, ffprobe

---

## File Structure

### Modify

- `src/sound_cut/models.py`
- `src/sound_cut/ffmpeg_tools.py`
- `src/sound_cut/render.py`
- `tests/test_ffmpeg_tools.py`
- `tests/test_render.py`

### Responsibilities

- `src/sound_cut/models.py`: carry source bitrate metadata through the existing media model
- `src/sound_cut/ffmpeg_tools.py`: probe bitrate metadata, derive fallback bitrate estimates, resolve delivery bitrate policy, and export compressed outputs with adaptive bitrate
- `src/sound_cut/render.py`: pass `SourceMedia` through to the delivery export helper while keeping internal WAV render semantics intact
- `tests/test_ffmpeg_tools.py`: verify bitrate parsing, adaptive policy bounds, and ffmpeg-backed compressed export bitrate behavior
- `tests/test_render.py`: verify render-to-delivery still works with adaptive bitrate and compressed-input accuracy coverage remains intact

## Task 1: Add Source Bitrate Metadata And Probe Parsing

**Files:**
- Modify: `src/sound_cut/models.py`
- Modify: `src/sound_cut/ffmpeg_tools.py`
- Modify: `tests/test_ffmpeg_tools.py`

- [ ] **Step 1: Write the failing probe parsing tests**

```python
# tests/test_ffmpeg_tools.py
from pathlib import Path

from sound_cut.ffmpeg_tools import _parse_source_media


def test_parse_source_media_prefers_format_bit_rate(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 1,
                "bit_rate": "64000",
            }
        ],
        "format": {
            "duration": "12.5",
            "bit_rate": "96000",
        },
    }

    source = _parse_source_media(payload, input_path=tmp_path / "sample.mp3")

    assert source.bit_rate_bps == 96_000


def test_parse_source_media_uses_stream_bit_rate_when_format_bit_rate_missing(tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "bit_rate": "88000",
            }
        ],
        "format": {
            "duration": "8.0",
        },
    }

    source = _parse_source_media(payload, input_path=tmp_path / "sample.m4a")

    assert source.bit_rate_bps == 88_000


def test_parse_source_media_estimates_bit_rate_from_file_size_when_metadata_missing(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"
    input_path.write_bytes(b"x" * 20_000)
    payload = {
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 1,
            }
        ],
        "format": {
            "duration": "2.0",
        },
    }

    source = _parse_source_media(payload, input_path=input_path)

    assert source.bit_rate_bps == 80_000
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_parse_source_media_prefers_format_bit_rate tests/test_ffmpeg_tools.py::test_parse_source_media_uses_stream_bit_rate_when_format_bit_rate_missing tests/test_ffmpeg_tools.py::test_parse_source_media_estimates_bit_rate_from_file_size_when_metadata_missing -q
```

Expected:

- FAIL because `_parse_source_media` does not exist and `SourceMedia` does not have `bit_rate_bps`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/models.py
@dataclass(frozen=True)
class SourceMedia:
    input_path: Path
    duration_s: float
    audio_codec: str | None
    sample_rate_hz: int | None
    channels: int | None
    bit_rate_bps: int | None = None
    has_video: bool = False
```

```python
# src/sound_cut/ffmpeg_tools.py
def _parse_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _estimate_bit_rate_bps(input_path: Path, *, duration_s: float) -> int | None:
    if duration_s <= 0:
        return None
    try:
        size_bytes = input_path.stat().st_size
    except OSError:
        return None
    return round(size_bytes * 8 / duration_s)


def _parse_source_media(payload: dict, *, input_path: Path) -> SourceMedia:
    streams = payload["streams"]
    format_data = payload["format"]
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    duration_s = float(format_data["duration"])
    bit_rate_bps = _parse_int(format_data.get("bit_rate"))
    if bit_rate_bps is None:
        bit_rate_bps = _parse_int(audio_stream.get("bit_rate"))
    if bit_rate_bps is None:
        bit_rate_bps = _estimate_bit_rate_bps(input_path, duration_s=duration_s)
    return SourceMedia(
        input_path=input_path,
        duration_s=duration_s,
        audio_codec=audio_stream.get("codec_name"),
        sample_rate_hz=int(audio_stream["sample_rate"]) if audio_stream.get("sample_rate") else None,
        channels=audio_stream.get("channels"),
        bit_rate_bps=bit_rate_bps,
        has_video=video_stream is not None,
    )


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
    try:
        payload = json.loads(result.stdout)
        return _parse_source_media(payload, input_path=input_path)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MediaError(f"Invalid ffprobe JSON for {input_path}") from exc
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_parse_source_media_prefers_format_bit_rate tests/test_ffmpeg_tools.py::test_parse_source_media_uses_stream_bit_rate_when_format_bit_rate_missing tests/test_ffmpeg_tools.py::test_parse_source_media_estimates_bit_rate_from_file_size_when_metadata_missing -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/models.py src/sound_cut/ffmpeg_tools.py tests/test_ffmpeg_tools.py
git commit -m "feat: probe source bitrate metadata"
```

## Task 2: Add Adaptive Delivery Bitrate Policy

**Files:**
- Modify: `src/sound_cut/ffmpeg_tools.py`
- Modify: `tests/test_ffmpeg_tools.py`

- [ ] **Step 1: Write the failing bitrate policy tests**

```python
# tests/test_ffmpeg_tools.py
from pathlib import Path

from sound_cut.ffmpeg_tools import resolve_delivery_bitrate_bps
from sound_cut.models import SourceMedia


def _source_media_with_bitrate(bit_rate_bps: int | None) -> SourceMedia:
    return SourceMedia(
        input_path=Path("input.mp3"),
        duration_s=10.0,
        audio_codec="mp3",
        sample_rate_hz=44_100,
        channels=1,
        bit_rate_bps=bit_rate_bps,
        has_video=False,
    )


def test_resolve_delivery_bitrate_caps_high_bitrates() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(192_000), ".mp3") == 128_000


def test_resolve_delivery_bitrate_preserves_midrange_bitrates() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(96_000), ".m4a") == 96_000


def test_resolve_delivery_bitrate_raises_low_bitrates_to_floor() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(48_000), ".mp3") == 64_000


def test_resolve_delivery_bitrate_uses_default_cap_when_unknown() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(None), ".m4a") == 128_000


def test_resolve_delivery_bitrate_returns_none_for_wav() -> None:
    assert resolve_delivery_bitrate_bps(_source_media_with_bitrate(96_000), ".wav") is None
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_caps_high_bitrates tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_preserves_midrange_bitrates tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_raises_low_bitrates_to_floor tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_uses_default_cap_when_unknown tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_returns_none_for_wav -q
```

Expected:

- FAIL because `resolve_delivery_bitrate_bps` does not exist

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/ffmpeg_tools.py
_MIN_DELIVERY_BIT_RATE_BPS = 64_000
_MAX_DELIVERY_BIT_RATE_BPS = 128_000


def resolve_delivery_bitrate_bps(source: SourceMedia, suffix: str) -> int | None:
    suffix = suffix.lower()
    if suffix == ".wav":
        return None
    if suffix not in {".mp3", ".m4a"}:
        raise MediaError(f"Unsupported output format: {suffix}")

    if source.bit_rate_bps is None:
        return _MAX_DELIVERY_BIT_RATE_BPS
    return min(max(source.bit_rate_bps, _MIN_DELIVERY_BIT_RATE_BPS), _MAX_DELIVERY_BIT_RATE_BPS)
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_caps_high_bitrates tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_preserves_midrange_bitrates tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_raises_low_bitrates_to_floor tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_uses_default_cap_when_unknown tests/test_ffmpeg_tools.py::test_resolve_delivery_bitrate_returns_none_for_wav -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/ffmpeg_tools.py tests/test_ffmpeg_tools.py
git commit -m "feat: add adaptive delivery bitrate policy"
```

## Task 3: Apply Adaptive Bitrate In Delivery Export And Render Integration

**Files:**
- Modify: `src/sound_cut/ffmpeg_tools.py`
- Modify: `src/sound_cut/render.py`
- Modify: `tests/test_ffmpeg_tools.py`
- Modify: `tests/test_render.py`

- [ ] **Step 1: Write the failing export integration tests**

```python
# tests/test_ffmpeg_tools.py
from pathlib import Path

from sound_cut.ffmpeg_tools import export_delivery_audio, probe_source_media
from sound_cut.models import SourceMedia
from tests.helpers import tone_samples, write_pcm_wave


def test_export_delivery_audio_uses_adaptive_mp3_bitrate(tmp_path: Path, ffmpeg_available) -> None:
    source_wav = tmp_path / "source.wav"
    output_mp3 = tmp_path / "output.mp3"
    write_pcm_wave(
        source_wav,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=1.0),
    )
    source = SourceMedia(
        input_path=Path("input.mp3"),
        duration_s=1.0,
        audio_codec="mp3",
        sample_rate_hz=16_000,
        channels=1,
        bit_rate_bps=64_000,
        has_video=False,
    )

    export_delivery_audio(source_wav, output_mp3, source)

    output_media = probe_source_media(output_mp3)
    assert output_media.audio_codec == "mp3"
    assert output_media.bit_rate_bps is not None
    assert output_media.bit_rate_bps < 128_000


def test_render_audio_from_edl_preserves_adaptive_delivery_output(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.mp3"
    write_pcm_wave(
        input_path,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5),
    )
    plan = RenderPlan(
        source=SourceMedia(
            input_path=input_path,
            duration_s=0.5,
            audio_codec="mp3",
            sample_rate_hz=16_000,
            channels=1,
            bit_rate_bps=64_000,
            has_video=False,
        ),
        edl=EditDecisionList(operations=(EditOperation("keep", TimeRange(0.0, 0.5), "speech"),)),
        output_path=output_path,
        target="audio",
        crossfade_ms=0,
    )

    summary = render_audio_from_edl(plan)
    output_media = probe_source_media(output_path)

    assert summary.output_duration_s == pytest.approx(output_media.duration_s, abs=1e-6)
    assert output_media.bit_rate_bps is not None
    assert output_media.bit_rate_bps < 128_000
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_export_delivery_audio_uses_adaptive_mp3_bitrate tests/test_render.py::test_render_audio_from_edl_preserves_adaptive_delivery_output -q
```

Expected:

- FAIL because `export_delivery_audio()` still uses fixed `128k` and does not accept `SourceMedia`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/ffmpeg_tools.py
def delivery_codec_for_suffix(suffix: str) -> tuple[str, bool]:
    mapping = {
        ".mp3": ("libmp3lame", True),
        ".m4a": ("aac", True),
        ".wav": ("pcm_s16le", False),
    }
    try:
        return mapping[suffix.lower()]
    except KeyError as exc:
        raise MediaError(f"Unsupported output format: {suffix}") from exc


def export_delivery_audio(source_wav: Path, output_path: Path, source: SourceMedia) -> None:
    ffmpeg = _require_binary("ffmpeg")
    codec_name, uses_bitrate = delivery_codec_for_suffix(output_path.suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-nostats",
        "-loglevel",
        "error",
        "-i",
        str(source_wav),
        "-c:a",
        codec_name,
    ]
    if uses_bitrate:
        command.extend(["-b:a", str(resolve_delivery_bitrate_bps(source, output_path.suffix))])
    if output_path.suffix.lower() == ".m4a":
        command.extend(["-f", "ipod"])
    elif output_path.suffix.lower() == ".wav":
        command.extend(["-f", "wav"])
    command.append(str(output_path))
    _run(command)
```

```python
# src/sound_cut/render.py
def render_audio_from_edl(plan: RenderPlan) -> RenderSummary:
    output_path = plan.output_path

    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_output_path = temp_dir / "render.wav"
        kept_segment_count = _render_internal_wave(plan, internal_output_path)
        export_delivery_audio(internal_output_path, output_path, plan.source)
    ...
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_export_delivery_audio_uses_adaptive_mp3_bitrate tests/test_render.py::test_render_audio_from_edl_preserves_adaptive_delivery_output -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/ffmpeg_tools.py src/sound_cut/render.py tests/test_ffmpeg_tools.py tests/test_render.py
git commit -m "feat: apply adaptive delivery bitrate on export"
```

## Task 4: Run Full Verification And Real MP3 Validation

**Files:**
- Modify: none
- Verify: `src/sound_cut/models.py`
- Verify: `src/sound_cut/ffmpeg_tools.py`
- Verify: `src/sound_cut/render.py`
- Verify: `tests/test_ffmpeg_tools.py`
- Verify: `tests/test_render.py`

- [ ] **Step 1: Run the full test suite**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q
```

Expected:

- PASS with the full suite green

- [ ] **Step 2: Run a real end-to-end MP3 sample**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m sound_cut '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3' --aggressiveness dense
```

Expected:

- PASS
- writes `/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3`
- summary output still reports durations and kept segment count

- [ ] **Step 3: Verify codec, duration, and size**

Run:

```bash
ls -lh '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3' '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3'
/opt/homebrew/bin/ffprobe -v error -show_entries stream=codec_name,bit_rate -show_entries format=duration,bit_rate -of json '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.cut.mp3'
```

Expected:

- output codec is `mp3`
- output duration remains correct
- output bitrate is no higher than `128k`
- output size is at least as close to the original as the prior fixed-`128k` export on the same sample

- [ ] **Step 4: Commit**

```bash
git add src/sound_cut/models.py src/sound_cut/ffmpeg_tools.py src/sound_cut/render.py tests/test_ffmpeg_tools.py tests/test_render.py
git commit -m "feat: adapt delivery bitrate to source media"
```
