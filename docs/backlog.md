# Backlog — 待优化清单

> 做完一条删一条。上一轮（2026-07-05 全量架构审查 + Codex 实现）的 23 条
> 已全部完成：原子写、manifest 生命周期/下游失效、export 完整性守门、
> 机态 CLI 契约、skill 打包与 `skill install`、glossary 工作流入 skill、
> over_budget/term_issues/next 反馈面、models pull 断点续传、DESIGN.md 刷新等。

## 遗留观察（暂不排期，出现痛点再做）

- **`translate apply` 并发无锁**：两个并发 apply 靠"最后写者赢"，单 agent
  串行使用没问题；如果将来出现多 agent 并发填同一 worksheet 的场景，再加
  锁文件或 batch 合并队列。
- **多语言共享单一 TRANSLATE stage**：manifest 只有一个 translate stage，
  多目标语言时 progress 反映"最近活动的那个语言"。多语言并行翻译成为常态
  时再考虑 per-lang stage 或 stage 内分桶。
- **`models pull --provider`**：模型目录已按 provider 建模，但 CLI 未暴露
  选择；等第二个 ASR 后端落地时一起做（见 memory）。
- **skill 双语同步**：`SKILL.zh-CN.md` 是源（维护者写中文），`SKILL.md`
  由 agent 生成。改中文后记得让 agent 重新生成英文并跑
  `openbbq skill install --force` 更新本机安装。
