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

## 文件格式

维护 `~/.openbbq/glossaries/<name>.json`：

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
```

然后主动审计候选和转写文本，不要只把候选当备注。双语 ASS/硬字幕尤其要审计
source 行，因为英文源文也会出现在成片里；中文译文正确不代表成片正确。

把候选分三类：

1. **ASR 错误或拼写变体**
   已知专名被听错、角色名拼错、作品名粘连/拆错。把错误形式加入既有 term 的
   `aliases`，或新增 canonical `source` term 并把错误形式放入 `aliases`。
   这类错误不应继续流到 `segment`。
2. **确定的新关键术语**
   同系列会反复出现的人名、地名、组织、技能、作品名、品牌等。译名确定就加入
   glossary；不确定就问用户或在 `note` 标记待确认。
3. **一次性普通词/低置信候选**
   不加入 glossary；可在回复或工作备注中记录，但不要阻塞流程。

更新 glossary 后必须在 `segment` 前完成。如果 `segment` 已跑过，更新后重跑：

```bash
openbbq segment --workspace workspaces/demo
openbbq translate init zh --workspace workspaces/demo
```

## 检查点

- `translate check` 的 `term_issues` 必须修完。
- 通过 `translate check` 不代表 source cue 没有 ASR 专名错误。
- 双语输出前抽查 `cues.json` 或 `translation.<lang>.json` 的 source 行。
