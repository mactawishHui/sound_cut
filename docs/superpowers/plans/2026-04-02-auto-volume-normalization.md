# Auto Volume Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional whole-output loudness normalization that can run in the same command as speech cutting, while reorganizing the codebase into clearer subpackages.

**Architecture:** First split the current flat `src/sound_cut/` module set into `core`, `analysis`, `editing`, and `media` subpackages. Then add a `LoudnessNormalizationConfig` carried through `cli.py` into `RenderPlan`, apply ffmpeg `loudnorm` to the internal rendered WAV when enabled, and keep final export unchanged except for consuming the post-processed WAV. Verify behavior with parser tests, pipeline/render unit tests, and ffmpeg-backed integration checks that prove the combined cut-and-normalize flow works.

**Tech Stack:** Python 3.11, dataclasses, pathlib, argparse, pytest, ffmpeg, ffprobe

---

## File Structure

### Create

- `src/sound_cut/core/__init__.py`
- `src/sound_cut/analysis/__init__.py`
- `src/sound_cut/editing/__init__.py`
- `src/sound_cut/media/__init__.py`
- `tests/test_package_layout.py`

### Move

- `src/sound_cut/config.py` -> `src/sound_cut/core/config.py`
- `src/sound_cut/errors.py` -> `src/sound_cut/core/errors.py`
- `src/sound_cut/models.py` -> `src/sound_cut/core/models.py`
- `src/sound_cut/vad.py` -> `src/sound_cut/analysis/vad.py`
- `src/sound_cut/pause_splitter.py` -> `src/sound_cut/analysis/pause_splitter.py`
- `src/sound_cut/timeline.py` -> `src/sound_cut/editing/timeline.py`
- `src/sound_cut/pipeline.py` -> `src/sound_cut/editing/pipeline.py`
- `src/sound_cut/ffmpeg_tools.py` -> `src/sound_cut/media/ffmpeg_tools.py`
- `src/sound_cut/render.py` -> `src/sound_cut/media/render.py`

### Modify

- `src/sound_cut/cli.py`
- `src/sound_cut/__main__.py`
- `README.md`
- `README_cn.md`
- `tests/test_cli.py`
- `tests/test_pipeline.py`
- `tests/test_render.py`
- `tests/test_ffmpeg_tools.py`
- `tests/test_vad.py`
- `tests/test_pause_splitter.py`
- `tests/test_timeline.py`

### Responsibilities

- `src/sound_cut/core/`: shared config, data models, domain errors
- `src/sound_cut/analysis/`: speech detection and pause refinement
- `src/sound_cut/editing/`: EDL construction and pipeline orchestration
- `src/sound_cut/media/`: ffmpeg integration, rendering, delivery export, loudness normalization
- `src/sound_cut/cli.py`: public entrypoint and CLI-only option validation
- `tests/test_package_layout.py`: smoke coverage for the new import paths
- existing `tests/test_*.py`: behavior coverage after import rewrites and new loudness functionality

## Task 1: Split The Package Layout Without Changing Behavior

**Files:**
- Create: `src/sound_cut/core/__init__.py`
- Create: `src/sound_cut/analysis/__init__.py`
- Create: `src/sound_cut/editing/__init__.py`
- Create: `src/sound_cut/media/__init__.py`
- Create: `tests/test_package_layout.py`
- Move: `src/sound_cut/config.py`
- Move: `src/sound_cut/errors.py`
- Move: `src/sound_cut/models.py`
- Move: `src/sound_cut/vad.py`
- Move: `src/sound_cut/pause_splitter.py`
- Move: `src/sound_cut/timeline.py`
- Move: `src/sound_cut/pipeline.py`
- Move: `src/sound_cut/ffmpeg_tools.py`
- Move: `src/sound_cut/render.py`
- Modify: `src/sound_cut/cli.py`
- Modify: `src/sound_cut/__main__.py`
- Test: `tests/test_package_layout.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_render.py`
- Test: `tests/test_ffmpeg_tools.py`
- Test: `tests/test_vad.py`
- Test: `tests/test_pause_splitter.py`
- Test: `tests/test_timeline.py`

