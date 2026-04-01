# Audio Silence Cut Design

## Summary

Build a CLI tool that accepts a single input audio file, detects human speech regions, removes long non-meaningful silent gaps, and writes a shortened output audio file that still sounds like normal continuous speech. The first version targets single-speaker, close-mic spoken audio.

Although v1 only implements audio silence cutting, the architecture must support future expansion into multi-speaker conversation handling, loudness balancing, video-synchronized cutting, and subtitle generation without rewriting the core pipeline.

## Goals

- Shorten spoken audio by removing long silent gaps between speech regions.
- Preserve spoken content while avoiding swallowed leading consonants, truncated tails, or obvious hard cuts.
- Favor higher information density, but keep the result sounding like a person speaking naturally.
- Provide a simple CLI experience: one input file, one output file, deterministic output.

## Non-Goals

- Real-time recording or streaming processing.
- Implementing multi-speaker diarization or speaker-aware editing in v1.
- Implementing loudness balancing in v1.
- Implementing video-synchronized cutting in v1.
- Implementing subtitle generation in v1.
- Background music, sound effects, or general-purpose media editing.
- Perfect support for conference, interview, or far-field microphone recordings in v1.

## User Experience

The initial interface is a command-line tool:

```bash
python -m sound_cut input.wav -o output.wav
```

Default behavior is tuned for single-speaker near-field speech and should:

- Detect speech automatically.
- Remove clearly long pauses.
- Keep short rhetorical pauses and breathing space when possible.
- Add small boundary padding around kept speech segments.
- Apply a very short smoothing fade at cut boundaries.
- Print a summary including original duration, output duration, removed duration ratio, and kept segment count.

## Architecture

The system should be built around a canonical timeline-edit model rather than a single-purpose "cut audio now" script. That timeline model is the extension point that future features reuse.

The v1 pipeline is still four stages, but each stage must produce explicit artifacts that later stages and future features can reuse:

1. **Media ingestion**
   - Probe source metadata.
   - Register source media streams and duration.
   - Decode audio into an analysis-friendly format.

2. **Analysis**
   - Run voice activity detection over short frames.
   - Produce reusable analysis tracks, not only a final cut decision.
   - Convert frame decisions into raw speech intervals.

3. **Edit decision shaping**
   - Merge neighboring speech intervals separated by tiny gaps.
   - Add front/back padding to avoid clipping word boundaries.
   - Remove only pauses above the configured threshold.
   - Produce a canonical keep/discard timeline.

4. **Rendering**
   - Render one or more outputs from the canonical timeline.
   - In v1 this means processed audio.
   - Later this same timeline can drive video cutting, subtitle remapping, and other synchronized outputs.

## Core Data Model

The core of the architecture is a small set of reusable domain objects.

### Source media

Represents the original input and its streams:

- input path
- duration
- audio stream metadata
- optional video stream metadata

This keeps the system ready for later video-aware workflows without making v1 video-dependent.

### Analysis tracks

Analysis tracks are time-aligned machine-readable outputs produced from source media. Examples:

- speech / non-speech decisions from VAD
- future speaker labels for multi-speaker dialogue
- future loudness measurements for gain normalization
- future ASR token or segment timestamps for subtitles

Each analysis track must be independent from rendering so new analyzers can be added without rewriting the edit logic.

### Edit decision list

The canonical output of the decision stage should be an edit decision list (EDL) or equivalent keep-timeline structure. Each entry represents:

- start time in source
- end time in source
- an edit action such as `keep` or `discard`
- optional metadata such as why a boundary exists

This object is the contract between analysis and rendering. It must remain media-agnostic so it can later drive both audio-only and audio+video rendering.

For implementation convenience, v1 may render from an ordered kept-interval list, but that list should be derived from the same canonical edit decision model rather than replacing it with a special-case structure.

### Render plan

A render plan combines:

- source media
- edit decision list
- output target type
- output-specific settings

Examples of output target types:

- processed audio
- future processed video
- future subtitle file
- future debug timeline JSON

This separation prevents output-specific code from leaking into the decision logic.

## Recommended Detection Strategy

Use a hybrid strategy:

- **Primary signal:** voice activity detection identifies where speech exists.
- **Secondary shaping rules:** gap thresholds, padding, and merge logic determine what gets cut and how aggressively.
- **Canonical timeline:** the shaping stage emits a reusable edit decision list.
- **Rendering layer:** ffmpeg performs the actual extraction and stitching because it is reliable for audio decoding and output generation.

