from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

from sound_cut.core import DependencyError

from .base import BaseEnhancer

_DEFAULT_MODEL = "htdemucs"


@dataclass(frozen=True)
class DemucsVocalsEnhancer(BaseEnhancer):
    backend_name = "demucs-vocals"

    def validate(self) -> None:
        if importlib.util.find_spec("demucs") is None:
            raise DependencyError(
                "demucs-vocals runtime is unavailable. Install optional runtime dependencies "
                '(for example: pip install sound-cut[demucs]) before enabling --enhance-speech.'
            )

    def enhance(self, input_path: Path, output_path: Path) -> None:
        self.validate()
        _run_demucs_vocals(
            input_path=input_path,
            output_path=output_path,
            model_dir=self.resolve_model_dir(),
        )


def _run_demucs_vocals(*, input_path: Path, output_path: Path, model_dir: Path) -> None:
    separation_dir = output_path.parent / "demucs-separated"
    model_dir.mkdir(parents=True, exist_ok=True)
    separation_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("TORCH_HOME", str(model_dir.parent))
    command = [
        sys.executable,
        "-m",
        "demucs.separate",
        "-n",
        _DEFAULT_MODEL,
        "-o",
        str(separation_dir),
        "--two-stems=vocals",
        str(input_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except OSError as exc:  # pragma: no cover - depends on local runtime
        raise DependencyError(f"demucs-vocals enhancement failed to start: {exc}") from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on external runtime behavior
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise DependencyError(f"demucs-vocals enhancement failed: {detail}") from exc

    stem_path = _locate_vocals_output(separation_dir=separation_dir, input_path=input_path)
    if stem_path is None:
        raise DependencyError(
            f"demucs-vocals enhancement did not produce a vocals stem for {input_path.name}"
        )
    shutil.copyfile(stem_path, output_path)


def _locate_vocals_output(*, separation_dir: Path, input_path: Path) -> Path | None:
    expected = separation_dir / _DEFAULT_MODEL / input_path.stem / "vocals.wav"
    if expected.exists():
        return expected

    for candidate in separation_dir.rglob("vocals.wav"):
        if candidate.is_file():
            return candidate
    return None
