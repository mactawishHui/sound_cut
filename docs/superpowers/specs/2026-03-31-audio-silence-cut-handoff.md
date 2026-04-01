# Audio Silence Cut Handoff

## Purpose

This document compresses the important context from the current implementation and validation cycle so later work can continue without replaying the full conversation history.

## Current Product State

The repository contains a Python 3.11 CLI tool that:

- accepts a single input audio file
- detects speech regions
- builds a canonical keep/discard edit decision list (EDL)
- renders a shortened WAV output
- prints a summary with input duration, output duration, removed duration, and kept segment count

The first supported use case is single-speaker spoken audio. The architecture still preserves room for later diarization, loudness balancing, video-synchronized cutting, and subtitles.

## Important User Priorities

- Preserve speech content before optimizing listening smoothness.
- Prefer higher information density, but do not swallow real words or syllables.
- `ffmpeg` is an accepted runtime dependency.
- All Python commands in this environment must use `python3.11`.

## Current Core Files

- `src/sound_cut/cli.py`
- `src/sound_cut/config.py`
- `src/sound_cut/errors.py`
- `src/sound_cut/models.py`
- `src/sound_cut/ffmpeg_tools.py`
- `src/sound_cut/timeline.py`
- `src/sound_cut/vad.py`
- `src/sound_cut/render.py`
- `src/sound_cut/pipeline.py`

## What Was Implemented In v1

### Canonical pipeline

The current pipeline is:

1. Probe source media with `ffprobe`
2. Normalize analysis audio to mono 16 kHz PCM WAV
3. Run WebRTC VAD to produce speech intervals
4. Shape speech intervals into a canonical EDL
5. Render kept audio ranges from the original source

### Profiles

The CLI exposes:

- `natural`
- `balanced`
- `dense`

It also supports:

- `--min-silence-ms`
- `--padding-ms`
- `--crossfade-ms`
- `--keep-temp`

## Bugs Found And Fixed

### 1. Semantic truncation at speech boundaries

**Symptom**

Real spoken content was being clipped. Users reported that meaningful speech was cut away, not only silence.

**Root cause**

`src/sound_cut/vad.py` originally collapsed raw WebRTC VAD flags directly into speech ranges. That made segment boundaries too tight and did not tolerate brief non-speech gaps around real speech.

**Fix**

The analyzer now uses a more conservative `collect_speech_ranges()` stage that:

- adds boundary padding around detected speech
- tolerates short false gaps
- still splits across long enough silent gaps

**Tests**

`tests/test_vad.py` now covers:

- lead-in and hangover padding
- preserving a segment across a short false gap
- still splitting across a genuinely long false gap

### 2. Rendered output became silent after later segments

**Symptom**

Rendered files could sound correct at the beginning and then become fully silent after a later timestamp.

**Root cause**

In `src/sound_cut/render.py`, each kept segment was extracted with `ffmpeg` using `-ss` after `-i`, while `afade` was applied to the segment. For later segments, the fade filter effectively operated against the original timeline and could fade the entire extracted segment to zero.

**Fix**

Kept segment extraction now places `-ss` and `-t` before `-i`, so the extracted segment timeline starts at zero before `afade` is applied.

**Regression test**

`tests/test_render.py` now includes a stereo multi-segment render case that verifies there is still real audio near the end of the rendered output.

## Current Validation Evidence

Fresh verification after the render fix:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m pytest -q
```

Result:

- `44 passed in 1.58s`

## Real-File Validation: "Say my name"

Input file:

- `/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3`

### Stable semantic-preserving version

Command:

```bash
PATH=/opt/homebrew/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$PATH PYTHONPATH=src python3.11 -m sound_cut \
  '/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3' \
  -o /tmp/say_my_name.semantic.wav \
  --aggressiveness dense \
  --min-silence-ms 180 \
  --padding-ms 50 \
  --crossfade-ms 6
```

Measured result:

- input duration: `49.002333s`
- output duration: `43.182333s`
- removed duration: `5.820000s`
- kept segment count: `7`

The rendered output now contains valid audio across the full duration instead of turning silent mid-file.

### More aggressive variants already tested

`/tmp/say_my_name.aggressive.wav`

- parameters: `--min-silence-ms 120 --padding-ms 30 --crossfade-ms 4`
- output duration: `42.942333s`
- kept segment count: `7`

`/tmp/say_my_name.very_aggressive.wav`

- parameters: `--min-silence-ms 80 --padding-ms 20 --crossfade-ms 3`
- output duration: `42.822333s`
- kept segment count: `7`

## Key Observation From Real Validation

The current bottleneck is no longer rendering or boundary swallowing. The bottleneck is analysis.

Changing render-side aggressiveness parameters only reduced the `Say my name` output by a few tenths of a second because the analyzer still grouped early speech into large continuous regions.

For the current semantic-preserving version, the first major kept region was:

- `keep 0.000-13.640 speech`

That means the early part of the file was not truly available for further trimming, because the analysis stage had already decided it was one large speech-dominated region.

## What This Means

Future work that wants more aggressive cuts should not focus mainly on:

- `--min-silence-ms`
- `--padding-ms`
- `--crossfade-ms`

Those still matter, but they are now secondary.

The next meaningful improvement must happen earlier:

- inside the analysis stage
- before the EDL is generated

## Recommended Next Scope

The next version should keep the current conservative speech envelope for semantic safety, then add a second pass that finds low-energy pause candidates inside long speech ranges.

That allows the system to:

- preserve word boundaries more safely than pure threshold cutting
- split overly broad VAD regions
- become more aggressive without going back to swallowing speech

## Non-Goals For The Next Iteration

- speaker diarization
- loudness balancing
- subtitle generation
- video-synchronized rendering
- listening-quality scoring

Those remain future architectural extensions, not part of the immediate next bugfix/iteration.
