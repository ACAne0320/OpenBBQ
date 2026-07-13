# OpenBBQ 字幕工作流（中文源文件）

> 本文件是 skill 的**源文件**，由维护者用中文撰写；英文版 `SKILL.md`
> 由 agent 基于本文生成。修改流程：先改本文，再同步 `SKILL.md`。

当用户要求用 OpenBBQ 制作字幕、翻译字幕、产出双语字幕/双语视频、烧录字幕、
转写视频/音频，或继续一个 OpenBBQ workspace 时使用本 skill。目标是处理
**单个视频的通用流程**；用户自己的批处理规范只在用户明确给出时遵循。

优先使用 OpenBBQ 的原子 CLI 命令，不要写临时脚本。

## 必读规则

- 自动化一律用 `openbbq --json ...`，除非用户明确要看人类终端 UI。
  成功输出里的 `next` 字段只是建议，不一定准确。
- 填译文只用两种方式：Edit 工具直接改 worksheet，或写批次文件走
  `openbbq translate apply`。**永远不要**写一次性脚本去编辑 worksheet。
- 中断后先跑 `openbbq --json status --workspace <ws>`。manifest 是 stage
  状态的事实来源；`running` 且标 `stale` 通常可以安全重跑。重跑上游 stage
  会把下游 stage 重置为 pending。
- zsh 等 shell 里 URL 参数要加引号。
- 长任务（`fetch`、`transcribe`、`burn`、`models pull`）可能需要轮询 status。
- 沙箱环境通常不能用本机 GPU 做 ASR；需要 GPU 时询问用户是否允许在沙箱外运行
  `transcribe`。
- 默认双语视频不要烧录 SRT；导出双语 ASS，再烧录 ASS。
- ASS preset 按目标画面选：`fansub` 更醒目，`mobile` 适合 9:16 竖屏。

## 何时读取 reference

- 处理系列、动漫、游戏、品牌、课程、访谈等专名密集内容，或 `glossary suggest`
  出现候选：读取 `references/glossary.zh-CN.md`。
- 需要完整 YouTube/本地文件命令模板、翻译批次格式、完成 QA：读取
  `references/workflows.zh-CN.md`。
- 如果只是回答概念性问题或检查已有 workspace 状态，先用本文件即可。

## 单视频通用流程

1. 运行时预检：首次在机器上处理字幕，或遇到依赖错误时，跑 `openbbq doctor`。
   正式转写前确认 Whisper 模型已缓存；缺模型再 `openbbq models pull <model>`。
2. 初始化 workspace。YouTube URL 和本地文件都可用 `openbbq init --workspace <ws>`；
   系列/专名内容先准备或复用 glossary，并在 `init` 时绑定 `--glossary <name>`。
3. YouTube 输入先检查 auth：`openbbq auth status youtube`。已有 auth 时优先
   `openbbq fetch --workspace <ws> --auth youtube`；没有 auth 再匿名 fetch。
   匿名失败且需要 cookies/bot check 时，用 `openbbq auth browser-login youtube`。
4. 本地文件跳过 fetch；YouTube fetch 后继续 `extract-audio`。
5. 转写：通常用 `openbbq transcribe --workspace <ws> --model large-v3-turbo
   --language <lang> --gpu`。沙箱无法用 GPU 时，按必读规则请求授权或改 CPU。
6. 专名处理：转写后必须跑 `openbbq glossary suggest --workspace <ws>`。按
   `references/glossary.zh-CN.md` 主动审计 ASR 专名错误、拼写变体和新关键术语；
   更新 glossary 后再 `segment`。如果 `segment` 已跑过，更新 glossary 后重跑
   `segment` 和 `translate init`。
7. 分段并初始化翻译：`segment` 后跑 `translate init <lang>`。
8. 填译文：少量 cue 用 Edit 工具；大量 cue 写 `{id: target}` 批次 JSON，再用
   `openbbq translate apply <lang> --workspace <ws> <batch.json>` 合并。
9. 机械检查：跑 `openbbq translate check <lang> --workspace <ws>`，清掉 `missing`、
   `over_budget`、`term_issues`。
10. 人工可视化审核：用户要求最终人工校对、调整 cue 时间或修复断句时，使用
    `openbbq review --workspace <ws> --to <lang>`。审核页会受控同步 cues 与所有
    worksheet；不要同时让其他 Agent 直接编辑这些文件。
11. 翻译质量自审：导出前抽查或通读 worksheet，主动修正误译、不自然、语气不符、
    上下文断裂、术语漂移和双语 source/target 不匹配的问题。修订后重新
    `translate apply` 和 `translate check`。
12. 导出和烧录：默认导出双语 ASS，再 burn。存在 review 文件时，未完成审核会
    阻止导出；只有明确需要草稿时才用 `--allow-unreviewed`。导出时可按场景选择
    `--ass-preset`。
13. 完成 QA：按 `references/workflows.zh-CN.md` 检查 status、translate check、
    输出 MP4 时长/大小，并截帧确认字幕渲染。

## Glossary 原则

Glossary 是活文档，用于 ASR 偏置、segment 纠错和 `translate check` 的术语一致性。
系列或专名密集内容应主动维护 glossary。

核心判断：

- ASR 错误或拼写变体：加入已有 term 的 `aliases`，或新增 canonical `source`
  并把错误形式放进 `aliases`。这类错误不能直接流到 `segment`，尤其双语硬字幕
  会把英文源文烧进成片。
- 确定的新关键术语：译名确定则加入 glossary；不确定先问用户或在 `note` 标记
  待确认。
- 一次性普通词/低置信候选：不加入 glossary，不阻塞流程。

详细格式、例子和主动审计流程见 `references/glossary.zh-CN.md`。

## 边界

- 第一阶段的浏览器登录只面向本地桌面环境，不要承诺 headless 服务器登录。
- 字体渲染因平台而异。当前 ASS 默认值按本地 macOS 渲染调校；商业分发需自行
  确认字体授权。
- OpenBBQ 不授予版权许可。翻译或烧录他人视频的字幕仍可能需要权利人许可。
