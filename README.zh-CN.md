# OpenBBQ

[English README](README.md) · [使用指南](docs/usage.zh-CN.md)

**OpenBBQ** 是一个专为智能体（Agent）设计的用于视频翻译和字幕制作的命令行工具。

OpenBBQ 提供默认的 `agent init/next/apply/finish` facade，让不同 Agent 用一句提示词
稳定执行同一套质量流程；同时保留视频下载、ASR、分段、翻译、校对、导出和烧录等
细粒度命令，供专家调试与兼容使用。

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

## 使用

推荐的 agent 入口：

```bash
openbbq --json agent init '<video-or-url>' --workspace workspaces/demo --to zh
openbbq --json agent next --workspace workspaces/demo
```

本地文件流程、YouTube 登录、ASS 预设、输出文件和完整命令说明见
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
