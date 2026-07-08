# OpenBBQ 使用指南

[README](../README.zh-CN.md) · [English Usage](usage.md)

这份文档说明本地视频和 YouTube URL 的完整流程。

## 检查环境

开发环境：

```bash
uv sync --extra whispercpp --dev
uv run pytest
```

运行检查：

```bash
openbbq doctor
openbbq models pull large-v3-turbo
```

如果要烧录字幕，`doctor` 应该能找到带 `ass` 和 `subtitles` filter 的 FFmpeg。

## YouTube 流程

zsh 这类 shell 里要给 URL 加引号：

```bash
openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

如果 YouTube 要求登录或人机验证：

```bash
openbbq auth browser-login youtube
openbbq fetch --workspace workspaces/demo
```

浏览器登录态保存在 `OPENBBQ_HOME` 下，默认是 `~/.openbbq`。这个目录需要可写。
如果运行环境是受限 sandbox，请在普通用户环境里执行 browser auth 和 `fetch`，或把
`OPENBBQ_HOME` 指到可写目录。公开视频如果因为已保存登录态触发 403，可以改用
`openbbq fetch --workspace workspaces/demo --no-auth`。

## 本地文件流程

本地视频可以跳过 `fetch`：

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

## ASR 和 GPU

所选 ASR 后端支持时，`--gpu` 是默认的快速路径。如果原生后端在受限 sandbox 中崩溃
或失败，请在 sandbox 外重新运行 `transcribe`，或改用 `--cpu` 重试。

## 翻译

创建中文翻译工作表：

```bash
openbbq translate init zh --workspace workspaces/demo
```

填写 `workspaces/demo/translation.zh.json` 中的 `target` 字段——可以直接编辑
文件，也可以分批合并：写一个 cue id → 译文的 JSON 对象，然后 apply（可重复
执行，适合长视频分批）：

```bash
echo '{"1": "第一句译文", "2": "第二句译文"}' > targets.json
openbbq translate apply zh --workspace workspaces/demo targets.json
```

检查工作表：

```bash
openbbq translate check zh --workspace workspaces/demo
```

## 导出和烧录

导出双语 ASS：

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --output out/zh.ass
```

烧录成视频：

```bash
openbbq burn --workspace workspaces/demo
```

烧录可能需要几分钟。JSON 或非 TTY 模式下，stdout 仍然只输出最后的单个 JSON
结果；进度会写进 workspace manifest。可以另开终端轮询：

```bash
openbbq --json status --workspace workspaces/demo
```

## ASS 预设

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`：常规 16:9 横屏视频。
- `fansub`：译文行更醒目。
- `mobile`：面向 9:16 竖屏视频，使用竖屏画布和更大的底部安全区。

`mobile` 只改变渲染样式。长字幕仍然需要更短的切分或更紧凑的翻译。

## Agent 使用

Agent 应把根级 `--json` 放在命令名前使用 JSON 输出：

```bash
openbbq --json status --workspace workspaces/demo
openbbq --json export --workspace workspaces/demo --to zh --mode bilingual --format ass
```

只有 stdout 是交互式 TTY 时，OpenBBQ 才使用 Rich 人类可读输出。在 Codex、CI 或
其他非 TTY 运行器里，即使没有显式传 `--json`，也会自动输出紧凑 JSON。

工作空间 manifest 记录了已完成、运行中和失败的阶段。`fetch`、`transcribe`、
`burn` 这类长任务可以通过 `status` 查询进度。

安装随包发布的 agent skill。默认目标是共享 agents 目录：

```bash
openbbq skill install
```

这会写入 `~/.agents/skills/openbbq-subtitles/`。如果当前 agent 读取自己的
skills 目录，Claude Code 使用 `openbbq skill install --agent claude`，Codex
使用 `openbbq skill install --agent codex`。一次安装所有支持目标使用
`openbbq skill install --agent all`。

安装固定写入英文 skill 及其英文 `references/`。

需要直接从 stdout 读取 skill 内容的 agent 可以使用 `openbbq skill show`。

## 输出文件

常见工作空间输出：

- `media/`：下载或生成的媒体文件。
- `transcript.json`：ASR 转录结果。
- `cues.json`：原文字幕 cue。
- `translation.<lang>.json`：可编辑翻译工作表。
- `out/<lang>.srt`：导出的 SRT 字幕。
- `out/<lang>.ass`：导出的 ASS 字幕。
- `out/<lang>-burned.mp4`：烧录硬字幕后的视频。

## 命令

```text
openbbq doctor
openbbq init
openbbq status
openbbq auth browser-login/status/clear
openbbq fetch
openbbq extract-audio
openbbq transcribe
openbbq segment
openbbq translate init/apply/check
openbbq glossary list/show/new/use/suggest
openbbq export
openbbq burn
openbbq models list/pull
```
