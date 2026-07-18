# OpenBBQ 字幕工作流（中文源文件）

> 本文件是 skill 的**源文件**，由维护者用中文撰写；英文版 `SKILL.md`
> 由 agent 基于本文生成。修改流程：先改本文，再同步 `SKILL.md`。

当用户要求用 OpenBBQ 制作字幕、翻译字幕、产出双语字幕/双语视频、烧录字幕、
转写视频/音频，或继续一个 OpenBBQ workspace 时使用本 skill。目标是处理
**单个视频的通用流程**；用户自己的批处理规范只在用户明确给出时遵循。

优先使用 OpenBBQ 的原子 CLI 命令，不要写临时脚本。

## 简单请求的默认约定

用户只给一个视频并说“帮我把这个视频制作成双语字幕的视频”时，直接执行完整工作流，
不要追问常规选项：目标语默认取用户当前使用的语言（中文请求默认 `zh`），输出默认双语
ASS 硬字幕视频，横屏默认 `fansub`。只有版权范围、目标语言确实不明或需要外部权限时才停下来
询问。默认流程不推断视频画面中的文字位置，也不做视觉排版返工。最终只有
`delivery check` 通过才可以说任务完成。

## 必读规则

- 自动化一律用 `openbbq --json ...`，除非用户明确要看人类终端 UI。
  成功输出里的 `next` 字段只是建议，不一定准确。
- 填译文只用两种方式：Edit 工具直接改 worksheet，或写批次文件走
  `openbbq translate apply`。**永远不要**写一次性脚本去编辑 worksheet。
- 中断后先跑 `openbbq --json status --workspace <ws>`。manifest 是 stage
  状态的事实来源；`running` 且标 `stale` 通常可以安全重跑。重跑上游 stage
  会把下游 stage 重置为 pending。
- 不要删除 fetch 的 `.part` 文件；fetch 支持断点续传。不要给 `fetch`、
  `transcribe`、`burn` 设置短于任务合理时长的 harness timeout。
- 不要手改 `manifest.json`、`cues.json` 或导出的 ASS。需要改原文、时间轴、
  译文或断句时使用 `openbbq review`；批量译文只走 `translate apply`。
- zsh 等 shell 里 URL 参数要加引号。
- 长任务（`fetch`、`transcribe`、`burn`、`models pull`）可能需要轮询 status。
- 沙箱环境通常不能用本机 GPU 做 ASR；需要 GPU 时询问用户是否允许在沙箱外运行
  `transcribe`。
- 默认双语视频不要烧录 SRT；导出双语 ASS，再烧录 ASS。
- 横屏默认 `fansub`，9:16 竖屏用 `mobile`。不要根据抽帧猜测视频文字位置，也不要
  自动切换到 `fansub-compact`；该预设只在用户明确指定时使用。
- 最终交付不得跳过 ASR 不确定词门禁、翻译风险审计、双语 ASS 校验、烧录 provenance
  和非空文件检查。视觉 QA 不属于默认交付门禁；没有图像输入能力的模型应直接跳过，
  不构成质量扣分或交付失败。

## 何时读取 reference

- 处理系列、动漫、游戏、品牌、课程、访谈等专名密集内容，或 `glossary suggest`
  出现候选：读取 `references/glossary.zh-CN.md`。
- 需要完整 YouTube/本地文件命令模板、翻译批次格式、完成交付检查：读取
  `references/workflows.zh-CN.md`。
- 如果只是回答概念性问题或检查已有 workspace 状态，先用本文件即可。

## 单视频通用流程

1. 运行时预检：每个简单请求开始先跑 `openbbq --json doctor`。如果已安装的 agent
   skill 过期，doctor 会不健康；先按 fix 执行 `openbbq skill install --force`，不能用旧
   工作流继续。正式转写前确认 Whisper 模型已缓存；缺模型再拉取。
2. 初始化 workspace。YouTube URL 和本地文件都可用 `openbbq init --workspace <ws>`；
   系列/专名内容先准备或复用 glossary，并在 `init` 时绑定 `--glossary <name>`。
3. YouTube 输入先检查 auth：`openbbq auth status youtube`。已有 auth 时优先
   `openbbq fetch --workspace <ws> --auth youtube --max-height 1080`；没有 auth 再匿名 fetch。
   匿名失败且需要 cookies/bot check 时，用 `openbbq auth browser-login youtube`。
4. 本地文件跳过 fetch；YouTube fetch 后继续 `extract-audio`。
5. 转写：通常用 `openbbq transcribe --workspace <ws> --model large-v3-turbo
   --language <lang> --gpu`。沙箱无法用 GPU 时，按必读规则请求授权或改 CPU。
