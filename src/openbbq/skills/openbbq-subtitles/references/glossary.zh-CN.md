# Glossary 参考

默认 agent 工作流会学习可复用术语，但不会因此在 happy path 中增加一个选择步骤。

## 默认行为

- 用户显式传入的 `--glossary <name>` 始终优先。
- URL 输入完成 fetch、取得作者元数据后，OpenBBQ 会绑定一个稳定的作者+目标语言
  glossary；同一作者、同一目标语言之后的视频会复用它，不会把不同语言的译名混在
  单一 `target` 字段中。
- 每个非删除型 `source_fix` 都会成为 workspace glossary candidate。agent 只需填写
  `reusable: true/false`；OpenBBQ 自动把可复用 candidate 提升到 overlay。
  `glossary_updates` 只用于没有对应 source correction 的新术语。
- segment 和 translate 会立即使用 base glossary 与 overlay 的合并结果；极少数
  触发 `review_source` 的情况也使用同一合并结果。
- `agent finish` 成功后才发布无冲突的 reusable 条目。冲突或权限失败不会阻塞视频
  交付；overlay 会保留，并返回可重试命令。

只有当某个错误形式在之后的同类视频中仍应稳定映射到同一 canonical term 时，才把它
记录为 reusable alias。普通词和依赖上下文的单次错误应使用 cue/segment scoped
`source_fix` 并标记 `reusable: false`，不要写进全局 glossary。

常用字段：

- `source`：规范的原文拼写。
- `target`：已知时使用的固定译名。
- `aliases`：可复用的 ASR 拼写或误识别形式。
- `note`：帮助消歧的上下文。
- `keep: true`：翻译时保留原文形式。

## 专家命令

以下命令只用于可选的检查和维护，不属于默认 one-shot 流程：

```bash
openbbq --json glossary list
openbbq --json glossary show <name>
openbbq glossary new <name> --context "<domain context>"
openbbq glossary use <name> --workspace <workspace>
openbbq glossary apply --workspace <workspace> <patch.json>
```

请应用有明确边界的 JSON patch，不要直接编辑全局 glossary 文件：

```json
{
  "terms": [
    {
      "source": "Codex",
      "target": "Codex",
      "aliases": ["Code X"],
      "note": "OpenAI coding agent",
      "keep": true
    }
  ]
}
```

该命令是原子的：source 或 alias 归属冲突时会拒绝整个 patch，不会覆盖已有条目。
