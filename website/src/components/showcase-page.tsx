import { ArrowRight } from "lucide-react";

type Locale = "en" | "zh";

const collectionUrl = "https://space.bilibili.com/7964710/lists/8516477?type=season";
const videoUrl = "https://www.bilibili.com/video/BV1ueMJ6cECV";

const copy = {
  en: {
    eyebrow: "OpenBBQ showcase",
    title: "Work made with OpenBBQ.",
    intro:
      "Published videos, subtitle systems, and production workflows built with the OpenBBQ command-line pipeline.",
    collectionLabel: "Published collection · Bilibili",
    collectionTitle: "Pey talks anime",
    collectionDescription:
      "English-language video essays translated and published with readable Simplified Chinese and English subtitles.",
    collectionMeta: "Bilibili collection",
    collectionAction: "View the collection",
    featured: "Featured video",
    videoTitle: "When small mistakes feel big",
    videoTitleZh: "小错误为何会显得很严重",
    watch: "Watch on Bilibili",
  },
  zh: {
    eyebrow: "OpenBBQ Showcase",
    title: "使用 OpenBBQ 制作的作品。",
    intro: "通过 OpenBBQ 命令行工作流制作并发布的视频、字幕系统和生产流程。",
    collectionLabel: "已发布合集 · Bilibili",
    collectionTitle: "Pey talks anime",
    collectionDescription: "将英语视频随笔翻译并制作成便于阅读的简体中文、英文双语字幕版本。",
    collectionMeta: "Bilibili 合集",
    collectionAction: "查看完整合集",
    featured: "精选视频",
    videoTitle: "小错误为何会显得很严重",
    videoTitleZh: "When small mistakes feel big",
    watch: "在 Bilibili 观看",
  },
} as const;

export function ShowcasePage({ locale }: { locale: Locale }) {
  const text = copy[locale];

  return (
    <main className="bbq-showcase">
      <header className="bbq-shell bbq-showcase-header">
        <p className="bbq-eyebrow">{text.eyebrow}</p>
        <h1>{text.title}</h1>
        <p>{text.intro}</p>
      </header>

      <section className="bbq-showcase-feature">
        <div className="bbq-shell bbq-showcase-feature-grid">
          <a className="bbq-video-cover" href={videoUrl} aria-label={`${text.watch}: ${text.videoTitle}`}>
            <img
              src="/showcase/when-small-mistakes-feel-big.webp"
              alt={`${text.videoTitleZh} | ${text.videoTitle}`}
              width="1280"
              height="720"
            />
            <span>09:07</span>
          </a>

          <div className="bbq-collection-copy">
            <p className="bbq-eyebrow">{text.collectionLabel}</p>
            <h2>{text.collectionTitle}</h2>
            <p>{text.collectionDescription}</p>
            <dl>
              <div>
                <dt>{text.featured}</dt>
                <dd>{text.videoTitleZh}<br />{text.videoTitle}</dd>
              </div>
              <div>
                <dt>{text.collectionMeta}</dt>
                <dd>BrokenIris · Bilibili</dd>
              </div>
            </dl>
            <div className="bbq-showcase-actions">
              <a className="bbq-button bbq-button-primary" href={collectionUrl}>
                {text.collectionAction} <ArrowRight aria-hidden="true" size={18} />
              </a>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
