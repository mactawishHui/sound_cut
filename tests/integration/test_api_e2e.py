"""SoundCut API end-to-end integration tests — real files edition.

Run:
    python tests/integration/test_api_e2e.py
"""
import time
import json
import sys
import requests
from pathlib import Path

BASE = "http://localhost:8766"
MP3 = str(Path.home() / "Downloads/牢a讲述朝圣者心态_哔哩哔哩_bilibili.mp3")
MP4 = str(Path.home() / "Downloads/37403561730-1-16.mp4")

RESULTS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def submit_job(file_path: str, cfg: dict) -> str:
    with open(file_path, "rb") as f:
        r = requests.post(
            f"{BASE}/api/jobs",
            files={"file": (Path(file_path).name, f)},
            data={"config": json.dumps(cfg)},
            timeout=120,
        )
    assert r.status_code == 202, f"Submit failed {r.status_code}: {r.text}"
    return r.json()["job_id"]


def wait_job(job_id: str, timeout: int = 2400) -> dict:
    """Poll until done/error or timeout (default 40 min for 18-min files)."""
    deadline = time.time() + timeout
    dots = 0
    while time.time() < deadline:
        r = requests.get(f"{BASE}/api/jobs/{job_id}", timeout=10)
        data = r.json()
        if data["status"] == "done":
            print()
            return data
        if data["status"] == "error":
            print()
            raise RuntimeError(data["error"])
        dots += 1
        if dots % 10 == 0:
            elapsed = int(time.time() - (deadline - timeout))
            print(f"   …{elapsed}s", end="", flush=True)
        else:
            print(".", end="", flush=True)
        time.sleep(3)
    print()
    raise TimeoutError(f"Job timed out after {timeout}s")


def run_scenario(label: str, file_path: str, cfg: dict) -> dict:
    print(f"\n{'='*62}")
    print(f"▶  {label}")
    print(f"   file={Path(file_path).name}  cfg={json.dumps(cfg, ensure_ascii=False)}")
    try:
        t0 = time.time()
        job_id = submit_job(file_path, cfg)
        print(f"   job_id={job_id}  waiting", end="", flush=True)
        data = wait_job(job_id)
        elapsed = time.time() - t0
        res = data["result"]
        print(f"   ✅ PASS  ({elapsed:.0f}s)  output={res['output_filename']}")
        print(f"      in={res['input_duration_s']:.1f}s  "
              f"out={res['output_duration_s']:.1f}s  "
              f"removed={res['removed_duration_s']:.1f}s  "
              f"segments={res['kept_segment_count']}")
        if res.get("has_subtitle"):
            print(f"      subtitle={res['subtitle_filename']}")
        return {"status": "PASS", "label": label,
                "file": Path(file_path).name, "result": res, "elapsed": elapsed}
    except Exception as exc:
        print(f"   ❌ FAIL  {exc}")
        return {"status": "FAIL", "label": label,
                "file": Path(file_path).name, "error": str(exc)}


# ---------------------------------------------------------------------------
# Round 1 – MP3
# ---------------------------------------------------------------------------

def run_mp3_tests() -> list[dict]:
    results = []

    # 1. 音量均衡 — 参数变体
    results.append(run_scenario("MP3 | 1a 音量均衡 (default -16 LUFS)", MP3,
        {"auto_volume": True}))
    results.append(run_scenario("MP3 | 1b 音量均衡 (target_lufs=-14)", MP3,
        {"auto_volume": True, "target_lufs": "-14"}))
    results.append(run_scenario("MP3 | 1c 音量均衡 (target_lufs=-23)", MP3,
        {"auto_volume": True, "target_lufs": "-23"}))

    # 2. 语音增强 — 参数变体
    results.append(run_scenario("MP3 | 2a 语音增强 (natural)", MP3,
        {"enhance_speech": True, "enhancer_backend": "deepfilternet3",
         "enhancer_profile": "natural"}))
    results.append(run_scenario("MP3 | 2b 语音增强 (strong)", MP3,
        {"enhance_speech": True, "enhancer_backend": "deepfilternet3",
         "enhancer_profile": "strong"}))
    results.append(run_scenario("MP3 | 2c 语音增强 (fallback=original)", MP3,
        {"enhance_speech": True, "enhancer_profile": "natural",
         "enhancer_fallback": "original"}))

    # 3. 静音裁切 — 参数变体
    results.append(run_scenario("MP3 | 3a 静音裁切 (balanced)", MP3,
        {"cut": True, "aggressiveness": "balanced"}))
    results.append(run_scenario("MP3 | 3b 静音裁切 (dense)", MP3,
        {"cut": True, "aggressiveness": "dense"}))
    results.append(run_scenario("MP3 | 3c 静音裁切 (natural, min_silence_ms=800)", MP3,
        {"cut": True, "aggressiveness": "natural", "min_silence_ms": "800"}))
    results.append(run_scenario("MP3 | 3d 静音裁切 (padding=50, crossfade=30)", MP3,
        {"cut": True, "aggressiveness": "balanced",
         "padding_ms": "50", "crossfade_ms": "30"}))

    # 4. 字幕 — 参数变体
    results.append(run_scenario("MP3 | 4a 字幕 (sidecar, srt, auto)", MP3,
        {"subtitle": True, "subtitle_sidecar": True,
         "subtitle_format": "srt", "subtitle_language": ""}))
    results.append(run_scenario("MP3 | 4b 字幕 (sidecar, vtt)", MP3,
        {"subtitle": True, "subtitle_sidecar": True, "subtitle_format": "vtt"}))
    results.append(run_scenario("MP3 | 4c 字幕 (sidecar, zh)", MP3,
        {"subtitle": True, "subtitle_sidecar": True, "subtitle_language": "zh"}))

    # 5. 语音增强 + 音量均衡
    results.append(run_scenario("MP3 | 5 语音增强 + 音量均衡", MP3,
        {"enhance_speech": True, "auto_volume": True}))

    # 6. 语音增强 + 音量均衡 + 静音裁切
    results.append(run_scenario("MP3 | 6 语音增强 + 音量均衡 + 静音裁切", MP3,
        {"enhance_speech": True, "auto_volume": True,
         "cut": True, "aggressiveness": "balanced"}))

    # 7. 全功能
    results.append(run_scenario("MP3 | 7 全功能", MP3,
        {"enhance_speech": True, "auto_volume": True, "cut": True,
         "subtitle": True, "subtitle_sidecar": True, "aggressiveness": "balanced"}))

    return results


