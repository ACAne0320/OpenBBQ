type Locale = "en" | "zh";

const items = [
  {
    title: { en: "Technical interview", zh: "技术访谈" },
    description: { en: "Terminology-aware bilingual subtitles", zh: "保留专业术语的双语字幕" },
    zh: "上下文窗口不是长期记忆。",
    en: "A context window is not long-term memory.",
  },
  {
    title: { en: "Product walkthrough", zh: "产品演示" },
    description: { en: "Readable line breaks and pacing", zh: "便于阅读的断句和节奏" },
    zh: "先验证工作流，再扩大自动化范围。",
    en: "Validate the workflow before expanding automation.",
  },
];

export function ShowcasePage({ locale }: { locale: Locale }) {
  return (
    <main className="bbq-shell">
      <header className="bbq-showcase-header">
        <p className="bbq-kicker">OpenBBQ output</p>
        <h1 className="bbq-title">{locale === "zh" ? "翻译效果" : "Translation showcase"}</h1>
        <p className="bbq-lede">
          {locale === "zh"
            ? "用于验证字幕断句、层级、可读性和中英文排版的示例。"
            : "Examples for checking subtitle timing, hierarchy, readability, and bilingual typography."}
        </p>
      </header>
      <section className="bbq-showcase-grid">
        {items.map((item, index) => (
          <article className="bbq-showcase-item" key={item.title.en}>
            <div
              className="bbq-subtitle-frame"
              style={{ background: index === 0 ? "#292524" : "#1f2937" }}
            >
              <div className="bbq-subtitle-copy">
                <strong>{item.zh}</strong>
                <span>{item.en}</span>
              </div>
            </div>
            <div className="bbq-showcase-meta">
              <h2>{item.title[locale]}</h2>
              <p>{item.description[locale]}</p>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
