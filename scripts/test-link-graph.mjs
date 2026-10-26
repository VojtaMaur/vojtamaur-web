import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { load } from 'cheerio';
import { collectGraph, generateLinkGraph, scriptJson, toGraphML, toSVG } from './lib/link-graph.mjs';
import { runOptionalGraph } from './generate-link-graph.mjs';
import { START, END } from './lib/link-graph-page.mjs';

async function fixture(t, files = {}) {
  const dir = await mkdtemp(path.join(tmpdir(), 'vm-link-graph-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  for (const [file, text] of Object.entries({
    'index.html': '<title>Home &amp; site</title><a href="/article/">A</a><a href="article/index.html?q=2#x">A again</a><a href="#home">Self</a><a href="https://external.test/x?q=1&amp;b=2#part">Ext</a><a href="javascript:alert(1)">Bad</a><a href="mailto:x@example.test">Mail</a><a href="data:text/html,x">Data</a><a href="https://u:password@external.test/">Credentials</a><iframe src="https://iframe.test/"></iframe><script>const x="https://script.test/";</script>',
    'article/index.html': '<title>Článek &lt; &amp; &quot;</title><a href="../">Home</a><a href="/files/a.pdf#page=1">PDF</a><a href="/files/a.pdf?download=1">PDF again</a><a href="https://external.test/x?q=1&amp;b=2#another">Ext</a><a href="https://external.test/x?q=2">Other query</a><area href="//mirror.test/a"/><a href="https://vojtamaur.cz/article">Absolute self</a><a href="/not-built/">Unresolved</a><a href="/%ZZ">Malformed</a>',
    'demos/index.html': '<title>Demo</title><base href="https://base.test/dir/"><a href="next#part">Base-relative</a>',
    '404.html': '<title>404 — Recovery | Vojta Maur</title><meta name="robots" content="noindex,follow"><a href="/ARCHIVE.txt">Archive</a><a href="https://recovery.test/mirror">Mirror</a>',
    'link-graph/index.html': `<title>Graf</title>${START}<p>Fallback</p>${END}`,
    ...files,
  })) {
    await mkdir(path.dirname(path.join(dir, file)), { recursive: true });
    await writeFile(path.join(dir, file), text);
  }
  return dir;
}

test('collects directed links from rendered HTML, normalizes URLs, counts duplicates and excludes non-links', async t => {
  const dist = await fixture(t);
  const graph = await collectGraph({ dist });
  const find = url => graph.nodes.find(n => n.url === url);
  const home = find('https://vojtamaur.cz/');
  const article = find('https://vojtamaur.cz/article/');
  assert.equal(graph.edges.find(e => e.source === home.id && e.target === article.id).count, 2);
  assert.equal(find('https://vojtamaur.cz/files/a.pdf').kind, 'internal');
  assert.equal(graph.edges.find(e => e.source === article.id && e.target === find('https://vojtamaur.cz/files/a.pdf').id).count, 2);
  assert.equal(find('https://vojtamaur.cz/not-built/').kind, 'internal');
  assert.equal(find('https://base.test/dir/next').kind, 'external');
  assert.equal(find('https://mirror.test/a').kind, 'external');
  assert.ok(find('https://external.test/x?q=1&b=2'));
  assert.ok(find('https://external.test/x?q=2'));
  assert.equal(article.label, 'Článek < & "');
  assert.ok(graph.edges.every(e => e.source !== e.target));
  assert.ok(graph.nodes.every(n => !/iframe\.test|script\.test|password|%ZZ|mailto:|javascript:/.test(n.url)));
  assert.equal(graph.nodes.length, new Set(graph.nodes.map(n => n.id)).size);
  assert.deepEqual(await collectGraph({ dist }), graph);
});

