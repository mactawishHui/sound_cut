# sound-cut

`sound-cut` is a Python tool for shortening spoken audio/video by removing low-value pauses, normalizing loudness, enhancing speech quality, and generating subtitles — available as both a **Web UI** and a **CLI**.

## Web UI (Recommended)

### Local Development

```bash
# 1. Start the API server
DASHSCOPE_API_KEY=<your-key> python start.py

# 2. Start the frontend dev server (in a separate terminal)
cd frontend && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### Deploy to Zeabur (Free, China-accessible)

1. Push the repo to GitHub
2. Create a project on [zeabur.com](https://zeabur.com) — choose **Hong Kong** or **Singapore** region
3. Add service → Git → select this repo, branch `feature/web-ui`
4. Set environment variable: `DASHSCOPE_API_KEY=<your-key>`
5. Generate a domain — done

The Dockerfile handles everything: Node frontend build + Python + ffmpeg.

### Deploy with Docker

```bash
docker build -t sound-cut .
docker run -p 8080:8080 -e DASHSCOPE_API_KEY=<your-key> sound-cut
```

Open [http://localhost:8080](http://localhost:8080).

---

## CLI

### Quick Start

```bash
sound-cut input.mp3 --cut
sound-cut input.mp4 --cut --auto-volume --enhance-speech
sound-cut input.mp3 --subtitle
```

Default output path:
- `input.mp3` → `input.cut.mp3`
- `input.mp4` → `input.cut.mp4`

Explicit output:

```bash
sound-cut input.mp3 -o output.mp3 --cut
```

### Installation

```bash
pip install -e ".[dev]"
```

Requires: Python 3.11+, `ffmpeg`, `ffprobe`

---

## Features

| Feature | Flag | Description |
|---------|------|-------------|
| Silent cut | `--cut` | Detect and remove long pauses |
| Auto volume | `--auto-volume` | Loudness normalization (default −16 LUFS) |
| Speech enhancement | `--enhance-speech` | AI denoising via DeepFilterNet3 |
| Subtitle generation | `--subtitle` | Speech-to-text via FunASR + DashScope API |

All four features are independent and can be combined freely.

### Processing Pipeline

```
probe_source_media()
  → enhance_audio()              # --enhance-speech
  → normalize_audio_for_analysis()
  → WebRtcSpeechAnalyzer.analyze()
  → refine_speech_ranges()
  → build_edit_decision_list()   # --cut
  → render_audio_from_edl()
  → normalize_loudness()         # --auto-volume
  → generate_subtitles()         # --subtitle
  → export_delivery_audio()
→ RenderSummary
```

---

## CLI Options

### Cut options
- `--cut` — enable silence removal
- `--aggressiveness {natural,balanced,dense}` — removal strength, default `balanced`
- `--min-silence-ms N` — minimum silence length to remove
- `--padding-ms N` — audio to keep around speech boundaries
- `--crossfade-ms N` — fade length at cut boundaries

### Volume options
- `--auto-volume` — enable loudness normalization
- `--target-lufs N` — normalization target, default `-16.0`

### Enhancement options
- `--enhance-speech` — enable speech enhancement
- `--enhancer-backend {deepfilternet3,resemble-enhance}` — backend, default `deepfilternet3`
- `--enhancer-profile {natural,strong}` — strength, default `natural`
- `--model-path PATH` — local model directory

### Subtitle options
- `--subtitle` — enable subtitle generation (requires `DASHSCOPE_API_KEY`)
- `--subtitle-language LANG` — language hint (e.g. `zh`, `en`, `ja`), default auto-detect
- `--subtitle-format {srt,vtt}` — output format, default `srt`
- `--subtitle-sidecar` — output subtitle file only, do not embed
- `--subtitle-mkv` — embed as MKV soft subtitle track
- `--subtitle-burn` — burn subtitles into video
- `--subtitle-max-chars N` — max characters per subtitle line, default `25`

### Other
- `--keep-temp` — keep intermediate files for debugging
- `-o / --output PATH` — explicit output path

---

## Examples

Trim pauses aggressively with crossfade:

```bash
sound-cut podcast.mp3 -o podcast.cut.mp3 \
  --cut --aggressiveness dense \
  --min-silence-ms 140 --crossfade-ms 5
```

Enhance, cut, and normalize in one pass:

```bash
sound-cut lecture.wav \
  --enhance-speech --cut --auto-volume --target-lufs -14
```

Generate a sidecar subtitle file:

```bash
DASHSCOPE_API_KEY=<key> sound-cut interview.mp3 \
  --subtitle --subtitle-language zh --subtitle-sidecar
```

Full pipeline — enhance + cut + normalize + burn subtitles:

```bash
DASHSCOPE_API_KEY=<key> sound-cut talk.mp4 \
  --enhance-speech --cut --auto-volume \
  --subtitle --subtitle-burn
```

---

## Model Management

```bash
sound-cut models list
sound-cut models install deepfilternet3
sound-cut models import deepfilternet3 /path/to/model-dir
sound-cut models verify deepfilternet3
```

DeepFilterNet3 also requires: `pip install deepfilternet`

---

## CLI Output

```text
input_duration_s=49.002
output_duration_s=38.402
removed_duration_s=10.600
kept_segment_count=11
```

---

## Run Tests

```bash
pytest
```

Integration tests (requires running API server):

```bash
python tests/integration/test_api_e2e.py
```
