# OpenBBQ 字幕工作流（中文源文件）

> 本文件是 skill 的中文源文件。先修改本文件，再同步英文 `SKILL.md`。

当用户要求用 OpenBBQ 转写、翻译、制作双语字幕或双语硬字幕视频时使用本 skill。
默认一次处理一个视频；中文请求的目标语言默认是 `zh`。把产物视为可靠的 AI 字幕底稿：
普通用户可直接使用，专业用户可继续精修。

## 单提示词默认流程

用户只说“帮我把这个视频制作成双语字幕视频”时，不要追问常规选项。创建新的 workspace，
初始化一次，然后让 `agent next` 驱动任务：

```bash
openbbq --json agent init '<source>' --workspace '<ws>' --to zh
openbbq --json agent next --workspace '<ws>'
```

重复以下步骤，直到收到 `done`：

1. `run_command`：原样执行返回的 `argv`，并服从 `execution.sandbox`。
   `outside_required` 必须在宿主机/沙箱外运行，`inside_allowed` 可在当前环境运行。
   fetch 可能需要宿主机网络与认证状态。transcribe 必须执行返回的沙箱外 GPU 命令并保留
   `--gpu`；只有该 GPU 命令确实失败且 `execution.cpu_fallback` 允许时，才可改用
   `--cpu` 重试。除此之外不要增加、删除或重排参数。若 harness 返回仍在运行的
   process/session ID，必须保留并轮询同一 session 直到得到 exit code；存在 session ID
   时，空 stdout 或外层 tool/cell 结束都不代表命令完成，不得重新执行 `argv`。
2. `translate`：服从 action 返回的 `brief` 和 glossary context，精确翻译每个
   `selected_id`，按 `response_schema` 生成一次响应并提交：

   ```bash
   openbbq --json agent apply --workspace '<ws>' response.json
   ```

   服从 `generation_policy`：译文必须由当前 agent 根据本批 source、上下文、glossary
   和规则直接生成。不得调用外部翻译服务或外部 LLM；脚本只能序列化和提交当前 agent
   已经生成的译文，不能生成译文本身。原样返回 `batch_id`、`policy_hash`、
   `generation_mode` 和完整的当前 ID 集合。neighbor cue 只作上下文，不得把内容移到
   其他 ID。部分 cue 可能带有局部 `reference_evidence`；它只是在时间上
   对齐的参考字幕分歧，不是权威原文。结合上下文与 glossary 判断，只有修正确认无疑时
   才提交 cue-scoped `source_fix`，否则保守翻译当前 source 并给出 warning。若
   `reusable: true`，`find`/`replacement` 必须是最小稳定术语，不能包含无关语法。
   OpenBBQ 会自动记录 glossary candidate 并提升可复用修正，不要再把同一修正重复写入
   `glossary_updates`。若对某条 cue 有具体可修的疑点，可在 `warnings` 中附结构化对象
   `{"cue_id", "message", "patch"}`（`patch` 至少含 source/target/start/end 之一，
   `cue_id` 必须属于本批 `selected_ids`）；它会作为 review suggestion 归档，不会进入
   session warnings。一般性不确定仍用自由文本 warning。
3. `review_source` 是罕见例外：仅在 `agent next` 报告确定性修复无法解决的结构性 ASR
   blocker 时处理。重复 run 可能用一个可见 segment 代表 issue 中列出的全部相同受影响
   ID；若整段 `reference_caption` 显示实际存在不同的连续语音，应替换该 issue，而不是
   丢弃整段。严格按 schema 和 ID 响应，apply 一次后继续。
4. `finish`：服从其 execution policy，只执行一次返回的
   `openbbq agent finish`。它会一次导出双语 ASS、一次烧录视频并验证产物。
5. `done`：交付返回的字幕、视频路径和 warning，并原样报告返回的
   `quality` 与 `human_reviewed`。

每次命令或 apply 成功后继续调用 `agent next`。同一时间只推进一个 action；重复调用会
返回同一 lease。`must_continue` 为 true 或 `terminal` 为 false 时继续运行。只有
`done` 且 `terminal: true` 才算完成。

## 翻译原则

- 服从本批 `brief`、glossary context 和目标语言规则。
- 由当前 agent 直接生成译文，不要调用外部翻译服务、外部 LLM 或自动翻译脚本。
- 译文自然、忠实，保留否定、数字、实体、条件和关键关系。
- 只翻译当前 cue；neighbor 只用于消歧，不能跨 ID 搬移内容。
- 含义和对齐优先于激进压缩。若不确定是否为 ASR 错误，翻译当前原文并提交 warning，
  不要臆造修正。
- 翻译阶段的 source fix 可以删除局部噪声，但不能删掉整条 cue；结构或边界调整应留给
  source review。
- 优先使用 action 已提供的标题、作者、glossary 和局部参考证据。普通歧义不要自行联网
  搜索或重新运行 ASR；保留 warning 交给后续人工精修。

不要手改 workspace 数据、创建并行 lease、运行视觉 QA 或使用 `fansub-compact`。fetch、
transcribe 和 finish 是长任务，应给出合理执行时间。

专业精修应在 `done` 后进行：可先运行
`openbbq review --prepare --workspace '<ws>' --to zh` 获取分析 JSON（已含各 cue 的
rule issues，不要重复确定性检查），按 `response_schema` 写出建议响应，再运行
`openbbq review --prepare --apply response.json --workspace '<ws>' --to zh` 写入建议，
然后运行 `openbbq review --workspace '<ws>' --to zh`，让用户在已带建议的工作台里精修；
或把导出的字幕放入 Aegisub/剪辑软件。人工修改是最终权威，不应再运行 agent workflow
覆盖它。

OpenBBQ 不授予版权许可；处理他人视频时仍应遵守相应权利要求。