- [ ] **Step 1: Write the failing package-layout smoke test**

```python
# tests/test_package_layout.py
import sound_cut.cli as cli
from sound_cut.analysis.pause_splitter import refine_speech_ranges
from sound_cut.analysis.vad import WebRtcSpeechAnalyzer
from sound_cut.core.config import build_profile
from sound_cut.core.errors import SoundCutError
from sound_cut.core.models import RenderPlan
from sound_cut.editing.pipeline import process_audio
from sound_cut.editing.timeline import build_edit_decision_list
from sound_cut.media.ffmpeg_tools import probe_source_media
from sound_cut.media.render import render_audio_from_edl


def test_reorganized_packages_expose_current_entrypoints() -> None:
    assert callable(cli.main)
    assert callable(build_profile)
    assert callable(process_audio)
    assert callable(build_edit_decision_list)
    assert callable(render_audio_from_edl)
    assert callable(probe_source_media)
    assert callable(refine_speech_ranges)
    assert WebRtcSpeechAnalyzer is not None
    assert SoundCutError is not None
    assert RenderPlan is not None
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_package_layout.py tests/test_cli.py::test_cli_module_import_does_not_require_pipeline -q
```

Expected:

- FAIL because `sound_cut.core`, `sound_cut.analysis`, `sound_cut.editing`, and `sound_cut.media` do not exist yet

- [ ] **Step 3: Create the package directories, move modules, and rewrite imports**

```bash
mkdir -p src/sound_cut/core src/sound_cut/analysis src/sound_cut/editing src/sound_cut/media
mv src/sound_cut/config.py src/sound_cut/core/config.py
mv src/sound_cut/errors.py src/sound_cut/core/errors.py
mv src/sound_cut/models.py src/sound_cut/core/models.py
mv src/sound_cut/vad.py src/sound_cut/analysis/vad.py
mv src/sound_cut/pause_splitter.py src/sound_cut/analysis/pause_splitter.py
mv src/sound_cut/timeline.py src/sound_cut/editing/timeline.py
mv src/sound_cut/pipeline.py src/sound_cut/editing/pipeline.py
mv src/sound_cut/ffmpeg_tools.py src/sound_cut/media/ffmpeg_tools.py
mv src/sound_cut/render.py src/sound_cut/media/render.py
```

```python
# src/sound_cut/core/__init__.py
"""Shared config, models, and errors for sound_cut."""
```

```python
# src/sound_cut/analysis/__init__.py
"""Speech analysis helpers for sound_cut."""
```

```python
# src/sound_cut/editing/__init__.py
"""Timeline building and pipeline orchestration for sound_cut."""
```

```python
# src/sound_cut/media/__init__.py
"""Media rendering and ffmpeg integration for sound_cut."""
```

```python
# src/sound_cut/cli.py
from sound_cut.core.config import build_profile
from sound_cut.core.errors import SoundCutError
```

```python
# src/sound_cut/__main__.py
from sound_cut.cli import main
```

```python
# src/sound_cut/editing/pipeline.py
from sound_cut.analysis.pause_splitter import refine_speech_ranges
from sound_cut.core.config import CutProfile
from sound_cut.core.errors import MediaError, NoSpeechDetectedError
from sound_cut.core.models import RenderPlan, RenderSummary
from sound_cut.editing.timeline import build_edit_decision_list
from sound_cut.media.ffmpeg_tools import normalize_audio_for_analysis, probe_source_media
from sound_cut.media.render import render_audio_from_edl
```

```python
# src/sound_cut/media/render.py
from sound_cut.core.models import RenderPlan, RenderSummary
from sound_cut.editing.timeline import kept_ranges
from sound_cut.media.ffmpeg_tools import _require_binary, _run, export_delivery_audio, probe_source_media
```

