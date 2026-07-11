import { ArrowRight, Captions, Languages, TerminalSquare } from "lucide-react";

type Locale = "en" | "zh";

const copy = {
  en: {
    kicker: "Agent-native video translation",
    title: "Translate video without leaving your terminal.",
    lede:
      "OpenBBQ turns video into polished bilingual subtitles through one inspectable command-line workflow.",
    docs: "Read the docs",
    showcase: "View showcase",
    workflow: "A workflow you can inspect",
    features: [
      ["Transcribe", "Create timestamped source subtitles from local audio or video."],
      ["Translate", "Preserve meaning and terminology with an editable glossary."],
      ["Publish", "Export bilingual subtitle files or burn styled ASS subtitles into video."],
    ],
    source: "AI agents can now operate the same workflow through a reusable skill.",
  },
  zh: {
    kicker: "面向 Agent 的视频翻译工具",
    title: "在终端里完成视频翻译。",
    lede: "OpenBBQ 用一条可检查、可恢复的命令行工作流，把视频制作成精校双语字幕。",
    docs: "阅读文档",
    showcase: "查看效果",
    workflow: "每一步都可以检查",
    features: [
      ["转录", "从本地音频或视频生成带时间轴的原文字幕。"],
      ["翻译", "通过可编辑术语表保持语义、专有名词和表达一致。"],
      ["发布", "导出双语字幕文件，或将排版后的 ASS 字幕烧录进视频。"],
    ],
    source: "AI Agent 也可以通过可复用 Skill 操作同一套工作流。",
  },
} satisfies Record<Locale, Record<string, unknown>>;

const icons = [Captions, Languages, TerminalSquare];

export function HomePage({ locale }: { locale: Locale }) {
  const text = copy[locale];
  const prefix = `/${locale}`;

  return (
    <main>
      <section className="bbq-shell bbq-hero">
        <div>
          <p className="bbq-kicker">{text.kicker}</p>
          <h1 className="bbq-title">{text.title}</h1>
          <p className="bbq-lede">{text.lede}</p>
          <div className="bbq-actions">
            <a className="bbq-button bbq-button-primary" href={`${prefix}/docs`}>
              {text.docs} <ArrowRight aria-hidden="true" size={18} />
            </a>
            <a className="bbq-button" href={`${prefix}/showcase`}>
              {text.showcase}
            </a>
          </div>
        </div>

        <div className="bbq-terminal" aria-label={text.workflow as string}>
          <div className="bbq-terminal-bar">
            <span>openbbq / workflow</span>
            <span>01:42</span>
          </div>
          <div className="bbq-terminal-body">
            <p><span className="bbq-prompt">$</span> openbbq run interview.mp4 --target zh</p>
            <p className="bbq-success">✓ transcript aligned</p>
            <p className="bbq-success">✓ translation reviewed</p>
            <p className="bbq-success">✓ bilingual.ass exported</p>
            <div className="bbq-subtitle-frame">
              <div className="bbq-subtitle-copy">
                <strong>工具应该让过程透明，而不是隐藏过程。</strong>
                <span>Tools should expose the process, not hide it.</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="bbq-section bbq-section-muted">
        <div className="bbq-shell">
          <p className="bbq-kicker">OpenBBQ pipeline</p>
          <h2>{text.workflow}</h2>
          <div className="bbq-grid">
            {(text.features as string[][]).map(([title, description], index) => {
              const Icon = icons[index]!;
              return (
                <article className="bbq-feature" key={title}>
                  <Icon aria-hidden="true" size={25} strokeWidth={1.8} />
                  <h3>{title}</h3>
                  <p>{description}</p>
                </article>
              );
            })}
          </div>
          <p className="bbq-lede">{text.source}</p>
        </div>
      </section>
    </main>
  );
}