test('inventories selected published content folders, preserving isolated files and merging linked assets without technical assets', async t => {
  const dist = await fixture(t, {
    'index.html': '<title>Home</title><a href="/images/linked%20image%20%231.jpg">Image</a><a href="./images/linked%20image%20%231.jpg?download=1#x">Again</a><iframe src="/files/note.txt"></iframe><iframe src="/images/kurt-godel-rat.jpg"></iframe><a href="/demos/support.js">Support code</a><a href="/images/style.css">Styles</a>',
    'images/kurt-godel-rat.jpg': 'unused image bytes',
    'images/linked image #1.jpg': 'image bytes',
    'files/note.txt': 'Readable content',
    'files/tool.py': 'downloadable source content',
    'keys/public-key.asc': 'public key',
    'demos/poster.png': 'demo poster',
    'demos/orphan.html': '<title>Unlinked demo</title>',
    'demos/support.js': 'console.log("support")',
    'images/style.css': 'body {}',
    'files/debug.map': '{}',
    'images/Thumbs.db': 'OS artifact',
    '_astro/unused.css': 'body {}',
    'other/unlisted.jpg': 'not selected',
    'rosetta/unlisted.txt': 'not selected',
    'SHA256SUMS.txt': 'not a graph input',
  });
  const graph = await generateLinkGraph({ dist });
  for (const file of ['images/kurt-godel-rat.jpg', 'files/note.txt', 'files/tool.py', 'keys/public-key.asc', 'demos/orphan.html']) {
    const node = graph.nodes.find(n => n.file === file);
    assert.ok(node, file);
    assert.equal(graph.nodes.filter(n => n.file === file).length, 1, file);
    assert.equal(graph.edges.filter(e => e.source === node.id || e.target === node.id).length, ['images/kurt-godel-rat.jpg', 'files/note.txt'].includes(file) ? 1 : 0, file);
  }
  const image = graph.nodes.find(n => n.file === 'images/linked image #1.jpg');
  assert.equal(image.url, 'https://vojtamaur.cz/images/linked%20image%20%231.jpg');
  assert.equal(graph.nodes.filter(n => n.file === image.file).length, 1);
  const edge = graph.edges.find(e => e.target === image.id);
  assert.deepEqual([edge.count, edge.linkCount, edge.embedCount], [2, 2, 0]);
  assert.equal(graph.nodes.find(n => n.file === 'demos/orphan.html').kind, 'page');
  assert.equal(graph.nodes.find(n => n.file === 'images/kurt-godel-rat.jpg').kind, 'internal');
  assert.ok(graph.nodes.every(n => !/poster\.png|support\.js|style\.css|debug\.map|Thumbs\.db|_astro\/|unlisted\.|SHA256SUMS/.test(n.file)));
  const xml = load(toGraphML(graph), { xml: true });
  const svg = load(toSVG(graph), { xml: true });
  const orphan = graph.nodes.find(n => n.file === 'images/kurt-godel-rat.jpg');
  assert.equal(xml(`node[id="${orphan.id}"] data[key="file"]`).text(), orphan.file);
  assert.equal(svg(`[data-node="${orphan.id}"]`).length, 1);
  assert.deepEqual(await generateLinkGraph({ dist }), graph);
});

