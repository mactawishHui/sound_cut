from pathlib import Path

from sound_cut.cli import build_parser


def test_build_parser_parses_required_arguments(tmp_path: Path) -> None:
    parser = build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav")])

    assert args.input == tmp_path / "input.wav"
    assert args.output == tmp_path / "output.wav"
    assert args.aggressiveness == "balanced"
    assert args.min_silence_ms is None
    assert args.padding_ms is None
    assert args.crossfade_ms is None
    assert args.keep_temp is False