```python
# tests/test_pipeline.py
from sound_cut.core.config import build_profile
from sound_cut.core.errors import MediaError
from sound_cut.core.models import AnalysisTrack, RenderSummary, TimeRange
from sound_cut.editing.pipeline import process_audio
```

```python
# tests/test_render.py
from sound_cut.core.models import EditDecisionList, EditOperation, RenderPlan, SourceMedia, TimeRange
from sound_cut.media.ffmpeg_tools import export_delivery_audio, probe_source_media
from sound_cut.media.render import render_audio_from_edl
```

```python
# tests/test_ffmpeg_tools.py
import sound_cut.media.ffmpeg_tools as ffmpeg_tools
from sound_cut.core.errors import MediaError
from sound_cut.core.models import SourceMedia
from sound_cut.media.ffmpeg_tools import (
    delivery_codec_for_suffix,
    export_delivery_audio,
    normalize_audio_for_analysis,
    probe_source_media,
    resolve_delivery_bitrate_bps,
)
```

```python
# tests/test_vad.py / tests/test_pause_splitter.py / tests/test_timeline.py
# update all internal imports to the new package roots:
# sound_cut.analysis.vad
# sound_cut.analysis.pause_splitter
# sound_cut.editing.timeline
# sound_cut.core.models
```

- [ ] **Step 4: Run the targeted tests to verify the move preserved imports**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_package_layout.py tests/test_cli.py::test_cli_module_import_does_not_require_pipeline tests/test_timeline.py::test_build_edit_decision_list_preserves_edge_silence tests/test_ffmpeg_tools.py::test_delivery_codec_for_suffix_maps_supported_formats -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/core src/sound_cut/analysis src/sound_cut/editing src/sound_cut/media src/sound_cut/cli.py src/sound_cut/__main__.py tests/test_package_layout.py tests/test_cli.py tests/test_pipeline.py tests/test_render.py tests/test_ffmpeg_tools.py tests/test_vad.py tests/test_pause_splitter.py tests/test_timeline.py
git commit -m "refactor: split sound_cut modules by responsibility"
```

## Task 2: Add Loudness Config And CLI-to-Pipeline Wiring

**Files:**
- Modify: `src/sound_cut/core/models.py`
- Modify: `src/sound_cut/cli.py`
- Modify: `src/sound_cut/editing/pipeline.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing CLI and pipeline wiring tests**

```python
# tests/test_cli.py
def test_build_parser_parses_auto_volume_defaults(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav")])

    assert args.auto_volume is False
    assert args.target_lufs is None


def test_main_rejects_target_lufs_without_auto_volume(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([str(tmp_path / "input.wav"), "--target-lufs", "-18"])

    assert excinfo.value.code == 2


def test_main_passes_default_loudness_config_to_process_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(input_path: Path, output_path: Path, profile, loudness=None, analyzer=None, keep_temp: bool = False):
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core.models").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(sys.modules, "sound_cut.editing.pipeline", types.SimpleNamespace(process_audio=fake_process_audio))

    exit_code = cli.main([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), "--auto-volume"])

    assert exit_code == 0
    assert captured["loudness"] == importlib.import_module("sound_cut.core.models").LoudnessNormalizationConfig(
        enabled=True,
        target_lufs=-16.0,
    )


def test_main_passes_explicit_target_lufs_to_process_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(input_path: Path, output_path: Path, profile, loudness=None, analyzer=None, keep_temp: bool = False):
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core.models").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(sys.modules, "sound_cut.editing.pipeline", types.SimpleNamespace(process_audio=fake_process_audio))

    exit_code = cli.main(
        [
            str(tmp_path / "input.wav"),
            "-o",
            str(tmp_path / "output.wav"),
            "--auto-volume",
            "--target-lufs",
            "-18",
        ]
    )

    assert exit_code == 0
    assert captured["loudness"] == importlib.import_module("sound_cut.core.models").LoudnessNormalizationConfig(
        enabled=True,
        target_lufs=-18.0,
    )
```

