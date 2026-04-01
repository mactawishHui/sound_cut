# Current State Handoff

## Purpose

This document compresses the current project context after the first usable version of the audio-cutting CLI and the first follow-up round of output-size optimization. A new thread should be able to read this file first and recover the important architecture, defaults, validation evidence, and next extension points without replaying the full conversation.

## Project Summary

The repository contains a Python 3.11 CLI tool for cutting low-value pauses from spoken audio.

Current user-facing behavior:

- input: one local audio file
- analysis: detect speech regions
- timeline: build a canonical keep/discard EDL
- render: cut kept ranges from the original media
- output: export a shortened file that follows the input format by default when supported
- summary: print `input_duration_s`, `output_duration_s`, `removed_duration_s`, and `kept_segment_count`

Current supported delivery formats:

- `.mp3`
- `.m4a`
- `.wav`

Current primary use case:

- single-speaker spoken audio

## Important User Priorities

- Preserve speech content before optimizing listening smoothness.
- Increase information density, but do not cut real words or syllables.
- `ffmpeg` and `ffprobe` are accepted runtime dependencies.
- All Python commands in this environment should use `python3.11`.
- Default delivery should not balloon file size and should feel reasonable for upload/transfer.

## Current CLI Behavior

Main entrypoint:

- [cli.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/cli.py)

Current CLI shape:

- positional input path
- optional `-o/--output`
- `--aggressiveness natural|balanced|dense`
- `--min-silence-ms`
- `--padding-ms`
- `--crossfade-ms`
- `--keep-temp`

Default output path behavior:

- `input.mp3` -> `input.cut.mp3`
- `input.m4a` -> `input.cut.m4a`
- `input.wav` -> `input.cut.wav`
- unsupported input suffix -> fallback `.m4a`

## Current Profiles

Profile definitions live in:

- [config.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/config.py)

Important current detail:

- only `dense` enables the second-pass internal pause splitter
- `natural` and `balanced` keep the earlier, more conservative analysis path

User-approved current default `dense` feel:

- `min_silence_ms=140`
- `padding_ms=40`
- `crossfade_ms=5`

These values were chosen after real-file listening validation, not just synthetic tests.

## Current Architecture

Core files:

- [cli.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/cli.py)
- [config.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/config.py)
- [errors.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/errors.py)
- [models.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/models.py)
- [ffmpeg_tools.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/ffmpeg_tools.py)
- [vad.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/vad.py)
- [pause_splitter.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/pause_splitter.py)
- [timeline.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/timeline.py)
- [render.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/render.py)
- [pipeline.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/pipeline.py)

Current pipeline:

1. Probe source media with `ffprobe`
2. Normalize analysis audio to mono 16 kHz PCM WAV
3. Run WebRTC VAD to get coarse speech ranges
4. If profile is `dense`, run a pause-splitting second pass inside long speech envelopes
5. Build a canonical keep/discard EDL
6. Render kept ranges from the original source to an internal WAV
7. Export the internal WAV to the final delivery format

Important separation:

- analysis and timeline logic decide what to keep
- rendering logic decides how to stitch audio cleanly
- delivery export decides codec/bitrate/container behavior

## Current Analysis Strategy

Speech analysis is intentionally split into layers:

1. conservative speech envelope
2. optional aggressive internal pause splitting

Important files:

- [vad.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/vad.py)
- [pause_splitter.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/pause_splitter.py)

Current important behavior:

- VAD boundary handling is conservative enough to avoid obvious semantic truncation
- `dense` performs additional low-energy pause splitting inside long speech ranges
- this second pass is the reason current `dense` can materially outperform `balanced`

## Current Render And Delivery Strategy

Important files:

- [render.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/render.py)
- [ffmpeg_tools.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/ffmpeg_tools.py)

Current render behavior:

- kept ranges are extracted with `atrim + asetpts`
- short fades are applied after timestamps are reset
- multi-segment outputs are concatenated back into an internal WAV

This matters because an earlier implementation using input seeking produced either inaccurate compressed-input cuts or later silent segments. The current `atrim + asetpts` approach is the stable path.

Current delivery behavior:

- `.wav` stays PCM
- `.mp3` / `.m4a` export from the internal WAV
- compressed export now uses adaptive bitrate instead of fixed `128k`

## Current Adaptive Bitrate Policy

Important model field:

- [models.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/models.py) `SourceMedia.bit_rate_bps`

Important helper:

- [ffmpeg_tools.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/ffmpeg_tools.py) `resolve_delivery_bitrate_bps()`

Current effective policy:

- `.wav` -> no bitrate policy
- `.mp3` / `.m4a` -> clamp into `64k..128k`
- unknown bitrate -> fallback `128k`

Current probing rules:

- audio-only inputs can use `format.bit_rate`
- if audio stream bitrate exists, it is used where appropriate
- muxed audio+video inputs do not infer audio bitrate from container-level metadata when the audio stream bitrate is missing
- audio-only inputs may still estimate bitrate from file size and duration

Important nuance:

- the original adaptive-bitrate spec said to use `format.bit_rate` before stream bitrate in general
- the current code intentionally diverged for muxed inputs because container bitrate polluted the audio reference
- treat the current code behavior as correct, not the earlier generic wording

