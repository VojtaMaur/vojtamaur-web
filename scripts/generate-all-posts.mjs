import fs from "node:fs/promises";
import path from "node:path";

const ROOT = process.cwd();
const CONTENT_DIR = path.join(ROOT, "src", "content", "posts");
const DIST_DIR = path.join(ROOT, "dist");
const OUTPUT_FILE = path.join(DIST_DIR, "ALL_POSTS.txt");

const SITE_URL = "https://vojtamaur.cz";

const MAX_BLOCK_LINES = 120;
const MAX_BLOCK_CHARS = 12000;

function normalizeSlashes(value) {
  return value.replaceAll(path.sep, "/");
}

function stripBom(value) {
  return value.replace(/^\uFEFF/, "");
}

function parseFrontmatter(source) {
  const clean = stripBom(source);
  const match = clean.match(/^---\s*\n([\s\S]*?)\n---\s*\n?/);

  if (!match) {
    return { data: {}, body: clean };
  }

  const raw = match[1];
  const body = clean.slice(match[0].length);
  const data = {};

  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();

    if (!trimmed || trimmed.startsWith("#")) continue;

    const pair = trimmed.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!pair) continue;

    const key = pair[1];
    let value = pair[2].trim();

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    data[key] = value;
  }

  return { data, body };
}

function decodeHtmlEntities(value) {
  return value
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, code) => String.fromCodePoint(parseInt(code, 16)))
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'");
}

