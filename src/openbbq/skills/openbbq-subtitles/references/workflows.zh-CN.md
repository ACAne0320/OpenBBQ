# OpenBBQ 单视频命令模板

## YouTube 输入

```bash
openbbq init --workspace workspaces/demo --glossary <name> '<youtube-url>'
openbbq auth status youtube
openbbq fetch --workspace workspaces/demo --auth youtube --max-height 1080
openbbq extract-audio --workspace workspaces/demo
openbbq transcribe --workspace workspaces/demo --model large-v3-turbo --language en --gpu
openbbq --json asr check --workspace workspaces/demo
openbbq glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --limit 20
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo --max-lines 2
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
openbbq --json asr check --workspace workspaces/demo
openbbq glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --limit 20
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

本地文件跳过 `fetch`。

## 处理 ASR 不确定词

`asr check` 未 ready 时，读取有界批次：

```bash
openbbq --json asr batch --workspace workspaces/demo --limit 20 --only-unresolved
```

核对上下文后写决策 JSON；接受和替换都必须给具体理由：

```json
{
  "s3:w8": {"action": "accept", "reason": "上下文与专名表都支持当前拼写"},
  "s7:w2": {
    "action": "replace",
    "find": "Sean Hongxiu",
    "replacement": "Sean Hongshu",
    "reason": "片尾署名和前文使用 Hongshu"
  },
  "a:repeat:205-221": {
    "action": "drop",
    "reason": "连续 17 段文字完全相同且跨越 30 秒，是解码器幻觉"
  }
}
```

```bash
openbbq asr apply --workspace workspaces/demo asr-decisions.json
```

重复 batch/apply，直到 `asr check` 返回 `ready: true`。不要为了通过门禁盲目接受。随后
翻完所有 `glossary audit` 页面；这一步由 Agent 结合语义发现与置信度无关的 ASR 错误。
没有 issue id 的上下文错误用 `asr amend`，安全且可复用的术语/alias 用
`glossary apply`，具体规则见 `glossary.zh-CN.md`。

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

## 检查、风险审计、导出、烧录

```bash
openbbq translate check zh --workspace workspaces/demo
openbbq --json translate audit zh --workspace workspaces/demo --coverage all --limit 20
openbbq export --workspace workspaces/demo --to zh --mode bilingual --format ass --ass-preset fansub --output out/zh.ass
openbbq burn --workspace workspaces/demo --subtitle out/zh.ass --output out/zh-burned.mp4
```

`translate check` 的 `missing`、`over_budget`、`zero_budget`、`term_issues`、
`quality_issues` 必须清零且 `ready` 为 `true` 后再导出。

`translate check` 是只读诊断，不会改 manifest 或让已经完成的 export/burn 失效。
风险审计返回未决 cue 时，写带理由的决策 JSON：

```json
{
  "43": {"action": "revise", "target": "Trash Taste 的 Garnt 也去过。", "reason": "补回节目名"},
  "92": {"action": "accept", "reason": "Mew 是画面和上下文一致的创作者名"}
}
```

```bash
openbbq translate audit-apply zh --workspace workspaces/demo translation-audit.json
```

重复 check/audit，直到两者都 `ready: true`。`coverage: all` 会风险优先返回，但全部
cue 都需要结合前后文审核；修改一条会使相邻上下文审核失效。最低要求：

- 对照 `translation.zh.json` 的 source/target，抽查或通读完整 worksheet。
- 主动修正误译、漏译、过度意译、中文不自然、语气不符、上下文承接断裂。
- 检查专名/术语是否前后一致；双语输出时检查英文 source 行与中文 target 是否
  指向同一含义。
- 修订只通过 Edit 工具或 `{id: target}` 批次 JSON + `translate apply` 完成。
- 修订后重新跑 `translate check` 和受影响的 audit；仍要保持所有门禁清零。

只有通过机械检查和质量自审后，才进入 `export` / `burn`。

## 完成交付检查

```bash
openbbq --json status --workspace workspaces/demo
openbbq translate check zh --workspace workspaces/demo
openbbq --json delivery check --workspace workspaces/demo --to zh
```

确认：

- manifest 相关 stage 全部完成，没有 failed/stale/running。
- `translate check` 返回 `ready: true`；最终流程没有使用
  `--allow-quality-warnings` 或 `burn --allow-stale`。
- `delivery check` 返回 `ready: true`，证明双语 ASS、源视频、烧录 MP4 和各阶段
  provenance 一致，并且 MP4 非空。

视觉 QA 不属于默认 one-shot 流程。只有用户明确要求且当前模型有图像能力时，才可选运行：

```bash
openbbq --json qa render --workspace workspaces/demo
openbbq --json qa check --workspace workspaces/demo
openbbq qa attest --workspace workspaces/demo --result pass --reason '<实际观察>'
```

视觉结果仅用于用户要求的人工诊断，不参与 `delivery check`，也不自动切换
`fansub-compact` 或触发重新烧录。没有图像输入能力时直接跳过即可。
