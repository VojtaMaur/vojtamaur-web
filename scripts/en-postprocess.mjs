import { readdir, readFile, writeFile, mkdir, unlink } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import * as cheerio from "cheerio";
import { i18nConfig } from "./i18n-config.mjs";

const DIST_DIR = process.env.DIST_DIR || "dist";
const MODE = process.env.EN_TRANSLATE || "off"; // off | missing | refresh
const STRICT = process.env.EN_STRICT === "1" || process.env.EN_STRICT === "true";
const AUTH_KEY = process.env.DEEPL_AUTH_KEY;
const DEEPL_API_URL =
  process.env.DEEPL_API_URL ||
  (AUTH_KEY?.endsWith(":fx")
    ? "https://api-free.deepl.com/v2/translate"
    : "https://api.deepl.com/v2/translate");

const PRUNE_CACHE = process.env.EN_PRUNE_CACHE === "1" || process.env.EN_PRUNE_CACHE === "true";
const PRUNE_DRY_RUN = process.env.EN_PRUNE_CACHE === "dry-run";
const usedCacheHashes = new Set();

const VALID_MODES = new Set(["off", "missing", "refresh"]);
if (!VALID_MODES.has(MODE)) {
  throw new Error(`Invalid EN_TRANSLATE=${MODE}. Use off, missing, or refresh.`);
}

async function walkHtmlFiles(dir) {
  const files = [];
  if (!existsSync(dir)) return files;

  async function walk(current) {
    const entries = await readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) await walk(full);
      else if (entry.isFile() && entry.name.endsWith(".html")) files.push(full);
    }
  }

  await walk(dir);
  return files;
}

function normalizeRel(filePath) {
  return path.relative(DIST_DIR, filePath).split(path.sep).join("/");
}

function localeForFile(filePath) {
  const rel = normalizeRel(filePath);
  if (rel === "en.html" || rel === "en/index.html" || rel.startsWith("en/")) return "en";
  return "cs";
}

function routeForFile(filePath) {
  let rel = normalizeRel(filePath);
  rel = rel.replace(/index\.html$/, "");
  rel = rel.replace(/\.html$/, "");
  if (!rel.startsWith("/")) rel = `/${rel}`;
  if (!rel.endsWith("/")) rel += "/";
  return rel.replace(/\/\/+/, "/");
}

function sha256(input) {
  return createHash("sha256").update(input).digest("hex");
}

function cacheKey({ routePath, purpose, sourceFragment }) {
  const cfg = i18nConfig;
  return sha256([
    `schema:${cfg.hashSchemaVersion}`,
    `purpose:${purpose}`,
    `route:${routePath}`,
    `${cfg.sourceLang}->${cfg.targetLang}`,
    `glossary:${cfg.glossaryRevision}`,
    `tag:${cfg.deepl.tagHandling}:${cfg.deepl.tagHandlingVersion}`,
    `split:${cfg.deepl.splitSentences}`,
    `preserve:${cfg.deepl.preserveFormatting}`,
    `formality:${cfg.deepl.formality ?? "none"}`,
    `selectorPolicy:${cfg.selectorPolicyRevision}`,
    sourceFragment
  ].join("\0"));
}

async function readCache(hash) {
  const file = path.join(i18nConfig.cacheDir, `${hash}.json`);
  if (!existsSync(file)) return null;
  return JSON.parse(await readFile(file, "utf8"));
}

async function readCacheFile(file) {
  return JSON.parse(await readFile(file, "utf8"));
}

async function writeCache(hash, entry) {
  await mkdir(i18nConfig.cacheDir, { recursive: true });
  const file = path.join(i18nConfig.cacheDir, `${hash}.json`);
  await writeFile(file, `${JSON.stringify(entry, null, 2)}\n`, "utf8");
}

function isProtectedCacheEntry(entry) {
  return entry?.manual === true || entry?.locked === true || entry?.edited === true;
}

function byteLength(value) {
  return Buffer.byteLength(value, "utf8");
}

