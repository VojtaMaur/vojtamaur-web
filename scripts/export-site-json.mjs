#!/usr/bin/env node
/**
 * Manual, offline JSON-LD 1.1 article export. Never runs a build.
 * node scripts/export-site-json.mjs [--dist dist] [--output exports/ALL_POSTS.json]
 * Selection and source metadata: finished ALL_POSTS.txt; full content: built HTML.
 * The inline context works offline. vm: terms belong to https://vojtamaur.cz/ns/,
 * an identifier namespace, not a dependency on a hosted vocabulary document.
 * vm:sourceMetadata retains original index fields as a JSON literal; vm:articleHtml
 * retains the parsed article fragment, including tables, code and relative URLs.
 * Paths and hashes refer to the selected build, never to current source MDX.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash, randomUUID } from "node:crypto";
import { parseArgs } from "node:util";
import { load } from "cheerio";

const SITE = "https://vojtamaur.cz/";
const VERSION = "1.0.0";
const CONTEXT = {
  "@version": 1.1,
  "@vocab": "https://schema.org/",
  vm: { "@id": "https://vojtamaur.cz/ns/", "@prefix": true },
  xsd: { "@id": "http://www.w3.org/2001/XMLSchema#", "@prefix": true },
  url: { "@id": "https://schema.org/url", "@type": "@id" },
  contentUrl: { "@id": "https://schema.org/contentUrl", "@type": "@id" },
  embedUrl: { "@id": "https://schema.org/embedUrl", "@type": "@id" },
  datePublished: { "@id": "https://schema.org/datePublished", "@type": "xsd:date" },
  "vm:sourceMetadata": { "@id": "vm:sourceMetadata", "@type": "@json" },
};
const REQUIRED = ["TITLE", "SLUG", "URL", "LANGUAGE", "SECTION", "DATE", "SOURCE", "BUILT_HTML"];
const SECTIONS = new Set(["volna-tvorba", "vystavy", "cestovani"]);
const BLOCKS = new Set("article section div p h1 h2 h3 h4 h5 h6 ul ol dl dt dd blockquote figure figcaption table details summary header".split(" "));
const MEDIA = new Set(["img", "iframe", "video", "audio", "object", "embed"]);
const SKIP = new Set(["script", "style", "noscript", "template", "nav", "button"]);
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const slash = (value) => value.split(path.sep).join("/");
const inline = (value) => value.replace(/\s+/gu, " ").trim();
const decode = (bytes) => new TextDecoder("utf-8", { fatal: true }).decode(bytes);

function inside(file, directory) {
  const relative = path.relative(directory, file);
  return relative !== "" && !relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative);
}

function parseIndex(text) {
  const normalized = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const headers = [...normalized.matchAll(/^={60}\n((?:[A-Z][A-Z0-9_]*: [^\n]*\n)+)={60}(?:\n|$)/gm)];
  if (!headers.length) throw new Error("No article metadata in ALL_POSTS.txt. Use a finished, unfiltered build index.");
  const seen = new Set();
  const urls = new Set();
  return headers.map((match, index) => {
    const data = {};
    for (const line of match[1].trimEnd().split("\n")) {
      const colon = line.indexOf(": ");
      const key = line.slice(0, colon);
      if (Object.hasOwn(data, key)) throw new Error(`Duplicate metadata ${key} in article ${index + 1}.`);
      data[key] = line.slice(colon + 2);
    }
    for (const key of REQUIRED) {
      if (!data[key]?.trim()) throw new Error(`Missing ${key} in article ${index + 1}.`);
    }
    if (!/^[\p{L}\p{N}_-]+(?:\/[\p{L}\p{N}_-]+)*$/u.test(data.SLUG)) throw new Error(`Invalid slug: ${data.SLUG}`);
    if (!["cs", "en"].includes(data.LANGUAGE) || !SECTIONS.has(data.SECTION)) throw new Error(`Invalid language or section: ${data.SLUG}`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(data.DATE) || !Number.isFinite(Date.parse(data.DATE)) || new Date(data.DATE).toISOString().slice(0, 10) !== data.DATE) throw new Error(`Invalid date: ${data.DATE}`);
    const expected = new URL(`${data.LANGUAGE === "en" ? "en/" : ""}${data.SLUG}/`, SITE).href;
    if (data.URL !== expected) throw new Error(`Unexpected canonical URL: ${data.URL}`);
    const key = `${data.LANGUAGE}/${data.SLUG}`;
    if (seen.has(key) || urls.has(data.URL)) throw new Error(`Duplicate article: ${key}`);
    seen.add(key);
    urls.add(data.URL);
    return data;
  });
}

async function findHtml(dist, metadata) {
  const route = `${metadata.LANGUAGE === "en" ? "en/" : ""}${metadata.SLUG}`;
  for (const candidate of [path.join(dist, route, "index.html"), path.join(dist, `${route}.html`)]) {
    try {
      const real = await fs.realpath(candidate);
      if (!inside(real, dist)) throw new Error(`Article resolves outside build: ${candidate}`);
      return real;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  throw new Error(`Built article missing: ${route}. Rebuild the website before exporting.`);
}

// Resolve relative URLs against the real built route, including flat USB files.
// Internal article links are then mapped back to their canonical public URLs.
function publicUrl(value, builtUrl, routes) {
  if (!value?.trim()) return "";
  let url;
  try { url = new URL(value.trim(), builtUrl); } catch { return ""; }
  if (!["https:", "http:", "mailto:", "tel:", "gemini:", "gopher:"].includes(url.protocol)) return "";
  if (url.origin === new URL(SITE).origin) {
    const canonical = routes.get(url.pathname);
    if (canonical) return canonical + url.search + url.hash;
  }
  return url.href;
}

function mediaObject($, node, resolve) {
  const item = $(node);
  const raw = item.attr("src") || item.attr("data") || item.find("source[src]").first().attr("src");
  const url = resolve(raw);
  if (!url) return null;
  const tag = node.name;
  const video = tag === "video" || /(^|\.)(youtube(-nocookie)?\.com|youtu\.be|vimeo\.com)$/.test(new URL(url).hostname);
  const result = {
    "@type": tag === "img" ? "ImageObject" : video ? "VideoObject" : tag === "audio" ? "AudioObject" : "MediaObject",
    [tag === "iframe" ? "embedUrl" : "contentUrl"]: url,
    "vm:element": tag,
    "vm:originalSource": raw,
  };
  const title = inline(item.attr("title") || "");
  if (title) result.name = title;
  if (tag === "img") {
    result["vm:altText"] = item.attr("alt") || "";
    const caption = inline(item.closest("figure").find("figcaption").first().text());
    if (caption) result.caption = caption;
  }
  if (/\.pdf$/i.test(new URL(url).pathname)) result.encodingFormat = "application/pdf";
  return result;
}

function articleText($, node, resolve) {
  if (node.type === "text") return node.data.replace(/\s+/gu, " ");
  const tag = node.name;
  if (SKIP.has(tag) || node.type === "comment") return "";
  const item = $(node);
  if (tag === "pre") return `\n[CODE BLOCK]\n${item.text()}\n[/CODE BLOCK]\n`;
  if (tag === "br" || tag === "hr") return "\n";
  if (MEDIA.has(tag)) {
    const media = mediaObject($, node, resolve);
    return media ? `\n[${media["@type"]}: ${media.contentUrl || media.embedUrl}${media["vm:altText"] ? ` | ${media["vm:altText"]}` : ""}]\n` : "";
  }
  if (tag === "svg" || tag === "canvas") return `\n[${tag.toUpperCase()}: ${inline(item.text()) || "visual content retained in vm:articleHtml"}]\n`;
  const children = (node.children || []).map((child) => articleText($, child, resolve)).join("");
  if (tag === "a") {
    const url = resolve(item.attr("href"));
    return url && inline(children) !== url ? `${children} [${url}]` : children;
  }
  if (tag === "li") return `\n- ${children}\n`;
  if (tag === "tr") return `\n${children}\n`;
  if (tag === "td" || tag === "th") return `${children}\t`;
  return BLOCKS.has(tag) ? `\n${children}\n` : children;
}

async function exportDocument(root, dist) {
  const indexBytes = await fs.readFile(path.join(dist, "ALL_POSTS.txt"));
  const indexText = decode(indexBytes);
  const metadata = parseIndex(indexText);
  const routes = new Map();
  const files = [];
  for (const entry of metadata) {
    const file = await findHtml(dist, entry);
    files.push(file);
    const route = slash(path.relative(dist, file));
    routes.set(new URL(route, SITE).pathname, entry.URL);
    routes.set(new URL(entry.URL).pathname, entry.URL);
  }
  const articles = [];
  for (const [index, entry] of metadata.entries()) {
    const file = files[index];
    const bytes = await fs.readFile(file);
    const $ = load(decode(bytes));
    const article = $("main article").first();
    if (!article.length || !article.find("h1").length || !article.find(".post-body").length) throw new Error(`Article content container missing: ${file}`);
    const resolve = (value) => publicUrl(value, new URL(slash(path.relative(dist, file)), SITE), routes);
    const robots = $("meta[name='robots']").map((_, node) => $(node).attr("content") || "").get().join(",");
    const node = {
      "@id": `${entry.URL}#article`,
      "@type": "BlogPosting",
      url: entry.URL,
      headline: inline(article.find("h1").first().text()),
      inLanguage: entry.LANGUAGE,
      articleSection: entry.SECTION,
      datePublished: entry.DATE,
      author: { "@type": "Person", "@id": `${SITE}#author`, name: "Vojta Maur" },
      isPartOf: { "@type": "WebSite", "@id": `${SITE}#website`, url: SITE, name: "Vojta Maur" },
      articleBody: articleText($, article.get(0), resolve).trim(),
      "vm:slug": entry.SLUG,
      "vm:position": index + 1,
      "vm:sourcePath": entry.SOURCE,
      "vm:builtHtmlPath": slash(path.relative(dist, file)),
      "vm:builtHtmlSha256": sha256(bytes),
      "vm:sourceMetadata": entry,
      "vm:renderedMetadata": article.find(".post-meta").map((_, item) => inline($(item).text())).get(),
      "vm:articleHtml": article.html(),
      "vm:robots": robots,
      "vm:languageStatus": entry.LANGUAGE === "cs" ? "original" : /\bnoindex\b/i.test(robots) ? "incomplete-czech-fallback" : "english-route",
    };
    const media = article.find([...MEDIA].join(",")).map((_, item) => mediaObject($, item, resolve)).get().filter(Boolean);
    node.associatedMedia = media;
    node.image = media.filter((item) => item["@type"] === "ImageObject");
    node["vm:links"] = article.find("a[href]").map((_, item) => {
      const url = resolve($(item).attr("href"));
      return url ? { "@type": "vm:Link", url, name: inline($(item).text()), "vm:originalHref": $(item).attr("href") } : null;
    }).get();
    if (!node.headline || !node.articleBody) throw new Error(`Empty article: ${entry.URL}`);
    articles.push(node);
  }
  const byKey = new Map(articles.map((article) => [`${article.inLanguage}/${article["vm:slug"]}`, article]));
  for (const article of articles) {
    const other = byKey.get(`${article.inLanguage === "en" ? "cs" : "en"}/${article["vm:slug"]}`);
    if (other) article[article.inLanguage === "en" ? "translationOfWork" : "workTranslation"] = { "@id": other["@id"] };
  }
  const document = {
    "@context": CONTEXT,
    "@id": `${SITE}#all-posts-export`,
    "@type": "Collection",
    name: "Vojta Maur — article archive",
    inLanguage: [...new Set(articles.map((article) => article.inLanguage))],
    "vm:exportVersion": VERSION,
    "vm:generatedAt": new Date().toISOString(),
    "vm:sourceIndexPath": slash(path.relative(root, path.join(dist, "ALL_POSTS.txt"))),
    "vm:sourceIndexSha256": sha256(indexBytes),
    "vm:sourceGeneratedAt": /^Generated: (.+)$/m.exec(indexText)?.[1].trim() || "",
    "vm:articleCount": articles.length,
    "vm:notes": [
      "Scope: article versions listed in the finished ALL_POSTS.txt; standalone pages and homepage-only sections are not included.",
      "Full article text comes from built HTML without code truncation. Media are references; binary files and external embed contents are not downloaded.",
      "vm:articleHtml is the parsed article fragment, not a standalone page. Relative references use vm:builtHtmlPath within the selected build.",
      "datePublished preserves the index DATE. Some legacy dates use the first day of the month for sorting; exact historical day may be unknown.",
      "inLanguage identifies the route; English routes may contain Czech ALT text or untranslated passages. vm:languageStatus records the build fallback marker, not an independent translation assessment.",
      "vm:declaredBuildSha256, when present, is read from BUILD_SHA256.txt. It does not assert checksum or signature verification.",
      "Article order is recorded explicitly as vm:position because JSON-LD arrays do not imply RDF ordering.",
    ],
    hasPart: articles,
  };
  try {
    const declared = decode(await fs.readFile(path.join(dist, "BUILD_SHA256.txt"))).trim();
    const hash = /^([a-fA-F0-9]{64})(?:\s|$)/.exec(declared)?.[1];
    if (!hash) throw new Error("Invalid BUILD_SHA256.txt.");
    document["vm:declaredBuildSha256"] = hash.toLowerCase();
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  return document;
}

async function main() {
  const { values } = parseArgs({ options: {
    "project-root": { type: "string", default: fileURLToPath(new URL("../", import.meta.url)) },
    dist: { type: "string", default: "dist" },
    output: { type: "string", default: "exports/ALL_POSTS.json" },
    "dry-run": { type: "boolean", default: false },
    help: { type: "boolean", short: "h" },
  } });
  if (values.help) {
    console.log("Usage: node scripts/export-site-json.mjs [--project-root PATH] [--dist PATH] [--output exports/ALL_POSTS.json] [--dry-run]\nPaths resolve from the project root. Output must be a .json/.jsonld file under exports/. Reads an existing build; never builds or accesses the network.");
    return;
  }
  const root = await fs.realpath(path.resolve(values["project-root"]));
  const dist = await fs.realpath(path.resolve(root, values.dist));
  const output = path.resolve(root, values.output);
  const exportsDir = path.join(root, "exports");
  if (!inside(output, exportsDir) || inside(output, dist) || !/\.json(ld)?$/i.test(output)) throw new Error("Output must be a JSON file under exports/ and outside the selected build.");
  // Check existing ancestors before mkdir: a nested output must not create
  // directories through an exports/ symlink pointing outside the export tree.
  let ancestor = path.dirname(output);
  while (true) {
    try {
      const real = await fs.realpath(ancestor);
      if (path.relative(ancestor, real) !== "") throw new Error("Output path must not pass through a symlink or junction.");
      break;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      ancestor = path.dirname(ancestor);
    }
  }
  const document = await exportDocument(root, dist);
  const serialized = JSON.stringify(document, null, 2) + "\n";
  if (!values["dry-run"]) {
    await fs.mkdir(path.dirname(output), { recursive: true });
    const realParent = await fs.realpath(path.dirname(output));
    if (realParent !== exportsDir && !inside(realParent, exportsDir)) throw new Error("Output directory resolves outside exports/.");
    if (realParent === dist || inside(realParent, dist)) throw new Error("Output directory resolves inside the selected build.");
    const temporary = path.join(realParent, `.all-posts-${randomUUID()}.tmp`);
    try {
      await fs.writeFile(temporary, serialized, { encoding: "utf8", flag: "wx" });
      await fs.rename(temporary, output);
    } finally { await fs.rm(temporary, { force: true }); }
  }
  console.log(`[JSON-LD] ${values["dry-run"] ? "Validated" : "Written"}: ${output}`);
  console.log(`[JSON-LD] Articles: ${document.hasPart.length}; languages: ${document.inLanguage.join(", ")}; bytes: ${Buffer.byteLength(serialized)}`);
  console.log(`[JSON-LD] SHA-256: ${sha256(serialized)}`);
}

main().catch((error) => {
  console.error(`[JSON-LD] Failed: ${error.message}`);
  process.exitCode = 1;
});
