from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

from sound_cut.core import SoundCutError, build_profile
from sound_cut.core.models import DEFAULT_TARGET_LUFS, LoudnessNormalizationConfig

_SUPPORTED_DELIVERY_SUFFIXES = {".mp3", ".m4a", ".wav"}


def _non_negative_int(value: str) -> int:
    parsed_value = int(value)
    if parsed_value < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed_value


def _finite_float(value: str) -> float:
    parsed_value = float(value)
    if not math.isfinite(parsed_value):
        raise argparse.ArgumentTypeError("must be a finite number")
    return parsed_value


def resolve_output_path(input_path: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return output_path

    suffix = input_path.suffix.lower()
    if suffix not in _SUPPORTED_DELIVERY_SUFFIXES:
        suffix = ".m4a"
    return input_path.with_name(f"{input_path.stem}.cut{suffix}")


def _resolve_loudness_config(args: argparse.Namespace) -> LoudnessNormalizationConfig:
    if args.target_lufs is not None and not args.auto_volume:
        raise argparse.ArgumentTypeError("--target-lufs requires --auto-volume")

    target_lufs = DEFAULT_TARGET_LUFS if args.target_lufs is None else args.target_lufs
    return LoudnessNormalizationConfig(enabled=args.auto_volume, target_lufs=target_lufs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=_non_negative_int)
    parser.add_argument("--padding-ms", type=_non_negative_int)
    parser.add_argument("--crossfade-ms", type=_non_negative_int)
    parser.add_argument("--auto-volume", action="store_true")
    parser.add_argument("--target-lufs", type=_finite_float)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        loudness = _resolve_loudness_config(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    profile = build_profile(args.aggressiveness)
    overrides = {
        "min_silence_ms": args.min_silence_ms,
        "padding_ms": args.padding_ms,
        "crossfade_ms": args.crossfade_ms,
    }
    profile = replace(profile, **{name: value for name, value in overrides.items() if value is not None})
    output_path = resolve_output_path(args.input, args.output)

    try:
        from sound_cut.editing.pipeline import process_audio

        summary = process_audio(args.input, output_path, profile, keep_temp=args.keep_temp, loudness=loudness)
    except SoundCutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"input_duration_s={summary.input_duration_s:.3f}")
    print(f"output_duration_s={summary.output_duration_s:.3f}")
    print(f"removed_duration_s={summary.removed_duration_s:.3f}")
    print(f"kept_segment_count={summary.kept_segment_count}")
    return 0
