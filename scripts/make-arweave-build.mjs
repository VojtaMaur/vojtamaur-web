import fs from "node:fs/promises";
import path from "node:path";

const SOURCE = "dist";
const TARGET = "dist-arweave";

function toPosix(p) {
  return p.split(path.sep).join("/");
}

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function walk(dir) {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const full = path.join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...await walk(full));
    } else {
      files.push(full);
    }
  }

  return files;
}

async function resolveRootPath(urlPath) {
  const [pathPartWithQuery, hash = ""] = urlPath.split("#");
  const [pathPart, query = ""] = pathPartWithQuery.split("?");

  let clean = pathPart.replace(/^\/+/, "");

  if (clean === "") {
    clean = "index.html";
  } else if (clean.endsWith("/")) {
    clean = `${clean}index.html`;
  } else {
    const asDirIndex = path.join(TARGET, clean, "index.html");
    const asHtml = path.join(TARGET, `${clean}.html`);

    if (await exists(asDirIndex)) {
      clean = `${clean}/index.html`;
    } else if (await exists(asHtml)) {
      clean = `${clean}.html`;
    }
  }

  return {
    clean: toPosix(clean),
    suffix: `${query ? `?${query}` : ""}${hash ? `#${hash}` : ""}`,
  };
}

async function makeRelative(fromFile, targetPath) {
  const fromRel = toPosix(path.relative(TARGET, fromFile));
  const fromDir = path.posix.dirname(fromRel);
  const baseDir = fromDir === "." ? "" : fromDir;

  let rel = path.posix.relative(baseDir, targetPath);

  if (!rel.startsWith(".") && !rel.startsWith("/")) {
    rel = `./${rel}`;
  }

  return rel;
}

async function rewriteRootUrl(fromFile, rawUrl) {
  if (!rawUrl.startsWith("/") || rawUrl.startsWith("//")) return rawUrl;

  const { clean, suffix } = await resolveRootPath(rawUrl);
  const rel = await makeRelative(fromFile, clean);

  return `${rel}${suffix}`;
}

async function rewriteHtml(file) {
  let html = await fs.readFile(file, "utf8");

  html = await replaceAsync(
    html,
    /\b(href|src|poster|action)=["'](\/(?!\/)[^"']*)["']/g,
    async (match, attr, url) => {
      const rewritten = await rewriteRootUrl(file, url);
      return `${attr}="${rewritten}"`;
    }
  );

  html = await replaceAsync(
    html,
    /\bsrcset=["']([^"']*)["']/g,
    async (match, srcset) => {
      const parts = await Promise.all(
        srcset.split(",").map(async (part) => {
          const trimmed = part.trim();
          const pieces = trimmed.split(/\s+/);
          const url = pieces[0];

          if (!url?.startsWith("/") || url.startsWith("//")) return part;

          const rewritten = await rewriteRootUrl(file, url);
          return [rewritten, ...pieces.slice(1)].join(" ");
        })
      );

      return `srcset="${parts.join(", ")}"`;
    }
  );

  html = await rewriteCssUrlsInText(file, html);

  await fs.writeFile(file, html);
}

async function rewriteCssUrlsInText(file, text) {
  return await replaceAsync(
    text,
    /url\((["']?)(\/(?!\/)[^)'" ]+)\1\)/g,
    async (match, quote, url) => {
      const rewritten = await rewriteRootUrl(file, url);
      return `url(${quote}${rewritten}${quote})`;
    }
  );
}

async function rewriteCss(file) {
  const css = await fs.readFile(file, "utf8");
  const rewritten = await rewriteCssUrlsInText(file, css);
  await fs.writeFile(file, rewritten);
}

async function replaceAsync(str, regex, asyncFn) {
  const matches = [...str.matchAll(regex)];

  let result = "";
  let lastIndex = 0;

  for (const match of matches) {
    result += str.slice(lastIndex, match.index);
    result += await asyncFn(...match);
    lastIndex = match.index + match[0].length;
  }

  result += str.slice(lastIndex);
  return result;
}

await fs.rm(TARGET, { recursive: true, force: true });
await fs.cp(SOURCE, TARGET, { recursive: true });

const files = await walk(TARGET);

for (const file of files) {
  if (file.endsWith(".html")) {
    await rewriteHtml(file);
  }

  if (file.endsWith(".css")) {
    await rewriteCss(file);
  }
}

console.log(`Arweave build prepared in ${TARGET}`);