6. 检测器引导的 ASR 审核：先跑 `openbbq --json asr check --workspace <ws>`；有未决项时，用
   `asr batch --limit 20` 分批读取。除低置信词外，还要处理重复段、异常词速和标题/作者
   实体冲突；YouTube 参考字幕可用时 batch 会附带同时间文字。词和实体使用
   accept/replace，幻觉重复段使用 keep_first/drop，整段损坏才用 replace。每个决定必须有
   具体证据，不能批量盲目接受。直到 `ready: true` 才能继续；ready 只表示检测器发现的
   问题已解决，不代表所有 ASR 原文都正确。
7. 全量上下文 source 审计：先跑 `glossary suggest`，再翻完所有
   `openbbq --json glossary audit --workspace <ws> --limit 20` 批次，高置信词也不能跳过。
   根据完整句子、前后段、主题、专名和可选参考字幕判断，概率与参考文字只作证据。
   没有 issue id 的一次性/依赖上下文错误用 `asr amend`；可复用术语和 ASR 变体用有界的
   `glossary apply` patch。不要把有歧义的普通词做成全局 alias。直到 `remaining: 0`。
8. Glossary 生效检查：更新后再跑 `segment`，检查 `glossary_matched_terms`、
   `glossary_aliases_applied` 和 `glossary_no_effect`；已绑定不等于实际使用。如果之前已跑
   segment，ASR/glossary 更新后重跑 `segment` 和 `translate init`。
9. 分段并初始化翻译：`segment` 后跑 `translate init <lang> --max-lines 2`。默认
   双语视频先给目标语两行空间，不要为了单行限制删掉原意。
10. 填译文：大量 cue 先用 `openbbq --json translate batch <lang> --workspace
   <ws> --from <id> --limit 20 --only-missing` 读取有界批次，再写 `{id: target}`
   批次 JSON，并用 `translate apply` 合并。不要把完整 worksheet 塞进上下文。
11. 机械检查：跑 `openbbq translate check <lang> --workspace <ws>`，清掉 `missing`、
   `over_budget`、`zero_budget`、`term_issues` 和 `quality_issues`；只有输出
   `ready: true` 才能进入审计。此命令只读；翻译 stage 由正式 `export` 完成。
12. 全覆盖语义审计：用 `translate audit <lang> --coverage all --limit 20` 分批读取；
   高风险 cue 优先，但每个已翻译 cue 都必须结合前后各一条上下文逐条 accept 或 revise，
   并用 `translate audit-apply` 写入带理由的决策。不能因为机械检查通过就批量接受。
   修改任一译文会使本条及相邻上下文审校失效，必须重新 check/audit，直到 ready。
13. 人工可视化审核：用户要求最终人工校对、调整 cue 时间或修复断句时，使用
    `openbbq review --workspace <ws> --to <lang>`。审核页会受控同步 cues 与所有
    worksheet；不要同时让其他 Agent 直接编辑这些文件。
14. 导出和烧录：默认导出双语 ASS，再 burn。存在 review 文件时，未完成审核会
    阻止导出；只有明确需要草稿时才用 `--allow-unreviewed`。导出时可按场景选择
    `--ass-preset`。`--allow-quality-warnings` 和 `burn --allow-stale` 只用于用户
    明确要求的草稿或手工外部产物，不能用于最终交付。
15. 完成交付检查：burn 后直接运行 `delivery check`。它检查 ASR、分段、翻译、全量
    语义审计、双语 ASS、export/burn freshness、烧录 provenance 和非空 MP4；默认不需要
    `qa render`、查看风险帧或 `qa attest`。只有用户明确要求视觉检查且当前模型有图像
    能力时，才把 `qa render/check/attest` 作为可选诊断；结果不触发自动预设切换或重烧录。
16. 硬交付门禁：最后运行 `openbbq --json delivery check --workspace <ws> --to <lang>`。
    只有退出码 0 且 `ready: true` 才能交付；否则严格执行返回的 fix，不能用文字解释绕过。

## Glossary 原则

Glossary 是活文档，用于 ASR 偏置、segment 纠错和 `translate check` 的术语一致性。
系列或专名密集内容应主动维护 glossary。

核心判断：

- ASR 错误或拼写变体：加入已有 term 的 `aliases`，或新增 canonical `source`
  并把错误形式放进 `aliases`。这类错误不能直接流到 `segment`，尤其双语硬字幕
  会把英文源文烧进成片。
- 确定的新关键术语：译名确定则加入 glossary；不确定先问用户或在 `note` 标记
  待确认。
- 一次性或依赖上下文的错误：使用 `asr amend`；不要把在其他上下文可能正确的普通词
  做成危险的全局 alias。
- 正确的一次性普通词/无关候选：不加入 glossary。置信度只用于排序，不能替代语义判断。

详细格式、例子和主动审计流程见 `references/glossary.zh-CN.md`。

## 边界

- 第一阶段的浏览器登录只面向本地桌面环境，不要承诺 headless 服务器登录。
- 字体渲染因平台而异。当前 ASS 默认值按本地 macOS 渲染调校；商业分发需自行
  确认字体授权。
- OpenBBQ 不授予版权许可。翻译或烧录他人视频的字幕仍可能需要权利人许可。
