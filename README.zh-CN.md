# OpenBBQ

[English README](README.md) · [使用指南](docs/usage.zh-CN.md)

**OpenBBQ** 是一个专为智能体（Agent）设计的用于视频翻译和字幕制作的命令行工具。

OpenBBQ 提供了一系列可组合的工具，涵盖视频下载、音频提取、ASR 转录、分段、翻译、校对、字幕导出以及烧录字幕等环节。
不强制采用固定的处理流程，而是更希望 Agent 根据用户的不同目标，灵活制定最合适的工作流程。

## Why OpenBBQ?

在中国字幕组和创作者社群中，翻译并制作外语视频字幕的过程通常被称为“烤肉”。
未经翻译的原始素材通常被称作“生肉”，而经过翻译和添加字幕的成品则变成了“熟肉”。

所以 OpenBBQ 的愿景是，做一个开源、开放的字幕翻译平台。

## 快速开始

## 前置条件

- Python 3.12 或更新版本
- [uv](https://docs.astral.sh/uv/)，用于安装 `openbbq` 命令和管理 Python 依赖
- [ffmpeg](https://www.ffmpeg.org/)，用于下载视频、合并音视频、抽取音频和视频烧录；如果有烧录字幕的需求，FFmpeg 还需要 `libass` 支持
- 一个 ASR 后端，目前仅支持 [whisper.cpp](https://github.com/absadiki/pywhispercpp) (Python Binding)
- 一个 ASR 模型，模型不随安装包一起下载，安装后用 `openbbq models list` 查看可用档位，再显式执行 `openbbq models pull ...`。
- 如果需要下载的视频平台要求登录、人机验证或浏览器挑战，需要本机桌面浏览器；

## For Agent

```markdown
查看[安装指南](https://raw.githubusercontent.com/ACAne0320/OpenBBQ/main/docs/install-agent.zh-CN.md)，帮我安装[OpenBBQ](https://github.com/ACAne0320/OpenBBQ)
```

## 手动安装

```bash
uv tool install 'openbbq[whispercpp]'
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
openbbq doctor
```

## 使用

Human 工作流：

```bash
openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'
cd workspaces/demo
openbbq fetch
openbbq extract-audio
openbbq transcribe --model large-v3-turbo --language en --gpu
openbbq segment
openbbq translate init zh
# 在 translation.zh.json 中填写翻译内容
openbbq translate check zh
openbbq export --to zh --mode bilingual --format ass --output out/zh.ass
openbbq burn
```

Agent 工作流：

```bash
openbbq --json status --workspace workspaces/demo
```

Agent 通常使用 `--json`，并且使用 `-w` 显式指明 workspace
当 stdout 不是 TTY 时，OpenBBQ 也会自动切到紧凑 JSON 输出；这在 Codex、CI
和其他 Agent 运行器里是预期行为。
当进行长任务时，使用 `openbbq status` 轮询工作空间状态
在具体的字幕任务中参考 `skills/openbbq-subtitles/SKILL.md` 中的使用方法

本地文件流程、YouTube 登录、ASS 预设、输出文件和完整命令说明见
[docs/usage.zh-CN.md](docs/usage.zh-CN.md)。

## 路线图

- [ ] Windows 和 Linux 支持
- [ ] 更多 ASR 后端支持
- [ ] 更多视频平台鉴权支持
- [ ] 面向人工翻译的可视化校对流程
- [ ] 更多字幕编辑与发布工作流

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