function getAttr(html, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`${escaped}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, "i");
  const match = html.match(re);
  return decodeHtmlEntities(match?.[2] ?? match?.[3] ?? match?.[4] ?? "").trim();
}

function htmlToPlainText(html) {
  let value = html;

  value = value.replace(/<script[\s\S]*?<\/script>/gi, "");
  value = value.replace(/<style[\s\S]*?<\/style>/gi, "");
  value = value.replace(/<svg[\s\S]*?<\/svg>/gi, "[SVG CONTENT OMITTED]");

  value = value.replace(/<figure[\s\S]*?<\/figure>/gi, (figure) => {
    const images = [...figure.matchAll(/<img\b[^>]*>/gi)];
    const captionMatch = figure.match(/<figcaption\b[^>]*>([\s\S]*?)<\/figcaption>/i);

    const caption = captionMatch
      ? htmlToPlainText(captionMatch[1]).trim()
      : "";

    if (images.length === 0) {
      return caption ? `\n\n[FIGURE]\nCAPTION: ${caption}\n\n` : "\n\n[FIGURE]\n\n";
    }

    const blocks = images.map((img) => {
      const src = getAttr(img[0], "src");
      const alt = getAttr(img[0], "alt");

      return [
        "[MEDIA: image]",
        src ? `FILE: ${src}` : "",
        alt ? `ALT: ${alt}` : "",
        caption ? `CAPTION: ${caption}` : "",
      ].filter(Boolean).join("\n");
    });

    return `\n\n${blocks.join("\n\n")}\n\n`;
  });

  value = value.replace(/<img\b[^>]*>/gi, (img) => {
    const src = getAttr(img, "src");
    const alt = getAttr(img, "alt");

    return "\n\n" + [
      "[MEDIA: image]",
      src ? `FILE: ${src}` : "",
      alt ? `ALT: ${alt}` : "",
    ].filter(Boolean).join("\n") + "\n\n";
  });

  value = value.replace(/<iframe\b[^>]*><\/iframe>/gi, (iframe) => {
    const src = getAttr(iframe, "src");
    const title = getAttr(iframe, "title");

    const type =
      src.toLowerCase().includes(".pdf") ? "[PDF EMBED]" :
      src.toLowerCase().includes("youtube") || src.toLowerCase().includes("youtu.be") ? "[VIDEO EMBED]" :
      "[INTERACTIVE EMBED]";

    return "\n\n" + [
      type,
      src ? `SOURCE: ${src}` : "",
      title ? `TITLE: ${title}` : "",
      "NOTE: Embedded or binary content is not represented in this plain-text export.",
    ].filter(Boolean).join("\n") + "\n\n";
  });

  value = value.replace(/<pre\b[^>]*>([\s\S]*?)<\/pre>/gi, (_, rawBlock) => {
    const noTags = rawBlock.replace(/<[^>]+>/g, "");
    const decoded = decodeHtmlEntities(noTags).replace(/\r\n/g, "\n").trimEnd();
    const lines = decoded ? decoded.split("\n").length : 0;
    const chars = decoded.length;

    if (lines > MAX_BLOCK_LINES || chars > MAX_BLOCK_CHARS) {
      return [
        "",
        "",
        "[LONG PROGRAM OUTPUT OMITTED]",
        `Original post contains a long generated/code/output block with ${lines} lines and ${chars} characters.`,
        "See the full website source or rendered post for the complete version.",
        "",
        "",
      ].join("\n");
    }

    return ["", "", "[CODE BLOCK]", decoded, "[/CODE BLOCK]", "", ""].join("\n");
  });

  value = value.replace(/<br\s*\/?>/gi, "\n");

  value = value.replace(/<\/(p|div|section|article|main|header|footer|blockquote|ul|ol|li|h1|h2|h3|h4|h5|h6|table|tr)>/gi, "\n\n");

  value = value.replace(/<li\b[^>]*>/gi, "- ");

  value = value.replace(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, (_, href, label) => {
    const text = htmlToPlainText(label).trim();
    const decodedHref = decodeHtmlEntities(href).trim();

    if (!decodedHref) return text;

    if (decodedHref.toLowerCase().endsWith(".pdf")) {
      return `${text}\n[PDF DOCUMENT: ${decodedHref}]`;
    }

    return text;
  });

  value = value.replace(/<[^>]+>/g, "");

  value = decodeHtmlEntities(value);

  value = value
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n{4,}/g, "\n\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();

  return value;
}

function extractMainContent(html) {
  const article = html.match(/<article\b[^>]*>([\s\S]*?)<\/article>/i);
  if (article) return article[1];

  const main = html.match(/<main\b[^>]*>([\s\S]*?)<\/main>/i);
  if (main) return main[1];

  const body = html.match(/<body\b[^>]*>([\s\S]*?)<\/body>/i);
  if (body) return body[1];

  return html;
}

function findBuiltHtml(slug, lang) {
  const candidates = lang === "en"
    ? [
        path.join(DIST_DIR, "en", slug, "index.html"),
        path.join(DIST_DIR, "en", `${slug}.html`),
      ]
    : [
        path.join(DIST_DIR, slug, "index.html"),
        path.join(DIST_DIR, `${slug}.html`),
      ];

  return candidates;
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function readIfExists(candidates) {
  for (const filePath of candidates) {
    if (await exists(filePath)) {
      return {
        filePath,
        html: await fs.readFile(filePath, "utf8"),
      };
    }
  }

  return null;
}

function formatDate(value) {
  return value || "unknown";
}

function canonicalUrl(slug, lang) {
  if (lang === "en") return `${SITE_URL}/en/${slug}/`;
  return `${SITE_URL}/${slug}/`;
}

async function getPosts() {
  const files = await fs.readdir(CONTENT_DIR);
  const mdxFiles = files.filter((file) => file.endsWith(".mdx"));

  const posts = [];

  for (const file of mdxFiles) {
    const fullPath = path.join(CONTENT_DIR, file);
    const source = await fs.readFile(fullPath, "utf8");
    const { data } = parseFrontmatter(source);

    if (String(data.draft).toLowerCase() === "true") continue;

    if (!data.slug || !data.title) {
      console.warn(`[ALL_POSTS] Skipping ${file}: missing title or slug.`);
      continue;
    }

    posts.push({
      title: data.title,
      slug: data.slug,
      section: data.section || "unknown",
      date: formatDate(data.date),
      sourcePath: normalizeSlashes(path.relative(ROOT, fullPath)),
    });
  }

  posts.sort((a, b) => String(b.date).localeCompare(String(a.date)));

  return posts;
}

async function buildEntry(post, lang) {
  const result = await readIfExists(findBuiltHtml(post.slug, lang));

  if (!result) {
    return "";
  }

  const mainContent = extractMainContent(result.html);
  const text = htmlToPlainText(mainContent);

  if (!text) {
    return "";
  }

  return [
    "============================================================",
    `TITLE: ${post.title}`,
    `SLUG: ${post.slug}`,
    `URL: ${canonicalUrl(post.slug, lang)}`,
    `LANGUAGE: ${lang}`,
    `SECTION: ${post.section}`,
    `DATE: ${post.date}`,
    `SOURCE: ${post.sourcePath}`,
    `BUILT_HTML: ${normalizeSlashes(path.relative(ROOT, result.filePath))}`,
    "============================================================",
    "",
    text,
    "",
    "",
  ].join("\n");
}

async function main() {
  if (!(await exists(DIST_DIR))) {
    throw new Error("dist/ does not exist. Run Astro build before generate-all-posts.mjs.");
  }

  const posts = await getPosts();
  const generatedAt = new Date().toISOString();

  const chunks = [
    "ALL_POSTS.txt",
    "Plain-text export of textual content from vojtamaur.cz.",
    "",
    "Generated from the built static website during build/postbuild.",
    "This file is intended for indexing, archiving, offline reading and long-term preservation.",
    "",
    `Primary website: ${SITE_URL}/`,
    `Generated: ${generatedAt}`,
    "Encoding: UTF-8 with BOM",
    "Encoding check: čeština, ř, ž, š, ě, ů, á, é, í, ý, —, “quotes”",
    "",
    "Notes:",
    "- Media, iframes, PDFs and other non-text content are represented by placeholders.",
    `- Long code/output blocks over ${MAX_BLOCK_LINES} lines or ${MAX_BLOCK_CHARS} characters are omitted from this export.`,
    "- For complete content, use the rendered website, source repository, or static snapshots.",
    "",
    "",
  ];

  for (const post of posts) {
    const cs = await buildEntry(post, "cs");
    if (cs) chunks.push(cs);

    const en = await buildEntry(post, "en");
    if (en) chunks.push(en);
  }

  const finalText = chunks
    .join("\n")
    .replace(/\n{5,}/g, "\n\n\n\n");

  await fs.writeFile(OUTPUT_FILE, "\uFEFF" + finalText, "utf8");

  console.log(`[ALL_POSTS] Written ${normalizeSlashes(path.relative(ROOT, OUTPUT_FILE))}`);
  console.log(`[ALL_POSTS] Source posts: ${posts.length}`);
}

main().catch((error) => {
  console.error("[ALL_POSTS] Failed:");
  console.error(error);
  process.exit(1);
});