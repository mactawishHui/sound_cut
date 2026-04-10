# 自动字幕生成设计

## 背景

sound-cut 目前支持 `--cut`、`--auto-volume`、`--enhance-speech` 三种可组合的处理模式。本功能新增第四种模式 `--subtitle`，在音视频处理完成后对输出文件跑本地 Whisper 转写，生成字幕。

## 目标

- 对处理后的输出文件（而非原始输入）生成字幕，时间戳天然对齐剪辑结果
- `--subtitle` 可单独使用，也可与其他三种模式自由组合
- 音频输出：生成 `.srt`（或 `.vtt`）到输出文件同目录
- 视频输出（`.mp4`）：将字幕以软字幕轨道（`mov_text`）嵌入 mp4，无单独字幕文件，无需重编码视频帧
- 完全离线，依赖 `faster-whisper`，模型缓存由 faster-whisper 自身管理

## 不在范围内

- 硬字幕（burn-in）
- 字幕驱动的剪辑决策
- 多说话人区分（diarization）
- 在线 ASR API

---

## 数据模型

在 `src/sound_cut/core/models.py` 新增：

```python
@dataclass(frozen=True)
class SubtitleSegment:
    index: int       # 1-based，符合 SRT 规范
    start_s: float
    end_s: float
    text: str

@dataclass(frozen=True)
class SubtitleConfig:
    enabled: bool
    language: str | None = None      # None = faster-whisper 自动检测
    format: str = "srt"              # "srt" | "vtt"
    model_size: str = "base"         # tiny | base | small | medium | large
    model_path: Path | None = None   # 覆盖默认 HuggingFace 缓存目录
```

`RenderSummary` 新增字段：

```python
subtitle_path: Path | None = None   # 音频输出时为 .srt/.vtt 路径；视频输出时与 output_path 相同（字幕已内嵌）；未启用时为 None
```

---

## 包结构

新增子包 `src/sound_cut/subtitles/`，与 `enhancement/` 对称：

```
subtitles/
  __init__.py
  pipeline.py    — generate_subtitles(audio_path, config) -> list[SubtitleSegment]
  whisper.py     — WhisperBackend，封装 faster-whisper 的 WhisperModel
  formatter.py   — write_srt(segments, path) / write_vtt(segments, path)，无外部依赖
```

`src/sound_cut/media/ffmpeg_tools.py` 新增：

```python
def embed_subtitle_track(video_path: Path, srt_path: Path, output_path: Path) -> None:
    """将 SRT 以 mov_text 轨道嵌入 mp4，视频/音频流使用 stream copy。"""
```

---

## Pipeline 集成

`process_audio()` 新增参数：

```python
def process_audio(
    ...,
    subtitle: SubtitleConfig | None = None,
) -> RenderSummary:
```

字幕生成作为最后一步，在所有渲染完成后执行：

```
render_*()  →  output_path
    ↓ subtitle.enabled
generate_subtitles(output_path, config)  →  list[SubtitleSegment]
    ↓ 音频输出
write_srt/vtt(segments, output_path.with_suffix(".srt/.vtt"))
    ↓ 视频输出（.mp4）
write_srt(segments, tmp_srt)
embed_subtitle_track(output_path, tmp_srt, tmp_video)   # ffmpeg 写临时文件
rename(tmp_video, output_path)                          # 原子替换
rm tmp_srt
    ↓
RenderSummary(... subtitle_path=...)
```

视频嵌入时，`embed_subtitle_track` 的 `video_path` 与 `output_path` 必须不同（ffmpeg 限制），pipeline 传入临时路径再 rename，调用方负责路径管理。

---

## `generate_subtitles()` 内部流程

```
WhisperBackend(model_size, model_path).transcribe(audio_path, language)
    → list[SubtitleSegment]
```

`WhisperBackend.transcribe()` 步骤：
1. 实例化 `faster_whisper.WhisperModel(model_size_or_path, device="auto")`
2. 调用 `model.transcribe(str(audio_path), language=language)`
3. 将返回的 `segments` 迭代器转为 `SubtitleSegment` 列表（index 从 1 开始）
4. 返回列表

---

## CLI 变更

新增四个参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--subtitle` | flag | — | 启用字幕生成 |
| `--subtitle-format {srt,vtt}` | str | `srt` | 字幕格式；视频输出时忽略此参数（始终嵌入为 mov_text 轨道） |
| `--subtitle-language LANG` | str | `None` | 语言代码，如 `zh`、`en`；省略则自动检测 |
| `--subtitle-model {tiny,base,small,medium,large}` | str | `base` | Whisper 模型规格 |
| `--subtitle-model-path PATH` | Path | `None` | 覆盖模型缓存目录 |

`--subtitle` 加入 `_PROCESSING_MODE_FLAGS`，`_SoundCutArgumentParser` 校验逻辑不变。

`main()` 新增输出行：

```
# 音频输出
subtitle_path=recording.cut.srt

# 视频输出（字幕已嵌入，无单独文件）
subtitle_path=recording.cut.mp4 (embedded)

# 未启用字幕
（不打印）
```

---

## 依赖

`pyproject.toml` 新增可选依赖组：

```toml
[project.optional-dependencies]
subtitle = [
    "faster-whisper>=1.0",
]
```

安装方式：`pip install "sound-cut[subtitle]"`。

`faster-whisper` 在 `WhisperBackend` 内部懒加载（`import` 在函数内），未安装时抛出 `DependencyError`，提示用户安装。

---

## 错误处理

- `faster-whisper` 未安装 → `DependencyError("faster-whisper is required for --subtitle; install it with: pip install 'sound-cut[subtitle]'")`
- Whisper 转写结果为空（无语音）→ 写出空字幕文件（0 条 segment），不报错；`RenderSummary.subtitle_path` 正常返回路径
- 视频嵌入失败（ffmpeg 报错）→ 抛出 `MediaError`

---

## 测试策略

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/test_subtitle_formatter.py` | `write_srt` / `write_vtt` 格式正确性，时间戳格式，特殊字符，空列表 |
| `tests/test_subtitle_pipeline.py` | `generate_subtitles` 调用路径；`WhisperBackend` 用 mock 替代，验证参数传递；`DependencyError` 路径 |
| `tests/test_pipeline.py`（扩展）| `process_audio()` 带 `SubtitleConfig` 时正确调用字幕阶段；`subtitle_path` 在 `RenderSummary` 中正确返回 |
| `tests/test_cli.py`（扩展）| `--subtitle` 独立有效；与其他 flag 组合有效；`--subtitle-format`/`--subtitle-language`/`--subtitle-model` 解析正确 |
| `tests/test_ffmpeg_tools.py`（扩展）| `embed_subtitle_track` 调用正确的 ffmpeg 命令（mock subprocess）|
