import fs from "node:fs/promises";
import path from "node:path";

const ROOT = process.cwd();
const CONTENT_DIR = path.join(ROOT, "src", "content", "posts");
const DIST_DIR = path.join(ROOT, "dist");
const OUTPUT_FILE = path.join(DIST_DIR, "ALL_POSTS.txt");
const RECOVERY_PAGE = path.join(DIST_DIR, "404.html");

const SITE_URL = "https://vojtamaur.cz";

const MAX_BLOCK_LINES = 120;
const MAX_BLOCK_CHARS = 12000;

function normalizeSlashes(value) {
  return value.replaceAll(path.sep, "/");
}

function stripBom(value) {
  return value.replace(/^\uFEFF/, "");
}

function escapeHtmlText(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function embedAllPostsInRecoveryPage(value) {
  if (!(await exists(RECOVERY_PAGE))) {
    console.warn("[404] dist/404.html not found; recovery page was not updated.");
    return;
  }

  const html = await fs.readFile(RECOVERY_PAGE, "utf8");
  const embedPattern = /(<pre\b(?=[^>]*\bdata-all-posts-embed\b)[^>]*>)[\s\S]*?(<\/pre>)/i;

  if (!embedPattern.test(html)) {
    throw new Error("dist/404.html does not contain the ALL_POSTS embed target.");
  }

  const updated = html.replace(
    embedPattern,
    (_match, openingTag, closingTag) =>
      `${openingTag}${escapeHtmlText(value)}${closingTag}`,
  );

  await fs.writeFile(RECOVERY_PAGE, updated, "utf8");
  console.log("[404] Embedded ALL_POSTS.txt in dist/404.html");
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

function normalizeInlineText(value) {
  return String(value ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t\r\n]+/g, " ")
    .trim();
}

function escapeTableCell(value) {
  return normalizeInlineText(value).replace(/\|/g, "\\|");
}

function inlineHtmlToTableCell(html) {
  let value = html;

  value = value.replace(/<script[\s\S]*?<\/script>/gi, "");
  value = value.replace(/<style[\s\S]*?<\/style>/gi, "");
  value = value.replace(/<svg[\s\S]*?<\/svg>/gi, "[SVG]");
  value = value.replace(/<br\s*\/?>/gi, " ");

  value = value.replace(/<img\b[^>]*>/gi, (img) => {
    const src = getAttr(img, "src");
    const alt = getAttr(img, "alt");
    const title = getAttr(img, "title");
    const label = alt || title || "image";

    return src ? `${label} (${src})` : label;
  });

  value = value.replace(
    /<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi,
    (_, href, label) => {
      const text = inlineHtmlToTableCell(label);
      const decodedHref = decodeHtmlEntities(href).trim();

      if (!decodedHref) return text;
      if (!text) return decodedHref;
      if (text === decodedHref) return text;

      return `${text} (${decodedHref})`;
    }
  );

  value = value.replace(/<[^>]+>/g, "");
  value = decodeHtmlEntities(value);

  return escapeTableCell(value);
}

function tableToPlainText(tableHtml) {
  const rowMatches = [...tableHtml.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)];

  if (rowMatches.length === 0) return "";

  const rows = rowMatches
    .map((rowMatch) => {
      const rowHtml = rowMatch[1];
      const cells = [];

      for (const cellMatch of rowHtml.matchAll(/<(th|td)\b[^>]*>([\s\S]*?)<\/\1>/gi)) {
        cells.push(inlineHtmlToTableCell(cellMatch[2]));
      }

      return cells;
    })
    .filter((row) => row.length > 0);

  if (rows.length === 0) return "";

  const width = Math.max(...rows.map((row) => row.length));
  const normalizedRows = rows.map((row) => [
    ...row,
    ...Array(width - row.length).fill(""),
  ]);

  const firstRowHasHeaders =
    /<thead\b/i.test(tableHtml) ||
    /<tr\b[^>]*>[\s\S]*?<th\b/i.test(rowMatches[0][0]);

  const lines = [
    "[TABLE]",
    `| ${normalizedRows[0].join(" | ")} |`,
  ];

  if (firstRowHasHeaders) {
    lines.push(`| ${Array(width).fill("---").join(" | ")} |`);
  }

  for (const row of normalizedRows.slice(1)) {
    lines.push(`| ${row.join(" | ")} |`);
  }

  lines.push("[/TABLE]");

  return lines.join("\n");
}

