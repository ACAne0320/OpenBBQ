import { ArrowRight } from "lucide-react";

type Locale = "en" | "zh";

const copy = {
  en: {
    eyebrow: "Open-source video translation",
    title: "Turn video into bilingual subtitles.",
    lede:
      "A resumable command-line workflow for transcription, translation, subtitle export, and hard-subtitle burning.",
    start: "Getting started",
    github: "View on GitHub",
    install: "Install with uv",
    workflow: "Workflow",
    workspace: "Workspace output",
    inspectEyebrow: "Inspectable by default",
    inspectTitle: "Each stage leaves an artifact you can review.",
    reference: "CLI reference",
    stages: [
      ["Source", "Fetch a URL or use a local video.", "media/audio.16k.wav"],
      ["Transcribe", "Create a timed source transcript.", "transcript.json"],
      ["Translate", "Review an editable target worksheet.", "translation.zh.json"],
      ["Export", "Write subtitles or a burned video.", "out/zh.ass"],
    ],
    agentsEyebrow: "Built for agents and people",
    agentsTitle: "Automate the routine. Keep every artifact editable.",
    agentsBody:
      "Commands are composable, progress is recorded in the workspace, and interrupted stages can be resumed without hiding the intermediate files.",
    agentsLink: "See the workflow model",
  },
  zh: {
    eyebrow: "开源视频翻译工具",
    title: "把视频制作成双语字幕。",
    lede: "一套可恢复的命令行工作流，覆盖转录、翻译、字幕导出与硬字幕烧录。",
    start: "开始使用",
    github: "在 GitHub 查看",
    install: "使用 uv 安装",
    workflow: "工作流",
    workspace: "Workspace 产物",
    inspectEyebrow: "默认可检查",
    inspectTitle: "每个阶段都会留下可供检查的产物。",
    reference: "CLI 参考",
    stages: [
      ["输入", "下载在线视频或使用本地视频。", "media/audio.16k.wav"],
      ["转录", "生成带时间轴的原文转录。", "transcript.json"],
      ["翻译", "检查并编辑目标语言工作表。", "translation.zh.json"],
      ["导出", "输出字幕文件或烧录后的视频。", "out/zh.ass"],
    ],
    agentsEyebrow: "为 Agent 和人而设计",
    agentsTitle: "让自动化处理重复工作，让产物始终可编辑。",
    agentsBody:
      "命令可以自由组合，进度会记录在 workspace 中；中断后可以继续执行，同时保留所有中间文件。",
    agentsLink: "了解工作流模型",
  },
} as const;

const commands = [
  "openbbq init --workspace workspaces/demo ./video.mp4",
  "openbbq transcribe --workspace workspaces/demo",
  "openbbq segment --workspace workspaces/demo",
  "openbbq translate init --workspace workspaces/demo --target-language zh",
  "openbbq export --workspace workspaces/demo --target-language zh --format ass",
];

const artifacts = [
  "manifest.json",
  "media/audio.16k.wav",
  "transcript.json",
  "cues.json",
  "translation.zh.json",
  "out/zh.ass",
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
            <code>uv tool install 'openbbq[whispercpp]'</code>
          </section>
          <section aria-labelledby="workflow-heading">
            <div className="bbq-workbench-heading" id="workflow-heading">{text.workflow}</div>
            <ol className="bbq-command-list">
              {commands.map((command) => <li key={command}><code>{command}</code></li>)}
            </ol>
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
