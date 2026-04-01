# Compressed Delivery Output Design

## Summary

The tool should stop treating WAV as the user-facing delivery format. WAV remains the safest internal render format for timeline-accurate cutting, but the final exported file should follow the input format by default so output size stays in the same general range as the original compressed file.

The recommended architecture is:

1. render internally to temporary WAV
2. export final delivery file in a format selected from the input or explicit output suffix

This preserves the current stable cut/render pipeline while solving the user-visible size blow-up problem.

## Problem Statement

Current output is always WAV. That creates a severe mismatch between user expectation and actual delivery size.

Example:

- input: compressed `mp3`, a few hundred KB
- output: uncompressed `wav`, several MB

For long recordings this gets much worse. A one-hour compressed audio file in the tens of MB can become roughly gigabyte-scale if exported as PCM WAV. That is unacceptable for upload cost, transfer time, storage, and user perception.

## Goals

- Keep current cut quality and timeline accuracy.
- Make final output file size stay in the same general order of magnitude as the original compressed input.
- Follow input format by default when the user does not explicitly request a different format.
- Preserve deterministic CLI behavior.
- Keep the implementation compatible with future video/subtitle work by not coupling output compression to the EDL model.

## Non-Goals

- Perfect preservation of original codec settings, VBR mode, or metadata.
- Bit-exact codec passthrough.
- Supporting every possible audio container in v1 of this change.
- Changing the analysis pipeline.
- Changing the edit decision logic.

## User Experience

### Default behavior

If the user does not provide `-o`, the tool should generate a default output path using the input stem plus `.cut` and the chosen output suffix.

Examples:

- `input.mp3` -> `input.cut.mp3`
- `input.m4a` -> `input.cut.m4a`
- `input.wav` -> `input.cut.wav`

### Output format selection

Rules:

1. If the user provides `-o output.xxx`, use the suffix from `output.xxx`.
2. If the user does not provide `-o`, infer the delivery suffix from the input suffix.
3. If the input suffix is unsupported as a delivery format, fall back to a known compressed default such as `.m4a`.

This means the user-facing format follows the input by default, but explicit output paths always win.

## Supported Delivery Formats

Initial delivery support should be intentionally small and explicit:

- `.mp3`
- `.m4a`
- `.wav`

The delivery format to ffmpeg encoder mapping is:

- `.mp3` -> `libmp3lame`
- `.m4a` -> `aac`
- `.wav` -> `pcm_s16le`

This mapping is an internal rule table, not a user-facing concept.

## Compression Defaults

The first version should optimize for stable, acceptable delivery rather than exposing many codec knobs.

Recommended defaults:

- MP3 delivery: `128k`
- M4A/AAC delivery: `128k`
- WAV delivery: PCM, unchanged behavior

These defaults are appropriate for spoken audio and should produce much smaller files than WAV while keeping voice quality acceptable.

Advanced codec controls such as `--bitrate` may be added later, but should not be required for this iteration.

## Architecture

The render pipeline should be split into two explicit layers.

### 1. Internal render layer

Responsibilities:

- consume the canonical EDL
- extract kept ranges
- apply fades
- preserve exact ordering and timing
- output a temporary WAV

This layer remains optimized for correctness and testability, not final size.

### 2. Delivery export layer

Responsibilities:

- choose the final encoder based on output suffix
- transcode the internal WAV into the final delivery file
- preserve output duration
- write the user-facing file

This layer owns size optimization and final container/codec selection.

## Why This Approach

This is preferable to rendering directly into MP3 or M4A segments because:

- the current WAV-based cut pipeline is already stable
- debugging cut correctness is much easier in PCM/WAV
- compressed per-segment rendering would make the pipeline more fragile
- a clean separation between internal render format and delivery format is reusable for future outputs

## CLI Behavior Changes

### `-o/--output`

`-o` should become optional.

If omitted:

- compute a default delivery path next to the input
- use input stem plus `.cut`
- use inferred output suffix

If provided:

- use the provided path directly
- delivery format is selected from that suffix

### Validation

Validation should reject:

- unsupported delivery suffixes
- in-place overwrite when resolved input and output paths are the same

### Summary output

The existing summary lines can remain unchanged:

- `input_duration_s=...`
- `output_duration_s=...`
- `removed_duration_s=...`
- `kept_segment_count=...`

There is no need to add codec information to the summary in this iteration.

## Code Changes

### `src/sound_cut/cli.py`

Changes:

- make `-o/--output` optional
- add output-path inference when omitted
- continue honoring explicit user output paths

### `src/sound_cut/models.py`

Add explicit delivery-format information to the render model, or split render planning into:

- internal temporary WAV path
- final delivery path
- delivery codec/format selection

This should be modeled cleanly so delivery logic does not leak into timeline logic.

### `src/sound_cut/render.py`

Change from:

- user output must be `.wav`

To:

- internal render always targets temporary `.wav`
- final export supports multiple delivery formats

The renderer should:

1. build the internal WAV exactly as today
2. if final delivery is WAV, copy or move that result
3. otherwise transcode that WAV to MP3 or M4A

### `src/sound_cut/ffmpeg_tools.py`

Add a helper for final export, for example:

- choose codec from suffix
- apply bitrate defaults
- run ffmpeg transcode

This keeps ffmpeg invocation details out of the higher-level renderer.

## Testing Strategy

### CLI tests

Add coverage for:

- omitted `-o` generates `input.cut.<same_ext>`
- explicit `-o output.mp3` preserves explicit output format
- unsupported inferred suffix falls back to a supported compressed format or raises, depending on final chosen rule

### Render/export tests

Add coverage for:

- MP3 output exists and ffprobe reports MP3-compatible audio
- M4A output exists and ffprobe reports AAC/M4A-compatible audio
- delivery output duration matches internal rendered duration closely

### End-to-end tests

Add coverage for:

- MP3 input to MP3 output
- WAV input to WAV output
- compressed output is materially smaller than equivalent WAV output for the same content

## Error Handling

The new export layer should surface clear domain errors for:

- unsupported output suffix
- missing ffmpeg encoder support
- export transcode failure

Errors should remain CLI-friendly and continue to return non-zero exit status.

## Future Compatibility

This change should not alter:

- canonical EDL semantics
- source-to-output timestamp logic
- future subtitle remapping design
- future video-synchronized cutting design

By keeping WAV as the internal render target, future media-synchronized workflows can still depend on a predictable intermediate result, while delivery formatting stays a separate concern.

## Recommended Scope

Keep this iteration tightly focused on:

- output path inference
- delivery format selection
- final export compression

Do not expand this change to include:

- bitrate tuning UI
- metadata copying
- waveform preview
- loudness normalization
- video export