## Edge Cases Already Found And Fixed

### 1. Semantic truncation at speech boundaries

Fixed in [vad.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/vad.py) by using a more conservative speech-range collector.

### 2. Later portions of rendered files turning silent

Original cause was the segment extraction/fade interaction. The current render path no longer uses the broken version.

### 3. Compressed-input cut inaccuracy

Using input-preseek for segment extraction caused short kept ranges from MP3 input to collapse into near-silence. The current render path uses `atrim + asetpts`, and tests cover this regression.

### 4. Output-size blow-up from WAV delivery

User-facing output is no longer fixed to WAV. Delivery now follows input format by default.

### 5. Fixed `128k` export still producing unnecessarily large compressed outputs

Adaptive bitrate now reduces output size when source media is lower bitrate.

### 6. Muxed container bitrate polluting audio bitrate inference

Current probe logic does not use container-level bitrate as a surrogate audio bitrate for muxed inputs when the audio stream bitrate is absent.

### 7. Empty keep set producing invalid compressed outputs

Current render path writes a tiny silent internal WAV for `.mp3` / `.m4a` empty outputs so ffmpeg produces a valid probeable compressed file. Summary duration now matches the actual exported file in this case.

## Current Validation Evidence

Latest full verification:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q
```

Result:

- `77 passed in 2.87s`

Focused render/export verification after the latest edge-case fixes:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest tests/test_ffmpeg_tools.py tests/test_render.py -q
```

Result:

- `33 passed in 1.61s`

## Real-File Validation

Primary real sample used repeatedly during development:

- [Say my name_哔哩哔哩_bilibili.mp3](/Users/bytedance/Downloads/Say%20my%20name_%E5%93%94%E5%93%A9%E5%93%94%E5%93%A9_bilibili.mp3)

Latest end-to-end result:

- input duration: `49.002333s`
- output duration: `38.402333s`
- removed duration: `10.600000s`
- kept segment count: `11`
- output file: [Say my name_哔哩哔哩_bilibili.cut.mp3](/Users/bytedance/Downloads/Say%20my%20name_%E5%93%94%E5%93%A9%E5%93%94%E5%93%A9_bilibili.cut.mp3)
- input size: `396K`
- output size: `301K`
- output codec: `mp3`
- output bitrate: about `64k`

Important comparison:

- before adaptive bitrate, the same sample exported around `601K`
- after adaptive bitrate, the same sample exported around `301K`

This is the current strongest real-world evidence that the delivery pipeline is behaving as intended.

## Current Important Tests

If a new thread needs to understand the current behavior quickly, these tests are the highest-value entry points:

- [test_vad.py](/Users/bytedance/codexProjects/sound_cut/tests/test_vad.py)
- [test_pause_splitter.py](/Users/bytedance/codexProjects/sound_cut/tests/test_pause_splitter.py)
- [test_timeline.py](/Users/bytedance/codexProjects/sound_cut/tests/test_timeline.py)
- [test_render.py](/Users/bytedance/codexProjects/sound_cut/tests/test_render.py)
- [test_ffmpeg_tools.py](/Users/bytedance/codexProjects/sound_cut/tests/test_ffmpeg_tools.py)
- [test_pipeline.py](/Users/bytedance/codexProjects/sound_cut/tests/test_pipeline.py)
- [test_cli.py](/Users/bytedance/codexProjects/sound_cut/tests/test_cli.py)

Especially important regressions:

- compressed-input short-range preservation
- multi-segment end-of-file audio preservation
- empty keep set compressed output validity
- muxed bitrate inference behavior
- adaptive bitrate export wiring

## Environment Notes

- Use `python3.11`, not `python3` or `python`
- Ensure PATH includes:
  - `/opt/homebrew/bin`
  - `/Library/Frameworks/Python.framework/Versions/3.11/bin`
- `ffmpeg` and `ffprobe` are expected to be available from `/opt/homebrew/bin`

## Suggested First Reads In A New Thread

If starting a fresh thread, the fastest recovery path is:

1. read this handoff file
2. read [cli.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/cli.py)
3. read [pipeline.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/pipeline.py)
4. read [render.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/render.py)
5. read [ffmpeg_tools.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/ffmpeg_tools.py)
6. read [config.py](/Users/bytedance/codexProjects/sound_cut/src/sound_cut/config.py)
7. skim [test_render.py](/Users/bytedance/codexProjects/sound_cut/tests/test_render.py) and [test_ffmpeg_tools.py](/Users/bytedance/codexProjects/sound_cut/tests/test_ffmpeg_tools.py)

## Recommended Next Scopes

The most natural next extensions are:

- multi-speaker dialogue support
- loudness balancing
- video-synchronized cutting using the same EDL
- subtitle generation and time remapping
- semantic-preservation checks through ASR comparison

Those were all discussed with the user and should continue to respect the existing architecture split:

- analysis tracks
- canonical EDL
- internal render
- final delivery export

## Non-Goals For The Next Thread Unless Explicitly Requested

- broad refactors unrelated to speech cutting
- metadata-copying work
- codec-specific tuning UI
- real-time recording support
- replacing ffmpeg
