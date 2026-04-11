import builtins
import importlib
import inspect
import sys
import types
from pathlib import Path

import pytest

import sound_cut.cli as cli
from sound_cut.cli import resolve_output_path
from sound_cut.core.models import DEFAULT_TARGET_LUFS
from sound_cut.editing.pipeline import process_audio as real_process_audio


def test_build_parser_parses_required_arguments(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), "--cut"])

    assert args.input == tmp_path / "input.wav"
    assert args.output == tmp_path / "output.wav"
    assert args.aggressiveness == "balanced"
    assert args.min_silence_ms is None
    assert args.padding_ms is None
    assert args.crossfade_ms is None
    assert args.cut is True
    assert args.keep_temp is False


def test_build_parser_parses_enhancement_flags(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            str(tmp_path / "input.wav"),
            "--cut",
            "--enhance-speech",
            "--enhancer-backend",
            "resemble-enhance",
            "--enhancer-profile",
            "strong",
            "--model-path",
            str(tmp_path / "models"),
        ]
    )

    assert args.enhance_speech is True
    assert args.enhancer_backend == "resemble-enhance"
    assert args.enhancer_profile == "strong"
    assert args.model_path == tmp_path / "models"


def test_build_parser_parses_model_list_subcommand() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["models", "list"])

    assert args.command == "models"
    assert args.models_command == "list"


def test_build_parser_defaults_enhancement_flags(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--cut"])

    assert args.enhance_speech is False
    assert args.enhancer_backend == "deepfilternet3"
    assert args.enhancer_profile == "natural"
    assert args.model_path is None


def test_build_parser_allows_enhance_only_mode(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--enhance-speech"])

    assert args.enhance_speech is True
    assert args.cut is False
    assert args.auto_volume is False


def test_resolve_output_path_defaults_to_input_suffix_when_output_is_omitted(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"

    resolved = resolve_output_path(input_path, None)

    assert resolved == tmp_path / "sample.cut.mp3"


def test_resolve_output_path_defaults_to_mp4_for_video_input(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp4"

    resolved = resolve_output_path(input_path, None)

    assert resolved == tmp_path / "sample.cut.mp4"


def test_resolve_output_path_uses_explicit_output_path_when_provided(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.mp3"
    explicit = tmp_path / "custom.m4a"

    resolved = resolve_output_path(input_path, explicit)

    assert resolved == explicit


def test_build_parser_output_is_optional(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.mp3"), "--auto-volume"])

    assert args.output is None


def test_build_parser_parses_auto_volume_defaults(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--auto-volume"])

    assert args.auto_volume is True
    assert args.target_lufs is None


def test_build_parser_parses_cut_mode_explicitly(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--cut"])

    assert args.cut is True
    assert args.auto_volume is False


def test_build_parser_rejects_commands_without_a_processing_mode(tmp_path: Path) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([str(tmp_path / "input.wav")])

    assert excinfo.value.code == 2


def test_build_parser_allows_models_commands_without_a_processing_mode() -> None:
    parser = cli.build_parser()

    args = parser.parse_args(["models", "verify", "deepfilternet3"])

    assert args.command == "models"
    assert args.models_command == "verify"
    assert args.backend == "deepfilternet3"


def test_build_parser_routes_bare_models_to_models_parser() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["models"])

    assert excinfo.value.code == 2


def test_build_parser_routes_models_help_to_models_parser() -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["models", "--help"])

    assert excinfo.value.code == 0


def test_main_processes_input_path_named_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["input_path"] = input_path
        captured["enable_cut"] = enable_cut
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    monkeypatch.chdir(tmp_path)
    input_path = tmp_path / "models"
    exit_code = cli.main(["models", "--cut"])

    assert exit_code == 0
    assert captured["input_path"] == Path("models")
    assert captured["enable_cut"] is True


@pytest.mark.parametrize("flag", ["--min-silence-ms", "--padding-ms", "--crossfade-ms"])
def test_build_parser_rejects_negative_tuning_arguments(tmp_path: Path, flag: str) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(
            [str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), "--cut", flag, "-1"]
        )

    assert excinfo.value.code == 2


def test_main_returns_1_and_prints_error_for_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output_path = tmp_path / "output.wav"

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        raise importlib.import_module("sound_cut.core").SoundCutError("missing.wav")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )
    try:
        exit_code = cli.main([str(tmp_path / "missing.wav"), "-o", str(output_path), "--cut"])
    finally:
        monkeypatch.undo()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "missing.wav" in captured.err


def test_main_passes_keep_temp_to_process_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["input_path"] = input_path
        captured["output_path"] = output_path
        captured["profile"] = profile
        captured["keep_temp"] = keep_temp
        captured["enable_cut"] = enable_cut
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), "--keep-temp", "--cut"])

    assert exit_code == 0
    assert captured["keep_temp"] is True
    assert captured["enable_cut"] is True


def test_main_passes_enhancement_config_to_process_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["enhancement"] = enhancement
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main(
        [
            str(tmp_path / "input.wav"),
            "-o",
            str(tmp_path / "output.wav"),
            "--cut",
            "--enhance-speech",
            "--enhancer-backend",
            "resemble-enhance",
            "--enhancer-profile",
            "strong",
            "--model-path",
            str(tmp_path / "models"),
        ]
    )

    enhancement = captured["enhancement"]
    assert exit_code == 0
    assert enhancement.enabled is True
    assert enhancement.backend == "resemble-enhance"
    assert enhancement.profile == "strong"
    assert enhancement.model_path == tmp_path / "models"


def test_main_passes_enhance_only_mode_to_process_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["enable_cut"] = enable_cut
        captured["enhancement"] = enhancement
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--enhance-speech"])

    enhancement = captured["enhancement"]
    assert exit_code == 0
    assert captured["enable_cut"] is False
    assert enhancement.enabled is True


def test_main_infers_output_path_when_omitted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["output_path"] = output_path
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.mp3"), "--cut"])

    assert exit_code == 0
    assert captured["output_path"] == tmp_path / "input.cut.mp3"


def test_main_prints_summary_for_successful_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        return importlib.import_module("sound_cut.core").RenderSummary(12.3456, 7.89, 4.4556, 3)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "-o", str(tmp_path / "output.wav"), "--cut"])

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
        if name == "sound_cut.editing.pipeline":
            raise AssertionError("pipeline import should not happen during cli module import")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    importlib.reload(cli)


