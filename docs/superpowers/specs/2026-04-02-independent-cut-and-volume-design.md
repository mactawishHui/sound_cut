# Independent Cut And Volume Design

## Context

The current pipeline treats speech cutting as the default processing mode. Loudness normalization is implemented as an optional post-processing step after cut rendering, so `--auto-volume` cannot be used independently.

The product requirement is that speech cutting and volume normalization are two independent features:

- cut only
- auto-volume only
- cut and auto-volume together

## Decision

Introduce an explicit cut toggle in the CLI and split the pipeline into two execution paths:

1. `cut` path
   - Analyze speech
   - Build EDL
   - Render kept ranges
   - Optionally normalize loudness
   - Export delivery audio

2. `normalize only` path
   - Skip speech analysis entirely
   - Convert the source into an internal WAV when needed
   - Apply loudness normalization
   - Export delivery audio

`--auto-volume` remains default-off. Cut behavior should also become explicit instead of being implicit in every command.

## CLI Behavior

Add `--cut` as the explicit switch for speech cutting.

Supported combinations:

- no flags: reject with a clear CLI error because no processing was requested
- `--cut`: perform speech cutting only
- `--auto-volume`: perform loudness normalization only
- `--cut --auto-volume`: perform both in one command

Existing cut parameters such as `--aggressiveness`, `--min-silence-ms`, `--padding-ms`, and `--crossfade-ms` only affect the command when `--cut` is enabled.

`--target-lufs` still requires `--auto-volume`.

## Pipeline Structure

Keep the current `process_audio()` behavior for cut-enabled requests. Add a separate pipeline entry for loudness-only processing so the non-cut path does not instantiate VAD analysis, EDL generation, or edit rendering.

The two paths should share the same delivery export and loudness helpers where possible, but the branch should happen before speech analysis begins.

## Testing

Add or update tests for:

- CLI rejection when neither `--cut` nor `--auto-volume` is provided
- CLI acceptance of `--auto-volume` without `--cut`
- pipeline behavior for normalization-only processing without analyzer usage
- end-to-end processing of a source file with `--auto-volume` only
- regression coverage that `--cut --auto-volume` still works together
