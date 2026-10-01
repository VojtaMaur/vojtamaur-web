import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { load } from 'cheerio';

const root = process.cwd();
const dist = path.resolve(root, process.env.ROSETTA_TEST_DIST || 'dist');
const statePath = path.join(root, 'rosetta.json');
const state = await fs.readFile(statePath, 'utf8').then(text => JSON.parse(text.replace(/^\uFEFF/, '')), error => { if (error.code === 'ENOENT') return undefined; throw error; });
const filenames = (await fs.readdir(path.join(root, 'public', 'rosetta')))
  .filter(name => /^ALL_POSTS__lang-/.test(name) && name.endsWith('.txt') && !/lang-(en|cs)\.txt$/.test(name));
const exists = async file => fs.access(file).then(() => true, () => false);
const usb = await exists(path.join(dist, 'rosetta.html'));
const page = code => path.join(dist, usb ? `${code}.html` : `${code}/index.html`);
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

test('Rosetta hub links to exactly the available non-English TXT languages', async () => {
  const $ = load(await fs.readFile(page('rosetta'), 'utf8'));
  assert.match($('[lang=en].rosetta-english').text(), /machine translations/);
  const codes = filenames.map(name => name.slice('ALL_POSTS__lang-'.length, -4)).sort();
  const links = $('.rosetta-grid a').toArray();
  assert.deepEqual(links.map(el => $(el).attr('hreflang')).sort(), codes);
  for (const el of links) {
    const code = $(el).attr('hreflang');
    assert.equal($(el).attr('href'), usb ? `./${code}.html` : `/${code}/`);
    assert.equal($(el).attr('lang'), code);
    assert.ok($(el).text().trim());
  }
  assert.ok(await exists(page('en')), 'Real English homepage still exists');
  assert.equal(await exists(path.join(dist, 'rosetta', 'ALL_POSTS__lang-en.txt')), false);
});

test('Every language page has localized text, the translation export date and working links; TXT stays byte-identical', async () => {
  for (const filename of filenames) {
    const code = filename.slice('ALL_POSTS__lang-'.length, -4);
    const file = page(code);
    const html = await fs.readFile(file, 'utf8');
    const $ = load(html);
    assert.equal($('html').attr('lang'), code);
    assert.equal($('html').attr('dir'), ['ar', 'fa', 'he', 'ps', 'sd', 'ur'].includes(code) ? 'rtl' : 'ltr');
    assert.equal($('link[rel=canonical]').attr('href'), `https://vojtamaur.cz/${code}/`);
    assert.equal($('link[hreflang]').length, 0, 'No misleading alternate full homepages');
    assert.ok($('.rosetta-notice').text().trim().length > 50);
    assert.equal($('main a').length, 4);
    assert.equal($('pre, iframe, script').length, 0, 'No embedded archive or client-side fetch');
    assert.ok(Buffer.byteLength(html) < 12000, `Small landing page: ${code}`);
    const original = await fs.readFile(path.join(root, 'public', 'rosetta', filename));
    const translatedAt = state?.manifest?.updatedAt;
    if (translatedAt) {
      assert.equal($('time').attr('datetime'), translatedAt);
      assert.equal($('time').text().trim(), translatedAt.slice(0, 10));
    } else {
      assert.equal($('time').length, 0, 'Do not label the source date as the translation date');
    }
    assert.equal(hash(await fs.readFile(path.join(dist, 'rosetta', filename))), hash(original));
    assert.equal($('.rosetta-open').attr('href'), usb ? `./rosetta/${filename}` : `/rosetta/${filename}`);
    for (const link of $('main a').toArray()) {
      const href = $(link).attr('href');
      const local = usb ? path.resolve(path.dirname(file), href) : path.join(dist, href.replace(/^\//, ''), href.endsWith('/') ? 'index.html' : '');
      assert.ok(await exists(local), `Broken ${code} link: ${href}`);
    }
  }
});

test('Rosetta working JSON never appears in the public build or checksum manifest', async () => {
  const files = [];
  async function visit(dir) {
    for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) await visit(path.join(dir, entry.name));
      else files.push(path.join(dir, entry.name));
    }
  }
  await visit(dist);
  assert.equal(files.some(file => path.basename(file) === 'rosetta.json'), false);
  const checksums = await fs.readFile(path.join(dist, 'SHA256SUMS.txt'), 'utf8');
  assert.equal(checksums.includes('rosetta.json'), false);
  for (const filename of filenames) assert.ok(checksums.includes(`rosetta/${filename}`));
});
