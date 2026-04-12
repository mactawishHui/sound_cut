from __future__ import annotations

import json
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sound_cut.core.errors import MediaError
from sound_cut.core.models import SubtitleConfig, SubtitleSegment

# Punctuation that marks a good sentence-end break point (highest priority)
_SENTENCE_END_RE = re.compile(r"[。？！；!?;]+")
# Softer pause punctuation (fallback split point)
_PAUSE_RE = re.compile(r"[，,、…]+")


def _split_text(text: str, max_chars: int) -> list[str]:
    """Split *text* into chunks of at most *max_chars* characters.

    Prefers sentence-end punctuation as break points, then pause punctuation,
    then a hard character-count split.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    while len(text) > max_chars:
        # Search for the last sentence-ending punctuation within the window.
        window = text[: max_chars + 1]
        best: int | None = None
        for m in _SENTENCE_END_RE.finditer(window):
            best = m.end()
        if best is None:
            for m in _PAUSE_RE.finditer(window):
                best = m.end()
        if not best:
            best = max_chars
        chunks.append(text[:best])
        text = text[best:]
    if text:
        chunks.append(text)
    return [c for c in chunks if c.strip()]


def _split_long_segments(
    segments: list[SubtitleSegment], max_chars: int
) -> list[SubtitleSegment]:
    """Post-process *segments*: split any segment whose text exceeds *max_chars*.

    Time is distributed proportionally to character count across the pieces.
    """
    if max_chars <= 0:
        return segments

    result: list[SubtitleSegment] = []
    for seg in segments:
        pieces = _split_text(seg.text, max_chars)
        if len(pieces) <= 1:
            result.append(seg)
            continue
        total_chars = sum(len(p) for p in pieces)
        duration = seg.end_s - seg.start_s
        t = seg.start_s
        for piece in pieces:
            piece_dur = duration * len(piece) / max(total_chars, 1)
            result.append(
                SubtitleSegment(index=1, start_s=t, end_s=t + piece_dur, text=piece.strip())
            )
            t += piece_dur

    # Re-index globally (1-based)
    return [
        SubtitleSegment(index=i + 1, start_s=s.start_s, end_s=s.end_s, text=s.text)
        for i, s in enumerate(result)
    ]

def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context with a valid CA bundle (uses certifi when available)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_DASHSCOPE_ASR_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
)
_DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

# Formats natively supported for audio extraction by the upload helper
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".m4v", ".avi", ".webm", ".flv"}


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 30,
    retries: int = 5,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise MediaError(f"HTTP {exc.code} calling {url}: {exc.read().decode()[:200]}") from exc
        except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # 1 s, 2 s, 4 s, 8 s …
    raise MediaError(f"Network error after {retries} attempts calling {url}: {last_exc}") from last_exc


def _multipart_body(path: Path, field: str, extra_fields: dict[str, str] | None = None) -> tuple[bytes, str]:
    """Build a multipart/form-data body; return (body_bytes, boundary_string)."""
    boundary = f"SoundCutBoundary{int(time.time())}"
    parts: list[bytes] = []
    sep = f"--{boundary}\r\n".encode()
    for name, value in (extra_fields or {}).items():
        parts.append(sep)
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    with open(path, "rb") as f:
        file_bytes = f.read()
    parts.append(sep)
    parts.append(
        f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode()
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def _try_upload(
    path: Path,
    upload_url: str,
    field: str,
    extra: dict[str, str] | None = None,
    *,
    insecure: bool = False,
) -> str:
    body, boundary = _multipart_body(path, field, extra)
    req = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    ctx = ssl.create_default_context() if insecure else _ssl_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        return resp.read().decode().strip()


def _is_ssl_like_error(exc: Exception) -> bool:
    """Return True if the exception looks like an SSL/TLS connectivity problem."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "ssl", "certificate", "handshake", "eof occurred", "protocol",
    ))


def _try_upload_with_retry(
    path: Path,
    upload_url: str,
    field: str,
    extra: dict[str, str] | None = None,
    *,
    retries: int = 3,
) -> str:
    """Call _try_upload up to *retries* times.

    For SSL / TLS errors (which urllib wraps in URLError), automatically
    retries with certificate verification disabled as a last resort.
    """
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(retries):
        # First try with normal cert verification.
        try:
            return _try_upload(path, upload_url, field, extra, insecure=False)
        except Exception as exc:
            last_exc = exc
            # If it looks like an SSL problem, retry immediately without cert check.
            if _is_ssl_like_error(exc):
                try:
                    return _try_upload(path, upload_url, field, extra, insecure=True)
                except Exception as exc2:
                    last_exc = exc2
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise last_exc


