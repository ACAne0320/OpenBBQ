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
   `--cpu` 重试。除此之外不要增加、删除或重排参数。
2. `translate`：服从 action 返回的 `brief` 和 glossary context，精确翻译每个
   `selected_id`，按 `response_schema` 生成一次响应并提交：

   ```bash
   openbbq --json agent apply --workspace '<ws>' response.json
   ```

   原样返回 `batch_id`、`policy_hash` 和完整的当前 ID 集合。neighbor cue 只作上下文，
   不得把内容移到其他 ID。原文明显错误时，按 schema 提交 cue-scoped `source_fix`；
   只需判断其中必填的 `reusable: true/false`。OpenBBQ 会自动记录 glossary candidate
   并提升可复用修正，不要再把同一修正重复写入 `glossary_updates`。
3. `review_source` 是罕见例外：仅在 `agent next` 报告确定性修复无法解决的结构性 ASR
   blocker 时处理。严格按 schema 和 ID 响应，apply 一次后继续。
4. `finish`：服从其 execution policy，只执行一次返回的
   `openbbq agent finish`。它会一次导出双语 ASS、一次烧录视频并验证产物。
5. `done`：交付返回的字幕、视频路径和 warning，并原样报告返回的
   `quality` 与 `human_reviewed`。

每次命令或 apply 成功后继续调用 `agent next`。同一时间只推进一个 action；重复调用会
返回同一 lease。`must_continue` 为 true 或 `terminal` 为 false 时继续运行。只有
`done` 且 `terminal: true` 才算完成。

## 翻译原则

- 服从本批 `brief`、glossary context 和目标语言规则。
- 译文自然、忠实，保留否定、数字、实体、条件和关键关系。
- 只翻译当前 cue；neighbor 只用于消歧，不能跨 ID 搬移内容。
- 含义和对齐优先于激进压缩。若不确定是否为 ASR 错误，翻译当前原文并提交 warning，
  不要臆造修正。

不要手改 workspace 数据、创建并行 lease、运行视觉 QA 或使用 `fansub-compact`。fetch、
transcribe 和 finish 是长任务，应给出合理执行时间。

专业精修应在 `done` 后进行：运行
`openbbq review --workspace '<ws>' --to zh`，或把导出的字幕放入 Aegisub/剪辑软件。
人工修改是最终权威，不应再运行 agent workflow 覆盖它。

OpenBBQ 不授予版权许可；处理他人视频时仍应遵守相应权利要求。
