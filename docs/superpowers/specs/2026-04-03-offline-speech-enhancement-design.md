# Offline Speech Enhancement Design

## Context

The current project supports:

- optional speech cutting
- optional loudness normalization

The recent auto-volume work exposed a real product gap: loudness normalization improves overall consistency, but it does not solve intelligibility problems when speech is weak and background noise is strong. In that case, normalization can raise the noise floor together with the voice.

The new requirement is to add a local, offline speech enhancement capability that:

- improves speech intelligibility before any optional cutting
- remains usable without network access
- stays installable by end users on Windows, Linux, and macOS
- keeps feature composition consistent with the rest of the CLI

## Product Decision

Upgrade the feature from "auto volume adjustment" to a broader speech-processing pipeline:

1. speech enhancement
2. optional speech cutting
3. final loudness normalization

The user priority is naturalness over aggressive cleanup. The enhancement stage should improve clarity without strongly separating vocals or introducing obvious artifacts unless the user explicitly opts into a stronger backend or profile.

## Backend Strategy

Use a two-tier offline model strategy:

1. `DeepFilterNet3` as the default enhancement backend
2. `Resemble Enhance` as an optional higher-cost backend

### Why DeepFilterNet3 by Default

`DeepFilterNet3` is the best fit for the first implementation because it is:

- offline and local
- designed for speech enhancement / denoising
- relatively lightweight compared with larger enhancement models
- better aligned with the "natural improvement" target

### Why Resemble Enhance As Optional

`Resemble Enhance` can be offered as a non-default backend for users who want stronger enhancement and accept:

- larger local model footprint
- heavier installation requirements
- a higher risk of audible processing artifacts

It should not be the default because the product goal is not aggressive source separation.

## Model Distribution

Do not ship model weights inside the git repository or default package payload.

Instead, implement local model management:

- install model weights into a local cache directory
- allow explicit user-provided model paths
- support manual offline import

Suggested cache locations:

- macOS/Linux: `~/.cache/sound-cut/models/`
- Windows: `%LOCALAPPDATA%/sound-cut/models/`

Suggested model commands:

```bash
sound-cut models install deepfilternet3
sound-cut models install resemble-enhance
sound-cut models list
sound-cut models import /path/to/model-dir
sound-cut models verify
```

This keeps the project itself lightweight while allowing fully offline inference after model installation.

## Processing Order

The pipeline order should be fixed as:

1. speech enhancement
2. optional speech cutting
3. final loudness normalization

This order matters:

- enhancement before cutting improves the signal used by VAD and pause analysis
- cutting remains optional and independent
- loudness normalization must remain the final delivery-stage operation

Supported compositions:

- enhance only
- cut only
- loudness only
- enhance + cut
- enhance + loudness
- cut + loudness
- enhance + cut + loudness

## CLI Design

Keep the independent feature-toggle model and add explicit enhancement flags.

### Main Processing Flags

- `--enhance-speech`
- `--cut`
- `--auto-volume`

### Enhancement Options

- `--enhancer-backend {deepfilternet3,resemble-enhance}`
  - default: `deepfilternet3`
- `--enhancer-profile {natural,strong}`
  - default: `natural`
- `--model-path PATH`
  - optional explicit model directory override

### Example Commands

```bash
sound-cut input.mp3 --enhance-speech
sound-cut input.mp3 --cut
sound-cut input.mp3 --auto-volume
sound-cut input.mp3 --enhance-speech --cut
sound-cut input.mp3 --enhance-speech --auto-volume
sound-cut input.mp3 --enhance-speech --cut --auto-volume
sound-cut input.mp3 --enhance-speech --enhancer-backend deepfilternet3 --enhancer-profile natural
sound-cut input.mp3 --enhance-speech --model-path /path/to/models/deepfilternet3
```

The CLI should continue to reject commands that request no processing at all.

## Architecture

Extend the current package structure with explicit enhancement and model-management modules.

### Target Structure

```text
src/sound_cut/
  __init__.py
  __main__.py
  cli.py

  core/
    __init__.py
    config.py
    errors.py
    models.py
    paths.py

  analysis/
    __init__.py
    vad.py
    pause_splitter.py

  editing/
    __init__.py
    timeline.py
    pipeline.py

  media/
    __init__.py
    ffmpeg_tools.py
    render.py

  enhancement/
    __init__.py
    base.py
    pipeline.py
    deepfilternet.py
    resemble_enhance.py

  models/
    __init__.py
    registry.py
    installer.py
    locator.py
    manifest.py
```

### Responsibility Boundaries

- `enhancement/`
  - model inference backends
  - enhancement-stage orchestration
  - backend-specific adapters

- `models/`
  - install / import / verify / locate model assets
  - backend metadata and version manifests

- `core/paths.py`
  - platform-specific cache/model directories

- `editing/pipeline.py`
  - high-level stage composition only
  - enhancement should appear here as a pre-cut stage, not as inline ffmpeg logic

## Pipeline Integration

The pipeline should branch by feature toggles, but enhancement must be represented as an explicit processing stage.

Conceptually:

1. probe source media
2. if `--enhance-speech`, produce an enhanced intermediate audio artifact
3. if `--cut`, run analysis and EDL generation on the enhanced artifact when present, otherwise on the original source
4. render final kept audio or full-audio path as appropriate
5. if `--auto-volume`, normalize the final audio before delivery export

This keeps feature composition consistent and avoids embedding model logic in VAD or render internals.

## Cross-Platform Constraints

The solution must remain usable on Windows, Linux, and macOS.

That implies:

- no requirement for online inference
- no assumption that users can reach foreign APIs or model hosts at runtime
- model installation must support manual/offline import
- backend selection should fail clearly when a required local model is missing

The first shipped backend should prefer the option with the lowest installation and runtime friction across the three platforms.

## Error Handling

Add explicit user-facing errors for:

- enhancement requested but backend dependencies are unavailable
- enhancement requested but no local model is installed or found
- unsupported backend value
- invalid model path
- backend install/import verification failure

These errors should be separate from generic media or ffmpeg failures so users can recover without reading stack traces.

## Testing

Add tests in layers:

1. CLI tests
   - enhancement flags parse correctly
   - enhancement can be combined with cut and/or loudness
   - no-processing commands still fail

2. Model-management tests
   - cache path resolution on each platform abstraction
   - model manifest validation
   - install/import/verify flows

3. Pipeline tests
   - enhancement-only path
   - enhancement + cut path uses enhanced artifact for analysis
   - enhancement + loudness path keeps full duration when cut is disabled
   - enhancement + cut + loudness path preserves stage order

4. Backend adapter tests
   - backend invocation shape
   - model path resolution
   - missing-model failures

5. End-to-end tests
   - real audio fixture through `enhance only`
   - `enhance + cut`
   - `enhance + cut + auto-volume`

The first implementation can mock actual heavy model inference in unit tests, but end-to-end coverage should exercise at least the selected default backend path when the local model is available.
