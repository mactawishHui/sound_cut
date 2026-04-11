from __future__ import annotations

import argparse
import math
import sys
from dataclasses import replace
from pathlib import Path

from sound_cut.core import EnhancementConfig, SoundCutError, build_profile
from sound_cut.core.models import DEFAULT_TARGET_LUFS, LoudnessNormalizationConfig, SubtitleConfig
from sound_cut.models.installer import import_model, install_model, model_install_state, verify_model
from sound_cut.models.locator import locate_model_dir
from sound_cut.models.registry import MODEL_REGISTRY

_SUPPORTED_DELIVERY_SUFFIXES = {".mp3", ".m4a", ".wav", ".mp4"}
_MODEL_COMMANDS = {"list", "install", "import", "verify"}
_PROCESSING_MODE_FLAGS = {"--cut", "--auto-volume", "--enhance-speech", "--subtitle"}


class _SoundCutArgumentParser(argparse.ArgumentParser):
    def __init__(self) -> None:
        super().__init__(prog="sound-cut")
        self._models_parser = _build_models_parser()
        self.add_argument("input", type=Path)
        self.add_argument("-o", "--output", type=Path)
        self.add_argument(
            "--aggressiveness",
            choices=("natural", "balanced", "dense"),
            default="balanced",
        )
        self.add_argument("--min-silence-ms", type=_non_negative_int)
        self.add_argument("--padding-ms", type=_non_negative_int)
        self.add_argument("--crossfade-ms", type=_non_negative_int)
        self.add_argument("--cut", action="store_true")
        self.add_argument("--auto-volume", action="store_true")
        self.add_argument("--target-lufs", type=_finite_float)
        self.add_argument("--keep-temp", action="store_true")
        self.add_argument("--enhance-speech", action="store_true")
        self.add_argument(
            "--enhancer-backend",
            choices=("deepfilternet3", "resemble-enhance"),
            default="deepfilternet3",
        )
        self.add_argument("--enhancer-profile", choices=("natural", "strong"), default="natural")
        self.add_argument("--model-path", type=Path)
        self.add_argument("--subtitle", action="store_true")
        self.add_argument(
            "--subtitle-format",
            choices=("srt", "vtt"),
            default="srt",
        )
        self.add_argument(
            "--subtitle-language",
            default=None,
        )
        self.add_argument(
            "--subtitle-model",
            choices=("tiny", "base", "small", "medium", "large"),
            default="base",
        )
        self.add_argument("--subtitle-model-path", type=Path)

    def parse_args(self, args=None, namespace=None):
        argv = sys.argv[1:] if args is None else list(args)
        if argv and argv[0] == "models":
            # Preserve the ability to process an input file literally named "models"
            # when explicit processing-mode flags are present.
            processing_mode_selected = any(flag in argv[1:] for flag in _PROCESSING_MODE_FLAGS)
            if not processing_mode_selected:
                return self._models_parser.parse_args(argv[1:], namespace)

        parsed_args = super().parse_args(argv, namespace)
        if not parsed_args.cut and not parsed_args.auto_volume and not parsed_args.enhance_speech and not parsed_args.subtitle:
            self.error(
                "at least one processing mode is required: --cut, --auto-volume, --enhance-speech, and/or --subtitle"
            )
        if parsed_args.target_lufs is not None and not parsed_args.auto_volume:
            self.error("--target-lufs requires --auto-volume")
        return parsed_args


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


def _resolve_enhancement_config(args: argparse.Namespace) -> EnhancementConfig:
    return EnhancementConfig(
        enabled=args.enhance_speech,
        backend=args.enhancer_backend,
        profile=args.enhancer_profile,
        model_path=args.model_path,
    )


def _resolve_subtitle_config(args: argparse.Namespace) -> SubtitleConfig:
    return SubtitleConfig(
        enabled=args.subtitle,
        language=args.subtitle_language,
        format=args.subtitle_format,
        model_size=args.subtitle_model,
        model_path=args.subtitle_model_path,
    )


def _build_models_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sound-cut models")
    parser.set_defaults(command="models")
    subparsers = parser.add_subparsers(dest="models_command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.set_defaults(models_command="list")

    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("backend", choices=tuple(MODEL_REGISTRY))
    install_parser.add_argument("--destination", type=Path)
    install_parser.set_defaults(models_command="install")

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("backend", choices=tuple(MODEL_REGISTRY))
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--destination", type=Path)
    import_parser.set_defaults(models_command="import")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("backend", choices=tuple(MODEL_REGISTRY))
    verify_parser.add_argument("model_dir", nargs="?", type=Path)
    verify_parser.set_defaults(models_command="verify")

    return parser


def build_parser() -> argparse.ArgumentParser:
    return _SoundCutArgumentParser()


def _run_models_command(args: argparse.Namespace) -> int:
    if args.models_command == "list":
        status_labels = {
            "missing": "not installed",
            "prepared": "prepared",
            "installed": "installed",
            "invalid": "invalid",
        }
        for backend in MODEL_REGISTRY:
            model_dir = locate_model_dir(backend)
            status = model_install_state(backend, model_dir)
            print(f"{backend}\t{status_labels.get(status, status)}\t{model_dir}")
        return 0

    try:
        if args.models_command == "install":
            installed_path = install_model(args.backend, args.destination)
            print(installed_path)
            return 0

        if args.models_command == "import":
            imported_path = import_model(args.backend, args.source, args.destination)
            print(imported_path)
            return 0
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.models_command == "verify":
        model_dir = args.model_dir or locate_model_dir(args.backend)
        if verify_model(args.backend, model_dir):
            print(f"verified {args.backend} {model_dir}")
            return 0
        print(f"missing {args.backend} {model_dir}", file=sys.stderr)
        return 1

    raise ValueError(f"unsupported models command: {args.models_command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None) == "models":
        return _run_models_command(args)

    try:
        loudness = _resolve_loudness_config(args)
        enhancement = _resolve_enhancement_config(args)
        subtitle = _resolve_subtitle_config(args)
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

        summary = process_audio(
            args.input,
            output_path,
            profile,
            keep_temp=args.keep_temp,
            loudness=loudness,
            enable_cut=args.cut,
            enhancement=enhancement,
            subtitle=subtitle,
        )
    except SoundCutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"input_duration_s={summary.input_duration_s:.3f}")
    print(f"output_duration_s={summary.output_duration_s:.3f}")
    print(f"removed_duration_s={summary.removed_duration_s:.3f}")
    print(f"kept_segment_count={summary.kept_segment_count}")
    if summary.subtitle_path is not None:
        print(f"subtitle_path={summary.subtitle_path}")
    return 0
