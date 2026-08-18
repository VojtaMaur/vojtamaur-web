import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import * as cheerio from "cheerio";

const ROOT = process.cwd();
const DEFAULT_DIST_DIR = path.join(ROOT, "dist");
const DEFAULT_OUTPUT_DIR = path.join(ROOT, "dist-gemini");
const DEFAULT_CONTENT_DIR = path.join(ROOT, "src", "content", "posts");
const DEFAULT_SITE_URL = "https://vojtamaur.cz";
const GEMINI_CAPSULE_PREFIX = "/~vojtamaur";
const GOPHER_HOST = "envs.net";
const GOPHER_PORT = "70";
const GOPHER_SELECTOR_PREFIX = GEMINI_CAPSULE_PREFIX;

const SECTION_DEFINITIONS = {
  personalWork: {
    sourceAliases: ["volna-tvorba", "personal-work", "volná tvorba", "personal work"],
    cs: { dir: "volna-tvorba", title: "Volná tvorba" },
    en: { dir: "personal-work", title: "Personal Work" },
  },
  exhibitions: {
    sourceAliases: ["vystavy", "exhibitions", "výstavy"],
    cs: { dir: "vystavy", title: "Výstavy" },
    en: { dir: "exhibitions", title: "Exhibitions" },
  },
  travel: {
    sourceAliases: ["cestovani", "travel", "cestování"],
    cs: { dir: "cestovani", title: "Cestování" },
    en: { dir: "travel", title: "Travel" },
  },
  videos: {
    sourceAliases: ["propagacni-videa", "promotional-videos", "videos", "videa"],
    cs: { dir: "videa", title: "Propagační videa" },
    en: { dir: "videos", title: "Promotional Videos" },
  },
  about: {
    sourceAliases: ["o-mne", "about", "about-me"],
    cs: { dir: "o-mne", title: "O mně" },
    en: { dir: "about", title: "About Me" },
  },
  contact: {
    sourceAliases: ["kontakt", "contact"],
    cs: { dir: "kontakt", title: "Kontakt" },
    en: { dir: "contact", title: "Contact" },
  },
};

const SECTION_ORDER = [
  "personalWork",
  "exhibitions",
  "travel",
  "videos",
  "about",
  "contact",
];

const POST_SECTION_KEYS = new Set(["personalWork", "exhibitions", "travel"]);

