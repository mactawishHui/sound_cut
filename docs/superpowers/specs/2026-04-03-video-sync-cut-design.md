# 视频同步剪切与音频处理回封装设计（mp4）

## 背景
- 现有能力已支持音频剪切、语音增强、响度归一化三者可组合。
- 新需求是支持视频输入（先聚焦 `mp4`），并保证在启用剪切时，音频与视频沿用同一时间线裁剪，输出后保持同步。

## 目标
- 支持 `mp4 -> mp4` 输出。
- 可单独使用 `--auto-volume` / `--enhance-speech`，也可与 `--cut` 组合。
- `--cut` 启用时，使用统一 EDL 同步裁剪音视频。
- 无剪切场景尽量复用原视频码流（`copy`）以维持文件体量同量级。

## 方案
1. 沿用现有音频分析与 EDL 生成流程，语音增强和响度归一化继续作用于音轨。
2. 当输入包含视频且输出后缀为 `.mp4`：
   - 无剪切：处理完整音轨后与原视频流复用封装（视频流 copy）。
   - 有剪切：使用同一 EDL 对视频流执行 `trim + concat`，并将同一 EDL 处理后的音轨回封装到剪切后视频。
3. 输出封装统一使用 mp4，音轨中间产物使用 m4a（AAC）以保证容器兼容性。

## 代码边界
- `src/sound_cut/editing/pipeline.py`
  - 新增视频分流：在 `process_audio` 内根据 `source.has_video` 与输出后缀决定走音频渲染或视频渲染。
  - 新增 `_process_cut_video`，复用 `_build_cut_plan` 保证音视频共享同一 EDL。
- `src/sound_cut/media/render.py`
  - 新增 `render_full_video`：完整音轨处理后与原视频复用封装。
  - 新增 `render_video_from_edl`：同一 EDL 下的音频剪切 + 视频剪切 + mux。
  - 新增内部 helper：`_render_internal_video`、`_mux_audio_with_video`。
- `src/sound_cut/cli.py`
  - 默认输出后缀支持 `.mp4`。

## 测试策略
- CLI：验证 `mp4` 输入未显式输出时默认 `.cut.mp4`。
- Pipeline：验证视频在有/无剪切时进入正确渲染分支，并传递正确 source/EDL 上下文。
- Render：验证视频回封装逻辑会复用原视频流；验证剪切场景音视频共享同一 EDL。

## 已知限制
- 当前视频输出范围先限定为 `mp4`。
- 剪切视频使用重编码（`libx264`）以保证时间线精度；无剪切场景保持视频流 copy。
