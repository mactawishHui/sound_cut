from __future__ import annotations

import argparse
from pathlib import Path


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


def main() -> int:
    build_parser().parse_args()
    return 0