function htmlToPlainText(html) {
  let value = html;

  const blockBreakToken = "\uE000ALL_POSTS_BLOCK_BREAK\uE001";
  const protectedBlocks = [];

  const protectBlock = (content) => {
    const token = `\uE000ALL_POSTS_BLOCK_${protectedBlocks.length}\uE001`;
    protectedBlocks.push({ token, content });
    return `\n${blockBreakToken}\n${token}\n${blockBreakToken}\n`;
  };

  value = value.replace(/<script[\s\S]*?<\/script>/gi, "");
  value = value.replace(/<style[\s\S]*?<\/style>/gi, "");
  value = value.replace(/<svg[\s\S]*?<\/svg>/gi, () =>
    protectBlock("[SVG CONTENT OMITTED]")
  );

  value = value.replace(/<table\b[^>]*>[\s\S]*?<\/table>/gi, (table) => {
    const tableText = tableToPlainText(table);
    return protectBlock(tableText || "[TABLE]\n[/TABLE]");
  });

  value = value.replace(/<figure[\s\S]*?<\/figure>/gi, (figure) => {
    const images = [...figure.matchAll(/<img\b[^>]*>/gi)];
    const captionMatch = figure.match(/<figcaption\b[^>]*>([\s\S]*?)<\/figcaption>/i);

    const caption = captionMatch
      ? htmlToPlainText(captionMatch[1]).trim()
      : "";

    if (images.length === 0) {
      return protectBlock(caption ? `[FIGURE]\nCAPTION: ${caption}` : "[FIGURE]");
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

    return protectBlock(blocks.join("\n\n"));
  });

  value = value.replace(/<img\b[^>]*>/gi, (img) => {
    const src = getAttr(img, "src");
    const alt = getAttr(img, "alt");

    return protectBlock([
      "[MEDIA: image]",
      src ? `FILE: ${src}` : "",
      alt ? `ALT: ${alt}` : "",
    ].filter(Boolean).join("\n"));
  });

  value = value.replace(/<iframe\b[^>]*><\/iframe>/gi, (iframe) => {
    const src = getAttr(iframe, "src");
    const title = getAttr(iframe, "title");

    const type =
      src.toLowerCase().includes(".pdf") ? "[PDF EMBED]" :
      src.toLowerCase().includes("youtube") || src.toLowerCase().includes("youtu.be") ? "[VIDEO EMBED]" :
      "[INTERACTIVE EMBED]";

    return protectBlock([
      type,
      src ? `SOURCE: ${src}` : "",
      title ? `TITLE: ${title}` : "",
      "NOTE: Embedded or binary content is not represented in this plain-text export.",
    ].filter(Boolean).join("\n"));
  });

  value = value.replace(/<pre\b[^>]*>([\s\S]*?)<\/pre>/gi, (_, rawBlock) => {
    const noTags = rawBlock.replace(/<[^>]+>/g, "");
    const decoded = decodeHtmlEntities(noTags).replace(/\r\n/g, "\n").trimEnd();
    const blockLines = decoded ? decoded.split("\n") : [];
    const lines = blockLines.length;
    const chars = decoded.length;

    const shouldTruncateByLines = lines > MAX_BLOCK_LINES;
    const shouldTruncateByChars = chars > MAX_BLOCK_CHARS;

    if (!shouldTruncateByLines && !shouldTruncateByChars) {
      return protectBlock(["[CODE BLOCK]", decoded, "[/CODE BLOCK]"].join("\n"));
    }

    let visible = blockLines.slice(0, MAX_BLOCK_LINES).join("\n").trimEnd();
    let shownLines = Math.min(lines, MAX_BLOCK_LINES);

    if (visible.length > MAX_BLOCK_CHARS) {
      visible = visible.slice(0, MAX_BLOCK_CHARS).trimEnd();
      shownLines = visible ? visible.split("\n").length : 0;
    }

    const omittedLines = Math.max(0, lines - shownLines);
    const omittedChars = Math.max(0, chars - visible.length);

    return protectBlock([
      "[CODE BLOCK]",
      visible,
      "",
      `[TRUNCATED: original code/output block had ${lines} lines and ${chars} characters; showing first ${shownLines} lines. Omitted ${omittedLines} lines and ${omittedChars} characters.]`,
      "See the full website source or rendered post for the complete version.",
      "[/CODE BLOCK]",
    ].join("\n"));
  });

  value = value.replace(/<br\s*\/?>/gi, "\n");

  value = value.replace(/<h([2-6])\b[^>]*>/gi, `\n${blockBreakToken}\n`);
  value = value.replace(/<\/h([2-6])>/gi, `\n${blockBreakToken}\n`);

  value = value.replace(/<\/(p|div|section|article|main|header|footer|blockquote|ul|ol|li|h1|table|tr)>/gi, "\n");

  value = value.replace(/<li\b[^>]*>/gi, "- ");

  value = value.replace(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, (_, href, label) => {
    const text = htmlToPlainText(label).trim();
    const decodedHref = decodeHtmlEntities(href).trim();

    if (!decodedHref) return text;

    if (decodedHref.toLowerCase().endsWith(".pdf")) {
      return `${text}\n[PDF DOCUMENT: ${decodedHref}]`;
    }

    if (!text) return decodedHref;
    if (text === decodedHref) return text;

    return `${text} [${decodedHref}]`;
  });

  value = value.replace(/<[^>]+>/g, "");

  value = decodeHtmlEntities(value);

  value = value
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/\n+/g, "\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();

  value = value
    .replaceAll(blockBreakToken, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  for (const { token, content } of protectedBlocks) {
    value = value.replaceAll(token, () => content);
  }

  return value.trim();
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
    `- Long code/output blocks over ${MAX_BLOCK_LINES} lines or ${MAX_BLOCK_CHARS} characters are truncated in this export, not omitted.`,
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

  const finalText = chunks.join("\n");

  await fs.writeFile(OUTPUT_FILE, "\uFEFF" + finalText, "utf8");
  await embedAllPostsInRecoveryPage(finalText);

  console.log(`[ALL_POSTS] Written ${normalizeSlashes(path.relative(ROOT, OUTPUT_FILE))}`);
  console.log(`[ALL_POSTS] Source posts: ${posts.length}`);
}

main().catch((error) => {
  console.error("[ALL_POSTS] Failed:");
  console.error(error);
  process.exit(1);
});
