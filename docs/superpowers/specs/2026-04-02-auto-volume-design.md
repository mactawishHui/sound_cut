# Auto Volume Normalization Design

## Summary

The next feature should add optional automatic volume normalization for spoken-audio outputs.

The user problem is not absolute loudness alone. Some recordings are produced with unstable capture conditions, and the final listening experience suffers because the output feels too quiet in one file and too loud in another. For this iteration, the approved scope is intentionally narrow:

1. add an explicit `--auto-volume` switch that is off by default
2. normalize the final kept audio to a target integrated loudness
3. allow this feature to run in the same command as the current speech-cutting flow
4. reshape the codebase into clearer subpackages before adding more post-processing features

The recommended implementation is to treat loudness normalization as an optional post-processing step applied to the internal rendered WAV before final delivery export.

## Problem Statement

Current behavior can shorten spoken audio effectively, but it does not control final playback loudness.

That creates two user-facing issues:

- some outputs remain noticeably quieter or louder than expected even after silence cutting
- the current pipeline shape does not yet express "multiple independent audio features in one command" as a first-class pattern

The user explicitly wants future features to compose in the same command invocation rather than becoming separate ad hoc tools.

## Goals

- Add optional automatic volume normalization for spoken audio outputs.
- Keep the feature disabled by default and enabled only with an explicit CLI flag.
- Apply normalization to the final kept audio so the user hears the intended result.
- Preserve compatibility with the current speech-cutting behavior.
- Establish a pipeline shape that can support multiple optional processing features in one command.
- Split the current `src/sound_cut/` flat module layout into clearer directories with responsibility-based boundaries.

## Non-Goals

- Dynamic range compression or aggressive line-by-line loudness riding.
- Per-segment gain analysis stored in the EDL.
- New profile presets for volume handling in this iteration.
- UI work beyond CLI argument additions.
- Full metadata preservation or tagging changes.
- Reworking the speech analysis strategy.

## User Experience

### Default behavior

If the user does not pass `--auto-volume`, the current behavior remains unchanged.

That means:

- speech cutting still works exactly as today
- output path and delivery format rules remain unchanged
- the command line remains backward compatible

### New CLI behavior

The CLI should add:

- `--auto-volume`
- `--target-lufs`

Approved defaults and behavior:

- `--auto-volume` is optional and defaults to disabled
- `--target-lufs` defaults to `-16.0`
- `--target-lufs` only changes behavior when `--auto-volume` is enabled

Examples:

```bash
sound-cut input.mp3 --auto-volume
sound-cut input.mp3 --aggressiveness dense --auto-volume
sound-cut input.mp3 --auto-volume --target-lufs -18
sound-cut input.mp3 --aggressiveness dense --padding-ms 40 --auto-volume --target-lufs -16
```

### Why `-16 LUFS`

The user-approved direction is whole-output target loudness normalization rather than aggressive dynamics processing.

`-16 LUFS` is the recommended default because it is a reasonable spoken-audio target that:

- is loud enough for ordinary listening
- avoids pushing gain so high that noise is unnecessarily exaggerated
- leaves room for user override if a different publishing target is needed later

## Functional Behavior

When `--auto-volume` is enabled:

1. run the existing speech-cutting flow
2. render kept ranges into the internal WAV
3. apply ffmpeg loudness normalization to that internal WAV
4. export the normalized WAV to the final delivery format

When `--auto-volume` is disabled:

1. run the existing speech-cutting flow
2. render kept ranges into the internal WAV
3. export as today with no additional processing

This means loudness normalization affects the final kept content, not the original full recording.

That execution order is explicitly approved because it best matches the actual listening result.

## Architecture

The current high-level architecture should stay recognizable:

1. source probe
2. analysis normalization WAV
3. speech analysis and optional pause refinement
4. EDL construction
5. internal kept-audio render
6. optional post-processing chain
7. delivery export

The important architectural change is to make step 6 explicit.

Instead of treating delivery as a single direct jump from internal WAV to final output, the renderer should support zero or more post-processing steps on the internal WAV. In this iteration there is only one such step:

- loudness normalization via ffmpeg `loudnorm`

That structure is preferable to inserting a one-off branch into the export helper because it creates a clean extension point for later features.

## Codebase Restructure

The current flat layout under `src/sound_cut/` should be reorganized into responsibility-based subpackages before or while adding the new feature.