test('image references connect actual local content files, merge aliases and preserve occurrence counts without demo support assets', async t => {
  const dist = await fixture(t, {
    'index.html': '<title>Home</title><img src="/images/thumbnail.jpg" srcset="/images/thumbnail.jpg 1x, /images/large.jpg 2x"><picture><source srcset="data:image/svg+xml,%3Csvg%3E 1x, /images/large.jpg?size=2#x 2x"><img src="/images/thumbnail.jpg"></picture><img src="/images/not-built.jpg"><img src="https://remote-image.test/photo.jpg"><img src="/other/not-selected.jpg"><img src="/images/style.css"><img src="/article/"><a href="/demos/pf/last_ziva.jpg">Support link</a><img src="/demos/pf/last_ziva.jpg"><iframe src="/demos/pf/"></iframe><a href="/images/large.jpg">Full size</a>',
    'en/article/index.html': '<title>English</title><base href="/images/"><img src="thumbnail.jpg?x=1#preview">',
    'usb-article.html': '<img src="./images/thumbnail.jpg">',
    'images/thumbnail.jpg': 'thumbnail',
    'images/large.jpg': 'full size',
    'images/orphan.jpg': 'unused',
    'images/style.css': 'body {}',
    'other/not-selected.jpg': 'unselected',
    'demos/pf/last_ziva.jpg': 'support image',
    'demos/pf/data.json': '{}',
    'demos/pf/index.html': '<title>PF</title><img src="last_ziva.jpg"><a href="data.json">Support data</a>',
  });
  const graph = await generateLinkGraph({ dist });
  const find = file => graph.nodes.find(n => n.file === file);
  const thumb = find('images/thumbnail.jpg');
  const incoming = graph.edges.filter(e => e.target === thumb.id);
  assert.equal(incoming.length, 3); // Distinct source pages, not occurrences.
  const homeThumb = incoming.find(e => e.source === find('index.html').id);
  assert.deepEqual([homeThumb.imageCount, homeThumb.linkCount, homeThumb.count], [3, 0, 3]);
  const large = find('images/large.jpg');
  const mixed = graph.edges.find(e => e.source === find('index.html').id && e.target === large.id);
  assert.deepEqual([mixed.imageCount, mixed.linkCount, mixed.count], [2, 1, 3]);
  assert.equal(graph.edges.filter(e => e.target === find('images/orphan.jpg').id).length, 0);
  assert.ok(graph.nodes.every(n => !/not-built\.jpg|remote-image|not-selected\.jpg|style\.css|last_ziva|data\.json|data:image/.test(n.url)));
  assert.equal(graph.edges.filter(e => e.target === find('demos/pf/index.html').id).length, 1);
  assert.ok(graph.edges.every(e => e.count === e.linkCount + e.embedCount + e.redirectCount + e.imageCount));
  const xml = load(toGraphML(graph), { xml: true });
  assert.equal(xml(`edge[source="${homeThumb.source}"][target="${thumb.id}"] data[key="imageCount"]`).text(), '3');
  const svg = load(toSVG(graph), { xml: true });
  assert.equal(svg(`path[data-source="${homeThumb.source}"][data-target="${thumb.id}"]`).attr('stroke'), '#28735c');
  const mixedPath = svg(`path[data-source="${mixed.source}"][data-target="${large.id}"]`);
  assert.equal(mixedPath.attr('stroke'), '#64748b');
  assert.match(mixedPath.find('title').text(), /použití obrázku: 2/);
  assert.deepEqual(await generateLinkGraph({ dist }), graph);
});

test('embedded PDFs and content files connect to their containing pages through iframe, object and embed', async t => {
  const dist = await fixture(t, {
    'article/index.html': '<title>Article</title><iframe src="/files/document%20%231.pdf#page=2"></iframe><iframe src="../files/document%20%231.pdf?download=1"></iframe><object data="/files/document%20%231.pdf#page=3" type="application/pdf"><a href="/files/document%20%231.pdf">Fallback download</a></object><embed src="/files/document%20%231.pdf"><iframe src="/files/iframe-only.pdf"></iframe><iframe src="/files/ignored-srcdoc.pdf" srcdoc="&lt;p&gt;Own content&lt;/p&gt;"></iframe><iframe src="/files/missing.pdf"></iframe><embed src="/files/missing-embed.pdf"><object data="https://remote-pdf.test/doc.pdf"></object><iframe src="/other/unselected.pdf"></iframe><embed src="/demos/pf/support.pdf"><object data="/demos/pf/last_ziva.jpg"></object><meta http-equiv="refresh" content="0;url=/files/ignored-redirect.pdf">',
    'en/article/index.html': '<base href="/files/"><iframe src="document%20%231.pdf#toolbar=0"></iframe>',
    'usb.html': '<object data="./files/document%20%231.pdf"></object><embed src="./demos/pf/index.html">',
    'files/document #1.pdf': 'PDF fixture',
    'files/iframe-only.pdf': 'iframe without hyperlink',
    'files/ignored-srcdoc.pdf': 'overridden',
    'files/ignored-redirect.pdf': 'not an HTML redirect destination',
    'other/unselected.pdf': 'not inventoried',
    'demos/pf/support.pdf': 'support file',
    'demos/pf/last_ziva.jpg': 'support file',
    'demos/pf/index.html': '<title>Demo</title>',
  });
  const graph = await generateLinkGraph({ dist });
  const find = file => graph.nodes.find(n => n.file === file);
  const pdf = find('files/document #1.pdf');
  const incoming = graph.edges.filter(e => e.target === pdf.id);
  assert.equal(incoming.length, 3);
  const article = find('article/index.html');
  const mixed = incoming.find(e => e.source === article.id);
  assert.deepEqual([mixed.embedCount, mixed.linkCount, mixed.count], [4, 1, 5]);
  const iframeOnly = find('files/iframe-only.pdf');
  assert.deepEqual(graph.edges.filter(e => e.target === iframeOnly.id).map(e => [e.source, e.embedCount, e.linkCount]), [[article.id, 1, 0]]);
  for (const file of ['files/ignored-srcdoc.pdf', 'files/ignored-redirect.pdf']) assert.equal(graph.edges.filter(e => e.target === find(file).id).length, 0);
  assert.ok(graph.nodes.every(n => !/missing|remote-pdf|unselected|support\.pdf|last_ziva/.test(n.url)));
  const demo = find('demos/pf/index.html');
  assert.equal(graph.edges.find(e => e.target === demo.id).embedCount, 1);
  const xml = load(toGraphML(graph), { xml: true });
  assert.equal(xml(`edge[source="${article.id}"][target="${pdf.id}"] data[key="embedCount"]`).text(), '4');
  const svg = load(toSVG(graph), { xml: true });
  assert.equal(svg(`path[data-target="${iframeOnly.id}"]`).attr('stroke-dasharray'), '9 6');
  assert.match(svg(`path[data-target="${iframeOnly.id}"] title`).text(), /vložení stránky nebo souboru: 1/);
  const page = load(await readFile(path.join(dist, 'link-graph/index.html'), 'utf8'));
  assert.match(page('.graph-legend').text(), /Vložení stránky nebo souboru/);
  assert.deepEqual(await generateLinkGraph({ dist }), graph);
});

