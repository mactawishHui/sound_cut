import builtins
import importlib
import sys
import types
from pathlib import Path

import pytest

import sound_cut.cli as cli
from sound_cut.cli import resolve_output_path


def test_build_parser_parses_required_arguments(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav")])

    assert args.input == tmp_path / "input.wav"
    assert args.output == tmp_path / "output.wav"
    assert args.aggressiveness == "balanced"
    assert args.min_silence_ms is None
    assert args.padding_ms is None
    assert args.crossfade_ms is None
    assert args.keep_temp is False


def test_resolve_output_path_defaults_to_input_suffix_when_output_is_omitted(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"

    resolved = resolve_output_path(input_path, None)

    assert resolved == tmp_path / "sample.cut.mp3"


def test_resolve_output_path_uses_explicit_output_path_when_provided(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"
    explicit = tmp_path / "custom.m4a"

    resolved = resolve_output_path(input_path, explicit)

    assert resolved == explicit


def test_build_parser_output_is_optional(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.mp3")])

    assert args.output is None


@pytest.mark.parametrize("flag", ["--min-silence-ms", "--padding-ms", "--crossfade-ms"])
def test_build_parser_rejects_negative_tuning_arguments(tmp_path: Path, flag: str) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), flag, "-1"])

    assert excinfo.value.code == 2


def test_main_returns_1_and_prints_error_for_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_path = tmp_path / "output.wav"

    exit_code = cli.main([str(tmp_path / "missing.wav"), "-o", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "missing.wav" in captured.err


def test_main_passes_keep_temp_to_process_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(input_path: Path, output_path: Path, profile, analyzer=None, keep_temp: bool = False):
        captured["input_path"] = input_path
        captured["output_path"] = output_path
        captured["profile"] = profile
        captured["keep_temp"] = keep_temp
        return importlib.import_module("sound_cut.models").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(sys.modules, "sound_cut.pipeline", types.SimpleNamespace(process_audio=fake_process_audio))

    exit_code = cli.main([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), "--keep-temp"])

    assert exit_code == 0
    assert captured["keep_temp"] is True


def test_main_infers_output_path_when_omitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(input_path: Path, output_path: Path, profile, analyzer=None, keep_temp: bool = False):
        captured["output_path"] = output_path
        return importlib.import_module("sound_cut.models").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(sys.modules, "sound_cut.pipeline", types.SimpleNamespace(process_audio=fake_process_audio))

    exit_code = cli.main([str(tmp_path / "input.mp3")])

    assert exit_code == 0
    assert captured["output_path"] == tmp_path / "input.cut.mp3"


def test_main_prints_summary_for_successful_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_process_audio(input_path: Path, output_path: Path, profile, analyzer=None, keep_temp: bool = False):
        return importlib.import_module("sound_cut.models").RenderSummary(12.3456, 7.89, 4.4556, 3)

    monkeypatch.setitem(sys.modules, "sound_cut.pipeline", types.SimpleNamespace(process_audio=fake_process_audio))

    exit_code = cli.main([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav")])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out == (
        "input_duration_s=12.346\n"
        "output_duration_s=7.890\n"
        "removed_duration_s=4.456\n"
        "kept_segment_count=3\n"
    )


def test_cli_module_import_does_not_require_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sound_cut.pipeline":
            raise AssertionError("pipeline import should not happen during cli module import")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(cli)
