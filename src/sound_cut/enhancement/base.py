from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Protocol

from sound_cut.core import EnhancementConfig
from sound_cut.models import locate_model_dir


class EnhancementBackend(Protocol):
    backend_name: ClassVar[str]
    config: EnhancementConfig

    def validate(self) -> None:
        """Raise when the configured backend cannot run in the current environment."""

    def enhance(self, input_path: Path, output_path: Path) -> None:
        """Enhance audio from input_path into output_path."""


@dataclass(frozen=True)
class BaseEnhancer:
    config: EnhancementConfig
    backend_name: ClassVar[str]

    def resolve_model_dir(self) -> Path:
        return locate_model_dir(self.backend_name, self.config.model_path)

    def enhance(self, input_path: Path, output_path: Path) -> None:
        _ = input_path, output_path
        self.validate()
        raise NotImplementedError(f"{self.backend_name} enhancement is not implemented yet.")