test('custom 404 recovery pages are graph sources even with noindex, without inventing incoming error-response edges', async t => {
  const dist = await fixture(t, {
    'unrelated/index.html': '<a href="/does-not-exist/">Missing page</a>',
  });
  const graph = await collectGraph({ dist });
  const recovery = graph.nodes.find(n => n.file === '404.html');
  assert.equal(recovery.kind, 'page');
  assert.equal(recovery.url, 'https://vojtamaur.cz/404.html');
  assert.equal(recovery.label, '404 — Recovery');
  const outgoing = graph.edges.filter(e => e.source === recovery.id);
  assert.equal(outgoing.length, 2);
  assert.deepEqual(outgoing.map(e => graph.nodes.find(n => n.id === e.target).url).sort(), ['https://recovery.test/mirror', 'https://vojtamaur.cz/ARCHIVE.txt']);
  assert.equal(graph.edges.filter(e => e.target === recovery.id).length, 0);
  const unrelated = graph.nodes.find(n => n.file === 'unrelated/index.html');
  assert.notEqual(graph.edges.find(e => e.source === unrelated.id).target, recovery.id);
  // An actual hyperlink creates an incoming relation and reuses the same page.
  await writeFile(path.join(dist, 'unrelated/index.html'), '<a href="/404.html">Recovery page</a>');
  const linked = await collectGraph({ dist });
  assert.equal(linked.nodes.find(n => n.file === '404.html').id, recovery.id);
  assert.equal(linked.edges.filter(e => e.target === recovery.id).length, 1);
  const xml = load(toGraphML(linked), { xml: true });
  assert.equal(xml(`node[id="${recovery.id}"] data[key="file"]`).text(), '404.html');
  const svg = load(toSVG(linked), { xml: true });
  assert.equal(svg(`[data-node="${recovery.id}"]`).length, 1);
});

test('page labels remove only the trailing site suffix and fall back from generic/missing titles to headings, then routes', async t => {
  const dist = await fixture(t, {
    'specific/index.html': '<title>  Článek   | Vojta Maur </title><h1>Different heading</h1>',
    'generic/index.html': '<title>Vojta Maur</title><h1>  Hlavní   nadpis </h1>',
    'empty/index.html': '<title> </title><h1>Untitled document heading</h1>',
    'missing/index.html': '<h1>Missing title heading</h1>',
    'route/index.html': '<title>Vojta Maur</title><p>No heading</p>',
    'svg/index.html': '<svg><title>Graphic tooltip</title></svg><h1>HTML heading</h1>',
    'interior/index.html': '<title>Vojta Maur | Archive</title><h1>Heading</h1>',
    'brand-only/index.html': '<title> | Vojta Maur</title><h1>Useful heading</h1>',
  });
  const graph = await collectGraph({ dist });
  const expected = {
    'specific/index.html': 'Článek',
    'generic/index.html': 'Hlavní nadpis',
    'empty/index.html': 'Untitled document heading',
    'missing/index.html': 'Missing title heading',
    'route/index.html': '/route/',
    'svg/index.html': 'HTML heading',
    'interior/index.html': 'Vojta Maur | Archive',
    'brand-only/index.html': 'Useful heading',
  };
  for (const [file, label] of Object.entries(expected)) {
    assert.equal(graph.nodes.find(n => n.file === file).label, label, file);
  }
});

