# OpenBBQ Agent 安装 Playbook

这份说明给 AI Agent 使用。目标是把 OpenBBQ 装到用户本机，并且只补齐用户当前任务真正需要的依赖。

## 原则

- 不偷偷安装系统依赖，不偷偷下载模型。
- 先问清楚会影响下载量和安装方式的问题。
- 先跑 `openbbq doctor --json`，再根据结果只补缺失项。
- 安装系统包、下载模型、写入浏览器登录态、配置 API key 前，都先让用户确认。
- 最后以 `openbbq doctor` 通过作为安装完成的门槛。

## 先问用户

开始前确认这些信息：

- 平台：macOS、Linux 还是 Windows。
- 用户是否有[uv](https://docs.astral.sh/uv/)
- 主要输入来源：本地视频、本地音频，还是 YouTube / 其他在线视频。
- 源语言和目标语言。
- 模型档位：`base` 适合快速预览，`large-v3` 或 `large-v3-turbo` 适合正式字幕。
- 是否需要烧录硬字幕。
- 是否需要说话人分离。
- 是否需要调用 API 翻译。
- 本机是否有 GPU，以及大致类型：Apple Silicon、NVIDIA、AMD / Intel，或只用 CPU。

## Bootstrap

优先使用发布包：

```bash
uv tool install openbbq
```

如果用户已经确认使用默认 whisper.cpp 后端，也可以直接安装 extra：

```bash
uv tool install 'openbbq[whispercpp]'
```

基于本仓库开发时，才在仓库目录下安装本地版本：

```bash
uv tool install '.[whispercpp]'
```

## 检查环境

```bash
openbbq doctor --json
```

按输出补缺失项。常见项如下：

- Python 需要 3.12 或更新版本。
- 缺 FFmpeg 时，安装带 `libass` 的 FFmpeg。烧录硬字幕需要 `ass` 和 `subtitles` filter。
- 缺 ASR 后端时，默认补 `pywhispercpp`。macOS 通常可直接用 wheel 的 Metal 支持；NVIDIA / Vulkan 路线可能需要本机 toolkit 和源码编译。
- 缺模型时，先让用户确认模型大小，再执行 `openbbq models pull <model>`。
- YouTube 需要登录或人机验证时，执行 `openbbq auth browser-login youtube`。
- 如果用户要说话人分离，再安装 whisperX 并确认 Hugging Face token。
- 如果用户要 API 翻译，再配置对应 provider 的 key。

## 模型

先看可用档位和缓存状态：

```bash
openbbq models list
```

快速预览：

```bash
openbbq models pull base
```

正式字幕：

```bash
openbbq models pull large-v3-turbo
```

如果用户网络访问 Hugging Face 不稳定，可以让用户确认后设置镜像：

```bash
HF_ENDPOINT=https://hf-mirror.com openbbq models pull large-v3-turbo
```

模型放在 OpenBBQ 的全局缓存里，跨 workspace 复用，不写进视频项目目录。

## 完成检查

安装和模型下载完成后再跑：

```bash
openbbq doctor
```

如果用户要烧录字幕，确认 FFmpeg 的 `ass` 和 `subtitles` filter 都可用。检查通过后，再进入具体字幕工作流。
