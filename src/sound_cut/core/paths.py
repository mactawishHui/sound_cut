from __future__ import annotations

import os
import sys
from pathlib import Path


def default_model_cache_dir(*, platform_name: str | None = None) -> Path:
    platform = (platform_name or sys.platform).lower()

    if platform.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            local_app_data = str(Path.home() / "AppData" / "Local")
        return Path(local_app_data) / "sound-cut" / "models"

    return Path.home() / ".cache" / "sound-cut" / "models"