This is preferred over pure ffmpeg silence detection because the product goal is to preserve speech naturally, not merely remove low-energy sections. Pure amplitude-based silence detection is more sensitive to room noise, microphone gain, trailing syllables, and low-volume speech.

## Processing Pipeline Details

### 1. Media ingestion and input normalization

Before analysis, convert the source into a canonical analysis format:

- Mono channel
- Fixed sample rate such as 16 kHz or 32 kHz
- PCM WAV for predictable frame access

The normalized audio is used for detection only. Final cutting should still reference the original source so the exported output preserves original source quality as much as possible.

The ingestion layer should also preserve original media metadata so future synchronized video rendering can use the same source time base.

### 2. Voice activity detection

Run VAD on short sequential frames so the detector can capture:

- Lightly spoken words
- Soft phrase starts
- Word endings and trailing syllables
- Short pauses inside sentences

The output is a sequence of speech and non-speech frame labels, which is then collapsed into a reusable speech analysis track and coarse speech intervals.

### 3. Interval shaping and edit decision generation

Raw VAD intervals need post-processing to sound usable:

- Merge intervals if the silent gap between them is very short.
- Drop only long silent gaps that exceed the configured removal threshold.
- Add padding to both sides of speech intervals.
- Clamp intervals to valid source duration bounds.

This stage is where the "balanced" listening profile is defined: long useless pauses are removed, but short sentence-level rhythm is preserved.

The result of this stage is not merely "segments to cut right now", but a canonical edit decision list that can be reused by:

- the v1 audio renderer
- a future video renderer that cuts the same timeline
- a future subtitle remapper that preserves only kept time ranges
- future debugging or auditing outputs

### 4. Output rendering

The renderer should:

- Extract each kept interval from the original source audio.
- Preserve interval order exactly.
- Join intervals without introducing clicks or abrupt waveform discontinuities.
- Add a very short smoothing transition at joins.

The implementation can use either:

- `ffmpeg` concat with per-segment fades
- `ffmpeg` filter graph with `atrim`, timestamp reset, and `acrossfade` or very short `afade`

The exact rendering implementation should be chosen during implementation based on which path is simpler to test and more stable for small numbers of segments.

The renderer boundary should be explicit so future renderers can reuse the same edit decision list:

- **Audio renderer (v1):** outputs processed audio
- **Video renderer (future):** cuts video and audio using the same kept intervals
- **Subtitle renderer (future):** emits subtitle segments aligned to the kept timeline

## Future Expansion Design

The architecture must leave clear extension points for these later features.

### 1. Multi-speaker conversation support

Future support for multiple speakers should be added as an analyzer layer, not as a rewrite of the cutter. The system should allow an additional analysis track containing speaker segmentation or diarization labels.

This enables future policies such as:

- cut silence across all speakers
- keep conversational overlap intact
- treat turn-taking pauses differently from monologue pauses

The edit decision logic should therefore consume generic interval metadata rather than assuming all speech belongs to one unnamed speaker.

### 2. Loudness balancing

Loudness balancing should be modeled as an optional transformation stage or renderer option that operates after keep intervals are selected and before final output is written.

Reasons to keep it separate from VAD:

- silence detection and loudness normalization solve different problems
- future loudness processing may work on kept segments only
- users may want silence cutting without gain changes, or vice versa

The design should support a future loudness analysis track containing per-segment or rolling loudness measurements, plus a renderer-side normalization pass.

### 3. Video-synchronized cutting

Video support should not require inventing a second timeline system. The same edit decision list produced from audio analysis should become the source of truth for synchronized cutting.

That means v1 must keep interval timing precise and source-referenced. Future video rendering can then:

- apply the same kept intervals to the video stream
- preserve A/V sync by using source-based timestamps
- export a shortened video matching the processed audio timeline

### 4. Subtitle generation

Subtitle generation should be treated as an optional analyzer plus renderer pair:

- analyzer side: speech-to-text and timestamped transcript segments
- renderer side: write subtitle formats such as SRT or VTT

Because silence cutting changes output time, subtitle support must not depend only on source timestamps. It needs the canonical edit decision list to remap source timestamps into output timestamps. This is another reason the edit timeline must be a first-class object.

## Aggressiveness Profiles

The CLI exposes a single high-level mode selector:

