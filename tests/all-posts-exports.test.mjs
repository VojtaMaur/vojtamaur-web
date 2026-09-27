import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const project = fileURLToPath(new URL('../', import.meta.url));
const python = process.env.PYTHON_BIN || 'python';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

function run(root, script, args = [], expected = 0) {
  const isPython = script.endsWith('.py');
  const result = spawnSync(isPython ? python : process.execPath, [path.join(project, 'scripts', script), ...args], {
    cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(result.status, expected, `${script}: ${result.error || ''}\n${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

async function fixture(t, flat = false) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'all-posts-test-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  await fs.mkdir(path.join(root, 'src/content/posts'), { recursive: true });
  await fs.writeFile(path.join(root, 'src/content/posts/sample.mdx'), '---\ntitle: "Český název"\nslug: "sample"\nsection: "volna-tvorba"\ndate: 2026-09-20\n---\n');
  const code = Array.from({ length: 140 }, (_, i) => `  line ${i}`).join('\n') + '\n\n  final line  ';
  for (const lang of ['cs', 'en']) {
    const route = `${lang === 'en' ? 'en/' : ''}sample${flat ? '.html' : '/index.html'}`;
    const file = path.join(root, 'dist', route);
    await fs.mkdir(path.dirname(file), { recursive: true });
    await fs.writeFile(file, `<html><main><article><h1>${lang === 'cs' ? 'Český název' : 'English title'}</h1><div class="post-meta">${lang === 'cs' ? 'září' : 'September'} 2026</div><div class="post-body"><p>Text <a href="/sample/">link</a>.</p><figure><img src="/images/sample.jpg" alt="Žluťoučký obrázek"><figcaption>Caption</figcaption></figure><iframe src="/files/sample.pdf"></iframe><pre>${code}</pre></div></article></main></html>`);
  }
  await fs.writeFile(path.join(root, 'dist/404.html'), '<html><body><pre data-all-posts-embed></pre></body></html>');
  return root;
}

async function verify(root, dist = 'dist') {
  const dir = path.join(root, dist);
  const doc = JSON.parse(await fs.readFile(path.join(dir, 'ALL_POSTS.json')));
  assert.equal(doc['vm:articleCount'], 2);
  assert.equal(doc['vm:sourceIndexSha256'], hash(await fs.readFile(path.join(dir, 'ALL_POSTS.txt'))));
  assert.equal(doc['vm:declaredBuildSha256'], undefined);
  for (const article of doc.hasPart) {
    assert.equal(article['vm:builtHtmlSha256'], hash(await fs.readFile(path.join(dir, article['vm:builtHtmlPath']))));
    assert.match(article.articleBody, /line 139/);
    assert.equal(article.image[0].contentUrl, 'https://vojtamaur.cz/images/sample.jpg');
  }
  return doc;
}

test('build step creates TXT and JSON; rewrites refresh HTML hashes for web, Arweave and USB', async t => {
  const root = await fixture(t);
  run(root, 'generate-all-posts.mjs');
  await verify(root);
  await fs.writeFile(path.join(root, 'dist/BUILD_SHA256.txt'), 'a'.repeat(64));
  run(root, 'make-arweave-build.mjs');
  await verify(root, 'dist-arweave');
  const usb = await fixture(t, true);
  run(usb, 'generate-all-posts.mjs');
  const before = await verify(usb);
  run(usb, 'usb-rewrite.mjs');
  const after = await verify(usb);
  assert.notEqual(before.hasPart[0]['vm:builtHtmlSha256'], after.hasPart[0]['vm:builtHtmlSha256']);
});

test('JSON CLI supports custom dist, snapshots, dry runs and rejects unsafe output paths', async t => {
  const root = await fixture(t);
  run(root, 'generate-all-posts.mjs');
  await fs.rename(path.join(root, 'dist'), path.join(root, 'custom-build'));
  const args = ['--project-root', root, '--dist', 'custom-build'];
  await fs.rm(path.join(root, 'custom-build/ALL_POSTS.json'));
  run(root, 'export-site-json.mjs', [...args, '--dry-run']);
  await assert.rejects(fs.access(path.join(root, 'custom-build/ALL_POSTS.json')));
  run(root, 'export-site-json.mjs', args);
  await verify(root, 'custom-build');
  run(root, 'export-site-json.mjs', [...args, '--output', 'exports/snapshot.jsonld']);
  assert.equal(JSON.parse(await fs.readFile(path.join(root, 'exports/snapshot.jsonld')))['vm:articleCount'], 2);
  run(root, 'export-site-json.mjs', [...args, '--output', 'src/overwrite.json'], 1);
});

test('Rosetta uses build JSON even with a newer legacy snapshot; explicit snapshots still work', async t => {
  const root = await fixture(t);
  run(root, 'generate-all-posts.mjs');
  await fs.mkdir(path.join(root, 'exports'));
  const legacy = JSON.parse(await fs.readFile(path.join(root, 'dist/ALL_POSTS.json')));
  legacy['vm:generatedAt'] = '2099-01-01T00:00:00Z';
  await fs.writeFile(path.join(root, 'exports/ALL_POSTS.json'), JSON.stringify(legacy));
  const args = ['--project-root', root, '--languages', 'de', '--limit', '1', '--dry-run'];
  run(root, 'export-site-rosetta.mjs', args);
  const state = JSON.parse(await fs.readFile(path.join(root, 'exports/rosetta/rosetta.json')));
  assert.equal(state.plan.sourcePath, path.join(root, 'dist/ALL_POSTS.json'));
  run(root, 'export-site-rosetta.mjs', [...args, '--input', 'exports/ALL_POSTS.json', '--output', 'exports/legacy']);
  await fs.rm(path.join(root, 'dist/ALL_POSTS.json'));
  run(root, 'export-site-rosetta.mjs', [...args, '--output', 'exports/missing'], 1);
});

test('JSON filtering preserves full code, media, rendered titles, selection and legacy TXT support', async t => {
  const root = await fixture(t);
  run(root, 'generate-all-posts.mjs');
  const input = path.join(root, 'dist/ALL_POSTS.json');
  const output = path.join(root, 'compact.txt');
  run(root, 'filter-all-posts.py', [input, '--language', 'en', '--section', 'volna-tvorba', '--from-date', '2026-09-20', '--to-date', '2026-09-20', '--format', 'compact', '--output', output]);
  const text = await fs.readFile(output, 'utf8');
  assert.ok(text.startsWith('\uFEFF'));
  assert.match(text, /Articles: 1 of 2/);
  assert.match(text, /\[English title\|2026-09\]/);
  assert.match(text, /\[img:sample.jpg\|ALT: Žluťoučký obrázek\|CAPTION: Caption\]/);
  assert.match(text, /\[pdf\|SOURCE: https:\/\/vojtamaur.cz\/files\/sample.pdf\]/);
  assert.match(text, /  line 139\n\n  final line  \n/);
  const doc = JSON.parse(await fs.readFile(input));
  doc.hasPart.reverse();
  await fs.writeFile(input, JSON.stringify(doc));
  run(root, 'filter-all-posts.py', [input, '--output', output]);
  const structured = await fs.readFile(output, 'utf8');
  assert.ok(structured.indexOf('LANGUAGE: cs') < structured.indexOf('LANGUAGE: en'));
  run(root, 'filter-all-posts.py', [path.join(root, 'dist/ALL_POSTS.txt'), '--dry-run']);
  run(root, 'filter-all-posts.py', [input, '--from-date', '2099-01-01', '--dry-run'], 2);
  run(root, 'filter-all-posts.py', [input, '--from-date', '2099-01-01', '--allow-empty', '--dry-run']);
  doc.hasPart[1]['vm:position'] = doc.hasPart[0]['vm:position'];
  await fs.writeFile(input, JSON.stringify(doc));
  run(root, 'filter-all-posts.py', [input, '--dry-run'], 2);
});
