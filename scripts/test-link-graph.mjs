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
    '404.html': '<a href="https://not-a-source.test/">Excluded</a>',
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
  assert.ok(graph.nodes.every(n => !/iframe\.test|script\.test|not-a-source\.test|password|%ZZ|mailto:|javascript:/.test(n.url)));
  assert.equal(graph.nodes.length, new Set(graph.nodes.map(n => n.id)).size);
  assert.deepEqual(await collectGraph({ dist }), graph);
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
  assert.deepEqual(graph.edges.filter(e => e.source === cs.id), [{ source: cs.id, target: demo.id, count: 2, linkCount: 0, embedCount: 2, redirectCount: 0 }]);
  const mixed = graph.nodes.find(n => n.file === 'mixed/index.html');
  const mixedEdge = incoming.find(e => e.source === mixed.id);
  assert.deepEqual([mixedEdge.linkCount, mixedEdge.embedCount, mixedEdge.count], [1, 1, 2]);
  assert.ok(graph.nodes.every(n => !n.url.includes('remote-demo.test')));
  assert.ok(graph.edges.every(e => e.count === e.linkCount + e.embedCount + e.redirectCount));
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
