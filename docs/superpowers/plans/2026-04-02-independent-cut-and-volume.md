# Independent Cut And Volume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make speech cutting and auto-volume independent CLI features so users can run cut only, auto-volume only, or both together in one command.

**Architecture:** Add an explicit `--cut` switch at the CLI boundary and branch processing before speech analysis starts. Keep the existing cut pipeline for cut-enabled runs, and add a normalization-only pipeline entry that skips VAD/EDL work while reusing the existing ffmpeg normalization and delivery export helpers.

**Tech Stack:** Python 3.11, argparse, ffmpeg/ffprobe, pytest

---

### Task 1: Lock Down The New CLI Contract

**Files:**
- Modify: `src/sound_cut/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
def test_build_parser_parses_cut_flag(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--cut"])

    assert args.cut is True


def test_main_rejects_missing_processing_mode(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([str(tmp_path / "input.wav")])

    assert excinfo.value.code == 2


def test_main_allows_auto_volume_without_cut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        *,
        enable_cut: bool,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
    ):
        captured["enable_cut"] = enable_cut
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 1.0, 0.0, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--auto-volume"])

    assert exit_code == 0
    assert captured["enable_cut"] is False
    assert captured["loudness"].enabled is True
```

- [ ] **Step 2: Run the focused CLI tests and verify they fail for the right reason**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py -q`

Expected: FAIL because `--cut` does not exist yet, the CLI still accepts no processing flags, and `process_audio()` does not accept an explicit `enable_cut` argument.

- [ ] **Step 3: Implement the minimal CLI behavior**

```python
def _validate_processing_mode(args: argparse.Namespace) -> None:
    if not args.cut and not args.auto_volume:
        raise argparse.ArgumentTypeError("at least one processing mode is required: --cut or --auto-volume")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--cut", action="store_true")
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--auto-volume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_processing_mode(args)
        loudness = _resolve_loudness_config(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    summary = process_audio(
        args.input,
        output_path,
        profile,
        enable_cut=args.cut,
        keep_temp=args.keep_temp,
        loudness=loudness,
    )
```

- [ ] **Step 4: Run the CLI tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_cli.py -q`

Expected: PASS

- [ ] **Step 5: Commit the CLI contract change**

```bash
git add src/sound_cut/cli.py tests/test_cli.py
git commit -m "feat: require explicit cut or volume processing mode"
```

### Task 2: Add A Normalization-Only Pipeline Path

**Files:**
- Modify: `src/sound_cut/editing/pipeline.py`
- Modify: `src/sound_cut/media/render.py`
- Modify: `src/sound_cut/core/models.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing pipeline and render tests**

```python
def test_process_audio_skips_analyzer_when_cut_disabled(
    tmp_path: Path, ffmpeg_available, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(input_path, sample_rate_hz=48_000, samples=tone_samples(sample_rate_hz=48_000, duration_s=0.5))

    def fail_analyze(_wav_path: Path) -> AnalysisTrack:
        raise AssertionError("analyzer should not be used when cut is disabled")

    analyzer = types.SimpleNamespace(analyze=fail_analyze)

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=False,
        analyzer=analyzer,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0),
    )

    assert summary.input_duration_s == pytest.approx(0.5, abs=1e-9)
    assert summary.output_duration_s == pytest.approx(0.5, abs=0.02)
    assert summary.removed_duration_s == pytest.approx(0.0, abs=0.02)
    assert summary.kept_segment_count == 1


def test_render_audio_without_cut_can_normalize_full_source(
    tmp_path: Path, ffmpeg_available
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=1.0, amplitude=400),
    )

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=False,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0),
    )

    assert summary.kept_segment_count == 1
    assert _integrated_lufs(output_path, target_lufs=-14.0) == pytest.approx(-14.0, abs=1.0)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py tests/test_render.py -q`

Expected: FAIL because `process_audio()` still always analyzes speech and there is no path that renders the full source without an EDL.

- [ ] **Step 3: Implement the minimal split pipeline**

```python
def _process_cut_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    *,
    analyzer,
    keep_temp: bool,
    loudness: LoudnessNormalizationConfig,
) -> RenderSummary:
    source = probe_source_media(input_path)
    if keep_temp:
        normalized_path = output_path.with_name(f"{output_path.stem}.analysis.wav")
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
        analyzer = analyzer or WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
        analysis = analyzer.analyze(normalized_path)
        analysis = _refine_analysis_ranges(normalized_path, analysis, profile)
    else:
        with tempfile.TemporaryDirectory(prefix="sound-cut-analysis-") as temp_dir_name:
            normalized_path = Path(temp_dir_name) / "analysis.wav"
            normalize_audio_for_analysis(input_path, normalized_path, sample_rate_hz=16_000)
            analyzer = analyzer or WebRtcSpeechAnalyzer(vad_mode=profile.vad_mode)
            analysis = analyzer.analyze(normalized_path)
            analysis = _refine_analysis_ranges(normalized_path, analysis, profile)
    edl = build_edit_decision_list(
        duration_s=source.duration_s,
        speech_ranges=analysis.ranges,
        padding_ms=profile.padding_ms,
        min_silence_ms=profile.min_silence_ms,
        merge_gap_ms=profile.merge_gap_ms,
    )
    return render_audio_from_edl(
        RenderPlan(
            source=source,
            edl=edl,
            output_path=output_path,
            target="audio",
            crossfade_ms=profile.crossfade_ms,
            loudness=loudness,
        )
    )