test('embedded local HTML demos connect to their containing articles, including USB-relative and mixed relationships', async t => {
  const dist = await fixture(t, {
    'demo-article/index.html': '<title>Český článek</title><iframe src="/demos/fractal/demo.html"></iframe><iframe src="../demos/fractal/demo.html?q=1#x"></iframe><iframe src="/files/a.pdf"></iframe><iframe src="/not-built/"></iframe><iframe src="https://remote-demo.test/"></iframe><iframe src="/demos/fractal/demo.html" srcdoc="&lt;p&gt;Inline content&lt;/p&gt;"></iframe>',
    'en/demo-article/index.html': '<title>English article</title><iframe src="../../demos/fractal/demo.html"></iframe>',
    'mixed/index.html': '<a href="/demos/fractal/demo.html">Open demo</a><iframe src="/demos/fractal/demo.html"></iframe>',
    'demos/fractal/demo.html': '<title>Interactive demo</title><canvas></canvas>',
    'usb-article.html': '<iframe src="./demos/fractal/demo.html"></iframe>',
  });
  const graph = await collectGraph({ dist });
  const demo = graph.nodes.find(n => n.file === 'demos/fractal/demo.html');
  const incoming = graph.edges.filter(e => e.target === demo.id);
  assert.equal(incoming.length, 4);
  assert.equal(graph.edges.filter(e => e.source === demo.id).length, 0);
  for (const file of ['en/demo-article/index.html', 'usb-article.html']) {
    const source = graph.nodes.find(n => n.file === file);
    const edge = incoming.find(e => e.source === source.id);
    assert.deepEqual([edge.linkCount, edge.embedCount, edge.count], [0, 1, 1]);
  }
  const cs = graph.nodes.find(n => n.file === 'demo-article/index.html');
  assert.deepEqual(graph.edges.filter(e => e.source === cs.id), [{ source: cs.id, target: demo.id, count: 2, linkCount: 0, embedCount: 2, redirectCount: 0, imageCount: 0 }]);
  const mixed = graph.nodes.find(n => n.file === 'mixed/index.html');
  const mixedEdge = incoming.find(e => e.source === mixed.id);
  assert.deepEqual([mixedEdge.linkCount, mixedEdge.embedCount, mixedEdge.count], [1, 1, 2]);
  assert.ok(graph.nodes.every(n => !n.url.includes('remote-demo.test')));
  assert.ok(graph.edges.every(e => e.count === e.linkCount + e.embedCount + e.redirectCount + e.imageCount));
  const xml = load(toGraphML(graph), { xml: true });
  for (const edge of incoming) {
    const record = xml(`edge[source="${edge.source}"][target="${edge.target}"]`);
    assert.equal(Number(record.find('data[key="embedCount"]').text()), edge.embedCount);
    assert.equal(Number(record.find('data[key="linkCount"]').text()), edge.linkCount);
  }
  const svg = load(toSVG(graph), { xml: true });
  assert.ok(svg(`path[data-source="${cs.id}"][data-target="${demo.id}"]`).attr('stroke-dasharray'));
  assert.equal(svg(`path[data-source="${mixed.id}"][data-target="${demo.id}"]`).attr('stroke-dasharray'), undefined);
});