# ---------------------------------------------------------------------------
# Round 2 – MP4
# ---------------------------------------------------------------------------

def run_mp4_tests() -> list[dict]:
    results = []

    # 1. 音量均衡
    results.append(run_scenario("MP4 | 1 音量均衡", MP4,
        {"auto_volume": True, "target_lufs": "-16"}))

    # 2. 语音增强
    results.append(run_scenario("MP4 | 2 语音增强 (natural)", MP4,
        {"enhance_speech": True, "enhancer_profile": "natural"}))

    # 3. 静音裁切
    results.append(run_scenario("MP4 | 3 静音裁切 (balanced)", MP4,
        {"cut": True, "aggressiveness": "balanced"}))

    # 4. 字幕 — embed_mode 变体
    results.append(run_scenario("MP4 | 4a 字幕 (mp4 软字幕)", MP4,
        {"subtitle": True, "subtitle_format": "srt"}))
    results.append(run_scenario("MP4 | 4b 字幕 (mkv 软字幕)", MP4,
        {"subtitle": True, "subtitle_mkv": True}))
    results.append(run_scenario("MP4 | 4c 字幕 (burn 硬烧录)", MP4,
        {"subtitle": True, "subtitle_burn": True}))
    results.append(run_scenario("MP4 | 4d 字幕 (sidecar only)", MP4,
        {"subtitle": True, "subtitle_sidecar": True}))

    # 5. 语音增强 + 音量均衡
    results.append(run_scenario("MP4 | 5 语音增强 + 音量均衡", MP4,
        {"enhance_speech": True, "auto_volume": True}))

    # 6. 语音增强 + 音量均衡 + 静音裁切
    results.append(run_scenario("MP4 | 6 语音增强 + 音量均衡 + 静音裁切", MP4,
        {"enhance_speech": True, "auto_volume": True, "cut": True}))

    # 7. 全功能
    results.append(run_scenario("MP4 | 7 全功能", MP4,
        {"enhance_speech": True, "auto_volume": True, "cut": True,
         "subtitle": True, "subtitle_sidecar": True}))

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: list[dict]) -> None:
    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] == "FAIL"]
    print("\n" + "=" * 62)
    print("FINAL TEST REPORT")
    print("=" * 62)
    print(f"PASS: {len(passed)} / {len(results)}")
    print(f"FAIL: {len(failed)} / {len(results)}")
    if passed:
        print("\nPassed:")
        for r in passed:
            elapsed = f"  ({r.get('elapsed',0):.0f}s)" if r.get('elapsed') else ""
            print(f"  ✅ {r['label']}{elapsed}")
    if failed:
        print("\nFailed:")
        for r in failed:
            print(f"  ❌ {r['label']}")
            print(f"     {r.get('error','')}")
    print()
    return len(failed)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Which rounds to run — pass "mp3" or "mp4" as arg to run only one round
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"

    print("SoundCut API E2E Integration Test")
    print(f"API : {BASE}")
    print(f"MP3 : {MP3}  ({Path(MP3).stat().st_size//1024//1024}MB)")
    print(f"MP4 : {MP4}  ({Path(MP4).stat().st_size//1024//1024}MB)")

    all_results: list[dict] = []

    if arg in ("all", "mp3"):
        print("\n" + "#" * 62)
        print("ROUND 1 — MP3 AUDIO")
        print("#" * 62)
        all_results += run_mp3_tests()

    if arg in ("all", "mp4"):
        print("\n" + "#" * 62)
        print("ROUND 2 — MP4 VIDEO")
        print("#" * 62)
        all_results += run_mp4_tests()

    fail_count = print_report(all_results)
    sys.exit(fail_count)
