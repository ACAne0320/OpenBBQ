# OpenBBQ

[English README](README.md) · [使用指南](docs/usage.zh-CN.md)

**OpenBBQ** 是一个面向智能体（Agent）的视频翻译和字幕制作命令行工具。

OpenBBQ 提供默认的 `agent init/next/apply/finish` facade，让不同 Agent 用一句提示词
生成可编辑的双语字幕底稿。默认流程追求稳定的 70–80 分初稿：普通用户无需配置复杂
流程即可使用，但它不会冒充经过专业人工审核的最终字幕。

OpenBBQ 确定性地保证结构正确、翻译批次有界、产物新鲜和只导出/烧录一次。Agent
负责翻译，并可在翻译时修正明显的单处 ASR 错误或学习可复用的 glossary 术语。
低置信词、显示预算和 glossary 一致性只作为提示，不会制造强制审核队列。

显式 `--glossary` 始终优先。否则，URL fetch 得到作者后，OpenBBQ 会自动绑定稳定的
作者+目标语言 glossary。任务 overlay 中学到的术语会在交付后冲突安全地发布，并被
同作者、同目标语言的后续视频复用；不需要模型选择 glossary。

专业用户可以在同一 workspace 中运行 `openbbq review`，或把 ASS 导入 Aegisub /
剪辑软件继续精修。人工修改具有最高权威，自动流程不会覆盖。细粒度 ASR、glossary、
翻译、导出和烧录命令仍作为专家工具保留。

## Why OpenBBQ?

在中国字幕组和创作者社群中，翻译并制作外语视频字幕的过程通常被称为“烤肉”。
未经翻译的原始素材通常被称作“生肉”，而经过翻译和添加字幕的成品则变成了“熟肉”。

所以 OpenBBQ 的愿景是，做一个开源、开放的字幕翻译平台。

## 前置条件

- Python 3.12 或更新版本
- [uv](https://docs.astral.sh/uv/)，用于安装 `openbbq` 命令和管理 Python 依赖
- [ffmpeg](https://www.ffmpeg.org/)，用于下载视频、合并音视频、抽取音频和视频烧录；如果有烧录字幕的需求，FFmpeg 还需要 `libass` 支持
- 一个 ASR 后端，目前仅支持 [whisper.cpp](https://github.com/absadiki/pywhispercpp) (Python Binding)
- 一个 ASR 模型，模型不随安装包一起下载，安装后用 `openbbq models list` 查看可用档位，再显式执行 `openbbq models pull ...`。
- 如果需要下载的视频平台要求登录、人机验证或浏览器挑战，需要本机桌面浏览器；

## 安装

### Agent 安装

```markdown
查看[安装指南](https://raw.githubusercontent.com/ACAne0320/OpenBBQ/main/docs/install-agent.zh-CN.md)，帮我安装[OpenBBQ](https://github.com/ACAne0320/OpenBBQ)
```

### 手动安装

```bash
uv tool install 'openbbq[whispercpp]'
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
openbbq doctor
```

## 快速开始

安装 OpenBBQ 和 agent skill 后，只需向 Agent 发送一句提示词：

> 帮我把这个视频制作成中英双语字幕视频：https://www.youtube.com/watch?v=...

Agent 会自行完成完整流程，并返回可编辑的 ASS 字幕和烧录后的视频。提示词中不需要
解释 ASR、分批翻译、glossary 维护、导出或烧录步骤。

底层的 agent 入口是：

```bash
openbbq --json agent init '<video-or-url>' --workspace workspaces/demo --to zh [--glossary <name>]
openbbq --json agent next --workspace workspaces/demo
```

持续遵循 `agent next`，直到它返回 `done`。正常任务只包含机械命令、每批最多 20 条
的翻译、一次 finish，默认不做视觉 QA。

本地文件流程、YouTube 登录、专业审核、ASS 预设、输出文件和完整命令说明见
[使用指南](docs/usage.zh-CN.md)。

Agent 安装和随包发布的 OpenBBQ skill 说明见
[Agent 安装指南](docs/install-agent.zh-CN.md) 和
[OpenBBQ Skill](src/openbbq/skills/openbbq-subtitles/SKILL.md)。

## 路线图

- [ ] 演示视频
- [ ] 详细文档站点
- [ ] Windows 和 Linux 支持
- [ ] 更多 ASR 后端支持
- [ ] 更多视频平台鉴权支持
- [ ] Agent 自行探索值得翻译的视频
- [x] 按目标语言固化的可复现翻译 brief
- [x] 面向人工翻译的可视化校对流程
- [ ] 更多字幕编辑与发布工作流

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。
