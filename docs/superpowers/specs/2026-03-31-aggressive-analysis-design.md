# Aggressive Analysis Strategy Design

## Summary

The next iteration should make cutting more aggressive without regressing semantic retention. The current VAD-based speech envelope is now conservative enough to avoid swallowing speech boundaries, but it still merges long stretches of content that contain meaningful removable pauses. The next version should preserve the safe outer speech envelope and introduce a second analysis pass that finds removable internal pauses inside long speech regions.

## Problem Statement

Current behavior is limited by the analysis stage, not by render-side trim parameters.

Observed on `/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3`:

- semantic-safe output removed `5.820s`
- more aggressive parameter sets only removed an additional `0.24s` to `0.36s`
- early content was still grouped into a single keep region of `0.000-13.640`

This shows that the present VAD collector is conservative enough to protect speech, but too coarse to expose internal pause opportunities to the timeline shaper.

## Goals

- Keep the current semantic-retention improvements.
- Split overly broad VAD regions when they contain clearly removable internal pauses.
- Preserve deterministic output and CLI simplicity.
- Avoid reverting to naive amplitude-only silence cutting.

## Non-Goals

- Replacing WebRTC VAD entirely.
- Rebuilding the renderer.
- Changing the canonical EDL model.
- Adding ASR, diarization, subtitles, or video support in this iteration.

## Approaches Considered

### 1. Only tighten existing CLI parameters

Lower `min_silence_ms`, lower `padding_ms`, and reduce fade durations further.

**Pros**

- smallest code change
- minimal new concepts

**Cons**

- already tested and showed limited gains
- does not split broad VAD regions
- risks making boundaries harsher before it meaningfully increases density

### 2. Replace VAD with pure low-energy pause detection

Use only RMS or amplitude thresholds to find silence and cut directly from that.

**Pros**

- can become very aggressive
- exposes internal pauses directly

**Cons**

- much higher risk of swallowing quiet speech
- more sensitive to background noise and recording quality
- regresses the semantic-retention work that was just fixed

### 3. Recommended: two-stage analysis

Keep the current VAD-driven conservative speech envelope, then run an internal pause splitter inside long speech-dominated ranges using short-time energy.

**Pros**

- preserves semantic safety at outer boundaries
- exposes more cut opportunities inside broad regions
- fits the current architecture cleanly

**Cons**

- introduces more analysis logic and tuning
- requires new tests for second-pass splitting behavior

## Recommended Design

Use two-stage analysis:

1. `speech envelope`
   - keep the current conservative `collect_speech_ranges()` behavior
   - this remains responsible for protecting real speech boundaries

2. `internal pause splitting`
   - for each sufficiently long speech envelope, compute short-window energy
   - identify low-energy valleys that are long enough to be meaningful pauses
   - split the envelope only when the valley is surrounded by stable speech on both sides

The output remains a speech-oriented analysis track, but one that is more finely segmented than the current VAD-only collector.

## Proposed Component Changes

### `src/sound_cut/vad.py`

Retain the WebRTC VAD wrapper, but treat its output as the coarse speech envelope rather than the final segmentation result.

### New analysis helper

Add an energy-based helper, likely in a new module such as:

- `src/sound_cut/pause_splitter.py`

Responsibilities:

- compute short-window RMS over the normalized analysis WAV
- inspect each coarse speech envelope
- return refined speech sub-ranges

### `src/sound_cut/pipeline.py`

After VAD envelope generation:

- pass the normalized analysis WAV and envelope ranges to the pause splitter
- use refined speech ranges when building the EDL

### `src/sound_cut/config.py`

Profiles should gain analysis-side settings for internal pause splitting, for example:

- minimum envelope length before second-pass splitting is attempted
- energy window size
- low-energy threshold or ratio
- minimum internal pause duration
- required speech context on both sides of the pause

`dense` should use more aggressive splitting than `balanced`.

## Splitting Rules

The second pass should only split when all of the following are true:

- the envelope is long enough to justify inspection
- a low-energy valley lasts longer than the configured internal pause threshold
- the valley is not too close to the start or end of the envelope
- there is stable speech context on both sides

This prevents the system from:

- splitting inside a single drawn-out syllable
- turning tiny hesitations into cuts
- cutting too close to true word boundaries

## Testing Strategy

### Unit tests

Add deterministic tests for:

- splitting a long speech envelope around a genuine internal low-energy gap
- not splitting when the gap is too short
- not splitting when the low-energy region is near an outer boundary
- not splitting when one side lacks enough surrounding speech

### Integration tests

Use synthetic WAV samples that combine:

- tone segments as stand-ins for speech
- low-energy valleys inside broader kept regions
- multiple channels where relevant

### Real-file validation

Re-run:

- `/Users/bytedance/Downloads/Say my name_哔哩哔哩_bilibili.mp3`

Success should look like:

- output duration shorter than the current `43.182333s`
- no regression to missing audio mid-file
- no obvious return of swallowed speech at segment starts or ends

## Scope Boundary

This iteration should stay tightly focused on one change:

- better analysis-side segmentation inside already-detected speech regions

Do not expand this iteration to cover:

- loudness balancing
- subtitles
- diarization
- video rendering
- subjective listening-quality scoring