Approved target structure:

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
```

Boundary intent:

- `core/` holds stable shared types, config, and domain errors
- `analysis/` decides which ranges represent speech
- `editing/` turns analysis into edit decisions and orchestrates the processing flow
- `media/` handles ffmpeg integration, rendering, delivery, and post-processing

`cli.py` remains top-level because it is the public entrypoint and should stay easy to discover.

This is intentionally a moderate split. It improves boundaries without overfitting the project to a heavyweight layered architecture.

## Data Model Changes

The render layer currently receives a `RenderPlan` with source, EDL, output path, target, and crossfade settings.

This iteration should extend the render configuration with an explicit loudness normalization object rather than adding loose scalar parameters.

Recommended model:

- `LoudnessNormalizationConfig`
  - `enabled: bool`
  - `target_lufs: float`

Recommended render-plan change:

- `RenderPlan`
  - existing fields unchanged
  - add `loudness: LoudnessNormalizationConfig`

This keeps the optional feature cohesive and makes future processing additions easier to represent clearly.

## Media Processing Strategy

The implementation should use ffmpeg `loudnorm` against the rendered internal WAV.

Recommended scope for this iteration:

- use a simple one-pass `loudnorm` invocation
- target integrated loudness with `I=<target_lufs>`
- do not add a second-pass measured loudness workflow yet
- do not introduce dynamic normalization filters such as `dynaudnorm`

Why this approach:

- it matches the approved "whole-output target loudness" behavior
- it keeps implementation localized to media processing rather than analysis logic
- it is stable and readily available in ffmpeg
- it avoids moving into compression-heavy behavior that the user did not ask for

## Integration Points

### CLI

`cli.py` should:

- parse `--auto-volume` as a boolean flag
- parse `--target-lufs` as a float
- validate that `--target-lufs` is only used to tune an optional processing step
- pass the resulting configuration into the processing pipeline

### Pipeline

The pipeline module should keep orchestration responsibilities only.

It should:

- build the profile as today
- build loudness normalization config from CLI options
- construct the `RenderPlan`
- continue delegating ffmpeg behavior to media helpers

The pipeline should not embed ffmpeg filter strings directly.

### Render layer

The render path should change from:

1. internal WAV render
2. final export

To:

1. internal WAV render
2. optional post-process WAV transform chain
3. final export

Implementation detail:

- if loudness normalization is disabled, export the rendered WAV directly
- if enabled, write a second temporary WAV containing normalized audio, then export that WAV

This preserves the internal WAV contract and keeps the export helper focused on delivery format concerns.

### FFmpeg helpers

The ffmpeg helper module should gain a focused helper such as:

- `normalize_loudness(source_wav: Path, output_wav: Path, target_lufs: float) -> None`

That helper should:

- require `ffmpeg`
- run with existing log-suppression conventions
- force WAV PCM output for the transformed intermediate file
- surface failures as `MediaError` via the existing `_run()` wrapper

## Testing Strategy

This feature must be implemented with TDD.

### CLI tests

Add coverage that verifies:

- `--auto-volume` defaults to `False`
- `--target-lufs` defaults to `-16.0`
- explicit `--auto-volume` parses as enabled
- explicit `--target-lufs` is passed through to the pipeline configuration

### Pipeline tests

Add coverage that verifies:

- loudness config is present on the render plan
- normalization disabled does not trigger the post-process helper
- normalization enabled keeps working with current speech-cut behavior

### FFmpeg helper tests

Add focused tests for the new helper to verify:

- the generated ffmpeg command includes `loudnorm`
- the target LUFS is forwarded correctly
- output is explicitly forced to WAV PCM
- log suppression flags remain present

### Render integration tests

Add real ffmpeg-backed coverage that:

- renders a low-amplitude WAV with normalization disabled and captures baseline loudness proxy
- renders the same audio with normalization enabled and confirms the result is louder
- preserves output duration within reasonable tolerance
- still writes correct compressed delivery formats when normalization is enabled

The tests do not need exact measured LUFS equality. They need to prove the optional post-processing step is applied and materially changes the output in the expected direction.

## Error Handling

The feature should not introduce new bespoke user-facing error categories.

Rules:

- invalid input and output path handling remains unchanged
- ffmpeg failures from normalization surface through the existing media error path
- if normalization is disabled, the feature adds no extra failure surface
- unsupported output formats remain handled by the current delivery-export rules

## Compatibility And Future Extensions

The important long-term outcome of this change is not only `--auto-volume`.

It is the introduction of a composable post-processing stage that can support future features in one command without tangling analysis, timeline, and delivery logic together.

Future optional steps could include:

- noise cleanup
- trim/fade polish
- additional mastering presets

Those future ideas are out of scope for this design, but the architecture here should make them straightforward to add without redesigning the pipeline again.