```python
# tests/test_pipeline.py
from sound_cut.core.models import LoudnessNormalizationConfig


def test_process_audio_passes_loudness_config_into_render_plan(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.5),))
    captured: dict[str, object] = {}

    def fake_render_audio_from_edl(plan):
        captured["plan"] = plan
        return RenderSummary(plan.source.duration_s, plan.source.duration_s, 0.0, 1)

    monkeypatch.setattr("sound_cut.editing.pipeline.render_audio_from_edl", fake_render_audio_from_edl)

    process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-18.0),
        analyzer=analyzer,
    )

    assert captured["plan"].loudness == LoudnessNormalizationConfig(enabled=True, target_lufs=-18.0)
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py::test_build_parser_parses_auto_volume_defaults tests/test_cli.py::test_main_rejects_target_lufs_without_auto_volume tests/test_cli.py::test_main_passes_default_loudness_config_to_process_audio tests/test_cli.py::test_main_passes_explicit_target_lufs_to_process_audio tests/test_pipeline.py::test_process_audio_passes_loudness_config_into_render_plan -q
```

Expected:

- FAIL because the parser has no loudness flags, `LoudnessNormalizationConfig` does not exist, and `process_audio()` does not accept `loudness`

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/core/models.py
@dataclass(frozen=True)
class LoudnessNormalizationConfig:
    enabled: bool
    target_lufs: float


@dataclass(frozen=True)
class RenderPlan:
    source: SourceMedia
    edl: EditDecisionList
    output_path: Path
    target: Literal["audio"]
    crossfade_ms: int
    loudness: LoudnessNormalizationConfig
```

```python
# src/sound_cut/cli.py
from sound_cut.core.models import LoudnessNormalizationConfig

_DEFAULT_TARGET_LUFS = -16.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=_non_negative_int)
    parser.add_argument("--padding-ms", type=_non_negative_int)
    parser.add_argument("--crossfade-ms", type=_non_negative_int)
    parser.add_argument("--auto-volume", action="store_true")
    parser.add_argument("--target-lufs", type=float)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.target_lufs is not None and not args.auto_volume:
        parser.error("--target-lufs requires --auto-volume")

    loudness = LoudnessNormalizationConfig(
        enabled=args.auto_volume,
        target_lufs=args.target_lufs if args.target_lufs is not None else _DEFAULT_TARGET_LUFS,
    )
    profile = build_profile(args.aggressiveness)
    output_path = resolve_output_path(args.input, args.output)

    try:
        from sound_cut.editing.pipeline import process_audio

        summary = process_audio(
            args.input,
            output_path,
            profile,
            loudness=loudness,
            keep_temp=args.keep_temp,
        )
    except SoundCutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
```

```python
# src/sound_cut/editing/pipeline.py
from sound_cut.core.models import LoudnessNormalizationConfig, RenderPlan, RenderSummary


def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    loudness: LoudnessNormalizationConfig | None = None,
    analyzer=None,
    keep_temp: bool = False,
) -> RenderSummary:
    if loudness is None:
        loudness = LoudnessNormalizationConfig(enabled=False, target_lufs=-16.0)
    if input_path.resolve(strict=False) == output_path.resolve(strict=False):
        raise MediaError(f"Input and output paths must be different: {input_path}")

    if not input_path.exists():
        raise MediaError(f"Input media not found: {input_path}")

    source = probe_source_media(input_path)

    if keep_temp:
        normalized_path = output_path.with_name(f"{output_path.stem}.analysis.wav")
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
        if analyzer is None:
            from sound_cut.analysis.vad import WebRtcSpeechAnalyzer

            analyzer = WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
        analysis = analyzer.analyze(normalized_path)
        analysis = _refine_analysis_ranges(normalized_path, analysis, profile)
    else:
        with tempfile.TemporaryDirectory(prefix="sound-cut-analysis-") as temp_dir_name:
            normalized_path = Path(temp_dir_name) / "analysis.wav"
            normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
            if analyzer is None:
                from sound_cut.analysis.vad import WebRtcSpeechAnalyzer

                analyzer = WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
            analysis = analyzer.analyze(normalized_path)
            analysis = _refine_analysis_ranges(normalized_path, analysis, profile)

    if not analysis.ranges:
        raise NoSpeechDetectedError(f"No speech detected in {input_path}")

    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=analysis.ranges,
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
        loudness=loudness,
    )
    return render_audio_from_edl(plan)
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py::test_build_parser_parses_auto_volume_defaults tests/test_cli.py::test_main_rejects_target_lufs_without_auto_volume tests/test_cli.py::test_main_passes_default_loudness_config_to_process_audio tests/test_cli.py::test_main_passes_explicit_target_lufs_to_process_audio tests/test_pipeline.py::test_process_audio_passes_loudness_config_into_render_plan -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/core/models.py src/sound_cut/cli.py src/sound_cut/editing/pipeline.py tests/test_cli.py tests/test_pipeline.py
git commit -m "feat: wire optional loudness normalization config"
```

## Task 3: Add ffmpeg Loudness Normalization And Render Post-Processing

**Files:**
- Modify: `src/sound_cut/media/ffmpeg_tools.py`
- Modify: `src/sound_cut/media/render.py`
- Test: `tests/test_ffmpeg_tools.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing helper and render tests**

