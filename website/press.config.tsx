import { defineConfig } from "fumapress";
import { fumadocsMdx } from "fumapress/adapters/mdx";
import { createDocsLayoutPage } from "fumapress/layouts/docs";
import { createHomeLayout, createHomeLayoutPage } from "fumapress/layouts/home";
import { createLayoutSwitch } from "fumapress/layouts/switch";
import { flexsearchPlugin } from "fumapress/plugins/flexsearch";
import { linkValidationPlugin } from "fumapress/plugins/link-validation";
import { llmsPlugin } from "fumapress/plugins/llms.txt";
import { takumiPlugin } from "fumapress/plugins/takumi";
import { defineI18n } from "fumadocs-core/i18n";
import { zhCN } from "@fumapress/language/zh-cn";
import { docs } from "./.source/server";
import type { Node, Root } from "fumadocs-core/page-tree";

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

const docsLayout = createDocsLayoutPage<PressContext>({
  async render(page) {
    const lang = page.url.startsWith("/zh/") ? "zh" : "en";
    const tree = (await this.getLoader()).getPageTree(lang);
    const docsUrl = `/${lang}/docs`;
    const belongsToDocs = (node: Node): boolean => {
      if (node.type === "page") return node.url === docsUrl || node.url.startsWith(`${docsUrl}/`);
      if (node.type === "separator") return false;
      return Boolean(
        (node.index && belongsToDocs(node.index)) || node.children.some(belongsToDocs),
      );
    };

    return {
      layoutProps: {
        tree: {
          ...tree,
          name: lang === "zh" ? "文档" : "Documentation",
          children: tree.children.filter(belongsToDocs),
        } as Root,
      },
    };
  },
});

export default config
  .layouts({
    defaultProps({ lang }) {
      const prefix = `/${lang ?? "en"}`;

      return {
        nav: { title: "OpenBBQ", url: prefix },
        links: [
          { text: lang === "zh" ? "文档" : "Documentation", url: `${prefix}/docs`, on: "nav" },
          { text: lang === "zh" ? "作品展示" : "Showcase", url: `${prefix}/showcase`, on: "nav" },
        ],
      };
    },
    page: createLayoutSwitch(
      (page) => (page.path.startsWith("docs/") || page.path === "docs" ? "docs" : "home"),
      {
        docs: docsLayout,
        home: createHomeLayoutPage(),
      },
    ),
  })
  .plugins(
    flexsearchPlugin(),
    linkValidationPlugin(),
    llmsPlugin(),
    takumiPlugin(),
  )
  .adapters(fumadocsMdx());
