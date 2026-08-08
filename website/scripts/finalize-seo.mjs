import { readFile, writeFile } from "node:fs/promises";

const sitemapPath = new URL("../dist/public/sitemap.xml", import.meta.url);
const siteRoot = "https://openbbq.acane.dev/";
const urlEntryPattern = /<url>.*?<\/url>/gs;

const sitemap = await readFile(sitemapPath, "utf8");
const entries = sitemap.match(urlEntryPattern) ?? [];
const rootEntries = entries.filter((entry) => entry.includes(`<loc>${siteRoot}</loc>`));
const rootEntry = rootEntries[0];

if (rootEntries.length !== 1 || rootEntry === undefined) {
  throw new Error(`Expected exactly one redirect-only root URL in the sitemap, found ${rootEntries.length}.`);
}

const finalized = sitemap.replace(rootEntry, "");
const locations = [...finalized.matchAll(/<loc>(.*?)<\/loc>/g)].flatMap((match) =>
  match[1] === undefined ? [] : [match[1]],
);

if (locations.length === 0) {
  throw new Error("The finalized sitemap contains no URLs.");
}

if (new Set(locations).size !== locations.length) {
  throw new Error("The finalized sitemap contains duplicate URLs.");
}

const invalidLocations = locations.filter(
  (location) => !location.startsWith(siteRoot) || location === siteRoot || location.endsWith(".md"),
);

if (invalidLocations.length > 0) {
  throw new Error(`The finalized sitemap contains invalid URLs: ${invalidLocations.join(", ")}`);
}

await writeFile(sitemapPath, finalized, "utf8");
console.log(`SEO sitemap finalized: ${locations.length} canonical, indexable URLs.`);
