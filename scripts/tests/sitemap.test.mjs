import test from 'node:test';
import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { load } from 'cheerio';
import { enrichSitemap } from '../enrich-sitemap.mjs';

const site = 'https://vojtamaur.cz';
async function fixture(t) {
  const dist = await fs.mkdtemp(path.join(os.tmpdir(), 'sitemap-test-'));
  t.after(() => fs.rm(dist, { recursive: true, force: true }));
  const files = {
    'sitemap-index.xml': `<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>${site}/sitemap-0.xml</loc></sitemap><sitemap><loc>${site}/sitemap-1.xml</loc></sitemap></sitemapindex>`,
    'sitemap-0.xml': `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml"><url><loc>${site}/post/</loc><lastmod>2026-09-28</lastmod><xhtml:link rel="alternate" href="${site}/en/post/" hreflang="en"/></url></urlset>`,
    'sitemap-1.xml': `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>${site}/en/post/</loc></url></urlset>`,
    'post/index.html': '<img src="/images/one.jpg"><img src="/images/one.jpg#x"><picture><source srcset="/images/two.webp 1x, /images/three.png 2x"></picture><a href="/images/full.jpg">Full</a><img src="/missing.jpg"><img src="https://elsewhere.example/image.jpg"><img src="data:image/png;base64,aaaa"><iframe src="/files/one.pdf#page=1"></iframe><a href="/SHA256SUMS.txt">hash</a><img src="/images/a%20%26%20b.jpg">',
    'en/post/index.html': '<img src="../../images/one.jpg"><a href="/files/one.pdf">PDF</a>',
    'images/one.jpg': 'image', 'images/two.webp': 'image', 'images/three.png': 'image',
    'images/full.jpg': 'image', 'images/a & b.jpg': 'image',
    'images/orphan.jpg': 'image', 'files/one.pdf': 'pdf', 'files/unlinked.pdf': 'pdf',
    'files/settings.txt': 'text', 'ALL_POSTS.txt': 'text', 'ARCHIVE.txt': 'text',
    'robots.txt': 'technical', 'SHA256SUMS.txt': 'technical', 'MEDIA_SHA256SUMS.txt': 'zip-only',
  };
  for (const [file, content] of Object.entries(files)) {
    await fs.mkdir(path.dirname(path.join(dist, file)), { recursive: true });
    await fs.writeFile(path.join(dist, file), content);
  }
  return { dist, files };
}

test('preserves Astro index/shards and metadata, associates only existing local images, adds documents once', async t => {
  const { dist, files } = await fixture(t);
  const result = await enrichSitemap({ dist });
  assert.equal(result.images, 6);
  assert.equal(result.added, 5);
  assert.equal(await fs.readFile(path.join(dist, 'sitemap-index.xml'), 'utf8'), files['sitemap-index.xml']);
  const first = await fs.readFile(path.join(dist, 'sitemap-0.xml'), 'utf8');
  const $ = load(first, { xml: true });
  assert.equal($('lastmod').text(), '2026-09-28');
  assert.equal($('xhtml\\:link').attr('hreflang'), 'en');
  const images = $('image\\:loc').map((_, el) => $(el).text()).get();
  assert.equal(new Set(images).size, 5);
  assert.ok(images.includes(site + '/images/a%20%26%20b.jpg'));
  assert.ok(!first.includes('missing.jpg') && !first.includes('orphan.jpg'));
  const second = await fs.readFile(path.join(dist, 'sitemap-1.xml'), 'utf8');
  assert.ok(second.includes('/ALL_POSTS.txt') && second.includes('/files/unlinked.pdf'));
  assert.ok(!second.includes('SHA256SUMS') && !second.includes('robots.txt'));
  await enrichSitemap({ dist });
  assert.equal(await fs.readFile(path.join(dist, 'sitemap-0.xml'), 'utf8'), first);
  assert.equal(await fs.readFile(path.join(dist, 'sitemap-1.xml'), 'utf8'), second);
});

test('USB skips sitemap even without a dist directory', async () => {
  assert.deepEqual(await enrichSitemap({ dist: 'does-not-exist', usb: true }), { skipped: true });
});

test('missing web index fails; missing page fails before changing any shard', async t => {
  const { dist, files } = await fixture(t);
  await fs.unlink(path.join(dist, 'post/index.html'));
  await assert.rejects(enrichSitemap({ dist }), /Missing rendered page/);
  assert.equal(await fs.readFile(path.join(dist, 'sitemap-0.xml'), 'utf8'), files['sitemap-0.xml']);
  await fs.unlink(path.join(dist, 'sitemap-index.xml'));
  await assert.rejects(enrichSitemap({ dist }), /ENOENT/);
});

test('rejects escaping or foreign child sitemap paths', async t => {
  const { dist } = await fixture(t);
  for (const url of ['https://foreign.example/sitemap.xml', site + '/%2e%2e%2fsecret.xml', site + '/C:%5csecret.xml']) {
    await fs.writeFile(path.join(dist, 'sitemap-index.xml'), `<sitemapindex><sitemap><loc>${url}</loc></sitemap></sitemapindex>`);
    await assert.rejects(enrichSitemap({ dist }), /missing or non-local/);
  }
});

test('all web pipelines enrich after content and before integrity; signed builds only sign afterwards', async () => {
  const { scripts } = JSON.parse(await fs.readFile(new URL('../../package.json', import.meta.url), 'utf8'));
  for (const name of ['build:web', 'build:web:translate', 'build:web:refresh', 'build:web:strict']) {
    const command = scripts[name];
    assert.ok(command.indexOf('generate:source-bundle') < command.indexOf('generate:sitemap'));
    assert.ok(command.indexOf('generate:sitemap') < command.indexOf('generate:integrity'));
  }
  for (const [name, command] of Object.entries(scripts)) {
    if (name.endsWith(':signed') && command.includes('&&')) assert.match(command, /&& npm run sign:build(?::arweave)?$/);
    if (name.startsWith('build:usb')) assert.ok(!command.includes('generate:sitemap'));
  }
  const workflow = await fs.readFile(new URL('../../.github/workflows/pages.yml', import.meta.url), 'utf8');
  assert.ok(workflow.indexOf('Refresh content checksums after mirror rewrites') > workflow.indexOf('walk(distDir)'));
  assert.ok(workflow.indexOf('npm run generate:integrity') < workflow.indexOf('Upload Pages artifact'));
});

test('image limit is enforced without silently truncating or writing shards', async t => {
  const { dist, files } = await fixture(t);
  const images = [];
  for (let i = 0; i < 1001; i++) {
    const name = `images/limit-${i}.jpg`;
    await fs.writeFile(path.join(dist, name), 'image');
    images.push(`<img src="/${name}">`);
  }
  await fs.writeFile(path.join(dist, 'post/index.html'), images.join(''));
  await assert.rejects(enrichSitemap({ dist }), /More than 1000 images/);
  assert.equal(await fs.readFile(path.join(dist, 'sitemap-0.xml'), 'utf8'), files['sitemap-0.xml']);
});