```python
# tests/test_ffmpeg_tools.py
def test_normalize_loudness_builds_loudnorm_pcm_wave_command(monkeypatch, tmp_path) -> None:
    source_wav = tmp_path / "source.wav"
    output_wav = tmp_path / "normalized.wav"
    recorded_command: list[str] = []

    source_wav.write_bytes(b"wave")

    monkeypatch.setattr(ffmpeg_tools, "_require_binary", lambda name: name)
    monkeypatch.setattr(ffmpeg_tools, "_run", lambda command: recorded_command.extend(command))

    ffmpeg_tools.normalize_loudness(source_wav, output_wav, target_lufs=-16.0)

    assert "-af" in recorded_command
    assert "loudnorm=I=-16.0" in recorded_command
    assert "-c:a" in recorded_command
    assert "pcm_s16le" in recorded_command
    assert "-f" in recorded_command
    assert "wav" in recorded_command
```

```python
# tests/test_render.py
import shutil

from sound_cut.core.models import LoudnessNormalizationConfig


def test_render_audio_from_edl_normalizes_internal_wave_before_delivery(monkeypatch, tmp_path) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
    source = SourceMedia(
        input_path=input_path,
        duration_s=0.5,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        has_video=False,
    )
    plan = RenderPlan(
        source=source,
        edl=EditDecisionList(operations=(EditOperation("keep", TimeRange(0.0, 0.5), "speech"),)),
        output_path=output_path,
        target="audio",
        crossfade_ms=10,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-18.0),
    )
    recorded_calls: list[tuple[Path, Path, float]] = []

    def fake_render_internal_wave(plan, rendered_path, *, force_nonempty: bool = False) -> int:
        write_pcm_wave(rendered_path, sample_rate_hz=16_000, samples=tone_samples(sample_rate_hz=16_000, duration_s=0.5))
        return 1

    monkeypatch.setattr("sound_cut.media.render._render_internal_wave", fake_render_internal_wave)
    monkeypatch.setattr(
        "sound_cut.media.render.normalize_loudness",
        lambda source_wav, normalized_wav, target_lufs: (
            recorded_calls.append((source_wav, normalized_wav, target_lufs)),
            shutil.copyfile(source_wav, normalized_wav),
        ),
    )
    monkeypatch.setattr(
        "sound_cut.media.render.export_delivery_audio",
        lambda source_wav, delivered_path, received_source: shutil.copyfile(source_wav, delivered_path),
    )

    summary = render_audio_from_edl(plan)

    assert summary.kept_segment_count == 1
    assert recorded_calls and recorded_calls[0][2] == -18.0
    assert output_path.exists()
```

