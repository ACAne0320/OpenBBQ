# OpenBBQ Agent 安装 Playbook

这份说明给 AI Agent 使用。目标是把 OpenBBQ 装到用户本机，并且只补齐用户当前任务真正需要的依赖。

## 原则

- 不偷偷安装系统依赖，不偷偷下载模型。
- 先问清楚会影响下载量和安装方式的问题。
- 先跑 `openbbq --json doctor`，再根据结果只补缺失项。
- 安装系统包、下载模型、写入浏览器登录态前，都先让用户确认。
- 在 browser auth、模型下载和长媒体任务前，确认 `OPENBBQ_HOME` 和用户级缓存目录可写。
- 最后以 `openbbq doctor` 通过作为安装完成的门槛。

## 先问用户

开始前确认这些信息：

- 平台：macOS、Linux 还是 Windows。
- 用户是否有[uv](https://docs.astral.sh/uv/)
- 主要输入来源：本地视频、本地音频，还是 YouTube / 其他在线视频。
- 源语言和目标语言。
- 模型档位：`base` 适合快速预览，`large-v3` 或 `large-v3-turbo` 适合正式字幕。
- 是否需要烧录硬字幕。
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

然后安装随包发布的 agent skill。默认目标是共享 agents 目录：

```bash
openbbq skill install
```

这会把 skill 复制到 `~/.agents/skills/openbbq-subtitles/`。如果用户当前使用的
agent 只读取自己的 skills 目录，就安装到对应目录：Claude Code 使用
`openbbq skill install --agent claude`，Codex 使用
`openbbq skill install --agent codex`。一次安装所有支持目标使用
`openbbq skill install --agent all`。如果 agent 需要直接从 stdout 读取 skill
内容，可以使用 `openbbq skill show`。

安装固定写入英文 skill 及其英文 `references/`，因此 skill 中引用的工作流说明
也会随安装一起可用。需要直接检查随包内容的 agent 可以使用
`openbbq skill show`。

## 检查环境

```bash
openbbq --json doctor
```

在 Codex、CI 和其他非 TTY 运行器里，即使没有传 `--json`，OpenBBQ 也可能输出紧凑
JSON。Agent 需要解析输出时，优先显式使用 `--json`。

按输出补缺失项。常见项如下：

- Python 需要 3.12 或更新版本。
- 缺 FFmpeg 时，安装带 `libass` 的 FFmpeg。烧录硬字幕需要 `ass` 和 `subtitles` filter。
- 缺 ASR 后端时，默认补 `pywhispercpp`。macOS 通常可直接用 wheel 的 Metal 支持；NVIDIA / Vulkan 路线可能需要本机 toolkit 和源码编译。
- 缺模型时，先让用户确认模型大小，再执行 `openbbq models pull <model>`。
- YouTube 需要登录或人机验证时，执行 `openbbq auth browser-login youtube`。
- browser auth 和带登录态的 `fetch` 需要可写的 `OPENBBQ_HOME`（默认 `~/.openbbq`）。
  受限 sandbox 中请在普通用户环境里运行，或把 `OPENBBQ_HOME` 指到可写目录。
- 如果 agent skill 缺失或过期，按 doctor 提示执行 `openbbq skill install` 或
  `openbbq skill install --force`。

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

如果原生 ASR 后端在受限 sandbox 中使用 `--gpu` 失败或崩溃，请在 sandbox 外重新运行
`transcribe`，或改用 `--cpu` 重试。

## 完成检查

安装和模型下载完成后再跑：

```bash
openbbq doctor
```

如果用户要烧录字幕，确认 FFmpeg 的 `ass` 和 `subtitles` filter 都可用。检查通过后，再进入具体字幕工作流。
