# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development (editable)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_pipeline.py

# Run a single test by name
pytest tests/test_vad.py::test_collapse_speech_flags_converts_frames_to_ranges

# Run the CLI
sound-cut input.mp3 --cut --auto-volume

# Build wheel
python -m build
```

Tests that call ffmpeg/ffprobe are guarded by the `ffmpeg_available` session-scoped fixture in `conftest.py` — they skip automatically if the binaries are absent.

## Architecture

`sound-cut` is a CLI tool that removes low-value pauses from spoken audio/video. Processing is orchestrated by `process_audio()` in `src/sound_cut/editing/pipeline.py`, which chains:

```
probe_source_media()          # ffprobe → SourceMedia
  → enhance_audio()           # optional DeepFilterNet3 denoising
  → normalize_audio_for_analysis()  # 16kHz mono PCM for VAD
  → WebRtcSpeechAnalyzer.analyze()  # webrtcvad → AnalysisTrack (speech ranges)
  → refine_speech_ranges()    # optional energy-based pause splitting within speech
  → build_edit_decision_list()  # AnalysisTrack → EditDecisionList (keep/discard ops)
  → render_audio_from_edl()   # ffmpeg segments + crossfades + concat
  → normalize_loudness()      # optional loudnorm filter
  → export_delivery_audio()   # adaptive bitrate encode (64–128k)
→ RenderSummary               # metrics returned to CLI
```

### Package layout

```
src/sound_cut/
  core/        — data models, config profiles, error hierarchy
  analysis/    — VAD (webrtcvad wrapper) and pause splitter
  editing/     — pipeline orchestrator and timeline/EDL builder
  media/       — ffmpeg/ffprobe wrappers and audio/video renderer
  enhancement/ — speech enhancement backends (DeepFilterNet3, Resemble-Enhance stub)
  models/      — model installer, locator, registry
```

Top-level shim files (`src/sound_cut/config.py`, `vad.py`, etc.) are backward-compat re-exports that redirect `sys.modules` to the canonical subpackage path. The canonical locations are in the subpackages above.

### Key data types (core/models.py)

- `TimeRange` — immutable `(start_s, end_s)` segment
- `SourceMedia` — probed input metadata (codec, sample rate, has_video, etc.)
- `AnalysisTrack` — tuple of `TimeRange` objects produced by analysis
- `EditOperation` — `action: "keep"|"discard"` with a `TimeRange` and optional reason
- `EditDecisionList` — ordered tuple of `EditOperation`
- `RenderPlan` — stateless blueprint passed to the renderer (source, EDL, output path, loudness config)
- `EnhancementConfig` / `LoudnessNormalizationConfig` — feature-specific config objects

### Cut profiles (core/config.py)

`build_profile(name, **overrides)` returns one of three frozen `CutProfile` presets:
- `natural` — vad_mode=1, 700ms min silence, 120ms padding
- `balanced` — vad_mode=2, 550ms min silence, 100ms padding (default)
- `dense` — vad_mode=3, 140ms min silence, 40ms padding, aggressive pause splitting

### Enhancement backends (enhancement/)

`EnhancementBackend` is an abstract base class. `DeepFilterNet3Backend` (`enhancement/deepfilternet.py`) is the only production implementation; `ResembleEnhanceBackend` is a not-yet-implemented placeholder. Models are managed via `models/` (installer, locator, registry).

### Three independent processing modes

`--cut`, `--auto-volume`, and `--enhance-speech` are independent flags; at least one must be supplied. The CLI enforces this in `_SoundCutArgumentParser`. Each generates its own ffmpeg pass; they do not share state except through the intermediate audio file on disk.