function protectFragment($, root) {
  $(i18nConfig.protectSelector, root).each((_, el) => {
    const currentClass = ($(el).attr("class") || "").split(/\s+/).filter(Boolean);
    if (!currentClass.includes("notranslate")) currentClass.push("notranslate");
    $(el).attr("class", currentClass.join(" "));
    $(el).attr("translate", "no");
  });
}

function prepareSourceFragment(rootHtml) {
  const $$ = cheerio.load(`<div id="__i18n_root__">${rootHtml}</div>`, { decodeEntities: false });
  const root = $$("#__i18n_root__");
  const protectedFragments = [];

  protectFragment($$, root);

  $$(i18nConfig.protectSelector, root).each((index, el) => {
    const id = `p${index}`;
    protectedFragments.push({
      id,
      html: $$.html(el)
    });

    $$(el).replaceWith(
      `<span data-i18n-protected="${id}" translate="no" class="notranslate"></span>`
    );
  });

  return {
    sourceFragment: root.html() || "",
    protectedFragments
  };
}

function restoreProtectedFragments(fragment, protectedFragments) {
  if (protectedFragments.length === 0) return fragment;

  const $$ = cheerio.load(`<div id="__i18n_root__">${fragment}</div>`, { decodeEntities: false });
  const root = $$("#__i18n_root__");

  for (const item of protectedFragments) {
    root.find(`[data-i18n-protected="${item.id}"]`).replaceWith(item.html);
  }

  return root.html() || "";
}

function hasTranslatableText(fragment) {
  const $$ = cheerio.load(`<div id="__i18n_root__">${fragment}</div>`, { decodeEntities: false });
  const root = $$("#__i18n_root__");
  root.find("[data-i18n-protected]").remove();
  return root.text().replace(/\s+/g, "").length > 0;
}

function applyLangBlocks($, locale) {
  $("[data-lang-only]").each((_, el) => {
    const only = String($(el).attr("data-lang-only") || "").toLowerCase();
    if (only === locale) $(el).replaceWith($(el).html() || "");
    else $(el).remove();
  });
}

function markNoIndex($) {
  const head = $("head");
  if (head.length === 0) return;

  const robots = head.find('meta[name="robots"]');
  if (robots.length > 0) robots.attr("content", "noindex,follow");
  else head.append('\n<meta name="robots" content="noindex,follow">\n');
}

async function deeplRequest(text, routePath, pageTitle, { html = true } = {}) {
  if (!AUTH_KEY) throw new Error("DEEPL_AUTH_KEY is not set.");

  const body = new URLSearchParams();
  body.set("text", text);
  body.set("source_lang", i18nConfig.sourceLang);
  body.set("target_lang", i18nConfig.targetLang);

  if (html) {
    body.set("tag_handling", i18nConfig.deepl.tagHandling);
    body.set("tag_handling_version", i18nConfig.deepl.tagHandlingVersion);
    body.set("split_sentences", i18nConfig.deepl.splitSentences);
    body.set("preserve_formatting", i18nConfig.deepl.preserveFormatting ? "1" : "0");
  }

  if (i18nConfig.deepl.formality) {
    body.set("formality", i18nConfig.deepl.formality);
  }

  const context = pageTitle ? `Page title: ${pageTitle}. Route: ${routePath}.` : `Route: ${routePath}.`;
  body.set("context", context);

  const data = await withRetry(async () => {
    const response = await fetch(DEEPL_API_URL, {
      method: "POST",
      headers: {
        "authorization": `DeepL-Auth-Key ${AUTH_KEY}`,
        "content-type": "application/x-www-form-urlencoded"
      },
      body
    });

    if (!response.ok) {
      const message = await response.text().catch(() => "");
      const error = new Error(`DeepL HTTP ${response.status}: ${message}`);
      error.status = response.status;
      throw error;
    }

    return response.json();
  });

  const translated = data?.translations?.[0]?.text;
  if (!translated || !translated.trim()) throw new Error(`DeepL returned empty translation for ${routePath}.`);
  return translated;
}

