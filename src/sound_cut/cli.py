from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from sound_cut.config import build_profile
from sound_cut.errors import SoundCutError
from sound_cut.pipeline import process_audio


def _non_negative_int(value: str) -> int:
    parsed_value = int(value)
    if parsed_value < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=_non_negative_int)
    parser.add_argument("--padding-ms", type=_non_negative_int)
    parser.add_argument("--crossfade-ms", type=_non_negative_int)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = build_profile(args.aggressiveness)
    overrides = {
        "min_silence_ms": args.min_silence_ms,
        "padding_ms": args.padding_ms,
        "crossfade_ms": args.crossfade_ms,
    }
    profile = replace(profile, **{name: value for name, value in overrides.items() if value is not None})

    try:
        summary = process_audio(args.input, args.output, profile)
    except SoundCutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Input duration: {summary.input_duration_s:.3f}s")
    print(f"Output duration: {summary.output_duration_s:.3f}s")
    print(f"Removed duration: {summary.removed_duration_s:.3f}s")
    print(f"Kept segments: {summary.kept_segment_count}")
    return 0
