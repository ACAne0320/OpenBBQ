# OpenBBQ 字幕工作流（中文源文件）

> 本文件是 skill 的中文源文件。先修改本文件，再同步英文 `SKILL.md`。

当用户要求用 OpenBBQ 转写、翻译、制作双语字幕或双语硬字幕视频时使用本 skill。
默认处理单个视频；中文请求的目标语言默认是 `zh`。

## 单提示词默认流程

用户只说“帮我把这个视频制作成双语字幕视频”时，不要追问常规选项。初始化一次，然后
只服从 `agent next` 返回的 action：

```bash
openbbq --json agent init '<source>' --workspace '<ws>' --to zh
openbbq --json agent next --workspace '<ws>'
```

循环处理 `agent next`：

1. `run_command`：原样执行返回的 `argv`，完成后再次运行 `agent next`。不要自行增加、
   删除或重排流程命令。
2. `select_glossary`、`review_source`、`translate`、`review_risks`：按 action 给出的
   `response_schema` 写一个 JSON 文件，再提交：

   ```bash
   openbbq --json agent apply --workspace '<ws>' response.json
   ```

   随后再次运行 `agent next`。必须原样返回 `batch_id`、`policy_hash`，并提交完整、精确的
   当前 ID 集合；不能拆批、漏项或加入其他 ID。
3. `finish`：执行 action 返回的 `argv`。`agent finish` 会一次性导出双语 ASS、烧录视频、
   运行 delivery check，并在交付成功后发布无冲突的 glossary 学习结果。
4. `done`：只有此时才向用户交付返回的字幕和视频路径，同时说明结构化 warning。

不要同时推进多个 action。重复 `agent next` 会返回同一个活动 lease；语义批次未成功
`apply` 前不要继续。

## 语义 action 的判断原则

### `review_source`

- 审核 batch 中每个 segment；结合完整句子、前后文、标题/作者、参考字幕、glossary 和
  主题判断，不要只看置信度。
- 当前 detector issue 必须逐项决定。没有 detector issue 的上下文错词放进
  `source_fixes`，并给一句具体证据。
- `collapsed_word_timestamps`、`reference_timeline_mismatch` 表示 ASR 时间轴已损坏，
  不能 `accept`；有 timed reference replacement 时据此 `replace`，否则结合上下文明确
  `replace` 或 `drop`。不要让损坏时间轴进入 segment。
- 只有可在后续同类视频中安全复用的专名、术语或 ASR 变体才写入
  `glossary_updates` 并标记 `reusable: true`。普通词的一次性误识别不能做全局 alias。
- `codex → Codex` 这类官方大小写规范化是有效修正；不要改动未声明的 occurrence。

### `translate`

- action 内的 `brief`、`glossary` 和 `policy_hash` 是本批唯一权威翻译规则。相邻 cue
  只用于消歧，译文必须留在当前 ID，不能发生内容漂移。
- 简体中文应自然、简洁，但必须保留否定、程度、数字、实体、因果、条件和操作步骤。
  glossary 的 target/keep/note、命令、代码、路径、flag、URL、产品名和模型名必须准确。
- 含义和 cue 对齐优先于字符预算；不能安全压缩时保留含义，让后续 risk review 处理，
  不得静默漏译。
- 翻译时发现疑似 ASR 错误，提交 cue-scoped `source_fixes` 后再翻译正确原文；不要根据
  错误原文强猜。
- CLI 保证每批最多 20 条。只填写 `selected_ids`，不要翻译 neighbor context。

### `review_risks`

- 只复查返回的高风险 cue。对照 source、target 和邻接上下文，可直接 `accept`；只有
  `revise` 需要新译文和简短原因。
- 如果到风险复查才发现 ASR 错词，在同一次响应中提交 cue-scoped `source_fixes`，并按
  修正后的 source 判断是否需要 `revise`；可安全复用的错词同时写入 `glossary_updates`。
- 不要伪造全量 audit，也不要因为一次修订自行重新导出或烧录；提交后继续 `agent next`。

## 不变量

- 默认流程不做视觉 QA、不查看风险帧、不预测画面文字位置，也不使用
  `fansub-compact`。横屏由 `finish` 选择 `fansub`，竖屏选择 `mobile`。
- 不手改 `manifest.json`、`cues.json`、worksheet 或 ASS；所有语义修改只走
  `agent apply`。
- 每次真实回归或并行 harness 测试使用独立的新 workspace；不得复用另一个正在运行的
  Agent/Pi workspace。
- 不写一次性脚本编辑字幕数据。
- `fetch`、`transcribe` 和 `burn` 是长任务，不要设置不合理的短 timeout；运行中可轮询
  status，但不能创建第二个 workspace 或并行 lease。
- glossary overlay 在任务中只写 workspace；全局冲突或权限错误是非阻塞 warning，不能
  覆盖旧条目，也不能因此否定已通过的成片交付。

## 专家参考

正常 one-shot 流程不要展开旧原子命令。只有认证、沙盒/GPU、失败恢复、手工专家流程或
兼容旧 workspace 时，才读取：

- `references/workflows.zh-CN.md`：YouTube 认证、长任务、恢复和旧原子命令。
- `references/glossary.zh-CN.md`：glossary schema、冲突和手工维护。

OpenBBQ 不授予版权许可；处理他人视频时仍应遵守相应权利要求。
