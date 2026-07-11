import { defineConfig } from "fumapress";
import { fumadocsMdx } from "fumapress/adapters/mdx";
import { createDocsLayoutPage } from "fumapress/layouts/docs";
import { createHomeLayout, createHomeLayoutPage } from "fumapress/layouts/home";
import { createLayoutSwitch } from "fumapress/layouts/switch";
import { flexsearchPlugin } from "fumapress/plugins/flexsearch";
import { llmsPlugin } from "fumapress/plugins/llms.txt";
import { takumiPlugin } from "fumapress/plugins/takumi";
import { defineI18n } from "fumadocs-core/i18n";
import { zhCN } from "@fumapress/language/zh-cn";
import { docs } from "./.source/server";

const i18n = defineI18n({
  languages: ["en", "zh"],
  defaultLanguage: "en",
});

const translations = i18n.translations().preset("zh", zhCN()).add({
  en: { displayName: "English" },
  zh: { displayName: "简体中文" },
});

const config = defineConfig({
  content: docs.toFumadocsSource(),
  i18n,
  translations,
  mode: "static",
  site: {
    name: "OpenBBQ",
    baseUrl: process.env.PUBLIC_SITE_URL ?? "http://localhost:3000",
    git: {
      user: "ACAne0320",
      repo: "OpenBBQ",
      branch: "main",
      rootDir: "website",
    },
  },
  meta: {
    root() {
      return (
        <>
          <link rel="preconnect" href="https://fonts.googleapis.com" />
          <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
          <link
            href="https://fonts.googleapis.com/css2?family=Geist:ital,wght@0,100..900;1,100..900&family=JetBrains+Mono:ital,wght@0,100..800;1,100..800&display=swap"
            rel="stylesheet"
          />
        </>
      );
    },
  },
});

export type PressContext = typeof config.$context;

export const HomeLayout = createHomeLayout<PressContext>();

export default config
  .layouts({
    defaultProps({ lang }) {
      const prefix = `/${lang ?? "en"}`;

      return {
        nav: { title: "OpenBBQ" },
        links: [
          { text: lang === "zh" ? "文档" : "Docs", url: `${prefix}/docs` },
          { text: "Showcase", url: `${prefix}/showcase` },
          {
            text: "GitHub",
            url: "https://github.com/ACAne0320/OpenBBQ",
            external: true,
          },
        ],
      };
    },
    page: createLayoutSwitch(
      (page) => (page.path.startsWith("docs/") || page.path === "docs" ? "docs" : "home"),
      {
        docs: createDocsLayoutPage(),
        home: createHomeLayoutPage(),
      },
    ),
  })
  .plugins(flexsearchPlugin(), llmsPlugin(), takumiPlugin())
  .adapters(fumadocsMdx());
