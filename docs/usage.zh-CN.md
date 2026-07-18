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
openbbq fetch --workspace workspaces/demo --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

如果 YouTube 要求登录或人机验证：

```bash
openbbq auth browser-login youtube
openbbq fetch --workspace workspaces/demo --max-height 1080
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

分段前必须处理所有低置信词和段级异常（重复幻觉、异常词速、标题/作者实体冲突）：

```bash
openbbq --json asr check --workspace workspaces/demo
openbbq --json asr batch --workspace workspaces/demo --limit 20 --only-unresolved
openbbq asr apply --workspace workspaces/demo asr-decisions.json
```

词和实体使用 accept/replace；重复段可用 keep_first/drop。所有决定都必须写理由；
短语 replace 还要提供精确的 `find` 与 `replacement`。fetch 到 YouTube VTT 时，batch
会附带同时间的参考文字。
重复处理直到 `asr check` 返回 `ready: true`；未决或过期决定会阻止 `segment`。

## 翻译

创建中文翻译工作表：

```bash
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

长视频先读取有界批次，避免 Agent 把整个 worksheet 塞进上下文：

```bash
openbbq --json translate batch zh --workspace workspaces/demo --from 1 --limit 20 --only-missing
```

把选中的 cue id → 译文写成 JSON，再用 apply 合并：

```bash
echo '{"1": "第一句译文", "2": "第二句译文"}' > targets.json
openbbq translate apply zh --workspace workspaces/demo targets.json
```

检查工作表：

```bash
openbbq translate check zh --workspace workspaces/demo
```

只有 `ready: true` 才表示翻译完成。必须处理 `missing`、`over_budget`、
`zero_budget`、`term_issues` 和 `quality_issues`；只有明确导出草稿时才使用
`--allow-quality-warnings` 绕过。
`translate check` 完全只读，不会让已完成的 export/burn 失效。双语 ASS 会按
worksheet 的目标语行预算确定性插入 `\N`，不会截断译文。

分批审核全覆盖语义队列（风险项优先，每条带前后文）：

```bash
openbbq --json translate audit zh --workspace workspaces/demo --coverage all --limit 20
openbbq translate audit-apply zh --workspace workspaces/demo translation-audit.json
```

每条 accept/revise 都要写理由，revise 还要带 `target`。每个 cue 都必须审核；修改一条
会使本条和相邻上下文决定失效。存在当前未审核项时，
正式导出会被阻止；`--allow-quality-warnings` 只用于明确草稿。

## 可视化审核与字幕编辑

安装可选的本地审核 UI，然后打开一个目标语言：

```bash
uv tool install 'openbbq[review]' --force
openbbq review --workspace workspaces/demo --to zh
```

浏览器把视频或音频、waveform、cue 时间轴、原文、译文、时间和审核状态放在同一
工作区中。文字修改会自动保存到 `cues.json` 和 `translation.<lang>.json`；支持
拆分、合并、新增、删除、撤销/重做，以及逐 cue 的已审核/待处理状态。SRT/ASS
仍是派生产物，需要显式执行 `export` 重新生成。

一旦存在 `review.<lang>.json`，对应的目标语/双语导出默认要求全部 cue 已审核。
只有明确需要草稿导出时才使用 `--allow-unreviewed`。

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

导出会记录 cues、译文、review 状态和 ASS 的内容哈希。burn 默认拒绝已改动或未追踪
的 workspace 内 ASS；`--allow-stale` 只用于明确的手工草稿，显式传入 workspace
外部 ASS 仍然受支持。成功 burn 还会记录最终 MP4，以及所用源视频和 ASS 的精确
内容哈希。

## 完成 QA

```bash
openbbq --json qa render --workspace workspaces/demo
openbbq --json qa check --workspace workspaces/demo
openbbq --json delivery check --workspace workspaces/demo --to zh
```

`qa render` 默认选择最多 7 张首尾、中段、长句、高 CPS、短时长风险帧。
`mechanical_status: pass` 只证明当前非空 MP4、源视频、ASS 和截帧 hash 一致，
不等于看过画面。只有实际打开并检查返回的每一张 frame 后，有视觉输入能力的审核者
才能运行 `qa attest --result pass|fail --reason ...`。失败必须额外用一个或多个
`--issue` 记录结构化问题。没有图像输入能力时必须保留
`visual_status: not_performed`，并明确说明未执行视觉检查。

最终 `delivery check` 是硬门禁：它综合 ASR、翻译机械检查、全覆盖上下文审校、
export/burn freshness 与视觉 QA。任一失败都会返回 `ready:false` 和非零退出码。

## ASS 预设

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub-compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`：常规 16:9 横屏视频。
- `fansub`：译文行更醒目。
- `fansub-compact`：更小且上移的双语堆叠，用于下三分之一冲突或遮挡修复。
- `mobile`：面向 9:16 竖屏视频，使用竖屏画布和更大的底部安全区。

`mobile` 只改变渲染样式。目标语行容量由 `translate init` 的覆盖参数控制；如果仍
超过阅读速度或行容量门禁，需要修订译文或重新切分。

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
- `.openbbq/asr-review.json`：绑定 transcript hash 的低置信词决定。
- `.openbbq/translation-audit.<lang>.json`：绑定当前 cue 内容的风险审核决定。
- `.openbbq/qa.json`：MP4/截帧证据和可选视觉证明。
- `review.<lang>.json`：逐 cue 的人工审核状态与已审核内容 hash。
- `.openbbq/artifacts.json`：供 burn 校验的导出来源与内容 hash。
- `.openbbq/review/`：本地 lock、checkpoint、waveform cache 和预览 proxy。
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
openbbq asr check/batch/apply
openbbq translate init/batch/apply/check/audit/audit-apply
openbbq review
openbbq glossary list/show/new/use/suggest
openbbq export
openbbq burn
openbbq qa render/check/attest
openbbq delivery check
openbbq models list/pull
```
