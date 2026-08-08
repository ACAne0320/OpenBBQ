# 专家与兼容工作流

普通 one-shot 字幕任务应遵循 `SKILL.zh-CN.md` 中的 agent facade。本页只用于诊断、
恢复、认证，或用户明确要求的原子命令工作流。

## 执行环境

必须遵守 `agent next` 返回的机器可读 `execution` 策略。fetch、GPU 转录和 finish
通常需要在 host 环境执行。不要把要求 GPU 的转录静默替换成沙箱 CPU；只有声明的
host/GPU 路径确实失败，并且返回策略允许 fallback 时，才使用 CPU。
若长命令返回 process/session ID，应使用 harness 的进程续跑接口轮询该 ID，直到得到
exit code。不要把外层 tool/cell 的结束或暂时为空的 stdout 当作底层进程完成，也不要
在原 session 仍运行时重复执行命令。

YouTube 认证命令：

```bash
openbbq auth status youtube
openbbq auth browser-login youtube
```

除非 OpenBBQ 明确报告需要认证，否则先尝试匿名 fetch。

## 原子命令

兼容的底层流程仍然可用：

```bash
openbbq init --workspace <workspace> <input>
openbbq fetch --workspace <workspace>
openbbq extract-audio --workspace <workspace>
openbbq transcribe --workspace <workspace> --model large-v3-turbo --gpu
openbbq segment --workspace <workspace>
openbbq translate init zh --workspace <workspace>
openbbq --json translate batch zh --workspace <workspace> --limit 20 --only-missing
openbbq translate apply zh --workspace <workspace> <targets.json>
```

不要把这些写命令与活动 agent lease 混用。尤其是 `asr apply` 与 `asr amend` 会被
拒绝，必须先通过 `agent apply` 提交当前 lease 的 `review_source` 响应。

本地输入跳过 `fetch`。如果要导出一个明确未人工审校的底层 draft，必须显式表达这个
选择：

```bash
openbbq export --workspace <workspace> --to zh --mode bilingual --format ass --allow-unreviewed
openbbq burn --workspace <workspace> --subtitle out/zh.ass --output out/zh-burned.mp4
```

`--allow-unreviewed` 只会导出一个明确未认证的底稿，不会伪造交付证据。只有 facade
生成了 fresh agent-draft evidence，或存在完整且当前有效的人工 review 时，
`delivery check` 才会 ready。目标是 one-shot 底稿时应优先使用 facade。

## 专业编辑

默认结果是可编辑底稿。字幕编辑者可以在 OpenBBQ review UI 中审校，或将 ASS 导入
Aegisub/剪辑软件。只要存在完整且当前有效的人工 review，它就是最高权威；agent
facade 不得覆盖这些译文，也不得强制再次语义审查。

把工作区交给人工审校前，agent 可以预先播种建议：运行
`openbbq review --prepare --workspace <workspace> --to zh` 获取分析 JSON（rule issues
已算好，专注语义疑点），按 `response_schema` 写出响应后运行
`openbbq review --prepare --apply response.json --workspace <workspace> --to zh`，
再启动 `openbbq review`。审校者打开的工作台已带可接受/拒绝的建议。

视觉 QA 和 `fansub-compact` 永远不会自动运行。只有用户明确要求这些专家诊断或
preset 时才使用。
