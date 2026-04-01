# Adaptive Delivery Bitrate Design

## Summary

The compressed delivery change solved the WAV size blow-up problem, but the current export bitrate is still fixed at `128k` for compressed outputs. That keeps quality stable, yet it can still produce files noticeably larger than the original compressed input.

The next change should keep the current quality-first posture while making output size track the input more closely. The recommended policy is:

1. keep the existing compressed delivery formats and internal WAV render pipeline
2. derive a reference bitrate from the input media
3. export compressed outputs at a bitrate capped at `128k` and floored at `64k`

This preserves voice quality, avoids obvious file size inflation for low-bitrate inputs, and keeps the implementation localized to media probing and delivery export.

## Problem Statement

Current compressed delivery uses a fixed bitrate:

- `.mp3` -> `128k`
- `.m4a` -> `128k`

That is stable, but it ignores the characteristics of the input file. For example:

- a source `mp3` encoded near `64k` may be exported at `128k`
- the resulting cut file can still be larger than the original file even though duration decreased

The user-approved direction is:

- quality first
- never default above `128k`
- within that limit, stay as close as practical to the input file size

## Goals

- Keep compressed delivery quality stable for spoken audio.
- Avoid exporting compressed outputs at a higher bitrate than necessary.
- Default to a bitrate no higher than `128k`.
- Use a source-aware bitrate choice so output size tracks the input more closely.
- Preserve current CLI behavior and avoid adding new required flags.
- Keep the solution compatible with future explicit bitrate controls.

## Non-Goals

- Bit-exact preservation of the original encoder mode or VBR profile.
- Copying metadata tags or container-level encoding settings.
- Reworking the cut analysis pipeline.
- Adding UI or CLI controls in this iteration.
- Optimizing non-audio media outputs.

## User Experience

### Default behavior

The user-facing format rules remain unchanged:

- if `-o` is omitted, output format follows the input suffix when supported
- if `-o` is provided, the output suffix determines the delivery format

The new behavior only changes the default bitrate selection for compressed outputs.

### Quality policy

For compressed delivery formats:

- default upper bound: `128k`
- default lower bound: `64k`

Within that range, choose a bitrate based on the input media rather than always forcing `128k`.

This means:

- high-bitrate sources are capped at `128k`
- low-bitrate spoken-audio sources stay closer to their original size
- extremely low or missing source metadata does not collapse output quality below an acceptable floor

### WAV behavior

`wav` output remains PCM and does not use adaptive bitrate logic.

## Bitrate Selection Strategy

The export layer should compute a reference bitrate in this order:

1. `ffprobe format.bit_rate`
2. audio stream `bit_rate`
3. estimated bitrate from file size and duration
4. fallback default when none of the above are reliable

Then apply the delivery policy:

- `target_bitrate = clamp(reference_bitrate, min=64k, max=128k)`

Where:

- `reference_bitrate` is in bits per second
- `64k` means `64_000 bps`
- `128k` means `128_000 bps`

Examples:

- input reference `192k` -> output `128k`
- input reference `96k` -> output `96k`
- input reference `48k` -> output `64k`
- reference unavailable -> output `128k`

## Source Bitrate Derivation

The source media model should carry bitrate information forward from probing so the renderer does not need to rediscover it later.

Recommended derivation rules:

1. If `format.bit_rate` is present and parseable, use it.
2. Else if the selected audio stream has `bit_rate`, use it.
3. Else if file size and duration are both known and duration is positive, estimate:

`estimated_bitrate_bps = round(file_size_bytes * 8 / duration_s)`

4. Else leave bitrate unknown and let delivery export fall back to the default cap.

This keeps probing resilient across containers that expose bitrate differently.

## Architecture

The current layering remains valid:

1. analysis and timeline build
2. internal WAV render
3. final delivery export

Only the delivery export layer changes behavior.

### Source media model

`SourceMedia` should gain:

- `bit_rate_bps: int | None`

This field represents the best available input bitrate reference and is not required for correctness. It exists only to improve delivery defaults.

### Delivery export

The delivery export helper should change from:

- fixed bitrate mapping for compressed outputs

To:

- suffix determines codec
- source media determines default compressed bitrate within the approved floor/cap

`wav` remains uncompressed and bypasses bitrate logic.

## Why This Approach

This is preferable to continuing with a fixed bitrate because:

- it preserves the current quality ceiling
- it avoids needless size inflation on low-bitrate voice inputs
- it does not require new CLI complexity
- it reuses information already available from `ffprobe`

It is also preferable to matching input bitrate exactly without bounds because:

- very low input bitrates may sound too degraded after re-encoding
- very high input bitrates do not improve the current speech-focused use case enough to justify the extra size

## Code Changes

### `src/sound_cut/models.py`

Add bitrate metadata to `SourceMedia`:

- `bit_rate_bps: int | None`

No other model changes are required in this iteration.

### `src/sound_cut/ffmpeg_tools.py`

Extend `probe_source_media()` to populate `bit_rate_bps` from:

- format bitrate
- stream bitrate
- size/duration estimate as fallback

Add a helper for delivery bitrate policy:

- `resolve_delivery_bitrate_bps(source: SourceMedia, suffix: str) -> int | None`

Behavior:

- `.wav` -> `None`
- `.mp3` / `.m4a` -> clamped bitrate in the `64k..128k` range

Then update `export_delivery_audio()` to use that resolved bitrate instead of a fixed `128k`.

### `src/sound_cut/render.py`

No timeline changes are needed.

The render step should continue to:

1. build the internal WAV
2. pass `plan.source` into the delivery export helper
3. write the final output format as today

### `src/sound_cut/cli.py`

No user-facing argument changes are required in this iteration.

The CLI summary can remain unchanged.

## Testing Strategy

### Probe tests

Add coverage for `probe_source_media()` or supporting helpers to verify:

- format bitrate is preferred when present
- stream bitrate is used when format bitrate is absent
- file-size estimation is used when metadata bitrate is absent

### Delivery bitrate policy tests

Add focused tests for:

- source bitrate above `128k` -> `128k`
- source bitrate between bounds -> unchanged
- source bitrate below `64k` -> `64k`
- unknown bitrate -> `128k`
- `.wav` output -> no bitrate

### Export integration tests

Add real ffmpeg-backed coverage that:

- exports `mp3` from a low-bitrate source and does not force `128k`
- exports `m4a` with the same adaptive policy
- preserves requested codec and output duration

The tests do not need to prove exact byte-for-byte file size. They need to prove the bitrate policy is being applied.

### End-to-end validation

Reuse a real `mp3` sample and confirm:

- default output still follows input format
- output duration remains correct
- output file size is closer to the input than the fixed-`128k` version for the same sample

## Error Handling

Adaptive bitrate logic should not introduce new user-facing failure modes beyond existing export errors.

Rules:

- if bitrate metadata is missing, fall back silently
- if bitrate estimation cannot be computed, fall back silently
- unsupported suffix handling remains unchanged
- ffmpeg export failures remain surfaced as media errors

## Future Compatibility

This design leaves room for later additions:

- explicit `--bitrate`
- separate defaults per codec
- loudness normalization before export
- source-aware video/audio joint delivery decisions

When explicit bitrate controls are added later, they should override the adaptive default policy rather than replace the probing machinery.

## Recommended Scope

Keep this iteration tightly focused on:

- carrying source bitrate through `SourceMedia`
- adaptive bitrate selection for compressed outputs
- tests proving the new default policy

Do not expand this change to include:

- new CLI flags
- metadata copying
- VBR profile preservation
- codec-specific tuning presets
