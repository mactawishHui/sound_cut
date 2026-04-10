from __future__ import annotations

from sound_cut.core import EnhancementConfig

from .base import BaseEnhancer, EnhancementBackend
from .deepfilternet import DeepFilterNetEnhancer
from .resemble_enhance import ResembleEnhancer

__all__ = [
    "BaseEnhancer",
    "DeepFilterNetEnhancer",
    "EnhancementBackend",
    "ResembleEnhancer",
    "select_enhancer",
]


def select_enhancer(config: EnhancementConfig) -> EnhancementBackend:
    if config.backend == DeepFilterNetEnhancer.backend_name:
        return DeepFilterNetEnhancer(config)
    if config.backend == ResembleEnhancer.backend_name:
        return ResembleEnhancer(config)
    raise ValueError(f"unsupported enhancement backend: {config.backend}")
