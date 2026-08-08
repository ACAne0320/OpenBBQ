import { readFile } from "node:fs/promises";

const host = "openbbq.acane.dev";
const key = "1f2ee02e273dc7e705f6a8f59d47e30b";
const keyLocation = `https://${host}/${key}.txt`;
const sitemapPath = new URL("../dist/public/sitemap.xml", import.meta.url);

const sitemap = await readFile(sitemapPath, "utf8");
const urlList = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].flatMap((match) =>
  match[1] === undefined ? [] : [match[1].replaceAll("&amp;", "&")],
);

if (urlList.length === 0) {
  throw new Error(`No URLs found in ${sitemapPath.pathname}`);
}

const response = await fetch("https://api.indexnow.org/indexnow", {
  method: "POST",
  headers: { "content-type": "application/json; charset=utf-8" },
  body: JSON.stringify({ host, key, keyLocation, urlList }),
});

if (response.status !== 200 && response.status !== 202) {
  const detail = await response.text();
  throw new Error(`IndexNow returned ${response.status}: ${detail}`);
}

console.log(
  JSON.stringify({
    endpoint: "https://api.indexnow.org/indexnow",
    status: response.status,
    submitted: urlList.length,
  }),
);