```python
# tests/test_render.py
def _wave_rms(path) -> float:
    with wave.open(str(path), "rb") as handle:
        samples = struct.unpack("<" + "h" * handle.getnframes() * handle.getnchannels(), handle.readframes(handle.getnframes()))
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def test_render_audio_from_edl_auto_volume_increases_low_level_output(tmp_path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    plain_output_path = tmp_path / "plain.wav"
    normalized_output_path = tmp_path / "normalized.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=16_000,
        samples=tone_samples(sample_rate_hz=16_000, duration_s=0.8, amplitude=500),
    )
    source = SourceMedia(
        input_path=input_path,
        duration_s=0.8,
        audio_codec="pcm_s16le",
        sample_rate_hz=16_000,
        channels=1,
        has_video=False,
    )
    edl = EditDecisionList(operations=(EditOperation("keep", TimeRange(0.0, 0.8), "speech"),))

    plain_summary = render_audio_from_edl(
        RenderPlan(
            source=source,
            edl=edl,
            output_path=plain_output_path,
            target="audio",
            crossfade_ms=0,
            loudness=LoudnessNormalizationConfig(enabled=False, target_lufs=-16.0),
        )
    )
    normalized_summary = render_audio_from_edl(
        RenderPlan(
            source=source,
            edl=edl,
            output_path=normalized_output_path,
            target="audio",
            crossfade_ms=0,
            loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-16.0),
        )
    )

    assert plain_summary.output_duration_s == pytest.approx(normalized_summary.output_duration_s, abs=1e-3)
    assert _wave_rms(normalized_output_path) > _wave_rms(plain_output_path)
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_normalize_loudness_builds_loudnorm_pcm_wave_command tests/test_render.py::test_render_audio_from_edl_normalizes_internal_wave_before_delivery tests/test_render.py::test_render_audio_from_edl_auto_volume_increases_low_level_output -q
```

Expected:

- FAIL because `normalize_loudness()` does not exist and `render_audio_from_edl()` has no post-processing branch

- [ ] **Step 3: Write the minimal implementation**

```python
# src/sound_cut/media/ffmpeg_tools.py
def normalize_loudness(source_wav: Path, output_wav: Path, target_lufs: float) -> None:
    ffmpeg = _require_binary("ffmpeg")
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            str(source_wav),
            "-af",
            f"loudnorm=I={target_lufs}",
            "-c:a",
            "pcm_s16le",
            "-f",
            "wav",
            str(output_wav),
        ]
    )
```

```python
# src/sound_cut/media/render.py
from sound_cut.media.ffmpeg_tools import (
    _require_binary,
    _run,
    export_delivery_audio,
    normalize_loudness,
    probe_source_media,
)


def render_audio_from_edl(plan: RenderPlan) -> RenderSummary:
    output_path = plan.output_path

    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_output_path = temp_dir / "render.wav"
        delivery_suffix = output_path.suffix.lower()
        force_nonempty = delivery_suffix in {".mp3", ".m4a"}
        kept_segment_count = _render_internal_wave(
            plan,
            internal_output_path,
            force_nonempty=force_nonempty,
        )
        delivery_input_path = internal_output_path
        if plan.loudness.enabled and kept_segment_count > 0:
            normalized_output_path = temp_dir / "normalized.wav"
            normalize_loudness(
                internal_output_path,
                normalized_output_path,
                target_lufs=plan.loudness.target_lufs,
            )
            delivery_input_path = normalized_output_path
        export_delivery_audio(delivery_input_path, output_path, plan.source)
    if kept_segment_count == 0 and delivery_suffix == ".wav":
        output_duration_s = 0.0
    elif delivery_suffix == ".wav":
        output_duration_s = _wave_duration_s(output_path)
    else:
        output_duration_s = probe_source_media(output_path).duration_s
    return RenderSummary(
        input_duration_s=plan.source.duration_s,
        output_duration_s=output_duration_s,
        removed_duration_s=max(0.0, plan.source.duration_s - output_duration_s),
        kept_segment_count=kept_segment_count,
    )
```

