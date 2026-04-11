from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sound_cut.core.errors import MediaError
from sound_cut.core.models import SubtitleConfig, SubtitleSegment

_DASHSCOPE_ASR_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
)
_DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
_TRANSFER_SH_URL = "https://transfer.sh/{filename}"

# Formats natively supported for audio extraction by the upload helper
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".flv"}


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise MediaError(f"HTTP {exc.code} calling {url}: {exc.read().decode()[:200]}") from exc


def _upload_to_transfer_sh(path: Path) -> str:
    """Upload *path* to transfer.sh and return the public download URL."""
    url = _TRANSFER_SH_URL.format(filename=path.name)
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/octet-stream",
            "Max-Downloads": "1",
            "Max-Days": "1",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.read().decode().strip()
    except urllib.error.HTTPError as exc:
        raise MediaError(f"Upload to transfer.sh failed ({exc.code}): {exc.read().decode()[:200]}") from exc


def _extract_audio(video_path: Path, temp_dir: Path) -> Path:
    """Extract 16 kHz mono MP3 from a video file for a smaller upload payload."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise MediaError("ffmpeg not found in PATH — required for audio extraction")
    out = temp_dir / "audio_for_asr.mp3"
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-b:a",
            "64k",
            str(out),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise MediaError(f"ffmpeg audio extraction failed: {result.stderr.decode()[:200]}")
    return out


def _parse_sentences(data: dict[str, Any]) -> list[SubtitleSegment]:
    """Convert FunASR result JSON into SubtitleSegment list."""
    segments: list[SubtitleSegment] = []
    index = 1
    for transcript in data.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            text = sentence.get("text", "").strip()
            if not text:
                continue
            segments.append(
                SubtitleSegment(
                    index=index,
                    start_s=sentence["begin_time"] / 1000.0,
                    end_s=sentence["end_time"] / 1000.0,
                    text=text,
                )
            )
            index += 1
    return segments


class FunASRBackend:
    """Transcribes audio using Alibaba Cloud FunASR via DashScope async API."""

    def __init__(self, config: SubtitleConfig) -> None:
        self._config = config
        self._api_key = config.api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not self._api_key:
            raise MediaError(
                "FunASR requires a DashScope API key. "
                "Pass --subtitle-api-key or set the DASHSCOPE_API_KEY environment variable."
            )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _submit_task(self, file_url: str) -> str:
        params: dict[str, Any] = {"channel_id": [0]}
        if self._config.language is not None:
            params["language_hints"] = [self._config.language]
        resp = _http_json(
            _DASHSCOPE_ASR_URL,
            method="POST",
            headers={
                **self._auth_headers(),
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            body={
                "model": "fun-asr",
                "input": {"file_urls": [file_url]},
                "parameters": params,
            },
        )
        return resp["output"]["task_id"]

    def _poll_task(self, task_id: str) -> list[dict[str, Any]]:
        url = _DASHSCOPE_TASK_URL.format(task_id=task_id)
        while True:
            resp = _http_json(url, headers=self._auth_headers())
            output = resp["output"]
            status = output["task_status"]
            if status == "SUCCEEDED":
                return output["results"]
            if status == "FAILED":
                raise MediaError(f"FunASR task failed: {output}")
            time.sleep(3)

    def transcribe(self, audio_path: Path) -> list[SubtitleSegment]:
        """Upload *audio_path*, run FunASR transcription, return timed segments."""
        with tempfile.TemporaryDirectory(prefix="sound-cut-funasr-") as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)

            # Extract audio from video to reduce upload size
            if audio_path.suffix.lower() in _VIDEO_SUFFIXES:
                upload_path = _extract_audio(audio_path, tmp_dir)
            else:
                upload_path = audio_path

            file_url = _upload_to_transfer_sh(upload_path)

        task_id = self._submit_task(file_url)
        results = self._poll_task(task_id)

        segments: list[SubtitleSegment] = []
        for result in results:
            transcription_url = result["transcription_url"]
            with urllib.request.urlopen(transcription_url, timeout=30) as resp:
                data = json.loads(resp.read())
            segments.extend(_parse_sentences(data))

        # Re-index globally (each file result starts from 1)
        return [
            SubtitleSegment(index=i + 1, start_s=s.start_s, end_s=s.end_s, text=s.text)
            for i, s in enumerate(segments)
        ]