test('explicit local meta refresh redirects connect to their demo without guessing remote or JavaScript redirects', async t => {
  const dist = await fixture(t, {
    'pf/index.html': '<meta http-equiv="refresh" content="0; url=/demos/pf/"><script>location.href="https://javascript-redirect.test/"</script>',
    'pf-quoted.html': '<meta http-equiv="Refresh" content="5; URL=&quot;./demos/pf/index.html?x=1#state&quot;">',
    'pf-invalid.html': '<meta http-equiv="refresh" content="5"><meta http-equiv="refresh" content="0;url=https://remote-redirect.test/"><meta http-equiv="refresh" content="0;url=/not-built/"><meta http-equiv="refresh" content="0;url=javascript:alert(1)">',
    'demos/pf/index.html': '<title>PF demo</title>',
  });
  const graph = await collectGraph({ dist });
  const demo = graph.nodes.find(n => n.file === 'demos/pf/index.html');
  const incoming = graph.edges.filter(e => e.target === demo.id);
  assert.equal(incoming.length, 2);
  for (const edge of incoming) assert.deepEqual([edge.count, edge.linkCount, edge.embedCount, edge.redirectCount], [1, 0, 0, 1]);
  assert.ok(graph.nodes.every(n => !/remote-redirect|javascript-redirect/.test(n.url)));
  const svg = load(toSVG(graph), { xml: true });
  assert.equal(svg(`path[data-source="${incoming[0].source}"][data-target="${demo.id}"]`).attr('stroke-dasharray'), '2 6');
  const xml = load(toGraphML(graph), { xml: true });
  assert.equal(xml(`edge[source="${incoming[0].source}"] data[key="redirectCount"]`).text(), '1');
});

test('writes equivalent exports, safe inline JSON and a self-contained page; reruns are stable', async t => {
  const dist = await fixture(t);
  const graph = await generateLinkGraph({ dist });
  const json = JSON.parse(await readFile(path.join(dist, 'link-graph/site-graph.json'), 'utf8'));
  assert.deepEqual(json, graph);
  const $ = load(toGraphML(graph), { xml: true });
  assert.equal($('node').length, graph.nodes.length);
  assert.equal($('edge').length, graph.edges.length);
  assert.equal($('graph').attr('edgedefault'), 'directed');
  for (const node of graph.nodes) {
    const record = $(`node[id="${node.id}"]`);
    assert.equal(record.find('data[key="url"]').text(), node.url);
    assert.equal(record.find('data[key="label"]').text(), node.label);
  }
  const svg = load(toSVG(graph), { xml: true });
  assert.equal(svg('[data-node]').length, graph.nodes.length);
  assert.equal(svg('[data-source]').length, graph.edges.length);
  // Previously nodes beyond the overview's label budget had no text element
  // at all, so zooming or selecting could never reveal their names.
  const crowded = { ...graph, edges: [], nodes: Array.from({ length: 80 }, (_, i) => ({
    ...graph.nodes[0], id: `crowded${i}`, label: `Node ${i} ${'long title '.repeat(8)}`,
  })) };
  const crowdedSVG = load(toSVG(crowded), { xml: true });
  assert.ok(crowdedSVG('text[data-label-priority="secondary"]').length > 0);
  for (const node of crowded.nodes) {
    const group = crowdedSVG(`[data-node="${node.id}"]`);
    assert.equal(group.find('text').length, 1);
    assert.match(group.find('text').text(), /…$/);
    assert.ok(group.find('title').text().includes(node.label));
  }
  const html = await readFile(path.join(dist, 'link-graph/index.html'), 'utf8');
  const page = load(html);
  assert.deepEqual(JSON.parse(page('#link-graph-data').text()), graph);
  assert.equal(page('a[download="site-graph.svg"]').attr('href'), './site-graph.svg');
  assert.equal(page('[data-root-prefix]').attr('data-root-prefix'), '../');
  assert.ok(page('.graph-canvas').next().hasClass('graph-legend'));
  assert.equal(page('[aria-label="Legenda grafu"]').length, 1);
  assert.equal(page('.graph-key').length, 3);
  assert.ok(svg('[data-node] > text').toArray().every(element => svg(element).attr('pointer-events') === 'none'));
  assert.equal(page('.graph-xml code').text(), toGraphML(graph));
  assert.deepEqual(await generateLinkGraph({ dist }), graph);
  assert.equal(await readFile(path.join(dist, 'link-graph/index.html'), 'utf8'), html);
  const adversarial = { value: '</script><img src=x onerror=alert(1)>\u2028\u2029' };
  assert.ok(!scriptJson(adversarial).includes('<'));
  assert.deepEqual(JSON.parse(scriptJson(adversarial)), adversarial);
});

