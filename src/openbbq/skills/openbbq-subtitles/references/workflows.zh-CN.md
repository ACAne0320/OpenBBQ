# OpenBBQ 单视频命令模板

## YouTube 输入

```bash
openbbq init --workspace workspaces/demo --glossary <name> '<youtube-url>'
openbbq auth status youtube
openbbq fetch --workspace workspaces/demo --auth youtube --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

如果没有 glossary，去掉 `--glossary <name>`；但转写后发现专名/术语时，应按
`glossary.zh-CN.md` 新建或绑定 glossary，再继续 `segment`。

如果 `auth status youtube` 未配置，先匿名 fetch；匿名失败且需要 cookies/bot check
时运行：

```bash
openbbq auth browser-login youtube
```

## 本地文件输入

```bash
openbbq init --workspace workspaces/demo --glossary <name> /path/to/video.mp4
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq glossary suggest --workspace workspaces/demo
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

本地文件跳过 `fetch`。

## 填写译文

大量 cue 先读取 20 条左右的有界上下文；不要把完整 worksheet 放进模型上下文：

```bash
openbbq --json translate batch zh --workspace workspaces/demo --from 1 --limit 20 --only-missing
```

然后写批次 JSON：

```json
{"1": "第一句译文", "2": "第二句译文"}
```

合并：

```bash
openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
```

可多批合并；后续批次不会影响未覆盖的译文。

## 检查、自审、导出、烧录

```bash
openbbq translate check zh --workspace workspaces/demo
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub --output out/zh.ass
openbbq burn --workspace workspaces/demo --subtitle out/zh.ass --output out/zh-burned.mp4
```

`translate check` 的 `missing`、`over_budget`、`zero_budget`、`term_issues`、
`quality_issues` 必须清零且 `ready` 为 `true` 后再导出。

导出前做一次 agent 翻译质量自审，避免烧录后才发现问题。最低要求：

- 对照 `translation.zh.json` 的 source/target，抽查或通读完整 worksheet。
- 主动修正误译、漏译、过度意译、中文不自然、语气不符、上下文承接断裂。
- 检查专名/术语是否前后一致；双语输出时检查英文 source 行与中文 target 是否
  指向同一含义。
- 修订只通过 Edit 工具或 `{id: target}` 批次 JSON + `translate apply` 完成。
- 自审修订后重新跑 `openbbq translate check zh --workspace workspaces/demo`；
  仍要保持 `missing`、`over_budget`、`term_issues` 清零。

只有通过机械检查和质量自审后，才进入 `export` / `burn`。

## 完成 QA

```bash
openbbq --json status --workspace workspaces/demo
openbbq translate check zh --workspace workspaces/demo
ffprobe -v error -show_entries format=duration,size -of json workspaces/demo/out/zh-burned.mp4
ffmpeg -y -ss 60 -i workspaces/demo/out/zh-burned.mp4 -frames:v 1 workspaces/demo/qa-frame-60s.png
```

确认：

- manifest 相关 stage 全部完成，没有 failed/stale/running。
- `translate check` 返回 `ready: true`；最终流程没有使用
  `--allow-quality-warnings` 或 `burn --allow-stale`。
- 输出 MP4 非空，时长与源视频一致。
- 截帧里字幕已渲染、位置正常；双语输出时两行都可读。