async function withRetry(fn) {
  let lastError;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      const status = error?.statusCode || error?.status || error?.code;
      const retryable = status === 429 || status === 500 || status === 502 || status === 503 || status === 504;
      if (!retryable || attempt === 3) break;
      const delay = 750 * 2 ** attempt;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
  throw lastError;
}

async function translateWithCache({ routePath, purpose, source, pageTitle, html }) {
  if (!source || !source.trim()) return { text: source, status: "empty" };

  const hash = cacheKey({ routePath, purpose, sourceFragment: source });
  let entry = await readCache(hash);

  if (entry && isProtectedCacheEntry(entry) && MODE === "refresh") {
    console.warn(`[i18n] Protected cache entry kept during refresh: ${hash}`);
  } else if (!entry || MODE === "refresh") {
    if (MODE === "off") {
      if (STRICT) {
        throw new Error(`Missing EN translation cache for ${routePath} (${purpose}, ${hash}). Run npm run build:web:translate or disable EN_STRICT.`);
      }
      return { text: source, status: "missing", hash };
    }

    if (html && byteLength(source) > i18nConfig.maxFragmentBytes) {
      throw new Error(`EN fragment for ${routePath} is ${byteLength(source)} bytes, above configured ${i18nConfig.maxFragmentBytes}. Split this article/region before translating. Tiny systems beat heroic garbage.`);
    }

    const translated = await deeplRequest(source, routePath, pageTitle, { html });
    entry = {
      schemaVersion: i18nConfig.hashSchemaVersion,
      hash,
      purpose,
      page: routePath,
      sourceLang: i18nConfig.sourceLang,
      targetLang: i18nConfig.targetLang,
      glossaryRevision: i18nConfig.glossaryRevision,
      deepl: i18nConfig.deepl,
      selectorPolicyRevision: i18nConfig.selectorPolicyRevision,
      manual: false,
      locked: false,
      edited: false,
      editedAt: null,
      editedBy: null,
      sourceFragment: source,
      translatedFragment: translated,
      createdAt: new Date().toISOString()
    };
    await writeCache(hash, entry);
  }

  usedCacheHashes.add(hash);
  return { text: entry.translatedFragment, status: "ok", hash };
}

async function processFile(filePath) {
  const locale = localeForFile(filePath);
  const routePath = routeForFile(filePath);
  const originalHtml = await readFile(filePath, "utf8");
  const $ = cheerio.load(originalHtml, { decodeEntities: false });
  let changed = false;
  let pageIncomplete = false;

  applyLangBlocks($, locale);
  changed = true;

  if (locale !== "en") {
    if (changed) await writeFile(filePath, $.html(), "utf8");
    return { translated: 0, missing: 0, skipped: 0 };
  }

  const pageTitle = ($("title").first().text() || $("h1").first().text() || "").trim();
  const roots = $(i18nConfig.translateSelector).toArray();

  if (roots.length === 0) {
    await writeFile(filePath, $.html(), "utf8");
    return { translated: 0, missing: 0, skipped: 1 };
  }

  let translated = 0;
  let missing = 0;

  for (const root of roots) {
    const originalRootHtml = $(root).html() || "";
    const { sourceFragment, protectedFragments } = prepareSourceFragment(originalRootHtml);
    if (!sourceFragment.trim()) continue;

    if (!hasTranslatableText(sourceFragment)) {
      // The whole region is protected with <NoTranslate> / code / embeds.
      // Leave the original DOM untouched and do not waste a DeepL request.
      continue;
    }

    const result = await translateWithCache({
      routePath,
      purpose: "html-region",
      source: sourceFragment,
      pageTitle,
      html: true
    });

    if (result.status === "missing") {
      missing += 1;
      pageIncomplete = true;
      continue;
    }

    $(root).html(restoreProtectedFragments(result.text, protectedFragments));
    translated += 1;
    changed = true;
  }

  // Keep <title> and meta description English too. This deliberately does not
  // translate alt/thumbnailAlt or arbitrary HTML attributes.
  const translatedH1 = $("h1").first().text().trim();
  const rawTitle = $("title").first().text().trim();
  const siteSuffix = " | Vojta Maur";

  if (translatedH1 && rawTitle) {
    const nextTitle = rawTitle.includes("|") ? `${translatedH1}${siteSuffix}` : translatedH1;
    $("title").first().text(nextTitle);
    changed = true;
  }

  const metaDescription = $('meta[name="description"]').first();
  const rawDescription = metaDescription.attr("content") || "";
  if (rawDescription.trim()) {
    const result = await translateWithCache({
      routePath,
      purpose: "meta-description",
      source: rawDescription,
      pageTitle: translatedH1 || pageTitle,
      html: false
    });

    if (result.status === "missing") {
      missing += 1;
      pageIncomplete = true;
    } else {
      metaDescription.attr("content", result.text);
      translated += 1;
      changed = true;
    }
  }

  if (pageIncomplete) {
    markNoIndex($);
    changed = true;
  }

  if (changed) await writeFile(filePath, $.html(), "utf8");
  return { translated, missing, skipped: 0 };
}

