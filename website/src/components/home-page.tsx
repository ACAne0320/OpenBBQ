import {
  ArrowRight,
  Bot,
  Braces,
  Captions,
  Flame,
  Gauge,
  Languages,
  ListChecks,
  Mic,
  MonitorCheck,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";

type Locale = "en" | "zh";
type TermLine = { kind: "cmd" | "ok" | "done"; text: string };

const copy = {
  en: {
    eyebrow: "Open-source · Driven by AI agents",
    titleA: "Raw in.",
    titleB: "Cooked out.",
    lede:
      "Fansub crews call an untranslated video raw meat, and a finished subtitled release cooked meat. OpenBBQ takes care of the work between them. From your terminal, an AI agent can download a video, transcribe it, translate and check every line, then burn the subtitles into the picture.",
    start: "Start cooking",
    github: "View on GitHub",
    terminalTitle: "openbbq - zsh",
    terminal: [
      { kind: "cmd", text: "openbbq init --workspace demo ./pey-talks-anime.mp4" },
      { kind: "ok", text: "workspace ready · manifest.json" },
      { kind: "cmd", text: "openbbq transcribe --workspace demo --model large-v3-turbo" },
      { kind: "ok", text: "318 lines · transcript.json" },
      { kind: "cmd", text: "openbbq asr check --workspace demo" },
      { kind: "ok", text: "ready: true" },
      { kind: "cmd", text: "openbbq translate init zh --workspace demo" },
      { kind: "cmd", text: "openbbq translate check zh --workspace demo" },
      { kind: "ok", text: "ready: true" },
      { kind: "cmd", text: "openbbq export --workspace demo --to zh --mode bilingual --format ass" },
      { kind: "ok", text: "out/zh.ass" },
      { kind: "cmd", text: "openbbq burn --workspace demo" },
      { kind: "ok", text: "out/zh-burned.mp4" },
      { kind: "cmd", text: "openbbq delivery check --workspace demo --to zh" },
      { kind: "done", text: "ready: true · cooked 熟肉出锅" },
    ] satisfies TermLine[],
    raw: "Raw 生肉",
    cooked: "Cooked 熟肉",
    workflowTitle: "From source video to finished subtitles",
    stages: [
      ["Fetch", "get the video"],
      ["Transcribe", "write down every word"],
      ["Segment", "cut it into lines"],
      ["Translate", "into your language"],
      ["Review", "check every line"],
      ["Export", "make subtitle files"],
      ["Burn", "into the picture"],
    ],
    gatesEyebrow: "Quality gates",
    gatesTitle: "Check every step.",
    gatesLead:
      "OpenBBQ checks each stage before the next one starts. If it finds a problem, it shows you what needs a decision and waits.",
    gates: [
      [
        "Listening check",
        "openbbq asr check",
        "Words the recognizer may have misheard are flagged one by one. Confirm or correct each one and record why before translation starts.",
      ],
      [
        "Translation check",
        "openbbq translate check",
        "Missing lines, lines too long to read, and inconsistent names are caught automatically and stop the next step.",
      ],
      [
        "Line-by-line review",
        "openbbq translate audit",
        "Every line is re-read together with its context. Keeping or changing it is a decision, and the reason is recorded.",
      ],
      [
        "Final check",
        "openbbq delivery check",
        "One last verification that the subtitles and the video are exactly what was reviewed. Only then does OpenBBQ answer ready: true.",
      ],
    ],
    reference: "CLI reference",
    agentsEyebrow: "Agent-native",
    agentsTitle: "Give the routine work to an agent.",
    agentsLead:
      "Tell Claude Code or Codex what you want to make. OpenBBQ gives the agent the commands, structured results, and checkpoints it needs to run the job.",
    agents: [
      [
        "Structured results",
        "Commands can return JSON, so agents read results without scraping terminal output.",
      ],
      [
        "Teach it once",
        "openbbq skill install gives your assistant the workflow and command patterns it needs.",
      ],
      [
        "Resume later",
        "Each stage writes its result to the workspace. Stop today and continue from the same files tomorrow.",
      ],
      [
        "Work in small batches",
        "Long transcripts are read and updated in bounded batches, which keeps the context focused and the work easy to review.",
      ],
    ],
    agentsLink: "Read the agent guide",
    craftEyebrow: "The fansub craft",
    craftTitle: "The agent handles the routine. You make the final call.",
    reviewTitle: "See it before you serve it",
    reviewBody:
      "openbbq review opens a local editor with the video, its sound waveform, and the subtitles side by side. Edits save automatically, with split, merge, and undo. Nothing exports until every line is confirmed.",
    reviewCmd: "openbbq review --workspace demo --to zh",
    presetsTitle: "Looks like a fansub made it",
    presetsBody:
      "Ready-made bilingual subtitle styles for landscape and vertical video, tidy line breaks, and a term list that keeps names consistent across episodes.",
    presetsCmd: "openbbq export --workspace demo --to zh --ass-preset fansub",
    presets: ["default", "fansub", "fansub-compact", "mobile"],
    ctaTitle: "Fire up the grill.",
    ctaBody:
      "Requires Python 3.12+, uv, and FFmpeg. OpenBBQ is still pre-alpha, so review the output before publishing.",
    ctaInstall: "uv tool install 'openbbq[whispercpp]'",
  },
  zh: {
    eyebrow: "开源 · 由 AI Agent 驱动",
    titleA: "生肉进，",
    titleB: "熟肉出。",
    lede:
      "字幕组把未翻译的视频叫“生肉”，把译制完成的版本叫“熟肉”。OpenBBQ 负责中间的整套工作。你只要在终端里说明目标，AI Agent 就能下载视频、听写、逐句翻译和校对，最后把字幕烧进画面。",
    start: "开始烤肉",
    github: "在 GitHub 查看",
    terminalTitle: "openbbq - zsh",
    terminal: [
      { kind: "cmd", text: "openbbq init --workspace demo ./pey-talks-anime.mp4" },
      { kind: "ok", text: "workspace 就绪 · manifest.json" },
      { kind: "cmd", text: "openbbq transcribe --workspace demo --model large-v3-turbo" },
      { kind: "ok", text: "318 句 · transcript.json" },
      { kind: "cmd", text: "openbbq asr check --workspace demo" },
      { kind: "ok", text: "ready: true" },
      { kind: "cmd", text: "openbbq translate init zh --workspace demo" },
      { kind: "cmd", text: "openbbq translate check zh --workspace demo" },
      { kind: "ok", text: "ready: true" },
      { kind: "cmd", text: "openbbq export --workspace demo --to zh --mode bilingual --format ass" },
      { kind: "ok", text: "out/zh.ass" },
      { kind: "cmd", text: "openbbq burn --workspace demo" },
      { kind: "ok", text: "out/zh-burned.mp4" },
      { kind: "cmd", text: "openbbq delivery check --workspace demo --to zh" },
      { kind: "done", text: "ready: true · 熟肉出锅" },
    ] satisfies TermLine[],
    raw: "生肉 Raw",
    cooked: "熟肉 Cooked",
    workflowTitle: "从原始视频到成品字幕",
    stages: [
      ["下载", "拿到视频文件"],
      ["听写", "记下每句话"],
      ["分段", "切成一行行字幕"],
      ["翻译", "译成目标语言"],
      ["校对", "逐句检查确认"],
      ["导出", "生成字幕文件"],
      ["烧录", "把字幕压进画面"],
    ],
    gatesEyebrow: "质量关卡",
    gatesTitle: "每一步，都检查清楚。",
    gatesLead:
      "进入下一阶段之前，OpenBBQ 会先检查当前结果。发现问题时，它会说明哪里需要你做决定，然后停下来等你。",
    gates: [
      [
        "听写检查",
        "openbbq asr check",
        "AI 没听准的词会被逐个挑出来。确认或改正、写明理由之后，才能开始翻译。",
      ],
      [
        "翻译检查",
        "openbbq translate check",
        "漏译、长到读不完、名词前后不一致，这些问题都会在这一步被自动拦下。",
      ],
      [
        "逐句审校",
        "openbbq translate audit",
        "每一句都结合上下文重新读一遍。保留还是修改都要做出决定，理由会被记下来。",
      ],
      [
        "出锅验收",
        "openbbq delivery check",
        "最后核对一次：字幕和视频确实是校对过的版本。全部通过，OpenBBQ 才会回答 ready: true。",
      ],
    ],
    reference: "CLI 参考",
    agentsEyebrow: "Agent 原生",
    agentsTitle: "重复工作交给 Agent。",
    agentsLead:
      "告诉 Claude Code 或 Codex 你想做什么。OpenBBQ 会给它所需的命令、结构化结果和检查点，让它把任务跑完。",
    agents: [
      [
        "结果有固定格式",
        "命令可以返回 JSON，Agent 不用读取终端截图，也不用猜结果。",
      ],
      [
        "只教一次",
        "openbbq skill install 会把工作流和常用命令交给你的 AI 助手。",
      ],
      [
        "以后接着做",
        "每个阶段都会把结果写进工作区。今天停下，明天可以从同一批文件继续。",
      ],
      [
        "分小批处理",
        "长听写稿会分批读取和更新，既控制上下文长度，也方便逐批检查。",
      ],
    ],
    agentsLink: "阅读 Agent 指南",
    craftEyebrow: "字幕组的手艺",
    craftTitle: "重复工作交给 Agent，最后一关由你来过。",
    reviewTitle: "上桌前先看一看",
    reviewBody:
      "openbbq review 会打开一个本地编辑器：视频、声音波形和字幕同屏对照。改动自动保存，可以拆分、合并、撤销。每一句都确认无误后，才能导出。",
    reviewCmd: "openbbq review --workspace demo --to zh",
    presetsTitle: "看起来就像字幕组出品",
    presetsBody:
      "现成的双语字幕样式，横屏竖屏都已调好；换行整齐，还有术语表让专有名词在每一集里都译得一致。",
    presetsCmd: "openbbq export --workspace demo --to zh --ass-preset fansub",
    presets: ["default", "fansub", "fansub-compact", "mobile"],
    ctaTitle: "开火。",
    ctaBody: "需要 Python 3.12+、uv 和 FFmpeg。OpenBBQ 仍处于 pre-alpha，发布前请检查输出。",
    ctaInstall: "uv tool install 'openbbq[whispercpp]'",
  },
} as const;

const gateIcons = [Mic, Languages, ListChecks, ShieldCheck];
const agentIcons = [Braces, Bot, RefreshCw, Gauge];

function Terminal({ title, lines }: { title: string; lines: readonly TermLine[] }) {
  return (
    <div className="bbq-term" role="img" aria-label="OpenBBQ terminal session">
      <div className="bbq-term-bar">
        <span className="bbq-term-dot bbq-term-dot-red" />
        <span className="bbq-term-dot" />
        <span className="bbq-term-dot" />
        <span className="bbq-term-title">{title}</span>
      </div>
      <div className="bbq-term-body">
        {lines.map((line, i) =>
          line.kind === "cmd" ? (
            <div className="bbq-term-line" key={i}>
              <span className="bbq-term-prompt">$</span> {line.text}
            </div>
          ) : line.kind === "done" ? (
            <div className="bbq-term-line bbq-term-done" key={i}>
              <Flame aria-hidden="true" size={13} /> {line.text}
            </div>
          ) : (
            <div className="bbq-term-line bbq-term-ok" key={i}>
              <span className="bbq-term-check">✓</span> {line.text}
            </div>
          ),
        )}
      </div>
    </div>
  );
}

function SectionHead({
  eyebrow,
  title,
  lead,
  link,
}: {
  eyebrow: string;
  title: string;
  lead?: string;
  link?: ReactNode;
}) {
  return (
    <div className="bbq-section-head">
      <div>
        <p className="bbq-eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        {lead ? <p className="bbq-section-lead">{lead}</p> : null}
      </div>
      {link}
    </div>
  );
}

export function HomePage({ locale }: { locale: Locale }) {
  const text = copy[locale];
  const prefix = `/${locale}`;

  return (
    <main className="bbq-home">
      <section className="bbq-hero bbq-shell">
        <div className="bbq-hero-copy">
          <p className="bbq-eyebrow">{text.eyebrow}</p>
          <h1>
            {text.titleA}
            <br />
            <span className="bbq-heat">{text.titleB}</span>
          </h1>
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
        <Terminal title={text.terminalTitle} lines={text.terminal} />
      </section>

      <section className="bbq-line-section">
        <div className="bbq-shell">
          <h2 className="sr-only">{text.workflowTitle}</h2>
          <div className="bbq-line-head">
            <span className="bbq-line-label">{text.raw}</span>
            <span className="bbq-line-track" />
            <span className="bbq-line-label bbq-line-label-hot">
              <Flame aria-hidden="true" size={14} /> {text.cooked}
            </span>
          </div>
          <ol className="bbq-line-stages">
            {text.stages.map(([name, caption], i) => (
              <li key={name} className={`bbq-stage bbq-stage-${i + 1}`}>
                <span className="bbq-stage-dot" />
                <span className="bbq-stage-index">{String(i + 1).padStart(2, "0")}</span>
                <h3>{name}</h3>
                <span className="bbq-stage-cap">{caption}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="bbq-section">
        <div className="bbq-shell">
          <SectionHead
            eyebrow={text.gatesEyebrow}
            title={text.gatesTitle}
            lead={text.gatesLead}
            link={
              <a className="bbq-text-link" href={`${prefix}/docs/reference/cli`}>
                {text.reference} <ArrowRight aria-hidden="true" size={17} />
              </a>
            }
          />
          <div className="bbq-gate-grid">
            {text.gates.map(([title, cmd, body], i) => {
              const Icon = gateIcons[i]!;
              return (
                <article key={title}>
                  <div className="bbq-gate-icon">
                    <Icon aria-hidden="true" size={17} />
                  </div>
                  <h3>{title}</h3>
                  <code className="bbq-gate-cmd">{cmd}</code>
                  <p>{body}</p>
                  <span className="bbq-ready">→ ready: true</span>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="bbq-section">
        <div className="bbq-shell bbq-agents">
          <div>
            <p className="bbq-eyebrow">{text.agentsEyebrow}</p>
            <h2>{text.agentsTitle}</h2>
            <p className="bbq-section-lead">{text.agentsLead}</p>
            <div className="bbq-feature-list">
              {text.agents.map(([title, body], i) => {
                const Icon = agentIcons[i]!;
                return (
                  <div key={title}>
                    <h3>
                      <Icon aria-hidden="true" size={16} /> {title}
                    </h3>
                    <p>{body}</p>
                  </div>
                );
              })}
            </div>
            <a className="bbq-text-link" href={`${prefix}/docs/guides/agents`}>
              {text.agentsLink} <ArrowRight aria-hidden="true" size={17} />
            </a>
          </div>
          <div className="bbq-term">
            <div className="bbq-term-bar">
              <span className="bbq-term-dot bbq-term-dot-red" />
              <span className="bbq-term-dot" />
              <span className="bbq-term-dot" />
              <span className="bbq-term-title">agent - zsh</span>
            </div>
            <div className="bbq-term-body">
              <div className="bbq-term-line">
                <span className="bbq-term-prompt">$</span> openbbq skill install --agent claude
              </div>
              <div className="bbq-term-line bbq-term-ok">
                <span className="bbq-term-check">✓</span> ~/.claude/skills/openbbq-subtitles/
              </div>
              <div className="bbq-term-line bbq-term-gap">
                <span className="bbq-term-prompt">$</span> openbbq --json translate check zh --workspace demo
              </div>
              <div className="bbq-term-line bbq-term-ok">{"{ \"ready\": true }"}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="bbq-section">
        <div className="bbq-shell">
          <SectionHead eyebrow={text.craftEyebrow} title={text.craftTitle} />
          <div className="bbq-craft-grid">
            <article>
              <div className="bbq-gate-icon">
                <MonitorCheck aria-hidden="true" size={17} />
              </div>
              <h3>{text.reviewTitle}</h3>
              <p>{text.reviewBody}</p>
              <code className="bbq-cmdbox">{text.reviewCmd}</code>
            </article>
            <article>
              <div className="bbq-gate-icon">
                <Captions aria-hidden="true" size={17} />
              </div>
              <h3>{text.presetsTitle}</h3>
              <p>{text.presetsBody}</p>
              <code className="bbq-cmdbox">{text.presetsCmd}</code>
              <div className="bbq-chips">
                {text.presets.map((preset) => (
                  <span className="bbq-chip" key={preset}>
                    {preset}
                  </span>
                ))}
              </div>
            </article>
          </div>
        </div>
      </section>

      <section className="bbq-cta bbq-shell">
        <h2>
          {text.ctaTitle} <Flame aria-hidden="true" className="bbq-cta-flame" size={36} />
        </h2>
        <p>{text.ctaBody}</p>
        <div className="bbq-install">
          <span className="bbq-term-prompt">$</span> <code>{text.ctaInstall}</code>
        </div>
        <div className="bbq-actions">
          <a className="bbq-button bbq-button-primary" href={`${prefix}/docs/getting-started`}>
            {text.start} <ArrowRight aria-hidden="true" size={18} />
          </a>
          <a className="bbq-text-link" href="https://github.com/ACAne0320/OpenBBQ">
            {text.github} <ArrowRight aria-hidden="true" size={17} />
          </a>
        </div>
      </section>
    </main>
  );
}
