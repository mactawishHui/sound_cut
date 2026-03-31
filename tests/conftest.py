from __future__ import annotations

import shutil

import pytest


@pytest.fixture(scope="session")
def ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required for integration tests")
