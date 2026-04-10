# sound-cut

`sound-cut` is a Python CLI for shortening spoken audio by removing low-value pauses while keeping speech content intact.

## Quick Start

Run the tool on an audio file:

```bash
python3.11 -m sound_cut input.mp3 --cut
```

When `--cut` is enabled, this will create a shortened output next to the input file. By default:

- `input.mp3` -> `input.cut.mp3`
- `input.m4a` -> `input.cut.m4a`
- `input.wav` -> `input.cut.wav`
- `input.mp4` -> `input.cut.mp4`

If you want an explicit output path:

```bash
python3.11 -m sound_cut input.mp3 -o output.mp3 --cut
```

## Requirements

- Python `3.11+`
- `ffmpeg`
- `ffprobe`

## Installation

Install in editable mode:

```bash
python3.11 -m pip install -e .[dev]
```

## How It Works

The CLI:

1. probes the input media
2. optionally enhances speech when `--enhance-speech` is set
3. detects speech regions
4. builds a keep/discard timeline
5. optionally cuts the source timeline when `--cut` is set
6. optionally applies loudness normalization when `--auto-volume` is set
7. exports the requested delivery file

For compressed outputs like `mp3` and `m4a`, delivery bitrate is chosen adaptively in a `64k..128k` range so output size stays reasonable.

## Processing Modes

`--enhance-speech`, `--cut`, and `--auto-volume` are independent features. You can use each one by itself or combine them in one command.

Valid command shapes:

```bash
sound-cut input.mp3 --enhance-speech
sound-cut input.mp3 --cut
sound-cut input.mp3 --auto-volume
sound-cut input.mp3 --enhance-speech --cut
sound-cut input.mp3 --enhance-speech --auto-volume
sound-cut input.mp3 --cut --aggressiveness dense --auto-volume
sound-cut input.mp3 --auto-volume --target-lufs -14
```

`--enhance-speech` runs local speech enhancement before optional cutting. `--cut` enables trimming based on the detected speech timeline. `--auto-volume` enables loudness normalization on the final output. No processing mode is enabled by default.

## Output Rules

- If `-o/--output` is omitted, the output format follows the input suffix when supported.
- Supported delivery formats are `.mp3`, `.m4a`, `.wav`, and `.mp4`.
- For `.mp4` output, audio processing runs first, then the processed track is muxed back into video.
- When `--cut` is enabled for `.mp4`, the same keep/discard timeline is applied to video and audio to keep A/V synchronized.
- Unsupported input suffixes fall back to `.m4a` when output is inferred automatically.
- Input and output paths must be different.

## Common Options

- `--aggressiveness {natural,balanced,dense}`
  Controls how aggressively pauses are removed. Default is `balanced`.
- `--min-silence-ms N`
  Override the minimum silence length that can be removed.
- `--padding-ms N`
  Keep extra audio around detected speech boundaries.
- `--crossfade-ms N`
  Apply short fades at cut boundaries.
- `--enhance-speech`
  Enable local offline speech enhancement before optional cutting.
- `--enhancer-backend {deepfilternet3,resemble-enhance}`
  Select enhancement backend. Default is `deepfilternet3`. `resemble-enhance` is currently a placeholder backend and not yet runnable.
- `--enhancer-profile {natural,strong}`
  Select enhancement strength profile. Default is `natural`.
- `--model-path PATH`
  Use an explicit local model directory for enhancement backends. For `deepfilternet3`, this path can point directly to raw model files (manifest not required).
- `--auto-volume`
  Enable loudness normalization on the final output. This is opt-in and disabled by default.
- `--target-lufs N`
  Set the normalization target when `--auto-volume` is enabled. Default is `-16.0`.
- `--cut`
  Enable trimming of the input audio. This is opt-in and disabled by default.
- `--keep-temp`
  Keep intermediate analysis audio for debugging.

## Example

More aggressive trimming with explicit output:

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
  --cut \
  --aggressiveness dense \
  --min-silence-ms 140 \
  --padding-ms 40 \
  --crossfade-ms 5
```

Trim pauses and normalize loudness in the same command:

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
  --cut \
  --aggressiveness dense \
  --min-silence-ms 140 \
  --padding-ms 40 \
  --crossfade-ms 5 \
  --auto-volume \
  --target-lufs -14.0
```

If you omit `--target-lufs`, `--auto-volume` uses the default target of `-16.0`:

```bash
python3.11 -m sound_cut interview.wav \
  --auto-volume
```

Enhance speech, cut pauses, and normalize loudness in one command:

```bash
python3.11 -m sound_cut lecture.wav \
  --enhance-speech \
  --cut \
  --auto-volume
```

## Model Commands

Install and inspect offline enhancement models:

```bash
python3.11 -m sound_cut models list
python3.11 -m sound_cut models install deepfilternet3
```

Import a locally downloaded model directory:

```bash
python3.11 -m sound_cut models import deepfilternet3 /path/to/model-dir
python3.11 -m sound_cut models verify deepfilternet3
```

`models install` prepares the local model directory and manifest scaffold.
`models import` copies actual model assets, then `models verify` checks readiness.
`models list` shows scaffold-only entries as `prepared`.

`DeepFilterNet3` enhancement also requires local runtime dependencies (for example `pip install deepfilternet`).

## CLI Output

The command prints a short summary:

- `input_duration_s`: original duration
- `output_duration_s`: final duration
- `removed_duration_s`: removed duration
- `kept_segment_count`: number of kept speech segments

Example:

```text
input_duration_s=49.002
output_duration_s=38.402
removed_duration_s=10.600
kept_segment_count=11
```

## Run Tests

```bash
python3.11 -m pytest -q
```
