# sound-cut

`sound-cut` is a Python CLI for shortening spoken audio by removing low-value pauses while keeping speech content intact.

## Quick Start

Run the tool on an audio file:

```bash
python3.11 -m sound_cut input.mp3 --aggressiveness dense
```

This will create a shortened output next to the input file. By default:

- `input.mp3` -> `input.cut.mp3`
- `input.m4a` -> `input.cut.m4a`
- `input.wav` -> `input.cut.wav`

If you want an explicit output path:

```bash
python3.11 -m sound_cut input.mp3 -o output.mp3 --aggressiveness dense
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
2. detects speech regions
3. builds a keep/discard timeline
4. cuts the original audio
5. exports a shortened delivery file

For compressed outputs like `mp3` and `m4a`, delivery bitrate is chosen adaptively in a `64k..128k` range so output size stays reasonable.

## Output Rules

- If `-o/--output` is omitted, the output format follows the input suffix when supported.
- Supported delivery formats are `.mp3`, `.m4a`, and `.wav`.
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
- `--auto-volume`
  Enable loudness normalization on the final output. This is opt-in and disabled by default.
- `--target-lufs N`
  Set the normalization target when `--auto-volume` is enabled. Default is `-16.0`.
- `--keep-temp`
  Keep intermediate analysis audio for debugging.

## Example

More aggressive trimming with explicit output:

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
  --aggressiveness dense \
  --min-silence-ms 140 \
  --padding-ms 40 \
  --crossfade-ms 5
```

Trim pauses and normalize loudness in the same command:

```bash
python3.11 -m sound_cut podcast.mp3 \
  -o podcast.cut.mp3 \
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
  --aggressiveness balanced \
  --min-silence-ms 180 \
  --auto-volume
```

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
