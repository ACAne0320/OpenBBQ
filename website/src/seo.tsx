type SeoPage = {
  url: string;
  locale?: string;
  slugs: string[];
  data: {
    title: string;
    description?: string;
  };
};

type AlternateLink = {
  rel: "alternate";
  hreflang: string;
  href: string;
};

const supportedLocales = ["en", "zh"] as const;

function stripLocale(pathname: string) {
  return pathname.replace(/^\/(?:en|zh)(?=\/|$)/, "");
}

function localizedPath(pathname: string, locale: (typeof supportedLocales)[number]) {
  return `/${locale}${stripLocale(pathname)}`;
}

export function getLocalizedPageUrls(pageUrl: string, siteUrl: string) {
  const absolute = (pathname: string) => new URL(pathname, siteUrl).href;
  const alternates = supportedLocales.map((locale) => ({
    rel: "alternate" as const,
    hreflang: locale,
    href: absolute(localizedPath(pageUrl, locale)),
  }));

  return {
    canonical: absolute(pageUrl),
    alternates: [
      ...alternates,
      {
        rel: "alternate" as const,
        hreflang: "x-default",
        href: absolute(localizedPath(pageUrl, "en")),
      },
    ] satisfies AlternateLink[],
  };
}

export function renderPageSeo(page: SeoPage, siteUrl: string) {
  const locale = page.locale === "zh" ? "zh" : "en";
  const ogLocale = locale === "zh" ? "zh_CN" : "en_US";
  const alternateOgLocale = locale === "zh" ? "en_US" : "zh_CN";
  const { canonical, alternates } = getLocalizedPageUrls(page.url, siteUrl);
  const description = page.data.description;
  const isHome = page.slugs.length === 0;
  const softwareDescription =
    locale === "zh"
      ? "把视频链接或本地文件交给 AI Agent，得到可编辑的双语字幕初稿和烧录成片。"
      : "Give an AI agent a video URL or local file and get an editable bilingual subtitle draft plus a burned video.";

  const structuredData = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebSite",
        "@id": `${siteUrl}/#website`,
        name: "OpenBBQ",
        url: `${siteUrl}/`,
        inLanguage: ["en", "zh-CN"],
      },
      {
        "@type": "SoftwareApplication",
        "@id": `${siteUrl}/#software`,
        name: "OpenBBQ",
        url: canonical,
        description: softwareDescription,
        applicationCategory: "UtilitiesApplication",
        applicationSubCategory: "Video translation and subtitle production",
        operatingSystem: "macOS",
        softwareRequirements: "Python 3.12+, uv, FFmpeg, and a whisper.cpp model",
        downloadUrl: "https://pypi.org/project/openbbq/",
        license: "https://www.apache.org/licenses/LICENSE-2.0",
        isAccessibleForFree: true,
        offers: {
          "@type": "Offer",
          price: "0",
          priceCurrency: "USD",
        },
        inLanguage: ["en", "zh-CN"],
        sameAs: [
          "https://github.com/ACAne0320/OpenBBQ",
          "https://pypi.org/project/openbbq/",
        ],
      },
      {
        "@type": "SoftwareSourceCode",
        "@id": `${siteUrl}/#source`,
        name: "OpenBBQ source code",
        codeRepository: "https://github.com/ACAne0320/OpenBBQ",
        programmingLanguage: ["Python", "TypeScript"],
        runtimePlatform: "Python 3.12+",
        license: "https://www.apache.org/licenses/LICENSE-2.0",
        targetProduct: {
          "@id": `${siteUrl}/#software`,
        },
      },
    ],
  };

  return (
    <>
      {description ? <meta name="description" content={description} /> : null}
      <link rel="canonical" href={canonical} />
      {alternates.map((alternate) => (
        <link
          key={alternate.hreflang}
          rel={alternate.rel}
          hrefLang={alternate.hreflang}
          href={alternate.href}
        />
      ))}
      <meta property="og:type" content="website" />
      <meta property="og:site_name" content="OpenBBQ" />
      <meta property="og:url" content={canonical} />
      <meta property="og:locale" content={ogLocale} />
      <meta property="og:locale:alternate" content={alternateOgLocale} />
      <meta name="twitter:title" content={page.data.title} />
      {description ? <meta name="twitter:description" content={description} /> : null}
      {isHome ? (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
        />
      ) : null}
    </>
  );
}
