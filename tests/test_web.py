from __future__ import annotations

from pathlib import Path

import pytest

from sound_cut.core import RenderSummary
from sound_cut.web import create_app


def test_index_page_renders() -> None:
    app = create_app()

    with app.test_client() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "声剪工作台".encode() in response.data
    assert "开始处理".encode() in response.data
    assert "高级配置".encode() in response.data


def test_process_upload_returns_download_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app()
    app.config["WORKSPACE"] = tmp_path

    output_path = tmp_path / "job" / "output" / "sample.cut.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"audio")

    subtitle_path = tmp_path / "job" / "output" / "sample.cut.srt"
    subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n")

    def fake_run_web_job(*, input_path: Path, output_dir: Path, form):
        assert input_path.exists()
        assert output_dir.exists()
        summary = RenderSummary(
            input_duration_s=10.0,
            output_duration_s=8.5,
            removed_duration_s=1.5,
            kept_segment_count=3,
            subtitle_path=subtitle_path,
        )
        return summary, output_path

    monkeypatch.setattr("sound_cut.web._run_web_job", fake_run_web_job)

    with app.test_client() as client:
        response = client.post(
            "/",
            data={
                "input_file": (open(__file__, "rb"), "sample.wav"),
                "enhance_speech": "on",
                "enhancer_backend": "deepfilternet3",
                "enhancer_profile": "natural",
                "enhancer_fallback": "fail",
                "subtitle": "on",
                "subtitle_format": "srt",
                "subtitle_max_chars": "25",
            },
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    assert "结果已经准备好了".encode() in response.data
    assert "下载处理结果".encode() in response.data
    assert "下载字幕文件".encode() in response.data


def test_download_route_serves_processed_file(tmp_path: Path) -> None:
    app = create_app()
    app.config["WORKSPACE"] = tmp_path
    output_path = tmp_path / "out.wav"
    output_path.write_bytes(b"audio")
    app.config["JOBS"]["abc123"] = {"output_path": output_path, "subtitle_path": None}

    with app.test_client() as client:
        response = client.get("/downloads/abc123/output")

    assert response.status_code == 200
    assert response.data == b"audio"
