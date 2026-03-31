from pathlib import Path

import pytest

from sound_cut.cli import build_parser, main


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


@pytest.mark.parametrize("flag", ["--min-silence-ms", "--padding-ms", "--crossfade-ms"])
def test_build_parser_rejects_negative_tuning_arguments(tmp_path: Path, flag: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), flag, "-1"])

    assert excinfo.value.code == 2


def test_main_returns_1_and_prints_error_for_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_path = tmp_path / "output.wav"

    exit_code = main([str(tmp_path / "missing.wav"), "-o", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "missing.wav" in captured.err
