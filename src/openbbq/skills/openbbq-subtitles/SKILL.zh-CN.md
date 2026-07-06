# OpenBBQ 字幕工作流（中文源文件）

> 本文件是 skill 的**源文件**，由维护者用中文撰写；英文版 `SKILL.md`
> （Claude Code 实际读取的文件）由 agent 基于本文生成。修改流程：
> 先改本文，再让 agent 重新生成并同步 `SKILL.md`。

当用户要求用 OpenBBQ 制作字幕、翻译字幕或产出带字幕的视频时使用本 skill。
优先使用 OpenBBQ 的原子 CLI 命令，不要写临时脚本。

## 操作守则

- 自动化一律用 `openbbq --json ...`，除非用户明确要看人类终端 UI。
  成功输出里的 `next` 字段是建议的下一步命令，并不一定准确。
- 填译文只用两种方式：Edit 工具直接改 worksheet，或写批次文件走
  `openbbq translate apply`——**永远不要**写一次性脚本去编辑 worksheet。
- 中断后先用 `openbbq --json status --workspace <ws>` 查看 workspace 状态，
  再按 manifest 中的 failed/stale/pending stage 继续或重跑对应命令。
- manifest 是各 stage 完成/进行/失败状态的唯一事实来源：translate stage 带
  真实的 `progress`（已填/总数）；`running` 且标了 `stale` 说明原进程大概率
  已死，可以安全重跑该 stage。重跑某个 stage 会自动把下游 stage 重置为
  pending。
- zsh 等 shell 里 URL 参数要加引号：
  `openbbq init --workspace workspaces/demo 'https://www.youtube.com/watch?v=...'`。
- 长任务（`fetch`、`transcribe`、`burn`、`models pull`）把进度写进
  workspace（或 stderr）；前台命令之外要看进度就轮询
  `openbbq --json status --workspace <ws>`。
- 当 Agent 在沙箱环境中工作时，通常无法使用已有 GPU 进行 ASR transcribe 加速，
  可以询问用户是否允许在沙箱外运行 transcribe 命令。
- 默认制作双语视频字幕的工作流不要烧录 SRT；导出双语 ASS，并烧录 ASS。
- ASS preset 按目标画面选：更醒目的双语样式用 `fansub`，9:16 竖屏用
  `mobile`。

## 运行时预检

首次在一台机器上处理字幕，或命令报环境/依赖错误时，先跑：

```bash
openbbq doctor
```

正式转写前确认 Whisper 模型已缓存（如 `large-v3-turbo`）；缺就下载需要使用的模型：

```bash
openbbq models pull large-v3-turbo
```

烧硬字幕要求 `doctor` 报告 ffmpeg 带 ASS/subtitles filter。macOS 上
Homebrew 的 `ffmpeg-full` 是带 libass 的实用构建。

## Glossary（系列/专名内容强烈建议）

Glossary 是**你和用户共同维护的活文档**，它同时作用于三个环节：ASR 偏置
（减少专名听错）、转写纠错（segment 时替换已知错听）、译名一致性检查
（`translate check` 的 `term_issues`）。
系列视频、或含有人名、地名、术语、品牌的内容，都应该维护 glossary。如果
转写后才发现这类词，也要补进 glossary：本次可用于 segment/translate，未来
同类视频还能用于 ASR 偏置。

例如翻译《葬送的芙莉莲》系列动画时，先新建 `frieren`：

```bash
openbbq glossary new frieren --context "葬送的芙莉莲，奇幻动画"
```

`context` 是系列/主题的简要上下文。新建后维护
`~/.openbbq/glossaries/<name>.json` 里的 `terms`：

- `source`：标准原文，供 ASR bias、纠错和译名检查使用。
- `target`：既定译名。
- `aliases`：ASR 常见误听、拼写变体或别名，会在 segment 时纠回 `source`。
- `note`：给 agent 的消歧说明。
- `keep: true`：目标语言里保留原文，不翻译。

```text
~/.openbbq/glossaries/frieren.json
```

```json
{
  "schema": "openbbq/glossary@1",
  "name": "frieren",
  "context": "葬送的芙莉莲，奇幻动画",
  "terms": [
    {
      "source": "Frieren",
      "target": "芙莉莲",
      "aliases": ["Freiren", "Freeran", "Fearin", "Frieran", "Freerun", "Freer", "Furian"],
      "note": "series & title character"
    },
    {
      "source": "Himmel",
      "target": "辛美尔",
      "note": "hero of the party"
    },
    {
      "source": "Heiter",
      "target": "海塔",
      "aliases": ["Heider", "Haider", "Hyder"],
      "note": "priest"
    }
  ]
}
```

工作流：

1. 开工时和用户确认核心术语（人名、地名、专有名词的既定译名），写进
   glossary。不要擅自发明官方译名。
2. 已知 glossary 时，优先在 `init` 阶段用 `--glossary <name>` 绑定；如果
   workspace 已创建，再用 `openbbq glossary use <name> --workspace <ws>` 绑定。
3. `transcribe` 之后跑 `openbbq glossary suggest --workspace <ws>`：它会从转写
   里挖候选术语。**把候选拿给用户确认**后再回填 glossary。
4. glossary 在对应阶段开始前已绑定时，`transcribe` / `segment` /
   `translate init` 会自动使用；worksheet 里会内嵌 glossary 映射，翻译时照着译。
5. `translate check` 返回的 `term_issues`（`[{id, term, expected}]`）指出
   哪条译文丢了术语的既定译法——逐条修正后重新 apply。

## 完整 YouTube 工作流

YouTube URL 先走匿名 fetch。若因鉴权/机器人检查/需要 cookies 导致失败，需要
在桌面 UI 上做一次浏览器登录：

```bash
openbbq auth browser-login youtube
```

如果这是系列/专名内容，先准备或复用 glossary；没有就按 Glossary 章节新建并
维护 terms。已知 glossary 时，在 `init` 阶段绑定，让 ASR、segment 和
translate 都能使用它：

```bash
openbbq init --workspace workspaces/demo --glossary frieren '<youtube-url>'
openbbq fetch --workspace workspaces/demo
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

`glossary suggest` 之后，把候选术语拿给用户确认；如果确认了新术语，用 Edit
工具回填 glossary 文件，再继续 `segment`。如果一开始没有 glossary，但转写后
发现了专名/术语：先 `openbbq glossary new <name> --context "..."`，编辑
terms，再 `openbbq glossary use <name> --workspace workspaces/demo`，然后继续
`segment`。非系列/无专名内容可以跳过 glossary 相关命令。

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

export 时可以带 preset：

```bash
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset mobile
```

最终产物：

- `out/zh.ass`：双语 ASS 字幕。
- `out/zh-burned.mp4`：烧录硬字幕的 MP4。

## 本地文件工作流

本地视频跳过 `fetch`。如果已有 glossary，`init` 同样带 `--glossary <name>`：

```bash
openbbq init --workspace workspaces/demo --glossary frieren /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

没有 glossary 时，去掉 `--glossary frieren`，并按 YouTube 流程里的规则在
转写后决定是否新建/绑定。之后的填译/检查/导出/烧录与 YouTube 工作流完全一致。

## 边界

- 第一阶段的浏览器登录只面向本地桌面环境，不要承诺 headless 服务器登录。
- 字体渲染因平台而异。当前 ASS 默认值按本地 macOS 渲染调校；商业分发需
  自行确认字体授权。
- OpenBBQ 不授予版权许可。翻译或烧录他人视频的字幕仍可能需要权利人许可。