async function pruneUnusedCache() {
  if (!PRUNE_CACHE && !PRUNE_DRY_RUN) {
    return {
      kept: 0,
      deleted: 0,
      wouldDelete: 0,
      lockedKept: 0,
      invalidKept: 0
    };
  }

  if (!existsSync(i18nConfig.cacheDir)) {
    return {
      kept: 0,
      deleted: 0,
      wouldDelete: 0,
      lockedKept: 0,
      invalidKept: 0
    };
  }

  const entries = await readdir(i18nConfig.cacheDir, { withFileTypes: true });
  let kept = 0;
  let deleted = 0;
  let wouldDelete = 0;
  let lockedKept = 0;
  let invalidKept = 0;

  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;

    const hash = entry.name.replace(/\.json$/, "");
    const file = path.join(i18nConfig.cacheDir, entry.name);

    if (usedCacheHashes.has(hash)) {
      kept += 1;
      continue;
    }

    let cacheEntry;
    try {
      cacheEntry = await readCacheFile(file);
    } catch (error) {
      invalidKept += 1;
      console.warn(`[i18n] prune: keeping unreadable cache file ${file}: ${error.message}`);
      continue;
    }

    if (isProtectedCacheEntry(cacheEntry)) {
      lockedKept += 1;
      console.log(`[i18n] prune: keeping protected cache file ${file}`);
      continue;
    }

    if (PRUNE_DRY_RUN) {
      wouldDelete += 1;
      console.log(`[i18n] prune dry-run: would delete ${file}`);
    } else {
      await unlink(file);
      deleted += 1;
      console.log(`[i18n] prune: deleted ${file}`);
    }
  }

  return {
    kept,
    deleted,
    wouldDelete,
    lockedKept,
    invalidKept
  };
}

async function main() {
  const files = await walkHtmlFiles(DIST_DIR);
  let translated = 0;
  let missing = 0;
  let skipped = 0;

  if (files.length === 0) {
    console.log(`[i18n] No HTML files found in ${DIST_DIR}.`);
    return;
  }

  for (const file of files) {
    const result = await processFile(file);
    translated += result.translated;
    missing += result.missing;
    skipped += result.skipped;
  }

  const pruneResult = await pruneUnusedCache();

  console.log(
    `[i18n] mode=${MODE}, strict=${STRICT ? "yes" : "no"}, translated/cache-used=${translated}, missing=${missing}, skipped=${skipped}, cache-kept=${pruneResult.kept}, cache-deleted=${pruneResult.deleted}, cache-would-delete=${pruneResult.wouldDelete}, cache-locked-kept=${pruneResult.lockedKept}, cache-invalid-kept=${pruneResult.invalidKept}`
  );

  if (missing > 0 && !STRICT) {
    console.warn(`[i18n] ${missing} EN item(s) had no cache and were left in source language with noindex on affected pages. Run build:*:translate before publishing.`);
  }
}

main().catch((error) => {
  console.error("[i18n] Postprocess failed:");
  console.error(error);
  process.exit(1);
});