import { ArrowRight } from "lucide-react";

type Locale = "en" | "zh";

const copy = {
  en: {
    eyebrow: "One prompt. Editable output.",
    title: "Turn video into bilingual subtitles.",
    lede:
      "Give your Agent a video. OpenBBQ keeps the workflow deterministic and returns an editable bilingual subtitle draft plus a hard-subtitled video.",
    start: "Getting started",
    github: "View on GitHub",
    install: "Install with uv",
    workflow: "Ask your Agent",
    prompt: "Make this video into a bilingual Chinese-English subtitled video: https://www.youtube.com/watch?v=...",
    workspace: "Workspace output",
    inspectEyebrow: "Inspectable by default",
    inspectTitle: "A useful first draft, with every artifact left editable.",
    reference: "CLI reference",
    stages: [
      ["Source", "Fetch a URL or use a local video.", "media/audio.16k.wav"],
      ["Transcribe", "Create and validate a timed source transcript.", "transcript.json"],
      ["Translate", "Process at most 20 aligned cues per Agent batch.", "translation.zh.json"],
      ["Deliver", "Export ASS and burn the video once.", "out/zh-burned.mp4"],
    ],
    agentsEyebrow: "Built for agents and people",
    agentsTitle: "Automate the routine. Keep every artifact editable.",
    agentsBody:
      "The Agent follows one authoritative next-action interface. Leases, hashes, timing checks, and artifact provenance keep the run resumable without hiding intermediate files.",
    agentsLink: "See the workflow model",
  },
  zh: {
    eyebrow: "一句提示词，产物始终可编辑",
    title: "把视频制作成双语字幕。",
    lede: "把视频交给 Agent。OpenBBQ 负责确定性工作流，返回可编辑的双语字幕底稿和烧录后的视频。",
    start: "开始使用",
    github: "在 GitHub 查看",
    install: "使用 uv 安装",
    workflow: "发送给 Agent",
    prompt: "帮我把这个视频制作成中英双语字幕视频：https://www.youtube.com/watch?v=...",
    workspace: "Workspace 产物",
    inspectEyebrow: "默认可检查",
    inspectTitle: "先得到可用底稿，并保留每一份可编辑产物。",
    reference: "CLI 参考",
    stages: [
      ["输入", "下载在线视频或使用本地视频。", "media/audio.16k.wav"],
      ["转录", "生成并校验带时间轴的原文转录。", "transcript.json"],
      ["翻译", "Agent 每批处理不超过 20 条对齐 cue。", "translation.zh.json"],
      ["交付", "只导出一次 ASS，并只烧录一次。", "out/zh-burned.mp4"],
    ],
    agentsEyebrow: "为 Agent 和人而设计",
    agentsTitle: "让自动化处理重复工作，让产物始终可编辑。",
    agentsBody:
      "Agent 只遵循一个权威的下一步接口。Lease、hash、时间轴检查和产物 provenance 让流程可恢复，同时保留所有中间文件。",
    agentsLink: "了解工作流模型",
  },
} as const;

const setupCommands = [
  "uv tool install 'openbbq[whispercpp]'",
  "openbbq skill install --agent all",
];

const artifacts = [
  "manifest.json",
  "media/audio.16k.wav",
  "transcript.json",
  "cues.json",
  "translation.zh.json",
  ".openbbq/agent-session.zh.json",
  ".openbbq/glossary-overlay.json",
  "out/zh.ass",
  "out/zh-burned.mp4",
];

export function HomePage({ locale }: { locale: Locale }) {
  const text = copy[locale];
  const prefix = `/${locale}`;

  return (
    <main className="bbq-home">
      <section className="bbq-hero bbq-shell">
        <div className="bbq-hero-copy">
          <p className="bbq-eyebrow">{text.eyebrow}</p>
          <h1>{text.title}</h1>
          <p className="bbq-lede">{text.lede}</p>
          <div className="bbq-actions">
            <a className="bbq-button bbq-button-primary" href={`${prefix}/docs/getting-started`}>
              {text.start} <ArrowRight aria-hidden="true" size={18} />
            </a>
            <a className="bbq-text-link" href="https://github.com/ACAne0320/OpenBBQ">
              {text.github} <ArrowRight aria-hidden="true" size={17} />
            </a>
          </div>
        </div>

        <div className="bbq-workbench">
          <section aria-labelledby="install-heading">
            <div className="bbq-workbench-heading" id="install-heading">{text.install}</div>
            <ol className="bbq-command-list">
              {setupCommands.map((command) => <li key={command}><code>{command}</code></li>)}
            </ol>
          </section>
          <section aria-labelledby="workflow-heading">
            <div className="bbq-workbench-heading" id="workflow-heading">{text.workflow}</div>
            <code>{text.prompt}</code>
          </section>
          <section aria-labelledby="workspace-heading">
            <div className="bbq-workbench-heading" id="workspace-heading">{text.workspace}</div>
            <ul className="bbq-file-tree">
              {artifacts.map((artifact) => <li key={artifact}><code>{artifact}</code></li>)}
            </ul>
          </section>
        </div>
      </section>

      <section className="bbq-band">
        <div className="bbq-shell">
          <div className="bbq-section-heading">
            <div>
              <p className="bbq-eyebrow">{text.inspectEyebrow}</p>
              <h2>{text.inspectTitle}</h2>
            </div>
            <a className="bbq-text-link" href={`${prefix}/docs/reference/cli`}>
              {text.reference} <ArrowRight aria-hidden="true" size={17} />
            </a>
          </div>
          <div className="bbq-stage-grid">
            {text.stages.map(([title, description, artifact]) => (
              <article key={title}>
                <h3>{title}</h3>
                <p>{description}</p>
                <code>{artifact}</code>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="bbq-shell bbq-agents">
        <div>
          <p className="bbq-eyebrow">{text.agentsEyebrow}</p>
          <h2>{text.agentsTitle}</h2>
        </div>
        <div>
          <p>{text.agentsBody}</p>
          <a className="bbq-text-link" href={`${prefix}/docs/getting-started/workflow`}>
            {text.agentsLink} <ArrowRight aria-hidden="true" size={17} />
          </a>
        </div>
      </section>
    </main>
  );
}