def _parse_upload_url(raw: str) -> str | None:
    """Return a public HTTPS/HTTP URL from a raw upload response, or None."""
    raw = raw.strip()
    if raw.startswith("https://") or raw.startswith("http://"):
        return raw
    # JSON responses: file.io {"link": "..."}, gofile.io {"data": {"downloadPage": ..., "link": ...}}
    try:
        data = json.loads(raw)
        # gofile.io: {"status": "ok", "data": {"link": "https://..."}}
        if isinstance(data.get("data"), dict):
            for key in ("link", "downloadPage", "url"):
                v = data["data"].get(key, "")
                if str(v).startswith("http"):
                    return str(v)
        # flat JSON: {"link": "...", "url": "...", "success": true}
        for key in ("link", "url", "download_url"):
            v = data.get(key, "")
            if str(v).startswith("http"):
                return str(v)
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def _urlopen_resilient(req: urllib.request.Request, timeout: int = 15) -> bytes:
    """urlopen with automatic insecure fallback on SSL errors."""
    for insecure in (False, True):
        ctx = ssl.create_default_context() if insecure else _ssl_context()
        if insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        except Exception as exc:
            if insecure or not _is_ssl_like_error(exc):
                raise
    raise RuntimeError("unreachable")


def _upload_to_gofile(path: Path) -> str:
    """Upload to gofile.io (two-step: get server, then upload)."""
    # Step 1: get the best available server
    srv_req = urllib.request.Request("https://api.gofile.io/servers", method="GET")
    srv_data = json.loads(_urlopen_resilient(srv_req, timeout=15))
    server = srv_data["data"]["servers"][0]["name"]
    upload_url = f"https://{server}.gofile.io/contents/uploadfile"
    raw = _try_upload_with_retry(path, upload_url, "file")
    data = json.loads(raw)
    if data.get("status") == "ok":
        link = data["data"].get("downloadPage") or data["data"].get("link", "")
        if link.startswith("http"):
            return link
    raise MediaError(f"gofile.io unexpected response: {raw[:120]}")


def upload_audio_for_asr(path: Path) -> str:
    """Upload *path* to a public temporary host and return the download URL.

    Tries multiple services in order (each with retries + SSL fallback); raises
    MediaError only if every service fails all attempts.
    """
    errors: list[str] = []

    # --- Simple multipart POST services ---
    simple_services = [
        ("0x0.st", "https://0x0.st", "file", None),
        (
            "litterbox",
            "https://litterbox.catbox.moe/resources/internals/api.php",
            "fileToUpload",
            {"reqtype": "fileupload", "time": "1h"},
        ),
        ("file.io", "https://file.io/?expires=1h", "file", None),
    ]
    for label, url, field, extra in simple_services:
        try:
            raw = _try_upload_with_retry(path, url, field, extra)
            parsed = _parse_upload_url(raw)
            if parsed:
                return parsed
            errors.append(f"{label}: unexpected response: {raw[:80]}")
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    # --- gofile.io (two-step, separate implementation) ---
    try:
        return _upload_to_gofile(path)
    except Exception as exc:
        errors.append(f"gofile.io: {exc}")

    raise MediaError(
        "Failed to upload audio for ASR. All upload services failed:\n"
        + "\n".join(f"  • {e}" for e in errors)
    )


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
        # Ask the API to split sentences at shorter silences so each subtitle
        # card covers less speech.  The parameter name used by DashScope FunASR
        # is sentence_split_interval (milliseconds); unknown params are ignored.
        params["sentence_split_interval"] = 300
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
            try:
                resp = _http_json(url, headers=self._auth_headers())
                output = resp["output"]
                status = output["task_status"]
                if status == "SUCCEEDED":
                    return output["results"]
                if status == "FAILED":
                    raise MediaError(f"FunASR task failed: {output}")
            except MediaError as exc:
                if "task failed" in str(exc):
                    raise
                # Transient network error during poll — log and keep waiting
                pass
            time.sleep(5)

    def transcribe(self, audio_path: Path) -> list[SubtitleSegment]:
        """Upload *audio_path*, run FunASR transcription, return timed segments."""
        with tempfile.TemporaryDirectory(prefix="sound-cut-funasr-") as tmp_dir_name:
            tmp_dir = Path(tmp_dir_name)

            # Extract audio from video to reduce upload size
            if audio_path.suffix.lower() in _VIDEO_SUFFIXES:
                upload_path = _extract_audio(audio_path, tmp_dir)
            else:
                upload_path = audio_path

            file_url = upload_audio_for_asr(upload_path)

        task_id = self._submit_task(file_url)
        results = self._poll_task(task_id)

        segments: list[SubtitleSegment] = []
        for result in results:
            transcription_url = result["transcription_url"]
            with urllib.request.urlopen(transcription_url, timeout=30, context=_ssl_context()) as resp:
                data = json.loads(resp.read())
            segments.extend(_parse_sentences(data))

        # Re-index globally (each file result starts from 1)
        segments = [
            SubtitleSegment(index=i + 1, start_s=s.start_s, end_s=s.end_s, text=s.text)
            for i, s in enumerate(segments)
        ]

        # Post-process: split any segment whose text is too long.
        segments = _split_long_segments(segments, self._config.max_chars_per_subtitle)
        return segments