function parseArgs(argv) {
  const options = {
    distDir: DEFAULT_DIST_DIR,
    outputDir: DEFAULT_OUTPUT_DIR,
    contentDir: DEFAULT_CONTENT_DIR,
    siteUrl: DEFAULT_SITE_URL,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const value = argv[index + 1];

    if (arg === "--dist" && value) {
      options.distDir = path.resolve(ROOT, value);
      index += 1;
    } else if (arg === "--output" && value) {
      options.outputDir = path.resolve(ROOT, value);
      index += 1;
    } else if (arg === "--content" && value) {
      options.contentDir = path.resolve(ROOT, value);
      index += 1;
    } else if (arg === "--site-url" && value) {
      options.siteUrl = value.replace(/\/+$/, "");
      index += 1;
    } else if (arg === "--help" || arg === "-h") {
      console.log(`Usage: node scripts/generate-gemini-capsule.mjs [options]\n\nOptions:\n  --dist <dir>       Built web directory (default: dist)\n  --output <dir>     Gemini output directory (default: dist-gemini)\n  --content <dir>    Source posts directory (default: src/content/posts)\n  --site-url <url>   HTTPS base URL for media and fallbacks\n`);
      process.exit(0);
    } else if (arg.startsWith("--")) {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  return options;
}

function normalizeSlashes(value) {
  return value.replaceAll(path.sep, "/");
}

function stripBom(value) {
  return value.replace(/^\uFEFF/, "");
}

function normalizeInlineText(value) {
  return String(value ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t\r\n]+/g, " ")
    .trim();
}

function normalizeMultilineText(value) {
  return String(value ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function normalizeInlineMultilineText(value) {
  return String(value ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function parseFrontmatter(source) {
  const clean = stripBom(source);
  const match = clean.match(/^---\s*\n([\s\S]*?)\n---\s*\n?/);

  if (!match) return { data: {}, body: clean };

  const data = {};

  for (const line of match[1].split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const pair = trimmed.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (!pair) continue;

    let value = pair[2].trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    data[pair[1]] = value;
  }

  return { data, body: clean.slice(match[0].length) };
}

async function exists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function ensureParent(filePath) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
}

function escapeReplacementCharacters(value) {
  return String(value ?? "").replaceAll("\uFFFD", "\\uFFFD");
}

async function writeUtf8(filePath, content) {
  await ensureParent(filePath);
  const normalized = normalizeMultilineText(content);
  const escaped = escapeReplacementCharacters(normalized);
  await fs.writeFile(filePath, `${escaped}\n`, "utf8");
}

function normalizeSectionValue(value) {
  return normalizeInlineText(value).toLocaleLowerCase("cs-CZ");
}

function resolveSectionKey(value) {
  const normalized = normalizeSectionValue(value);

  for (const [key, definition] of Object.entries(SECTION_DEFINITIONS)) {
    if (definition.sourceAliases.some((alias) => normalizeSectionValue(alias) === normalized)) {
      return key;
    }
  }

  return null;
}

function sectionDirectory(lang, sectionKey) {
  const definition = SECTION_DEFINITIONS[sectionKey];
  if (!definition) throw new Error(`Unknown section key: ${sectionKey}`);

  return lang === "cs"
    ? `cs/${definition.cs.dir}/`
    : `${definition.en.dir}/`;
}

function sectionRoot(lang, sectionKey) {
  return `${sectionDirectory(lang, sectionKey)}index.gmi`;
}

function articleCapsulePath(lang, sectionKey, slug) {
  return `${sectionDirectory(lang, sectionKey)}${slug}.gmi`;
}

function articleOutputPath(outputDir, lang, sectionKey, slug) {
  const definition = SECTION_DEFINITIONS[sectionKey];
  const parts = lang === "cs"
    ? [outputDir, "cs", definition.cs.dir, `${slug}.gmi`]
    : [outputDir, definition.en.dir, `${slug}.gmi`];

  return path.join(...parts);
}

function homepageCapsulePath(lang) {
  return lang === "cs" ? "cs/index.gmi" : "index.gmi";
}

function normalizeCapsulePath(value) {
  return String(value || "")
    .replace(/^\/+/, "")
    .replace(/\\/g, "/");
}

function capsuleHref(toCapsulePath, fromCapsulePath = null) {
  const to = normalizeCapsulePath(toCapsulePath) || "index.gmi";

  if (!fromCapsulePath) return `${GEMINI_CAPSULE_PREFIX}/${to}`;

  const from = normalizeCapsulePath(fromCapsulePath) || "index.gmi";
  const fromDirectory = from.endsWith("/") ? from : path.posix.dirname(from);
  const relativeFrom = fromDirectory === "." ? "" : fromDirectory;
  const relative = path.posix.relative(relativeFrom, to);

  return relative || path.posix.basename(to) || "index.gmi";
}

function gopherSelector(toCapsulePath) {
  const to = normalizeCapsulePath(toCapsulePath);
  return to ? `${GOPHER_SELECTOR_PREFIX}/${to}` : `${GOPHER_SELECTOR_PREFIX}/`;
}

function gopherDirectorySelector(toCapsulePath) {
  const to = normalizeCapsulePath(toCapsulePath);

  if (!to || to === "index.gmi") return `${GOPHER_SELECTOR_PREFIX}/`;
  if (to.endsWith("/index.gmi")) {
    return `${GOPHER_SELECTOR_PREFIX}/${to.slice(0, -"index.gmi".length)}`;
  }

  return gopherSelector(to);
}

function normalizeWebPathname(pathname) {
  let value = pathname || "/";
  value = value.replace(/\/index\.html$/i, "/");
  value = value.replace(/\.html$/i, "");
  if (!value.startsWith("/")) value = `/${value}`;
  if (value !== "/" && !path.extname(value) && !value.endsWith("/")) value += "/";
  return value;
}

function htmlFileCandidates(distDir, slug, lang) {
  return lang === "en"
    ? [
        path.join(distDir, "en", slug, "index.html"),
        path.join(distDir, "en", `${slug}.html`),
      ]
    : [
        path.join(distDir, slug, "index.html"),
        path.join(distDir, `${slug}.html`),
      ];
}

async function readFirstExisting(candidates) {
  for (const filePath of candidates) {
    if (await exists(filePath)) {
      return { filePath, html: await fs.readFile(filePath, "utf8") };
    }
  }
  return null;
}

function canonicalUrlFromHtml(html, fallbackUrl) {
  const $ = cheerio.load(html);
  const canonical = $("link[rel='canonical']").attr("href");
  return canonical || fallbackUrl;
}

function pageTitleFromHtml(html, fallback = "") {
  const $ = cheerio.load(html);
  const title =
    normalizeInlineText($("article h1").first().text()) ||
    normalizeInlineText($("main h1").first().text()) ||
    normalizeInlineText($("h1").first().text());

  if (title) return title;

  const documentTitle = normalizeInlineText($("title").first().text());
  if (!documentTitle) return fallback;
  return normalizeInlineText(documentTitle.split(/[|–—]/)[0]) || fallback;
}

async function getPosts(contentDir, distDir, siteUrl, warnings) {
  if (!(await exists(contentDir))) {
    throw new Error(`Post source directory does not exist: ${contentDir}`);
  }

  const files = (await fs.readdir(contentDir)).filter((file) => file.endsWith(".mdx"));
  const posts = [];

  for (const file of files) {
    const sourcePath = path.join(contentDir, file);
    const source = await fs.readFile(sourcePath, "utf8");
    const { data } = parseFrontmatter(source);

    if (String(data.draft).toLowerCase() === "true") continue;
    if (!data.slug) {
      warnings.push(`Skipping ${file}: missing slug.`);
      continue;
    }

    const sectionKey = resolveSectionKey(data.section);
    if (!sectionKey || !POST_SECTION_KEYS.has(sectionKey)) {
      warnings.push(`Skipping ${file}: unsupported section "${data.section || "unknown"}".`);
      continue;
    }

    const record = {
      slug: data.slug,
      sourceTitle: data.title || data.slug,
      sectionKey,
      date: data.date || "",
      sourcePath,
      languages: {},
    };

    for (const lang of ["cs", "en"]) {
      const built = await readFirstExisting(htmlFileCandidates(distDir, data.slug, lang));
      if (!built) {
        warnings.push(`Missing ${lang.toUpperCase()} build for ${data.slug}.`);
        continue;
      }

      const fallbackUrl = lang === "en"
        ? `${siteUrl}/en/${data.slug}/`
        : `${siteUrl}/${data.slug}/`;
      const canonicalUrl = canonicalUrlFromHtml(built.html, fallbackUrl);

      record.languages[lang] = {
        html: built.html,
        filePath: built.filePath,
        canonicalUrl,
        title: pageTitleFromHtml(built.html, data.title || data.slug),
      };
    }

    if (record.languages.cs || record.languages.en) posts.push(record);
  }

  posts.sort((a, b) => {
    const byDate = String(b.date).localeCompare(String(a.date));
    return byDate || a.slug.localeCompare(b.slug);
  });

  return posts;
}

function buildRouteMap(posts, homepageData, siteUrl) {
  const routeMap = new Map();
  const siteHost = new URL(siteUrl).host;

  const add = (urlOrPath, target) => {
    if (!urlOrPath || !target) return;
    try {
      const resolved = new URL(urlOrPath, siteUrl);
      if (resolved.host !== siteHost) return;
      routeMap.set(normalizeWebPathname(resolved.pathname), target);
    } catch {
      // Ignore malformed source URLs; they remain untouched in the rendered output.
    }
  };

  add("/", homepageCapsulePath("cs"));
  add("/en/", homepageCapsulePath("en"));

  for (const post of posts) {
    for (const lang of ["cs", "en"]) {
      const page = post.languages[lang];
      if (!page) continue;
      add(page.canonicalUrl, articleCapsulePath(lang, post.sectionKey, post.slug));

      const conventionalPath = lang === "en" ? `/en/${post.slug}/` : `/${post.slug}/`;
      add(conventionalPath, articleCapsulePath(lang, post.sectionKey, post.slug));
    }
  }

  for (const lang of ["cs", "en"]) {
    const data = homepageData[lang];
    if (!data) continue;

    for (const [sectionKey, section] of Object.entries(data.sections)) {
      if (section.href) add(section.href, sectionRoot(lang, sectionKey));
    }
  }

  // Conventional fallbacks only for sections that actually get Gemini index pages.
  for (const sectionKey of POST_SECTION_KEYS) {
    const definition = SECTION_DEFINITIONS[sectionKey];
    add(`/${definition.cs.dir}/`, sectionRoot("cs", sectionKey));
    add(`/en/${definition.en.dir}/`, sectionRoot("en", sectionKey));
    add(`/en/${definition.cs.dir}/`, sectionRoot("en", sectionKey));
  }

  return routeMap;
}

function isLikelyMediaPath(pathname) {
  const lower = pathname.toLowerCase();
  if (["/images/", "/files/", "/demos/", "/keys/"].some((prefix) => lower.startsWith(prefix))) {
    return true;
  }

  return /\.(?:avif|bmp|gif|jpe?g|png|svg|webp|mp3|m4a|ogg|wav|mp4|m4v|webm|mov|pdf|zip|7z|tar|gz|asc|txt|json|xml)$/i.test(lower);
}

function rewriteHref(rawHref, context) {
  const href = normalizeInlineText(rawHref);
  if (!href) return "";

  if (href.startsWith("#")) return href;
  if (/^(?:mailto|tel|gemini|gopher|ipfs|magnet):/i.test(href)) return href;
  if (/^(?:javascript|data):/i.test(href)) return "";

  let resolved;
  try {
    resolved = new URL(href, context.currentWebUrl || context.siteUrl);
  } catch {
    return href;
  }

  const siteUrl = new URL(context.siteUrl);
  if (resolved.host !== siteUrl.host) return resolved.toString();

  const normalizedPath = normalizeWebPathname(resolved.pathname);
  const mapped = context.routeMap.get(normalizedPath);
  if (mapped) {
    return `${capsuleHref(mapped, context.currentCapsulePath)}${resolved.hash || ""}`;
  }

  if (resolved.pathname.toLowerCase().startsWith("/keys/")) {
    const keyPath = resolved.pathname.replace(/^\/+/, "");
    return `${capsuleHref(keyPath, context.currentCapsulePath)}${resolved.search}${resolved.hash}`;
  }

  if (isLikelyMediaPath(resolved.pathname)) return resolved.toString();

  // Unknown internal HTML routes stay on the canonical HTTPS site rather than becoming broken Gemini links.
  return resolved.toString();
}

function linkLabel($, element, fallback) {
  const text = normalizeInlineText($(element).text());
  if (text) return text;

  const imageAlt = normalizeInlineText($(element).find("img").first().attr("alt"));
  return imageAlt || fallback;
}

function visibleMediaLinkLabel(href, description = "") {
  const target = normalizeInlineText(href);
  const label = normalizeInlineText(description);

  if (!target) return label;
  if (!label || label === "Image" || label === target) return target;

  return `${label} — ${target}`;
}

function isGenericDeadLinkLabel(value) {
  const label = normalizeInlineText(value).toLocaleLowerCase("cs-CZ");
  return label === "link" || label === "odkaz";
}

function isDisplayedTargetSameAsHref(label, href) {
  const displayed = normalizeInlineText(label);
  const target = normalizeInlineText(href);

  if (!displayed || !target) return false;
  if (displayed === target) return true;

  if (/^mailto:/i.test(target)) {
    return displayed.toLocaleLowerCase("en-US") === target.slice(7).toLocaleLowerCase("en-US");
  }

  if (/^tel:/i.test(target)) {
    const normalizePhone = (value) => value.replace(/[^+\d]/g, "");
    return normalizePhone(displayed) === normalizePhone(target.slice(4));
  }

  try {
    return new URL(displayed).toString() === new URL(target).toString();
  } catch {
    return false;
  }
}

function inlineContent($, node, context) {
  const result = { text: "", links: [] };

  const append = (part) => {
    result.text += part;
  };

  const visit = (current) => {
    if (!current) return;

    if (current.type === "text") {
      append(String(current.data || "").replace(/[ \t\r\n]+/g, " "));
      return;
    }

    if (current.type !== "tag") return;

    const tag = current.tagName.toLowerCase();
    const element = $(current);

    if (tag === "br") {
      append("\n");
      return;
    }

    if (tag === "a") {
      const href = rewriteHref(element.attr("href"), context);
      const image = element.find("img").first();

      if (image.length && href) {
        const label = visibleMediaLinkLabel(href, image.attr("alt"));
        append(label);
        result.links.push({ href, label });
        return;
      }

      const nested = { text: "", links: [] };
      for (const child of current.children || []) {
        const childResult = inlineContent($, child, context);
        nested.text += childResult.text;
        nested.links.push(...childResult.links);
      }

      if (!href) {
        if (!isGenericDeadLinkLabel(nested.text)) append(nested.text);
        result.links.push(...nested.links);
        return;
      }

      const label = normalizeInlineText(nested.text) || linkLabel($, current, href);
      if (!isDisplayedTargetSameAsHref(label, href)) append(label);
      result.links.push(...nested.links);
      result.links.push({ href, label });
      return;
    }

    if (tag === "img") {
      const src = rewriteHref(element.attr("src"), context);
      const label = visibleMediaLinkLabel(src, element.attr("alt"));
      append(label);
      if (src) result.links.push({ href: src, label });
      return;
    }

    if (["script", "style", "svg", "noscript"].includes(tag)) return;

    for (const child of current.children || []) visit(child);
  };

  visit(node);
  result.text = String(result.text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ");
  return result;
}

function linkLabelScore(label, href) {
  const normalized = normalizeInlineText(label);
  if (!normalized || isGenericDeadLinkLabel(normalized)) return 0;

  const lower = normalized.toLocaleLowerCase("en-US");
  if (["a", "an", "the"].includes(lower)) return 1;
  if (isDisplayedTargetSameAsHref(normalized, href)) return 10;

  return 100 + Math.min(normalized.length, 200);
}

function dedupeLinks(links) {
  const output = [];
  const byHref = new Map();

  for (const link of links) {
    if (!link?.href) continue;

    const href = normalizeInlineText(link.href);
    const label = normalizeInlineText(link.label) || href;
    const existingIndex = byHref.get(href);

    if (existingIndex === undefined) {
      byHref.set(href, output.length);
      output.push({ href, label });
      continue;
    }

    const existing = output[existingIndex];
    if (linkLabelScore(label, href) > linkLabelScore(existing.label, href)) {
      existing.label = label;
    }
  }

  return output;
}

function addInlineLinkReferences(text, links) {
  let annotated = text;
  const referencedLinks = [];
  const searchOffsets = new Map();

  for (const link of links) {
    const label = normalizeInlineText(link.label);

    if (
      !label ||
      isGenericDeadLinkLabel(label) ||
      isDisplayedTargetSameAsHref(label, link.href) ||
      /^(?:mailto|tel):/i.test(link.href)
    ) {
      referencedLinks.push({ ...link, reference: null });
      continue;
    }

    const searchFrom = searchOffsets.get(label) || 0;
    const index = annotated.indexOf(label, searchFrom);

    if (index === -1) {
      referencedLinks.push({ ...link, reference: null });
      continue;
    }

    const reference = referencedLinks.filter((item) => item.reference !== null).length + 1;
    const marker = ` [${reference}]`;
    const end = index + label.length;
    annotated = `${annotated.slice(0, end)}${marker}${annotated.slice(end)}`;
    searchOffsets.set(label, end + marker.length);
    referencedLinks.push({ ...link, reference });
  }

  return { text: annotated, links: referencedLinks };
}

function renderInlineBlock($, element, context, prefix = "") {
  const combined = { text: "", links: [] };
  for (const child of element.children || []) {
    const piece = inlineContent($, child, context);
    combined.text += piece.text;
    combined.links.push(...piece.links);
  }

  const text = normalizeInlineMultilineText(combined.text);
  const links = dedupeLinks(combined.links);

  if (!text && links.length === 0) return "";

  if (links.length === 1 && text === links[0].label) {
    return `${prefix}=> ${links[0].href} ${links[0].label}`.trimStart();
  }

  const referenced = addInlineLinkReferences(text, links);
  const blocks = [];
  if (referenced.text) blocks.push(`${prefix}${referenced.text}`);

  for (const link of referenced.links) {
    const label = link.reference === null
      ? link.label
      : `[${link.reference}] ${link.label}`;
    blocks.push(`=> ${link.href} ${label}`);
  }

  return blocks.join("\n");
}

function renderFigure($, element, context) {
  const figure = $(element);
  const caption = normalizeInlineText(figure.find("figcaption").first().text());
  const links = [];

  figure.find("img").each((_, image) => {
    const img = $(image);
    const src = rewriteHref(img.attr("src"), context);
    const alt = normalizeInlineText(img.attr("alt"));
    const label = visibleMediaLinkLabel(src, caption || alt);
    if (src) links.push(`=> ${src} ${label}`);
  });

  if (links.length === 0 && caption) return caption;
  return links.join("\n");
}

function classifyEmbed(src) {
  const lower = src.toLowerCase();
  if (lower.includes("youtube.com") || lower.includes("youtu.be") || lower.includes("vimeo.com")) return "Video";
  if (lower.endsWith(".pdf") || lower.includes(".pdf?")) return "PDF document";
  if (lower.includes("google.com/maps") || lower.includes("maps.google")) return "Map";
  if (lower.includes("sketchfab.com")) return "3D model";
  if (lower.includes("/demos/") || lower.endsWith(".html")) return "Interactive demo";
  return "";
}

function renderEmbed($, element, context) {
  const node = $(element);
  const rawSrc = node.attr("src") || node.find("source").first().attr("src") || node.attr("href");
  const src = rewriteHref(rawSrc, context);
  if (!src) return "";

  const explicitTitle = normalizeInlineText(node.attr("title"));
  const label = explicitTitle || classifyEmbed(src) || src;
  return `=> ${src} ${label}`;
}

function renderTable($, element) {
  const rows = [];
  $(element).find("tr").each((_, row) => {
    const cells = [];
    $(row).find("th, td").each((__, cell) => {
      cells.push(normalizeInlineText($(cell).text()));
    });
    if (cells.length > 0) rows.push(cells);
  });

  if (rows.length === 0) return "";
  const width = Math.max(...rows.map((row) => row.length));
  const normalized = rows.map((row) => [...row, ...Array(width - row.length).fill("")]);
  const body = normalized.map((row) => row.join("\t")).join("\n");
  return `\`\`\`table\n${body}\n\`\`\``;
}

function renderPreformatted($, element) {
  const pre = $(element);
  let content = pre.text().replace(/\r\n/g, "\n").trimEnd();
  content = content
    .split("\n")
    .map((line) => line.startsWith("```") ? ` ${line}` : line)
    .join("\n");

  if (!content) return "";

  const codeClass = pre.find("code").first().attr("class") || "";
  const language = codeClass.match(/(?:language-|lang-)([A-Za-z0-9_+-]+)/i)?.[1] || "";
  return `\`\`\`${language}\n${content}\n\`\`\``;
}

function renderList($, element, context, ordered) {
  const lines = [];

  $(element).children("li").each((index, item) => {
    const itemClone = $(item).clone();
    itemClone.children("ul, ol").remove();

    const combined = { text: "", links: [] };
    for (const child of itemClone.get(0)?.children || []) {
      const piece = inlineContent($, child, context);
      combined.text += `${piece.text} `;
      combined.links.push(...piece.links);
    }

    const text = normalizeInlineText(combined.text);
    const prefix = ordered ? `${index + 1}) ` : "";
    if (text) lines.push(`* ${prefix}${text}`);

    for (const link of dedupeLinks(combined.links)) {
      lines.push(`=> ${link.href} ${link.label}`);
    }

    $(item).children("ul, ol").each((_, nested) => {
      const nestedRendered = renderList($, nested, context, nested.tagName.toLowerCase() === "ol");
      if (nestedRendered) {
        lines.push(...nestedRendered.split("\n").map((line) => line.startsWith("* ") ? `*   ${line.slice(2)}` : line));
      }
    });
  });

  return lines.join("\n");
}

function renderNode($, node, context) {
  if (!node) return "";

  if (node.type === "text") return normalizeInlineText(node.data);
  if (node.type !== "tag") return "";

  const tag = node.tagName.toLowerCase();
  const element = $(node);

  if (["script", "style", "svg", "noscript", "template"].includes(tag)) return "";
  if (element.attr("aria-hidden") === "true") return "";
  if (element.hasClass("media-row__item--empty")) return "";

  if (/^h[1-6]$/.test(tag)) {
    const level = Math.min(Number(tag.slice(1)), 3);
    const text = normalizeInlineText(element.text());
    return text ? `${"#".repeat(level)} ${text}` : "";
  }

  if (tag === "p") return renderInlineBlock($, node, context);
  if (tag === "figure") return renderFigure($, node, context);
  if (tag === "img") {
    const src = rewriteHref(element.attr("src"), context);
    const label = visibleMediaLinkLabel(src, element.attr("alt"));
    return src ? `=> ${src} ${label}` : "";
  }
  if (tag === "iframe" || tag === "video" || tag === "audio") return renderEmbed($, node, context);
  if (tag === "pre") return renderPreformatted($, node);
  if (tag === "table") return renderTable($, node);
  if (tag === "ul") return renderList($, node, context, false);
  if (tag === "ol") return renderList($, node, context, true);
  if (tag === "blockquote") {
    const inner = renderChildren($, node, context);
    return inner
      .split("\n")
      .map((line) => line ? `> ${line}` : ">")
      .join("\n");
  }
  if (tag === "hr") return "----------";
  if (tag === "a") {
    const href = rewriteHref(element.attr("href"), context);

    if (!href) {
      const children = renderChildren($, node, context);
      return isGenericDeadLinkLabel(children) ? "" : children;
    }

    const image = element.find("img").first();
    if (image.length) {
      const label = visibleMediaLinkLabel(href, image.attr("alt"));
      return `=> ${href} ${label}`;
    }

    const label = linkLabel($, node, href);
    return `=> ${href} ${label}`;
  }
  if (tag === "br") return "\n";

  return renderChildren($, node, context);
}

function renderChildren($, parent, context) {
  const blocks = [];
  for (const child of parent.children || []) {
    const rendered = normalizeMultilineText(renderNode($, child, context));
    if (rendered) blocks.push(rendered);
  }
  return blocks.join("\n\n");
}

function prepareContentRoot(html, selectors) {
  const $ = cheerio.load(html);
  $("script, style, svg, noscript, template").remove();
  $("header.site-header, footer, nav, .breadcrumbs, .post-navigation").remove();

  for (const selector of selectors) {
    const selected = $(selector).first();
    if (selected.length) return { $, node: selected.get(0) };
  }

  return { $, node: $("body").get(0) };
}

function renderHtmlFragment(html, context) {
  if (!html) return "";
  const $ = cheerio.load(`<div id="gemini-root">${html}</div>`);
  return normalizeMultilineText(renderChildren($, $("#gemini-root").get(0), context));
}

function renderArticleHtml(html, context) {
  const { $, node } = prepareContentRoot(html, ["article", "main"]);
  return normalizeMultilineText(renderChildren($, node, context));
}

function identifyHomepageSection(title, href) {
  const haystack = `${normalizeSectionValue(title)} ${normalizeSectionValue(href)}`;
  if (haystack.includes("volna-tvorba") || haystack.includes("volná tvorba") || haystack.includes("personal work")) return "personalWork";
  if (haystack.includes("vystav") || haystack.includes("výstav") || haystack.includes("exhibition")) return "exhibitions";
  if (haystack.includes("cestov") || haystack.includes("travel")) return "travel";
  if (
    haystack.includes("video") ||
    haystack.includes("videa") ||
    haystack.includes("propagační") ||
    haystack.includes("propagacni") ||
    haystack.includes("youtube.com/playlist")
  ) return "videos";
  if (haystack.includes("o mně") || haystack.includes("o mne") || haystack.includes("about")) return "about";
  if (haystack.includes("kontakt") || haystack.includes("contact")) return "contact";
  return null;
}

async function readHomepage(distDir, lang, siteUrl, warnings) {
  const filePath = lang === "en"
    ? path.join(distDir, "en", "index.html")
    : path.join(distDir, "index.html");

  if (!(await exists(filePath))) {
    warnings.push(`Missing ${lang.toUpperCase()} homepage: ${normalizeSlashes(path.relative(ROOT, filePath))}`);
    return null;
  }

  const html = await fs.readFile(filePath, "utf8");
  const $ = cheerio.load(html);
  const sections = {};

  $(".home-section").each((_, sectionElement) => {
    const section = $(sectionElement);
    const heading = section.find(".section-header .page-title").first();
    const headingLink = heading.find("a").first();
    const title = normalizeInlineText(heading.text());
    const href = headingLink.attr("href") || "";
    const key = identifyHomepageSection(title, href);
    if (!key) return;

    const items = [];
    let moreHref = "";

    section.find(".post-grid a.post-card").each((__, cardElement) => {
      const card = $(cardElement);

      if (card.hasClass("post-card--more")) {
        moreHref = card.attr("href") || moreHref;
        return;
      }

      const itemHref = card.attr("href") || "";
      const itemTitle =
        normalizeInlineText(card.find(".post-card__title").first().text()) ||
        normalizeInlineText(card.text());

      if (itemHref && itemTitle) items.push({ href: itemHref, title: itemTitle });
    });

    sections[key] = {
      title: title || SECTION_DEFINITIONS[key][lang].title,
      description: normalizeInlineText(section.find(".section-description").first().text()),
      href,
      moreHref,
      items,
      aboutHtml: section.find(".home-about").first().html() || "",
      contactHtml: section.find(".home-contact").first().html() || "",
    };
  });

  return {
    filePath,
    html,
    canonicalUrl: canonicalUrlFromHtml(html, lang === "en" ? `${siteUrl}/en/` : `${siteUrl}/`),
    motto: normalizeInlineText($(".site-header__motto").first().text()),
    sections,
  };
}

function pageNavigation(lang, sectionKey = null, counterpart = null, currentCapsulePath = null) {
  const lines = [
    `=> ${capsuleHref(homepageCapsulePath(lang), currentCapsulePath)} ${lang === "cs" ? "Domů" : "Home"}`,
  ];
  if (sectionKey) {
    lines.push(
      `=> ${capsuleHref(sectionRoot(lang, sectionKey), currentCapsulePath)} ${SECTION_DEFINITIONS[sectionKey][lang].title}`,
    );
  }
  if (counterpart) {
    lines.push(`=> ${capsuleHref(counterpart.href, currentCapsulePath)} ${counterpart.label}`);
  }
  return lines.join("\n");
}

function ensurePageHeading(content, title) {
  if (/^#\s+/m.test(content)) return content;
  return `# ${title}\n\n${content}`;
}

function originalWebsiteLink(lang, url) {
  return `=> ${url} ${lang === "cs" ? "Plná webová verze" : "Full web version"}`;
}

async function generateArticles(posts, outputDir, siteUrl, routeMap, stats) {
  for (const post of posts) {
    for (const lang of ["en", "cs"]) {
      const page = post.languages[lang];
      if (!page) continue;

      const counterpartLang = lang === "en" ? "cs" : "en";
      const counterpartPage = post.languages[counterpartLang];
      const counterpart = counterpartPage
        ? {
            href: articleCapsulePath(counterpartLang, post.sectionKey, post.slug),
            label: counterpartLang === "cs" ? "Česká verze" : "English version",
          }
        : null;

      const currentCapsulePath = articleCapsulePath(lang, post.sectionKey, post.slug);
      const context = {
        siteUrl,
        routeMap,
        currentWebUrl: page.canonicalUrl,
        currentCapsulePath,
      };

      let body = renderArticleHtml(page.html, context);
      body = ensurePageHeading(body, page.title);

      const content = [
        pageNavigation(lang, post.sectionKey, counterpart, currentCapsulePath),
        body,
        originalWebsiteLink(lang, page.canonicalUrl),
      ].filter(Boolean).join("\n\n");

      await writeUtf8(articleOutputPath(outputDir, lang, post.sectionKey, post.slug), content);
      stats.articlePages += 1;
    }
  }
}

function homepageSectionTitle(homepage, lang, sectionKey) {
  return homepage?.sections?.[sectionKey]?.title || SECTION_DEFINITIONS[sectionKey][lang].title;
}

function homepageSectionDescription(homepage, sectionKey) {
  return homepage?.sections?.[sectionKey]?.description || "";
}

function routeHomepageItems(items, context) {
  return items
    .map((item) => ({
      title: item.title,
      href: rewriteHref(item.href, context),
    }))
    .filter((item) => item.href);
}

async function generateHomepage(lang, homepage, outputDir, siteUrl, routeMap, stats) {
  const otherLang = lang === "en" ? "cs" : "en";
  const currentCapsulePath = homepageCapsulePath(lang);
  const context = {
    siteUrl,
    routeMap,
    currentWebUrl: homepage?.canonicalUrl || (lang === "en" ? `${siteUrl}/en/` : `${siteUrl}/`),
    currentCapsulePath,
  };
  const showAllLabel = lang === "cs" ? "ZOBRAZIT VŠE" : "SHOW ALL";

  const lines = [
    "# Vojta Maur",
    homepage?.motto || (lang === "cs" ? "Tvořit je můj základní instinkt" : "Creating is my basic instinct"),
    "",
    `=> ${capsuleHref(homepageCapsulePath(otherLang), currentCapsulePath)} ${otherLang === "cs" ? "Čeština" : "English"}`,
    "",
    lang === "cs"
      ? "Toto je zjednodušená Gemini verze osobního webu Vojty Maura. Obrázky, PDF, videa a interaktivní ukázky zůstávají dostupné přes odkazy na hlavní web."
      : "This is a simplified Gemini version of Vojta Maur\'s personal website. Images, PDFs, videos and interactive demonstrations remain available through links to the main website.",
  ];

  for (const sectionKey of SECTION_ORDER) {
    const sectionData = homepage?.sections?.[sectionKey];
    const title = homepageSectionTitle(homepage, lang, sectionKey);
    const description = homepageSectionDescription(homepage, sectionKey);

    lines.push("", `## ${title}`);
    if (description) lines.push(description);

    if (POST_SECTION_KEYS.has(sectionKey)) {
      const items = routeHomepageItems(sectionData?.items || [], context).slice(0, 9);
      for (const item of items) lines.push(`=> ${item.href} ${item.title}`);

      if (sectionData?.moreHref) {
        lines.push(
          `=> ${capsuleHref(sectionRoot(lang, sectionKey), currentCapsulePath)} ${showAllLabel}`,
        );
      }
      continue;
    }

    if (sectionKey === "videos") {
      const items = routeHomepageItems(sectionData?.items || [], context);
      for (const item of items) lines.push(`=> ${item.href} ${item.title}`);

      const playlist = rewriteHref(sectionData?.moreHref || sectionData?.href, context);
      if (playlist) lines.push(`=> ${playlist} ${showAllLabel}`);
      continue;
    }

    if (sectionKey === "about" || sectionKey === "contact") {
      const sourceHtml = sectionKey === "about"
        ? sectionData?.aboutHtml
        : sectionData?.contactHtml;
      const rendered = renderHtmlFragment(sourceHtml || "", context);

      if (rendered) {
        lines.push(rendered);
      } else {
        lines.push(
          lang === "cs"
            ? "Obsah této sekce nebyl v hotovém buildu nalezen."
            : "This section was not found in the built website.",
        );
      }
    }
  }

  lines.push("", originalWebsiteLink(lang, homepage?.canonicalUrl || context.currentWebUrl));

  const target = lang === "cs"
    ? path.join(outputDir, "cs", "index.gmi")
    : path.join(outputDir, "index.gmi");
  await writeUtf8(target, lines.join("\n"));
  stats.homePages += 1;
}

async function generatePostSectionIndex(lang, sectionKey, posts, homepage, outputDir, siteUrl, stats) {
  const definition = SECTION_DEFINITIONS[sectionKey];
  const sectionData = homepage?.sections?.[sectionKey];
  const title = sectionData?.title || definition[lang].title;
  const description = sectionData?.description || "";
  const currentCapsulePath = sectionRoot(lang, sectionKey);
  const lines = [
    pageNavigation(lang, null, {
      href: sectionRoot(lang === "en" ? "cs" : "en", sectionKey),
      label: lang === "cs" ? "English version" : "Česká verze",
    }, currentCapsulePath),
    "",
    `# ${title}`,
  ];

  if (description) lines.push("", description);

  const relevantPosts = posts.filter((post) => post.sectionKey === sectionKey && post.languages[lang]);
  for (const post of relevantPosts) {
    const page = post.languages[lang];
    lines.push(
      `=> ${capsuleHref(articleCapsulePath(lang, sectionKey, post.slug), currentCapsulePath)} ${page.title}`,
    );
  }

  if (relevantPosts.length === 0) {
    lines.push("", lang === "cs" ? "V této sekci nejsou žádné dostupné položky." : "No entries are available in this section.");
  }

  if (sectionData?.href) {
    try {
      lines.push("", originalWebsiteLink(lang, new URL(sectionData.href, siteUrl).toString()));
    } catch {
      // Invalid source href is simply omitted.
    }
  }

  const target = lang === "cs"
    ? path.join(outputDir, "cs", definition.cs.dir, "index.gmi")
    : path.join(outputDir, definition.en.dir, "index.gmi");
  await writeUtf8(target, lines.join("\n"));
  stats.sectionPages += 1;
}


function cleanGopherLabel(value) {
  return normalizeInlineText(value)
    .replace(/[\t\r\n]/g, " ")
    .replace(/ {2,}/g, " ")
    .trim();
}

function gopherLine(type, label, selector = "", host = GOPHER_HOST, port = GOPHER_PORT) {
  const safeLabel = cleanGopherLabel(label) || " ";
  if (!selector) return `${type}${safeLabel}`;
  return `${type}${safeLabel}\t${selector}\t${host}\t${port}`;
}

function gopherInfo(label = "") {
  return gopherLine("i", label || " ");
}

function gopherText(label, toCapsulePath) {
  return gopherLine("0", label, gopherSelector(toCapsulePath));
}

function gopherDirectory(label, toCapsulePath) {
  return gopherLine("1", label, gopherDirectorySelector(toCapsulePath));
}

function gopherWeb(label, url) {
  const target = normalizeInlineText(url);
  if (!target) return "";
  return gopherLine("h", label, `URL:${target}`);
}

function capsuleDirectory(capsulePath) {
  const normalized = normalizeCapsulePath(capsulePath);
  if (!normalized || normalized === "index.gmi") return "";
  const directory = path.posix.dirname(normalized);
  return directory === "." ? "" : directory;
}

async function writeGopherMap(outputDir, capsulePathOrDirectory, lines, stats) {
  const normalized = normalizeCapsulePath(capsulePathOrDirectory);
  const directory = normalized.endsWith(".gmi")
    ? capsuleDirectory(normalized)
    : normalized.replace(/\/+$/, "");
  const parts = directory ? directory.split("/") : [];
  const target = path.join(outputDir, ...parts, "gophermap");
  const content = lines.filter((line) => line !== "").join("\n");
  await writeUtf8(target, content);
  stats.gopherMaps += 1;
}

function gopherHomepageLines(lang, homepage, siteUrl) {
  const otherLang = lang === "en" ? "cs" : "en";
  const lines = [
    gopherInfo("Vojta Maur"),
    gopherInfo(homepage?.motto || (lang === "cs" ? "Tvořit je můj základní instinkt" : "Creating is my basic instinct")),
    gopherInfo(),
    gopherText(lang === "cs" ? "Gemtext hlavní stránka" : "Gemtext homepage", homepageCapsulePath(lang)),
    gopherDirectory(otherLang === "cs" ? "Čeština" : "English", homepageCapsulePath(otherLang)),
    gopherInfo(),
  ];

  for (const sectionKey of POST_SECTION_KEYS) {
    lines.push(gopherDirectory(homepageSectionTitle(homepage, lang, sectionKey), sectionRoot(lang, sectionKey)));
  }

  const sectionData = homepage?.sections?.videos;
  const videoItems = sectionData?.items || [];
  if (videoItems.length > 0 || sectionData?.moreHref || sectionData?.href) {
    lines.push(gopherInfo(), gopherInfo(homepageSectionTitle(homepage, lang, "videos")));
    for (const item of videoItems) {
      try {
        lines.push(gopherWeb(item.title, new URL(item.href, siteUrl).toString()));
      } catch {
        // Invalid source URL is omitted.
      }
    }
    try {
      const playlist = sectionData?.moreHref || sectionData?.href;
      if (playlist) lines.push(gopherWeb(lang === "cs" ? "ZOBRAZIT VŠE" : "SHOW ALL", new URL(playlist, siteUrl).toString()));
    } catch {
      // Invalid source URL is omitted.
    }
  }

  lines.push(gopherInfo());
  lines.push(gopherWeb(lang === "cs" ? "Plná webová verze" : "Full web version", homepage?.canonicalUrl || (lang === "en" ? `${siteUrl}/en/` : `${siteUrl}/`)));

  return lines;
}

function gopherSectionLines(lang, sectionKey, posts, homepage, siteUrl) {
  const otherLang = lang === "en" ? "cs" : "en";
  const title = homepageSectionTitle(homepage, lang, sectionKey);
  const description = homepageSectionDescription(homepage, sectionKey);
  const relevantPosts = posts.filter((post) => post.sectionKey === sectionKey && post.languages[lang]);
  const lines = [
    gopherInfo("Vojta Maur"),
    gopherInfo(title),
  ];

  if (description) lines.push(gopherInfo(description));

  lines.push(
    gopherInfo(),
    gopherDirectory(lang === "cs" ? "Domů" : "Home", homepageCapsulePath(lang)),
    gopherDirectory(lang === "cs" ? "English version" : "Česká verze", sectionRoot(otherLang, sectionKey)),
    gopherText(lang === "cs" ? "Gemtext index sekce" : "Gemtext section index", sectionRoot(lang, sectionKey)),
    gopherInfo(),
  );

  if (relevantPosts.length === 0) {
    lines.push(gopherInfo(lang === "cs" ? "V této sekci nejsou žádné dostupné položky." : "No entries are available in this section."));
  } else {
    for (const post of relevantPosts) {
      const page = post.languages[lang];
      lines.push(gopherText(page.title, articleCapsulePath(lang, sectionKey, post.slug)));
    }
  }

  const sectionData = homepage?.sections?.[sectionKey];
  if (sectionData?.href) {
    try {
      lines.push(gopherInfo(), gopherWeb(lang === "cs" ? "Plná webová verze" : "Full web version", new URL(sectionData.href, siteUrl).toString()));
    } catch {
      // Invalid source URL is omitted.
    }
  }

  return lines;
}

async function generateGopherMaps(posts, homepageData, outputDir, siteUrl, stats) {
  for (const lang of ["en", "cs"]) {
    const homepage = homepageData[lang];
    await writeGopherMap(outputDir, homepageCapsulePath(lang), gopherHomepageLines(lang, homepage, siteUrl), stats);

    for (const sectionKey of POST_SECTION_KEYS) {
      await writeGopherMap(outputDir, sectionRoot(lang, sectionKey), gopherSectionLines(lang, sectionKey, posts, homepage, siteUrl), stats);
    }
  }
}


async function copyFirstExisting(candidates, destination, stats) {
  for (const source of candidates) {
    if (await exists(source)) {
      await ensureParent(destination);
      await fs.copyFile(source, destination);
      stats.copiedFiles += 1;
      return source;
    }
  }
  return null;
}

async function copyDirectoryIfPresent(source, destination, stats) {
  if (!(await exists(source))) return false;
  await fs.cp(source, destination, { recursive: true, force: true });

  const countFiles = async (directory) => {
    let count = 0;
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) count += await countFiles(entryPath);
      else count += 1;
    }
    return count;
  };

  stats.copiedFiles += await countFiles(source);
  return true;
}

function assertSafeOutputDirectory(outputDir, distDir) {
  const resolvedOutput = path.resolve(outputDir);
  const resolvedRoot = path.resolve(ROOT);
  const resolvedDist = path.resolve(distDir);
  const filesystemRoot = path.parse(resolvedOutput).root;

  if ([resolvedRoot, resolvedDist, filesystemRoot].includes(resolvedOutput)) {
    throw new Error(`Refusing to delete unsafe output directory: ${resolvedOutput}`);
  }

  if (!path.basename(resolvedOutput).toLowerCase().includes("gemini")) {
    throw new Error(`Refusing to replace output directory without "gemini" in its name: ${resolvedOutput}`);
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const { distDir, outputDir, contentDir, siteUrl } = options;
  const warnings = [];
  const stats = {
    articlePages: 0,
    sectionPages: 0,
    homePages: 0,
    gopherMaps: 0,
    copiedFiles: 0,
  };

  if (!(await exists(distDir))) {
    throw new Error(`Built web directory does not exist: ${distDir}. Run the web build first.`);
  }

  assertSafeOutputDirectory(outputDir, distDir);

  const homepageData = {
    cs: await readHomepage(distDir, "cs", siteUrl, warnings),
    en: await readHomepage(distDir, "en", siteUrl, warnings),
  };
  const posts = await getPosts(contentDir, distDir, siteUrl, warnings);
  const routeMap = buildRouteMap(posts, homepageData, siteUrl);

  await fs.rm(outputDir, { recursive: true, force: true });
  await fs.mkdir(outputDir, { recursive: true });

  await generateArticles(posts, outputDir, siteUrl, routeMap, stats);

  for (const lang of ["en", "cs"]) {
    const homepage = homepageData[lang];
    await generateHomepage(lang, homepage, outputDir, siteUrl, routeMap, stats);

    for (const sectionKey of ["personalWork", "exhibitions", "travel"]) {
      await generatePostSectionIndex(lang, sectionKey, posts, homepage, outputDir, siteUrl, stats);
    }

  }

  await generateGopherMaps(posts, homepageData, outputDir, siteUrl, stats);

  await copyFirstExisting(
    [path.join(distDir, "favicon.txt"), path.join(ROOT, "public", "favicon.txt")],
    path.join(outputDir, "favicon.txt"),
    stats,
  );

  const copiedDistKeys = await copyDirectoryIfPresent(
    path.join(distDir, "keys"),
    path.join(outputDir, "keys"),
    stats,
  );
  if (!copiedDistKeys) {
    await copyDirectoryIfPresent(path.join(ROOT, "public", "keys"), path.join(outputDir, "keys"), stats);
  }

  const totalPages = stats.articlePages + stats.sectionPages + stats.homePages;
  console.log(`[GEMINI] Written ${normalizeSlashes(path.relative(ROOT, outputDir))}/`);
  console.log(`[GEMINI] Pages: ${totalPages} (${stats.articlePages} articles, ${stats.sectionPages} sections, ${stats.homePages} homepages)`);
  console.log(`[GEMINI] Source posts: ${posts.length}`);
  console.log(`[GEMINI] Gopher maps: ${stats.gopherMaps}`);
  console.log(`[GEMINI] Copied static files: ${stats.copiedFiles}`);

  if (warnings.length > 0) {
    console.warn(`[GEMINI] Warnings: ${warnings.length}`);
    for (const warning of warnings) console.warn(`[GEMINI] ${warning}`);
  }
}

main().catch((error) => {
  console.error("[GEMINI] Failed:");
  console.error(error);
  process.exit(1);
});
