# OpenBBQ 字幕工作流（中文源文件）

> 本文件是 skill 的**源文件**，由维护者用中文撰写；英文版 `SKILL.md`
> （Claude Code 实际读取的文件）由 agent 基于本文生成。修改流程：
> 先改本文，再让 agent 重新生成并同步 `SKILL.md`。

当用户要求用 OpenBBQ 制作字幕、翻译字幕或产出带字幕的视频时使用本 skill。
优先使用 OpenBBQ 的原子 CLI 命令，不要写临时脚本。

## 操作守则

- 自动化一律用 `openbbq --json ...`，除非用户明确要看人类终端 UI。
  成功输出里的 `next` 字段是建议的下一步命令。
- 填译文只用两种方式：Edit 工具直接改 worksheet，或写批次文件走
  `openbbq translate apply`——**永远不要**写一次性脚本去编辑 worksheet。
- 中断后用 `openbbq --json status --workspace <ws>` 恢复。manifest 是各
  stage 完成/进行/失败状态的唯一事实来源：translate stage 带真实的
  `progress`（已填/总数）；`running` 且标了 `stale` 说明原进程大概率已死，
  可以安全重跑该 stage。重跑某个 stage 会自动把下游 stage 重置为 pending。
- zsh 等 shell 里 URL 参数要加引号：
  `openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'`。
- 长任务（`fetch`、`transcribe`、`burn`、`models pull`）把进度写进
  workspace（或 stderr）；前台命令之外要看进度就轮询
  `openbbq --json status --workspace <ws>`。
- 默认工作流不要烧 SRT：导出双语 ASS、烧 ASS。
- ASS preset 按目标画面选：密集下三分之一画面用 `compact`，更醒目的
  双语样式用 `fansub`，9:16 竖屏用 `mobile`。
- 用户说"处理清单里第一个/下一个"时：读 tracker，选中目标视频，创建或
  复用该视频的 workspace，然后跑完整工作流。

## 首次环境

```bash
openbbq doctor
```

正式转写用缓存好的 Whisper 模型（如 `large-v3-turbo`），缺就拉：

```bash
openbbq models pull large-v3-turbo
```

烧硬字幕要求 `doctor` 报告 ffmpeg 带 ASS/subtitles filter。macOS 上
Homebrew 的 `ffmpeg-full` 是带 libass 的实用构建。

## Glossary（系列/专名内容强烈建议）

Glossary 是**你和用户共同维护的活文档**，它同时作用于三个环节：ASR 偏置
（减少专名听错）、转写纠错（segment 时替换已知错听）、译名一致性检查
（`translate check` 的 `term_issues`）。系列视频、含人名/术语/品牌的内容
都应该建一个。

```bash
openbbq glossary new frieren --context "葬送的芙莉莲，奇幻动画"
openbbq glossary use frieren --workspace <ws>   # 绑定到 workspace
```

工作流：

1. 开工时和用户确认核心术语（人名、地名、专有名词的既定译名），写进
   glossary（`source` → `target`，或 `keep: true` 表示原文保留）。
2. `transcribe` 之后跑 `openbbq glossary suggest --workspace <ws>`：它会
   确定性地从转写里挖候选术语。**把候选拿给用户确认**后再回填 glossary——
   不要擅自定译名。
3. glossary 绑定后，`segment` / `translate init` 会自动使用；worksheet 里
   会内嵌 glossary 映射，翻译时照着译。
4. `translate check` 返回的 `term_issues`（`[{id, term, expected}]`）指出
   哪条译文丢了术语的既定译法——逐条修正后重新 apply。

## 完整 YouTube 工作流

YouTube URL 先走匿名 fetch。若因鉴权/机器人检查失败，在桌面 UI 上做一次
浏览器登录：

```bash
openbbq auth browser-login youtube
```

然后：

```bash
openbbq init --workspace workspaces/demo '<youtube-url>'
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

接着填译文。先 Read `workspaces/demo/translation.zh.json` 拿原文、每条的
字数预算（`budget.max_chars`，按目标语言 CPS 算）和 glossary 映射。译文要
**控制在预算内**（超了会在 check 里被 `over_budget` 点名）。禁止写辅助
脚本、禁止整文件重写 worksheet：

- 条数少（≤ ~30）：用 Edit 工具直接改 `target` 字段。
- 条数多：Write 一个或多个只含译文的批次文件——cue id → 译文的 JSON 对象：

  ```json
  {"1": "第一句译文", "2": "第二句译文"}
  ```

  逐批合并（可重复执行；后面的批次不会动前面的结果）：

  ```bash
  openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
  ```

全部填完后：

```bash
openbbq translate check zh --workspace workspaces/demo
```

check 返回三类信号，都要处理干净再导出：`missing`（漏译的 id）、
`over_budget`（超预算的 id，译得更精炼再 apply 覆盖）、`term_issues`
（丢了 glossary 译名的条目）。然后：

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --output out/zh.ass
openbbq burn --workspace workspaces/demo
```

密集画面或竖屏在 export 时带 preset：

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset compact
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

最终产物：

- `out/zh.ass`：双语 ASS 字幕。
- `out/zh-burned.mp4`：烧录硬字幕的 MP4。

## 本地文件工作流

本地视频跳过 `fetch`：

```bash
openbbq init --workspace workspaces/demo /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

之后的填译/检查/导出/烧录与 YouTube 工作流完全一致。

## 边界

- 第一阶段的浏览器登录只面向本地桌面环境，不要承诺 headless 服务器登录。
- 字体渲染因平台而异。当前 ASS 默认值按本地 macOS 渲染调校；商业分发需
  自行确认字体授权。
- OpenBBQ 不授予版权许可。翻译或烧录他人视频的字幕仍可能需要权利人许可。
