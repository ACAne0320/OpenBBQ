import type { RouteConfig } from "fumapress";

const siteUrl = new URL(process.env.PUBLIC_SITE_URL ?? "https://openbbq.acane.dev").origin;
const englishUrl = `${siteUrl}/en`;
const chineseUrl = `${siteUrl}/zh`;
const description =
  "OpenBBQ turns a video URL or local file into an editable bilingual subtitle draft and a burned video through one AI-agent prompt.";

export function getConfig() {
  return {
    autoI18n: false,
    render: "static",
  } satisfies RouteConfig;
}

export default function LanguageRedirect() {
  return (
    <html lang="en">
      <head>
        <meta httpEquiv="refresh" content="0;url=/en" />
        <meta name="description" content={description} />
        <link rel="canonical" href={englishUrl} />
        <link rel="alternate" hrefLang="en" href={englishUrl} />
        <link rel="alternate" hrefLang="zh" href={chineseUrl} />
        <link rel="alternate" hrefLang="x-default" href={englishUrl} />
        <meta property="og:title" content="OpenBBQ — Agent-Native Video Translation" />
        <meta property="og:description" content={description} />
        <meta property="og:url" content={englishUrl} />
        <script dangerouslySetInnerHTML={{ __html: "window.location.replace('/en')" }} />
        <title>OpenBBQ — Agent-Native Video Translation</title>
      </head>
      <body>
        <p>
          Continue in <a href="/en">English</a> or <a href="/zh">简体中文</a>.
        </p>
      </body>
    </html>
  );
}