def _process_full_audio(
    input_path: Path,
    output_path: Path,
    *,
    loudness: LoudnessNormalizationConfig,
) -> RenderSummary:
    source = probe_source_media(input_path)
    return render_full_audio(
        source=source,
        output_path=output_path,
        loudness=loudness,
    )


def process_audio(
    input_path: Path,
    output_path: Path,
    profile: CutProfile,
    *,
    enable_cut: bool,
    analyzer=None,
    keep_temp: bool = False,
    loudness: LoudnessNormalizationConfig | None = None,
) -> RenderSummary:
    loudness = loudness or LoudnessNormalizationConfig(enabled=False, target_lufs=DEFAULT_TARGET_LUFS)
    if enable_cut:
        return _process_cut_audio(
            input_path,
            output_path,
            profile,
            analyzer=analyzer,
            keep_temp=keep_temp,
            loudness=loudness,
        )
    return _process_full_audio(input_path, output_path, loudness=loudness)
```

```python
def render_full_audio(*, source: SourceMedia, output_path: Path, loudness: LoudnessNormalizationConfig) -> RenderSummary:
    with tempfile.TemporaryDirectory(prefix="sound-cut-render-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        internal_output_path = temp_dir / "render.wav"
        normalize_audio_for_analysis(source.input_path, internal_output_path, sample_rate_hz=source.sample_rate_hz or 48_000)
        delivery_input_path = internal_output_path
        if loudness.enabled:
            delivery_input_path = temp_dir / "normalized.wav"
            normalize_loudness(internal_output_path, delivery_input_path, target_lufs=loudness.target_lufs)
        export_delivery_audio(delivery_input_path, output_path, source)
    return RenderSummary(
        input_duration_s=source.duration_s,
        output_duration_s=probe_source_media(output_path).duration_s,
        removed_duration_s=0.0,
        kept_segment_count=1,
    )
```

- [ ] **Step 4: Run the focused tests again and verify they pass**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py tests/test_render.py -q`

Expected: PASS

- [ ] **Step 5: Commit the independent pipeline path**

```bash
git add src/sound_cut/editing/pipeline.py src/sound_cut/media/render.py src/sound_cut/core/models.py tests/test_pipeline.py tests/test_render.py
git commit -m "feat: support independent cut and loudness processing"
```

### Task 3: Verify Real CLI Flows And Reprocess The User Audio

**Files:**
- Modify: `README.md`
- Modify: `README_cn.md`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing regression test for the new CLI combinations**

```python
def test_process_audio_can_normalize_without_cutting(tmp_path: Path, ffmpeg_available) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "normalized.wav"
    write_pcm_wave(
        input_path,
        sample_rate_hz=48_000,
        samples=tone_samples(sample_rate_hz=48_000, duration_s=1.0, amplitude=400),
    )

    summary = process_audio(
        input_path=input_path,
        output_path=output_path,
        profile=replace(build_profile("balanced"), merge_gap_ms=0, min_silence_ms=0, padding_ms=0),
        enable_cut=False,
        loudness=LoudnessNormalizationConfig(enabled=True, target_lufs=-14.0),
    )

    assert summary.removed_duration_s == pytest.approx(0.0, abs=0.02)
    assert _integrated_lufs(output_path, target_lufs=-14.0) == pytest.approx(-14.0, abs=1.0)
```

- [ ] **Step 2: Run the regression test and verify it fails before the docs/test cleanups**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_pipeline.py::test_process_audio_can_normalize_without_cutting -q`

Expected: PASS if Task 2 already covered the behavior. If it already passes, keep the test and proceed without changing implementation.

- [ ] **Step 3: Update docs for the explicit modes and example commands**

```markdown
sound-cut input.mp3 --cut
sound-cut input.mp3 --auto-volume
sound-cut input.mp3 --cut --aggressiveness dense --auto-volume
sound-cut input.mp3 --auto-volume --target-lufs -14
```

- [ ] **Step 4: Run the full verification suite and the real user command**

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q`
Expected: PASS

Run: `PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m sound_cut '/Users/bytedance/Downloads/2010课堂录像_哔哩哔哩_bilibili.mp3' -o '/tmp/2010课堂录像_哔哩哔哩_bilibili.auto-volume-only.mp3' --auto-volume`
Expected: command exits `0`, output file exists, and summary shows `removed_duration_s=0.000` or near-zero.

- [ ] **Step 5: Commit docs and verification-driven follow-up**

```bash
git add README.md README_cn.md tests/test_pipeline.py
git commit -m "docs: describe independent cut and volume modes"
```
