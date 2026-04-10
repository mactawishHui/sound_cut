from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sound_cut.core import DependencyError

from .base import BaseEnhancer


@dataclass(frozen=True)
class ResembleEnhancer(BaseEnhancer):
    backend_name = "resemble-enhance"

    def validate(self) -> None:
        raise DependencyError(
            f"{self.backend_name} runtime is unavailable; the backend is not installed yet."
        )

    def enhance(self, input_path: Path, output_path: Path) -> None:
        _ = input_path, output_path
        self.validate()