def test_main_rejects_target_lufs_without_auto_volume(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([str(tmp_path / "input.wav"), "--cut", "--target-lufs", "-14.0"])

    assert excinfo.value.code == 2


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_main_rejects_non_finite_target_lufs(tmp_path: Path, value: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([str(tmp_path / "input.wav"), "--cut", "--auto-volume", "--target-lufs", value])

    assert excinfo.value.code == 2


def test_main_passes_default_loudness_config_to_process_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--auto-volume"])

    loudness = captured["loudness"]
    assert exit_code == 0
    assert loudness.enabled is True
    assert loudness.target_lufs == pytest.approx(DEFAULT_TARGET_LUFS)


def test_main_passes_auto_volume_only_with_cut_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["enable_cut"] = enable_cut
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--auto-volume"])

    loudness = captured["loudness"]
    assert exit_code == 0
    assert captured["enable_cut"] is False
    assert loudness.enabled is True
    assert loudness.target_lufs == pytest.approx(DEFAULT_TARGET_LUFS)


def test_main_passes_disabled_loudness_config_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--cut"])

    loudness = captured["loudness"]
    assert exit_code == 0
    assert loudness.enabled is False
    assert loudness.target_lufs == pytest.approx(DEFAULT_TARGET_LUFS)


def test_main_models_list_prints_registered_backends(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["models", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "deepfilternet3" in captured.out
    assert "resemble-enhance" in captured.out


def test_main_models_install_creates_backend_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    exit_code = cli.main(["models", "install", "deepfilternet3"])

    installed_path = tmp_path / ".cache" / "sound-cut" / "models" / "deepfilternet3"
    assert exit_code == 0
    assert installed_path.is_dir()
    assert (installed_path / "sound-cut-model.json").exists()


def test_main_models_list_marks_manifest_scaffold_as_prepared(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cli.main(["models", "install", "deepfilternet3"])

    exit_code = cli.main(["models", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "deepfilternet3\tprepared" in captured.out


def test_main_models_import_copies_source_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "weights.bin").write_text("weights")

    destination = tmp_path / "imported" / "resemble-enhance"
    exit_code = cli.main(
        ["models", "import", "resemble-enhance", str(source_dir), "--destination", str(destination)]
    )

    assert exit_code == 0
    assert (destination / "weights.bin").read_text() == "weights"


def test_main_models_import_reports_missing_source_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    exit_code = cli.main(["models", "import", "resemble-enhance", str(tmp_path / "missing-source")])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing-source" in captured.err


def test_main_models_import_rejects_file_source_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source_file = tmp_path / "weights.bin"
    source_file.write_text("weights")

    exit_code = cli.main(["models", "import", "resemble-enhance", str(source_file)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "weights.bin" in captured.err


def test_main_models_import_reports_overlapping_source_and_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "model.safetensors").write_text("weights")

    exit_code = cli.main(
        ["models", "import", "deepfilternet3", str(source_dir), "--destination", str(source_dir)]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "must not overlap" in captured.err


def test_main_models_verify_reports_missing_for_manifest_only_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cli.main(["models", "install", "deepfilternet3"])

    exit_code = cli.main(["models", "verify", "deepfilternet3"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing deepfilternet3" in captured.err


def test_main_models_verify_reports_success_for_installed_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    source_dir = tmp_path / "source-model"
    source_dir.mkdir()
    (source_dir / "model.safetensors").write_text("weights")
    cli.main(["models", "import", "deepfilternet3", str(source_dir)])

    exit_code = cli.main(["models", "verify", "deepfilternet3"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "verified" in captured.out


def test_main_models_list_treats_malformed_manifest_as_not_installed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    model_dir = tmp_path / ".cache" / "sound-cut" / "models" / "deepfilternet3"
    model_dir.mkdir(parents=True)
    (model_dir / "sound-cut-model.json").write_text("{")

    exit_code = cli.main(["models", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "deepfilternet3\tnot installed" in captured.out


def test_main_models_verify_reports_missing_for_malformed_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    model_dir = tmp_path / ".cache" / "sound-cut" / "models" / "deepfilternet3"
    model_dir.mkdir(parents=True)
    (model_dir / "sound-cut-model.json").write_text("{")

    exit_code = cli.main(["models", "verify", "deepfilternet3"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "missing deepfilternet3" in captured.err


def test_main_models_list_reports_resemble_not_installed_for_unrelated_assets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    model_dir = tmp_path / ".cache" / "sound-cut" / "models" / "resemble-enhance"
    model_dir.mkdir(parents=True)
    (model_dir / "README.txt").write_text("not a model")
    (model_dir / "sound-cut-model.json").write_text(
        '{"backend":"resemble-enhance","installed":true}'
    )

    exit_code = cli.main(["models", "list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "resemble-enhance\tinvalid" in captured.out


def test_main_passes_explicit_target_lufs_to_process_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["loudness"] = loudness
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--auto-volume", "--target-lufs", "-14.0"])

    loudness = captured["loudness"]
    assert exit_code == 0
    assert loudness.enabled is True
    assert loudness.target_lufs == pytest.approx(-14.0)


def test_real_process_audio_signature_accepts_enhancement() -> None:
    assert "enhancement" in inspect.signature(real_process_audio).parameters


def test_parse_args_subtitle_defaults(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--cut"])

    assert args.subtitle is False
    assert args.subtitle_format == "srt"
    assert args.subtitle_language is None
    assert args.subtitle_api_key is None
    assert args.subtitle_sidecar is False


def test_parse_args_subtitle_sets_flags(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            str(tmp_path / "input.wav"),
            "--subtitle",
            "--subtitle-format",
            "vtt",
            "--subtitle-language",
            "en",
            "--subtitle-api-key",
            "sk-test",
            "--subtitle-sidecar",
        ]
    )

    assert args.subtitle is True
    assert args.subtitle_format == "vtt"
    assert args.subtitle_language == "en"
    assert args.subtitle_api_key == "sk-test"
    assert args.subtitle_sidecar is True


def test_parse_args_subtitle_alone_is_valid(tmp_path: Path) -> None:
    parser = cli.build_parser()

    args = parser.parse_args([str(tmp_path / "input.wav"), "--subtitle"])

    assert args.subtitle is True
    assert args.cut is False
    assert args.auto_volume is False


def test_parse_args_no_mode_selected_still_errors(tmp_path: Path) -> None:
    parser = cli.build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args([str(tmp_path / "input.wav")])

    assert excinfo.value.code == 2


def test_resolve_subtitle_config_enabled(tmp_path: Path, monkeypatch) -> None:
    import argparse
    import os
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    args = argparse.Namespace(
        subtitle=True,
        subtitle_language="fr",
        subtitle_format="vtt",
        subtitle_api_key="sk-explicit",
        subtitle_sidecar=True,
    )

    config = cli._resolve_subtitle_config(args)

    from sound_cut.core.models import SubtitleConfig

    assert config.enabled is True
    assert config.language == "fr"
    assert config.format == "vtt"
    assert config.api_key == "sk-explicit"
    assert config.sidecar_only is True


def test_resolve_subtitle_config_reads_api_key_from_env(monkeypatch) -> None:
    import argparse
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")

    args = argparse.Namespace(
        subtitle=True,
        subtitle_language=None,
        subtitle_format="srt",
        subtitle_api_key=None,
        subtitle_sidecar=False,
    )

    config = cli._resolve_subtitle_config(args)
    assert config.api_key == "sk-from-env"


def test_main_passes_subtitle_to_process_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_process_audio(
        input_path: Path,
        output_path: Path,
        profile,
        analyzer=None,
        keep_temp: bool = False,
        loudness=None,
        enable_cut: bool = False,
        enhancement=None,
        subtitle=None,
    ):
        captured["subtitle"] = subtitle
        return importlib.import_module("sound_cut.core").RenderSummary(1.0, 0.5, 0.5, 1)

    monkeypatch.setitem(
        sys.modules,
        "sound_cut.editing.pipeline",
        types.SimpleNamespace(process_audio=fake_process_audio),
    )

    exit_code = cli.main([str(tmp_path / "input.wav"), "--subtitle"])

    from sound_cut.core.models import SubtitleConfig

    assert exit_code == 0
    subtitle = captured["subtitle"]
    assert isinstance(subtitle, SubtitleConfig)
    assert subtitle.enabled is True
