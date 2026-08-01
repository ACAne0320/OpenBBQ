# OpenBBQ 使用指南

[README](../README.zh-CN.md) · [English Usage](usage.md)

OpenBBQ 提供两条互补路径：

- 默认 agent facade：一句提示词生成结构完整、可编辑的 AI 字幕底稿；
- 专家原子命令与 `openbbq review`：用于诊断和专业人工精修。

自动流程的目标是稳定、可用的 70–80 分底稿，不代表每条 cue 都经过专业确认。

## 推荐：单提示词 Agent 流程

安装随包发布的 skill 后，用户只需发送：

> 帮我把这个视频制作成中英双语字幕视频：https://www.youtube.com/watch?v=...

下面的流程由 Agent 自行负责，用户不需要在提示词里逐项说明内部步骤。

初始化一次；只有明确知道现有 glossary 与视频匹配时才显式传入：

```bash
openbbq --json agent init 'https://www.youtube.com/watch?v=...' \
  --workspace workspaces/demo --to zh [--glossary <name>]
```

然后持续请求唯一权威的下一步：

```bash
openbbq --json agent next --workspace workspaces/demo
```

按返回的 action 执行：

- `run_command`：原样执行返回的 `argv`；若返回 process/session ID，轮询同一 session
  直到得到 exit code，不能因空 stdout 或外层 tool/cell 结束而重跑命令；
- `review_source`：仅在结构性 ASR 问题阻塞分段时，提交完整的有界响应；
- `translate`：翻译所有 selected ID，并提交响应；
- `finish`：执行其中的 `argv`；
- `done`：交付返回的字幕和视频路径。

语义 action 使用：

```bash
openbbq --json agent apply --workspace workspaces/demo response.json
```

正常流程是：

```text
fetch → extract → transcribe → validate/segment
      → translate（每批 ≤20 条）→ finish → done
```

默认没有模型驱动的 glossary 选择对话、额外语义复查队列或全量 AI audit。显式
`--glossary` 始终优先；否则 URL 任务会在 fetch 得到作者后绑定稳定的作者+目标语言
glossary。重复调用 `next` 会返回同一活动 lease。`apply` 必须带精确的 `batch_id`、
`policy_hash` 和完整 ID 集合；source 或 worksheet 过期时会被拒绝。
较长的重复 ASR run 会用一个可见 segment 代表 detector issue 列出的全部相同受影响
ID；若存在覆盖整个区间的时间对齐参考字幕，也会一并提供。活动 lease 存在时，专家
ASR 写命令不能修改该 review。

每个 `translate` action 还包含 `generation_policy`。当前译文必须由正在执行工作流的
agent 根据所给 source、上下文、glossary 和规则直接生成；不得调用外部翻译服务、外部
LLM 或自动翻译脚本。脚本只能保存和提交 agent 已生成的结果。`agent apply` 必须原样
回显 `generation_mode`。

翻译响应还可以提交：

- 明显 ASR 错误的 cue-scoped `source_fixes`；
- 真正可复用的 `glossary_updates`；
- 模型不确定时的简短 warning。

翻译阶段的 source fix 可以删除 cue 内的局部噪声，但不能删除整条 cue；涉及分段或
边界的结构调整应留在 source review 中处理。

若存在可靠的时间对齐参考字幕，个别 cue 可能带有简短 `reference_evidence`，只展示局部
分歧。它是提示而非权威原文，应结合已提供的上下文和 glossary 判断。普通歧义不应触发
联网搜索或重跑 ASR；保持 source 不变并返回 warning。可复用 source fix 应只包含最小
稳定术语与 alias，不要带入周边语法。

普通低置信 ASR 词、显示预算和 glossary 一致性都只作为提示。硬门禁只覆盖：schema
与时间轴有效、ID 完整、原文/译文非空、hash 当前、更新原子、产物 provenance
新鲜、最终文件非空，以及存在大量时间对齐参考语音的长字幕空洞。

`finish` 只导出和烧录一次；横屏使用 `fansub`，竖屏使用 `mobile`。默认不运行视觉
QA，也不选择 `fansub-compact`。正常 `done` 响应包含：

```json
{
  "artifact_ready": true,
  "quality": "draft",
  "human_reviewed": false
}
```

## 检查环境

开发环境：

```bash
uv sync --extra whispercpp --dev
uv run pytest
```

运行环境：

```bash
openbbq doctor
openbbq models list
openbbq models pull large-v3-turbo
```

烧录字幕需要 FFmpeg 提供 `ass` 和 `subtitles` filter。

## 输入、认证与 GPU

zsh 等 shell 中应给 URL 加引号。等价的 YouTube 原子流程是：

```bash
openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'
openbbq fetch --workspace workspaces/demo --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

本地文件跳过 `fetch`：

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
```

YouTube 要求登录或人工验证时：

```bash
openbbq auth browser-login youtube
openbbq fetch --workspace workspaces/demo --max-height 1080
```

浏览器状态保存在 `OPENBBQ_HOME`，默认是 `~/.openbbq`。受限 sandbox 无法访问状态
时，应在普通用户环境中执行浏览器认证和网络下载。公开视频若因已保存认证触发 403，
可用 `--no-auth` 重试。

所选后端支持时，GPU 是 ASR 默认路径。原生 GPU 与模型缓存应在受限 sandbox 外运行。
只有 sandbox 外 GPU 确实失败后，才改用 CPU：

```bash
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --cpu
```

## Glossary

仅在范围明确时显式使用现有 glossary：

```bash
openbbq glossary list
openbbq glossary show <name>
openbbq --json agent init '<source>' --workspace workspaces/demo --to zh --glossary <name>
```

