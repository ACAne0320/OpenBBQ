# OpenBBQ 单视频命令模板

## YouTube 输入

```bash
openbbq init --workspace workspaces/demo --glossary <name> '<youtube-url>'
openbbq auth status youtube
openbbq fetch --workspace workspaces/demo --auth youtube
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

先读取 `workspaces/demo/translation.zh.json`，看 source、`budget.max_chars` 和
worksheet 内嵌 glossary 映射。译文要控制在预算内。

少量 cue（约 30 条以内）可直接用 Edit 工具改 `target` 字段。大量 cue 写批次
JSON：

```json
{"1": "第一句译文", "2": "第二句译文"}
```

合并：

```bash
openbbq translate apply zh --workspace workspaces/demo targets.batch1.json
```

可多批合并；后续批次不会影响未覆盖的译文。

## 检查、导出、烧录

```bash
openbbq translate check zh --workspace workspaces/demo
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub --output out/zh.ass
openbbq burn --workspace workspaces/demo --subtitle out/zh.ass --output out/zh-burned.mp4
```

`translate check` 的 `missing`、`over_budget`、`term_issues` 必须清零后再导出。

## 完成 QA

```bash
openbbq --json status --workspace workspaces/demo
openbbq translate check zh --workspace workspaces/demo
ffprobe -v error -show_entries format=duration,size -of json workspaces/demo/out/zh-burned.mp4
ffmpeg -y -ss 60 -i workspaces/demo/out/zh-burned.mp4 -frames:v 1 workspaces/demo/qa-frame-60s.png
```

确认：

- manifest 相关 stage 全部完成，没有 failed/stale/running。
- `missing`、`over_budget`、`term_issues` 全清零。
- 输出 MP4 非空，时长与源视频一致。
- 截帧里字幕已渲染、位置正常；双语输出时两行都可读。
