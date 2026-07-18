# Glossary 主动工作流

Glossary 是你和用户共同维护的活文档，作用于三个环节：

- ASR 偏置：减少专名听错。
- segment 纠错：把已知错听或别名替换回 canonical source。
- 翻译检查：`translate check` 通过 `term_issues` 检查既定译名。

系列视频、动漫、游戏、课程、访谈、品牌内容，或任何专名密集内容，都应主动维护
glossary。如果转写后才发现术语，也要补进 glossary；本次可用于 segment/translate，
未来同类视频还能用于 ASR 偏置。

## 查找或创建

开工时先找可复用 glossary：

```bash
openbbq --json glossary list
openbbq --json glossary show <name>
```

如果已有同系列、同频道或同主题 glossary，优先在 `init` 阶段绑定：

```bash
openbbq init --workspace workspaces/demo --glossary frieren '<input>'
```

workspace 已创建时：

```bash
openbbq glossary use frieren --workspace workspaces/demo
```

没有合适 glossary 时，和用户确认核心术语后新建：

```bash
openbbq glossary new frieren --context "葬送的芙莉莲，奇幻动画"
```

不要擅自发明官方译名；不确定的译名先问用户，或在 `note` 里标记待确认。

## 安全维护

不要直接编辑 `~/.openbbq/glossaries/<name>.json`。先写一个有界 patch，再原子应用：

```json
{
  "terms": [
    {
      "source": "Andy Matuschak",
      "target": "安迪·马图沙克",
      "aliases": ["Annie Matushak"],
      "note": "研究者；根据上下文确认的 ASR 变体"
    }
  ]
}
```

```bash
openbbq glossary apply --workspace workspaces/demo glossary-terms.json
```

该命令新增 canonical term、合并既有 term 的新 alias，并保留 patch 中未提供的
target/note/keep。若同一 source 或 alias 被不同 term 占用，整批拒绝，不会留下半写状态。
成功更新会让当前 workspace 的 segment 及后续产物失效。
重复应用内容完全相同的 no-op patch 不会让产物失效。

存储字段如下：

- `source`：标准原文，供 ASR bias、纠错和译名检查使用。
- `target`：既定译名。
- `aliases`：ASR 常见误听、拼写变体或别名；segment 会纠回 `source`。
- `note`：给 agent 的消歧说明。
- `keep: true`：目标语言保留原文，不翻译。

```json
{
  "schema": "openbbq/glossary@1",
  "name": "frieren",
  "context": "葬送的芙莉莲，奇幻动画",
  "terms": [
    {
      "source": "Frieren",
      "target": "芙莉莲",
      "aliases": ["Freiren", "Freeran", "Fearin", "Frieran"],
      "note": "series & title character"
    },
    {
      "source": "Kraft",
      "target": "克拉夫特",
      "aliases": ["Craft"],
      "note": "monk; ASR may hear it as Craft"
    }
  ]
}
```

## Transcribe 后的主动审计

`transcribe` 后必须跑：

```bash
openbbq glossary suggest --workspace workspaces/demo
openbbq --json glossary audit --workspace workspaces/demo --offset 0 --limit 20
```

`suggest` 只负责提示优先级，不是完整性检查。必须翻完所有 `audit` 批次，高置信词所在
段也不能跳过。每项会给出已应用 ASR 决策的 source、变化前 raw source、前后段、词级
概率、同时间参考字幕（如有）和当前 glossary 命中。Agent 应根据语义、语法、主题、
专名和上下文自行判断；概率与参考字幕都只是证据，不是真值。

双语 ASS/硬字幕必须做这次全量 source 审计，因为原文会直接烧进成片；中文译文正确不
代表成片正确。沿返回的 `next_offset` 继续，直到 `remaining` 为 0。

把审计发现分四类：

1. **可复用的 ASR 错误或拼写变体**
   已知专名被听错、角色名拼错、作品名粘连/拆错。把错误形式加入既有 term 的
   `aliases`，或新增 canonical `source` term 并把错误形式放入 `aliases`。
   这类错误不应继续流到 `segment`。
2. **确定的新关键术语**
   同系列会反复出现的人名、地名、组织、技能、作品名、品牌等。译名确定就加入
   glossary；不确定就问用户或在 `note` 标记待确认。
3. **一次性或依赖上下文的 ASR 错误**
   不要把可能在别处成立的普通词做成危险的全局 alias。只记录本次精确修正：

   ```json
   {
     "amendments": [
       {
         "segment_id": 12,
         "find": "hot tick",
         "replacement": "hot take",
         "reason": "结合前后句可知这里使用的是固定表达 hot take。"
       }
     ]
   }
   ```

   ```bash
   openbbq asr amend --workspace workspaces/demo asr-amendments.json
   ```

4. **正确的一次性普通词/无关候选**
   不加入 glossary。不能只凭概率决定 accept 或 replace。

更新 glossary 后必须在 `segment` 前完成。如果 `segment` 已跑过，更新后重跑：

```bash
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo --max-lines 2
```

## 检查点

- 检查 `segment --json`：`glossary_matched_terms` 表示实际出现的 canonical term，
  `glossary_aliases_applied` 证明已知 ASR 变体确实被纠正；
  `glossary_no_effect: true` 表示虽然绑定了 glossary，但没有任何命中或纠错。
  “已绑定”不等于“已使用”。
- `translate check` 的 `term_issues` 必须修完。
- 通过 `translate check` 不代表 source cue 没有 ASR 专名错误。
- 双语输出前抽查 `cues.json` 或 `translation.<lang>.json` 的 source 行。
