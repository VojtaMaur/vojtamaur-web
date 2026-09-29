import { promises as fs } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { load } from 'cheerio';

const IMAGE_NS = 'http://www.google.com/schemas/sitemap-image/1.1';
const IMAGE = /\.(?:avif|bmp|gif|jpe?g|png|svg|webp)$/i;
const DOCUMENT = /\.(?:pdf|txt)$/i;
const ROOT_TEXT = new Set(['ALL_POSTS.txt', 'ARCHIVE.txt', 'PRESERVATION_INSTRUCTIONS.txt', 'llms.txt']);
const TECHNICAL = /^(?:robots\.txt|SHA256SUMS(?:\.txt)?|BUILD_SHA256\.txt|BUILD_HASH_HISTORY\.txt|SIGNING_STATUS\.txt|MEDIA_MANIFEST\.json|MEDIA_SHA256SUMS\.txt)$/i;
const MAX_BYTES = 50 * 1024 * 1024;

function localURL(value, base, origin) {
  if (!value || /[\x00-\x1f\\]/.test(value)) return null;
  try {
    const url = new URL(value, base);
    if (url.origin !== origin || url.username || url.password) return null;
    url.hash = '';
    // Static assets are served without query-dependent content.
    url.search = '';
    return url;
  } catch { return null; }
}

async function localFile(root, url, html = false) {
  let segments;
  try { segments = decodeURIComponent(url.pathname).split('/').filter(Boolean); }
  catch { return null; }
  if (segments.some(s => s === '.' || s === '..' || /[\\:\x00-\x1f]/.test(s))) return null;
  let file = path.join(root, ...segments);
  if (html && url.pathname.endsWith('/')) file = path.join(file, 'index.html');
  try {
    const real = await fs.realpath(file);
    const relative = path.relative(root, real);
    if (relative.startsWith('..') || path.isAbsolute(relative)) return null;
    return (await fs.stat(real)).isFile() ? real : null;
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null;
    throw error;
  }
}

async function walk(root, dir = root) {
  const files = [];
  for (const item of await fs.readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, item.name);
    if (item.isDirectory()) files.push(...await walk(root, file));
    else if (item.isFile()) files.push(path.relative(root, file).split(path.sep).join('/'));
  }
  return files.sort();
}

export async function enrichSitemap({ dist = 'dist', site = 'https://vojtamaur.cz', usb = process.env.BUILD_TARGET === 'usb' } = {}) {
  if (usb) return { skipped: true };
  const root = await fs.realpath(dist);
  const origin = new URL(site).origin;
  const indexPath = path.join(root, 'sitemap-index.xml');
  const index = load(await fs.readFile(indexPath, 'utf8'), { xml: true });
  const maps = [];
  const seenMaps = new Set();
  const seenURLs = new Set();
  const documents = new Set();
  let imageCount = 0;
  for (const entry of index('sitemapindex > sitemap > loc').toArray()) {
    const url = localURL(index(entry).text(), site, origin);
    const file = url && await localFile(root, url);
    if (!file) throw new Error('Sitemap index refers to a missing or non-local sitemap');
    if (seenMaps.has(file)) continue;
    seenMaps.add(file);
    const $ = load(await fs.readFile(file, 'utf8'), { xml: true });
    if ($('urlset').length !== 1) throw new Error(`Expected urlset: ${file}`);
    $('urlset').attr('xmlns:image', IMAGE_NS);
    maps.push({ file, $ });
    for (const node of $('urlset > url').toArray()) {
      const pageURL = localURL($(node).children('loc').text(), site, origin);
      if (!pageURL) throw new Error(`Invalid sitemap page URL in ${file}`);
      seenURLs.add(pageURL.href);
      if (DOCUMENT.test(pageURL.pathname)) continue;
      const htmlFile = await localFile(root, pageURL, true);
      if (!htmlFile) throw new Error(`Missing rendered page: ${pageURL.href}`);
      const html = load(await fs.readFile(htmlFile, 'utf8'));
      const base = localURL(html('base[href]').first().attr('href'), pageURL, origin) || pageURL;
      const candidates = [];
      html('img[src], img[data-src], source[src], a[href], iframe[src], embed[src], object[data], meta[property="og:image"], meta[name="twitter:image"]').each((_, el) => {
        for (const attr of ['src', 'data-src', 'href', 'data', 'content']) {
          if (html(el).attr(attr)) candidates.push(html(el).attr(attr));
        }
      });
      html('img[srcset], source[srcset], img[data-srcset]').each((_, el) => {
        for (const attr of ['srcset', 'data-srcset']) {
          // Ignore data URIs; static URL candidates can have width/density descriptors.
          const value = html(el).attr(attr) || '';
          if (!value.trim().startsWith('data:')) {
            candidates.push(...value.split(',').map(v => v.trim().split(/\s+/)[0]));
          }
        }
      });
      const images = new Set();
      for (const candidate of candidates) {
        const asset = localURL(candidate, base, origin);
        if (!asset || (!IMAGE.test(asset.pathname) && !DOCUMENT.test(asset.pathname))) continue;
        if (!await localFile(root, asset)) continue;
        if (IMAGE.test(asset.pathname)) images.add(asset.href);
        else if (!TECHNICAL.test(path.posix.basename(asset.pathname))) documents.add(asset.href);
      }
      if (images.size > 1000) throw new Error(`More than 1000 images on ${pageURL.href}`);
      $(node).children('image\\:image').remove();
      for (const image of [...images].sort()) {
        const child = $('<image:image><image:loc/></image:image>');
        child.children().text(image);
        $(node).append(child);
        imageCount++;
      }
    }
  }
  if (!maps.length) throw new Error('Sitemap index contains no sitemaps');
  for (const file of await walk(root)) {
    if (/\.pdf$/i.test(file) || (/\.txt$/i.test(file) && (file.startsWith('files/') || ROOT_TEXT.has(file)))) {
      if (!TECHNICAL.test(path.posix.basename(file))) {
        documents.add(new URL('/' + file.split('/').map(encodeURIComponent).join('/'), origin).href);
      }
    }
  }
  let added = 0;
  const last = maps.at(-1).$;
  for (const url of [...documents].sort()) {
    if (seenURLs.has(url)) continue;
    const entry = last('<url><loc/></url>');
    entry.children().text(url);
    last('urlset').append(entry);
    seenURLs.add(url);
    added++;
  }
  // Keep Astro's index and shard names intact. Fail rather than publish an
  // oversized sitemap or silently omit content if future growth reaches limits.
  const outputs = maps.map(({ file, $ }) => ({ file, xml: $.xml(), count: $('urlset > url').length }));
  for (const output of outputs) {
    if (output.count > 50000 || Buffer.byteLength(output.xml) > MAX_BYTES) {
      throw new Error(`Sitemap limits exceeded: ${output.file}`);
    }
  }
  for (const output of outputs) await fs.writeFile(output.file, output.xml, 'utf8');
  return { maps: maps.length, images: imageCount, documents: documents.size, added };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  enrichSitemap({ dist: process.argv[2] || 'dist' }).then(result => {
    console.log('[sitemap]', JSON.stringify(result));
  }).catch(error => { console.error('[sitemap]', error.message); process.exitCode = 1; });
}
