from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument(
        "--aggressiveness",
        choices=("natural", "balanced", "dense"),
        default="balanced",
    )
    parser.add_argument("--min-silence-ms", type=int)
    parser.add_argument("--padding-ms", type=int)
    parser.add_argument("--crossfade-ms", type=int)
    parser.add_argument("--keep-temp", action="store_true")
    return parser


def main() -> int:
    build_parser().parse_args()
    return 0