显式 glossary 始终优先。未显式指定时，URL 任务等待 fetch 元数据，然后根据作者派生
稳定的 `author-<slug>-<target>-<hash>` glossary；同作者、同目标语言的后续视频会
得到同一 glossary，同时避免不同目标语言共用单一 `target` 字段，不依赖
模型判断。本地文件如果没有显式 glossary，则只使用任务 overlay。

翻译时，OpenBBQ 会提供已绑定的 glossary context，以及 selected/neighbor cue 或局部
参考证据命中的相关术语。可复用发现保存在任务级 `.openbbq/glossary-overlay.json`。任务中立即
使用 base + overlay，但只在成功交付后更新全局库。

发布过程不会覆盖已有 owner 或字段。冲突、缺少绑定或权限失败会保留 overlay，并返回
不阻塞视频交付的重试 warning。

## 专家 ASR 诊断

以下命令是可选专家工具，不是默认 one-shot 步骤：

```bash
openbbq --json asr check --workspace workspaces/demo
openbbq --json asr batch --workspace workspaces/demo --limit 20 --only-unresolved
openbbq asr apply --workspace workspaces/demo asr-decisions.json
openbbq asr amend --workspace workspaces/demo asr-amendments.json
openbbq --json glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --offset 0 --limit 20
openbbq glossary apply --workspace workspaces/demo glossary-terms.json
```

它们用于诊断已知 ASR 问题、迁移旧 workspace，或执行人工主导的彻底检查。低置信本身
不要求替换；全转录 audit 也不是默认交付门禁。单次修正必须限定 occurrence；只有
明确可复用的 glossary alias 才能影响之后匹配的文本。

## 专家翻译命令

facade 通常会创建并维护翻译 worksheet。等价的原子命令仍可使用：

```bash
openbbq translate init zh --workspace workspaces/demo --max-lines 2
openbbq --json translate batch zh --workspace workspaces/demo --from 1 --limit 20 --only-missing
openbbq translate apply zh --workspace workspaces/demo targets.json
openbbq translate check zh --workspace workspaces/demo
```

`translate check` 把缺失/空译文作为错误，也可能把预算或 glossary 问题报告为
warning。这些 warning 帮助编辑者排序，不证明含义正确，也不会在默认流程中制造
强制复查循环。

## 专业审核与编辑

安装可选的本地 review UI，并打开已生成的 workspace：

```bash
uv tool install 'openbbq[review]' --force
openbbq review --workspace workspaces/demo --to zh
```

浏览器会同时展示视频或音频、waveform、cue 时间轴、原文、译文、时间和审核状态。
它支持修改原文/译文/时间、拆分/合并/新增/删除、撤销/重做，以及逐 cue 的
reviewed/flagged 状态。修改会自动保存到 workspace 的权威数据。

人工修改具有最高权威，自动流程不会覆盖。编辑完成后，应主动重新导出 SRT/ASS 和
烧录视频。ASS 也可以导入 Aegisub 或其他剪辑软件继续处理。

当每条当前 cue 都经过确认后，OpenBBQ 可以报告：

```json
{
  "quality": "human-reviewed",
  "human_reviewed": true
}
```

这表示人工审核状态完整，不是自动语义评分。

## 导出、烧录与交付

人工修改后可使用原子命令重新生成产物：

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual \
  --format ass --output out/zh.ass
openbbq burn --workspace workspaces/demo
openbbq --json delivery check --workspace workspaces/demo --to zh
```

export 会记录内容 hash。burn 会拒绝被改动或未追踪的 workspace ASS，并记录源视频、
ASS 和最终 MP4 hash。delivery 检查 schema、完整非空内容、有效时间轴、产物新鲜度
和 provenance。语义 warning 不会声称或否定专业准确率。

长任务会把进度写入 workspace manifest：

```bash
openbbq --json status --workspace workspaces/demo
```

`qa render/check/attest` 仍是人工明确要求视觉检查时的可选诊断。它们不会自动执行、
选择预设或触发重烧录。

## ASS 预设

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset default
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub-compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

- `default`：常规 16:9 样式；
- `fansub`：译文更醒目，也是默认横屏选择；
- `fansub-compact`：用户显式选择的更小、上移双语堆叠；
- `mobile`：9:16 样式和更大的底部安全区。

预设只影响渲染，不影响翻译含义。OpenBBQ 不预测视频中任意文字会出现在哪里。

## Agent 安装与输出

安装随包发布的 skill：

```bash
openbbq skill install
```

如果 harness 读取独立 skill 目录，可使用 `--agent claude`、`--agent codex` 或
`--agent all`。`openbbq skill show` 会输出已安装的说明。

常见 workspace 产物：

- `transcript.json`：ASR 转录；
- `cues.json`：权威原文 cue；
- `translation.<lang>.json`：可编辑翻译 worksheet；
- `.openbbq/agent-session.<lang>.json`：lease 与翻译证据；
- `.openbbq/glossary-overlay.json`：任务级可复用 glossary 学习；
- `review.<lang>.json`：人工审核状态；
- `.openbbq/artifacts.json`：export/burn provenance；
- `out/<lang>.srt` 与 `out/<lang>.ass`：字幕；
- `out/<lang>-burned.mp4`：烧录硬字幕视频。

## 命令

```text
openbbq agent init/next/apply/finish
openbbq doctor
openbbq init
openbbq status
openbbq auth browser-login/status/clear
openbbq fetch
openbbq extract-audio
openbbq transcribe
openbbq segment
openbbq asr check/batch/apply/amend
openbbq translate init/batch/apply/check
openbbq review
openbbq glossary list/show/new/use/suggest/audit/apply
openbbq export
openbbq burn
openbbq qa render/check/attest
openbbq delivery check
openbbq models list/pull
```