- `natural`
- `balanced`
- `dense`

The default is `balanced`.

These profiles are bundles of internal parameters rather than entirely separate algorithms:

- **natural**
  - Higher silence-removal threshold
  - Larger retained pauses
  - Slightly more padding
  - Lowest risk of sounding over-cut

- **balanced**
  - Removes most non-meaningful long pauses
  - Keeps short rhetorical pauses
  - Default recommendation for spoken monologue

- **dense**
  - Removes more pause time aggressively
  - Keeps less silence between nearby speech regions
  - Higher information density, with higher risk of sounding tightly cut

## Public CLI Parameters

Keep the v1 CLI intentionally small:

- `input` positional input file
- `-o, --output` output file path
- `--aggressiveness {natural,balanced,dense}`
- `--min-silence-ms`
- `--padding-ms`
- `--crossfade-ms`
- `--keep-temp`

The high-value defaults should make the tool useful without additional tuning. Internal lower-level thresholds may exist in code but should not be exposed initially unless implementation proves they are necessary.

Internally, the CLI should still be structured so future commands or flags can be added cleanly, for example:

- audio-only cut
- future cut-and-normalize
- future cut-and-export-video
- future cut-and-generate-subtitles

This does not require exposing those commands in v1, but the code structure should avoid baking all behavior into a single monolithic command handler.

## Error Handling

The CLI should fail fast and clearly for these cases:

- Input file does not exist.
- Input file cannot be decoded.
- ffmpeg is not installed or not callable.
- Output path is not writable.
- No usable speech intervals are detected.

For low-impact edge cases, the tool should still succeed:

- If only one large speech interval is detected, output the normalized edited result without meaningful shortening.
- If almost no removable silence exists, write an output file and report that compression benefit was low.

All hard failures should return a non-zero exit code and a direct error message suitable for terminal use.

## Determinism

Given the same input file and same parameters, the tool must produce the same kept intervals and the same output audio structure on repeated runs.

For future synchronized outputs, the same input and same parameters must also produce the same edit decision list.

## Acceptance Criteria

The first version is successful if it meets all of the following:

- Output duration is clearly shorter than the input when long pauses are present.
- Spoken content is preserved without frequent swallowed starts or clipped word endings.
- Join points do not produce obvious clicks or repeated audible cut artifacts.
- Default settings work well for single-speaker close-mic speech.
- The result sounds like natural continuous speech rather than word-by-word splicing.
- Runs are deterministic for the same input and parameters.
- The internal architecture cleanly separates analysis, edit decisions, and rendering so future multi-speaker, loudness, video, and subtitle features can be added without replacing the core pipeline.

## Testing Strategy

### Unit tests

Cover pure interval logic:

- frame labels to intervals
- merging neighboring intervals
- applying padding
- filtering long gaps
- clamping bounds
- generating final keep timeline
- remapping kept source intervals into output timeline positions

### Integration tests

Use synthetic or bundled fixture audio to verify:

- long silences are removed
- short pauses are preserved
- output duration is shorter than input where expected
- no empty output is produced for valid spoken input
- no output is produced when no speech is detected
- the edit decision list matches the rendered output duration

### Manual listening checks

Keep a small set of spoken-audio fixtures for ear-based validation:

- normal sentence pauses
- long between-thought pauses
- soft starts
- trailing word endings
- breathy or lightly spoken syllables

Manual checks are necessary because artifact acceptability is partly perceptual even when duration metrics are correct.

## Implementation Notes

- Prefer a Python CLI with ffmpeg as an external dependency.
- Structure the code so interval logic is independent from analyzers and rendering backends.
- Keep rendering details replaceable in case concat-with-fades and filter-graph rendering need to be swapped later.
- Avoid exposing too many tuning flags in v1.
- Use a first-class edit decision list as the contract between decision-making and output generation.
- Design internals so conference or multi-speaker support can be added later without rewriting the CLI contract.
- Keep analyzer interfaces extensible so VAD, diarization, loudness analysis, and ASR can coexist as separate modules.

## Open Decisions Resolved For v1

- Target scenario: single-speaker close-mic spoken audio.
- Interface: offline CLI, not a GUI or real-time recorder.
- Primary quality target: higher information density with natural speech continuity.
- External dependency: ffmpeg is allowed and expected.
- Default profile: `balanced`.
- Future features are accommodated by architecture now, but remain out of scope for v1 implementation.