- [ ] **Step 4: Run the targeted tests to verify they pass**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py::test_normalize_loudness_builds_loudnorm_pcm_wave_command tests/test_render.py::test_render_audio_from_edl_normalizes_internal_wave_before_delivery tests/test_render.py::test_render_audio_from_edl_auto_volume_increases_low_level_output -q
```

Expected:

- PASS

- [ ] **Step 5: Commit**

```bash
git add src/sound_cut/media/ffmpeg_tools.py src/sound_cut/media/render.py tests/test_ffmpeg_tools.py tests/test_render.py
git commit -m "feat: normalize rendered audio loudness"
```

## Task 4: Document The New CLI And Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `README_cn.md`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing end-to-end pipeline composition test**

```python
# tests/test_pipeline.py
import math
import struct
import wave

from sound_cut.core.models import LoudnessNormalizationConfig


def _wave_rms(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        raw = handle.readframes(handle.getnframes())
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def test_process_audio_can_cut_and_normalize_in_one_command(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    plain_output_path = tmp_path / "plain.wav"
    normalized_output_path = tmp_path / "normalized.wav"
    samples = (
        tone_samples(sample_rate_hz=48_000, duration_s=0.40, amplitude=500)
        + silence_samples(sample_rate_hz=48_000, duration_s=0.20)
        + tone_samples(sample_rate_hz=48_000, duration_s=0.40, amplitude=500)
    )
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=samples)
    analyzer = FakeSpeechAnalyzer((TimeRange(0.0, 0.4), TimeRange(0.6, 1.0)))
    profile = replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0, crossfade_ms=0)

    plain_summary = process_audio(
        input_path=input_path,
        output_path=plain_output_path,
        profile=profile,
        loudness=LoudnessNormalizationConfig(enabled=False, target_lufs=-16.0),
        analyzer=analyzer,
    )
    normalized_summary = process_audio(
        input_path=input_path,
        output_path=normalized_output_path,
        profile=profile,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-16.0),
        analyzer=FakeSpeechAnalyzer((TimeRange(0.0, 0.4), TimeRange(0.6, 1.0))),
    )

    assert plain_summary.kept_segment_count == 2
    assert normalized_summary.kept_segment_count == 2
    assert normalized_summary.output_duration_s == pytest.approx(plain_summary.output_duration_s, abs=1e-3)
    assert _wave_rms(normalized_output_path) > _wave_rms(plain_output_path)
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py::test_process_audio_can_cut_and_normalize_in_one_command -q
```

Expected:

- FAIL until the loudness-enabled render path and pipeline wiring work together end-to-end

- [ ] **Step 3: Update the README files with the new options and combined-command examples**

```markdown
# README.md
- `--auto-volume`
  Normalize the final kept audio to a target loudness. Disabled by default.
- `--target-lufs N`
  Override the target loudness used with `--auto-volume`. Default effective value is `-16.0`.
```

```bash
python3.11 -m sound_cut input.mp3 --aggressiveness dense --auto-volume
python3.11 -m sound_cut input.mp3 --aggressiveness dense --auto-volume --target-lufs -18
```

```markdown
# README_cn.md
- `--auto-volume`：对最终保留的音频做目标响度归一化，默认关闭。
- `--target-lufs N`：配合 `--auto-volume` 覆盖目标响度。默认生效值为 `-16.0`。
```

```bash
python3.11 -m sound_cut input.mp3 --aggressiveness dense --auto-volume
python3.11 -m sound_cut input.mp3 --aggressiveness dense --auto-volume --target-lufs -18
```

- [ ] **Step 4: Run the end-to-end test and the full suite**

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py::test_process_audio_can_cut_and_normalize_in_one_command -q
```

Expected:

- PASS

Run:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q
```

Expected:

- PASS with no failures

- [ ] **Step 5: Commit**

```bash
git add README.md README_cn.md tests/test_pipeline.py tests/test_cli.py tests/test_render.py tests/test_ffmpeg_tools.py tests/test_package_layout.py src/sound_cut
git commit -m "docs: document auto volume normalization"
```