test('supports flattened USB pages and final relative links with no fetch or module loader', async t => {
  const dist = await fixture(t, {
    'link-graph/index.html': '',
    'link-graph.html': `<title>Graf</title>${START}Fallback${END}`,
    'a.html': '<a href="./b.html#x">B</a><a href="/b/">Canonical B</a>',
    'b.html': '<a href="./index.html">Home</a>',
  });
  await rm(path.join(dist, 'link-graph/index.html'));
  const graph = await generateLinkGraph({ dist });
  const a = graph.nodes.find(n => n.file === 'a.html');
  const b = graph.nodes.find(n => n.file === 'b.html');
  assert.equal(graph.edges.find(e => e.source === a.id && e.target === b.id).count, 2);
  const $ = load(await readFile(path.join(dist, 'link-graph.html'), 'utf8'));
  assert.equal($('a[download="site-graph.svg"]').attr('href'), 'link-graph/site-graph.svg');
  assert.equal($('[data-root-prefix]').attr('data-root-prefix'), './');
});

test('a missing optional module or generator error warns, removes stale downloads and returns success to the pipeline', async t => {
  const dist = await fixture(t);
  await generateLinkGraph({ dist });
  const warnings = [];
  const result = await runOptionalGraph({ dist, loadGenerator: () => import('./missing-optional-parser-for-test.mjs'), warn: message => warnings.push(message) });
  assert.equal(result.ok, false);
  assert.ok(warnings.some(w => w.includes('WARNING') && w.includes('continuing')));
  assert.deepEqual((await readdir(path.join(dist, 'link-graph'))).sort(), ['index.html']);
  const $ = load(await readFile(path.join(dist, 'link-graph/index.html'), 'utf8'));
  assert.equal($('#link-graph-data').length, 0);
  assert.equal($('a[download]').length, 0);
  assert.match($.text(), /není k dispozici/);
  const cli = spawnSync(process.execPath, [fileURLToPath(new URL('./generate-link-graph.mjs', import.meta.url)), dist], {
    env: { ...process.env, LINK_GRAPH_FORCE_FAILURE: '1' }, encoding: 'utf8',
  });
  assert.equal(cli.status, 0, cli.stderr);
  assert.match(cli.stderr, /WARNING.*Simulated optional generator failure.*continuing/);
  const successCli = spawnSync(process.execPath, [fileURLToPath(new URL('./generate-link-graph.mjs', import.meta.url)), dist], {
    env: { ...process.env, LINK_GRAPH_FORCE_FAILURE: '' }, encoding: 'utf8',
  });
  assert.equal(successCli.status, 0, successCli.stderr);
  assert.match(successCli.stdout, /Generated JSON, GraphML and SVG/);
  assert.equal((await runOptionalGraph({ dist, warn: message => warnings.push(message) })).ok, true);
});

test('even missing output and failed cleanup only warn', async t => {
  const parent = await fixture(t);
  const warnings = [];
  const result = await runOptionalGraph({ dist: path.join(parent, 'not-built'), warn: message => warnings.push(message) });
  assert.equal(result.ok, false);
  assert.ok(warnings.length >= 1);
});

test('a real output write failure removes partial files, restores the page and tolerates cleanup errors', async t => {
  const dist = await fixture(t);
  // A directory at the SVG file path simulates an output failure after the
  // JSON/GraphML writes, without changing real project files or dependencies.
  await mkdir(path.join(dist, 'link-graph/site-graph.svg'));
  const warnings = [];
  const result = await runOptionalGraph({ dist, warn: message => warnings.push(message) });
  assert.equal(result.ok, false);
  assert.ok(warnings.some(w => w.includes('continuing')));
  assert.ok(warnings.some(w => w.includes('Could not remove site-graph.svg')));
  const files = await readdir(path.join(dist, 'link-graph'));
  assert.ok(!files.includes('site-graph.json'));
  assert.ok(!files.includes('site-graph.graphml'));
  const $ = load(await readFile(path.join(dist, 'link-graph/index.html'), 'utf8'));
  assert.match($.text(), /není k dispozici/);
  assert.equal($('a[download], #link-graph-data').length, 0);
  const thrownValue = await runOptionalGraph({ dist, loadGenerator: () => { throw null; }, warn: message => warnings.push(message) });
  assert.equal(thrownValue.ok, false);
});
