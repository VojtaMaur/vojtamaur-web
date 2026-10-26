import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
// Already used by the existing HTML exporters. Loaded only inside the optional
// step, so parser/import failures are caught by generate-link-graph.mjs.
import { load } from 'cheerio';
import { graphPage, replaceGraph } from './link-graph-page.mjs';

const SITE = 'https://vojtamaur.cz';
const NODE_COLORS = { page: '#175f9c', internal: '#79521b', external: '#9a3670' };
const INVENTORY_ROOTS = new Set(['files', 'images', 'keys']);
const TECHNICAL_ASSET = /\.(?:css|scss|sass|less|[cm]?js|jsx|tsx?|map|woff2?|ttf|otf|eot)$/i;
const OS_ARTIFACT = /(?:^|\/)(?:\.DS_Store|Thumbs\.db)$/i;
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const id = value => `n${createHash('sha256').update(value).digest('hex').slice(0, 24)}`;
export const xml = value => String(value).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g, '')
  .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[c]);
export const scriptJson = value => JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');

async function walk(dir, prefix = '') {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const relative = prefix + entry.name;
    if (entry.isDirectory()) files.push(...await walk(path.join(dir, entry.name), relative + '/'));
    else if (entry.isFile()) files.push(relative);
  }
  return files.sort(compare); // Ignore symlinks, never crawl outside dist or HTTP.
}

function pagePath(file) {
  if (file === 'index.html') return '/';
  if (file.endsWith('/index.html')) return '/' + file.slice(0, -10);
  return '/' + file;
}

function decodedPath(url) {
  try {
    const decoded = decodeURIComponent(url.pathname);
    if (/[\\\u0000-\u001f]/.test(decoded)) return null;
    return decoded;
  } catch { return null; }
}

// Read URL tokens without splitting commas inside a URL (notably data URLs).
// Descriptors are irrelevant: every declared image candidate is a relationship.
function srcsetURLs(value = '') {
  const urls = [];
  let rest = value;
  while (rest) {
    rest = rest.replace(/^[\s,]+/, '');
    const match = rest.match(/^\S+/);
    if (!match) break;
    const token = match[0];
    urls.push(token.replace(/,+$/, ''));
    rest = rest.slice(token.length);
    if (!token.endsWith(',')) {
      // Skip descriptors, including any parenthesized content, up to the next
      // candidate separator. Never extract a URL from a data URL's payload.
      let depth = 0, end = 0;
      for (; end < rest.length; end++) {
        if (rest[end] === '(') depth++;
        else if (rest[end] === ')') depth = Math.max(0, depth - 1);
        else if (rest[end] === ',' && depth === 0) break;
      }
      rest = rest.slice(end + 1);
    }
  }
  return urls;
}

export async function collectGraph({ dist, site = SITE }) {
  const origin = new URL(site).origin;
  // Include the custom 404 recovery document: its archive map contains real
  // outgoing links even though the host serves it as an error response.
  const builtFiles = await walk(dist);
  const files = builtFiles.filter(file => file.endsWith('.html'));
  const nodes = new Map();
  const aliases = new Map();
  const pages = [];
  for (const file of files) {
    const route = pagePath(file);
    const url = new URL(route, origin).href;
    const $ = load(await readFile(path.join(dist, file), 'utf8'));
    // Ignore our own generated UI on reruns: downloads and selected neighbours
    // are presentation, not new source relationships.
    $('[data-link-graph-generated]').remove();
    // Use the document title, not a title belonging to an embedded SVG. Keep
    // the shared brand suffix out of graph labels; generic site titles should
    // not hide a page's more useful heading.
    const title = $('head > title').first().text().replace(/\s+/g, ' ').trim()
      .replace(/\s*\|\s*Vojta Maur$/i, '').trim();
    const specificTitle = title.toLowerCase() === 'vojta maur' ? '' : title;
    const heading = $('h1').first().text().replace(/\s+/g, ' ').trim();
    const label = specificTitle || heading || route;
    const node = { id: id(url), url, label, kind: 'page', file };
    nodes.set(url, node);
    for (const alias of new Set([route, '/' + file, ...(route.endsWith('/') ? [route.slice(0, -1)] : [])])) {
      aliases.set(alias || '/', node);
    }
    // Astro's portable build flattens foo/ to foo.html. Fold canonical /foo/
    // links into that same page while retaining real .html URLs for offline use.
    if (file !== 'index.html' && !file.endsWith('/index.html')) {
      const flat = '/' + file.slice(0, -5);
      if (!aliases.has(flat)) aliases.set(flat, node);
      if (!aliases.has(flat + '/')) aliases.set(flat + '/', node);
    }
    pages.push({ $, node, route });
  }

  // The final SHA manifest runs after this graph (and hashes the graph itself).
  // Inventory the selected published directories directly, without reading a
  // stale manifest or hashing assets again. Files do not imply relationships.
  for (const file of builtFiles) {
    if (!INVENTORY_ROOTS.has(file.split('/')[0]) || TECHNICAL_ASSET.test(file) || OS_ARTIFACT.test(file)) continue;
    if (aliases.has('/' + file)) continue; // HTML already has a page node.
    const pathname = '/' + file.split('/').map(encodeURIComponent).join('/');
    const url = new URL(pathname, origin).href;
    const node = { id: id(url), url, label: '/' + file, kind: 'internal', file };
    nodes.set(url, node);
    aliases.set('/' + file, node);
  }

  const edges = new Map();
  for (const { $, node, route } of pages) {
    let base = new URL(route, origin);
    const declaredBase = $('base[href]').first().attr('href');
    if (declaredBase) {
      try { base = new URL(declaredBase, base); } catch { /* use page URL */ }
    }
    const references = [];
    $('a[href], area[href], iframe[src], object[data], embed[src]').each((_, element) => {
      const isEmbed = ['iframe', 'object', 'embed'].includes(element.tagName);
      // srcdoc overrides src in the browser; it is not a relationship to the
      // fallback URL. Embeds can use existing HTML pages or content files
      // from the selected inventory (for example, an article's PDF document).
      if (element.tagName === 'iframe' && $(element).attr('srcdoc') !== undefined) return;
      const attribute = element.tagName === 'object' ? 'data' : isEmbed ? 'src' : 'href';
      references.push({ href: $(element).attr(attribute), type: isEmbed ? 'embedCount' : 'linkCount' });
    });
    $('img[src], img[srcset], picture source[srcset]').each((_, element) => {
      if (element.tagName === 'img' && $(element).attr('src')) {
        references.push({ href: $(element).attr('src'), type: 'imageCount' });
      }
      for (const href of srcsetURLs($(element).attr('srcset'))) {
        references.push({ href, type: 'imageCount' });
      }
    });
    $('meta[http-equiv][content]').each((_, element) => {
      if ($(element).attr('http-equiv').trim().toLowerCase() !== 'refresh') return;
      // Only explicit HTML refresh targets; never infer HTTP/JS redirects or
      // follow anything over the network. Quoted and unquoted URLs are allowed.
      const match = $(element).attr('content').match(/^\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(?:"([^"]*)"|'([^']*)'|(.+?))\s*$/i);
      if (match) references.push({ href: match[1] ?? match[2] ?? match[3], type: 'redirectCount' });
    });
    for (const reference of references) {
      const href = reference.href?.trim();
      const isEmbed = reference.type === 'embedCount';
      const localPageOnly = reference.type === 'redirectCount';
      const isImage = reference.type === 'imageCount';
      if (!href || /[\u0000-\u001f\\]/.test(href)) continue;
      let target;
      try { target = new URL(href, base); } catch { continue; }
      if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password) continue;
      target.hash = '';
      let destination;
      if (target.origin === origin) {
        const pathname = decodedPath(target);
        if (pathname === null) continue;
        if (TECHNICAL_ASSET.test(pathname) || OS_ARTIFACT.test(pathname)) continue;
        destination = aliases.get(pathname);
        // Demos are HTML documents. Their private images/data are supporting
        // implementation files, not additional demos or inventory entries.
        if (pathname.startsWith('/demos/') && destination?.kind !== 'page') continue;
        if (localPageOnly && destination?.kind !== 'page') continue;
        const inventoriedFile = destination?.kind === 'internal' && INVENTORY_ROOTS.has(destination.file.split('/')[0]);
        if (isEmbed && destination?.kind !== 'page' && !inventoriedFile) continue;
        // Image use adds edges only to existing selected content files. Do not
        // invent missing assets or import remote image hosts into this model.
        if (isImage && !inventoriedFile) continue;
        if (!destination) {
          target.search = '';
          const url = target.href;
          destination = nodes.get(url) || { id: id(url), url, label: pathname, kind: 'internal', file: pathname.slice(1) };
          nodes.set(url, destination);
        }
      } else {
        if (localPageOnly || isEmbed || isImage) continue; // No remote embeds, redirects or images.
        const url = target.href;
        destination = nodes.get(url) || { id: id(url), url, label: target.hostname + target.pathname + target.search, kind: 'external', file: '' };
        nodes.set(url, destination);
      }
      if (node.id === destination.id) continue; // fragments and self-links
      const key = `${node.id}:${destination.id}`;
      const edge = edges.get(key) || { source: node.id, target: destination.id, count: 0, linkCount: 0, embedCount: 0, redirectCount: 0, imageCount: 0 };
      edge.count++;
      edge[reference.type]++;
      edges.set(key, edge);
    }
  }
  const sortedNodes = [...nodes.values()].sort((a, b) => compare(a.url, b.url));
  const sortedEdges = [...edges.values()].sort((a, b) => compare(`${a.source}:${a.target}`, `${b.source}:${b.target}`));
  // Stable, purely geometric layout: central pages, then local targets, then
  // outgoing URLs. Coordinates are exported identically in all three formats.
  for (const kind of ['page', 'internal', 'external']) {
    const group = sortedNodes.filter(n => n.kind === kind);
    const [inner, outer] = kind === 'page' ? [50, 820] : kind === 'internal' ? [900, 1080] : [1160, 1400];
    group.forEach((node, index) => {
      const radius = Math.sqrt(inner ** 2 + (outer ** 2 - inner ** 2) * (index + 0.5) / group.length);
      const angle = index * Math.PI * (3 - Math.sqrt(5));
      node.x = Math.round(1500 + Math.cos(angle) * radius);
      node.y = Math.round(1540 + Math.sin(angle) * radius);
    });
  }
  return {
    schemaVersion: 1, site: origin, directed: true,
    scope: 'All local built HTML pages (including demos) and content-file inventory under files/, images/ and keys/, including unlinked files. Non-HTML support files under demos/ are excluded. CSS, JavaScript/TypeScript, source maps, fonts and OS artifacts are excluded from internal targets and inventory. Relationships come from HTML a[href] and area[href], plus iframe[src] (excluding srcdoc), object[data] and embed[src] pointing to existing same-origin HTML pages or inventoried content files, including PDFs. Explicit meta-refresh redirects point only to existing same-origin HTML pages. Image use in img[src], img[srcset] and picture source[srcset] creates imageCount relationships only to existing inventoried local content files; all declared candidates are counted, regardless of viewport. Inventory alone creates no edges. Edges aggregate linkCount, embedCount, redirectCount and imageCount; count is their sum. No network crawling, remote embedded sources or inferred HTTP/JavaScript redirects. Internal query/fragment variants and external fragments are merged; repeated source/target relationships are counted; self-links are omitted. Mirrors are external. Other internal targets may be files or unresolved URLs, not validated by this graph. Layout is geometric, not semantic.',
    nodes: sortedNodes, edges: sortedEdges,
  };
}

export function toGraphML(graph) {
  const keys = [['url', 'node', 'string'], ['label', 'node', 'string'], ['kind', 'node', 'string'], ['file', 'node', 'string'], ['x', 'node', 'double'], ['y', 'node', 'double'], ['count', 'edge', 'int'], ['linkCount', 'edge', 'int'], ['embedCount', 'edge', 'int'], ['redirectCount', 'edge', 'int'], ['imageCount', 'edge', 'int'], ['scope', 'graph', 'string'], ['site', 'graph', 'string']];
  return '<?xml version="1.0" encoding="UTF-8"?>\n<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n'
    + keys.map(([name, owner, type]) => `  <key id="${name}" for="${owner}" attr.name="${name}" attr.type="${type}"/>`).join('\n')
    + '\n  <graph id="website" edgedefault="directed">\n'
    + `    <data key="scope">${xml(graph.scope)}</data>\n    <data key="site">${xml(graph.site)}</data>\n`
    + graph.nodes.map(node => `    <node id="${node.id}">${['url', 'label', 'kind', 'file', 'x', 'y'].map(key => `<data key="${key}">${xml(node[key])}</data>`).join('')}</node>`).join('\n')
    + '\n' + graph.edges.map((edge, index) => `    <edge id="e${index}" source="${edge.source}" target="${edge.target}"><data key="count">${edge.count}</data><data key="linkCount">${edge.linkCount}</data><data key="embedCount">${edge.embedCount}</data><data key="redirectCount">${edge.redirectCount}</data><data key="imageCount">${edge.imageCount}</data></edge>`).join('\n')
    + '\n  </graph>\n</graphml>\n';
}

export function toSVG(graph) {
  const nodes = new Map(graph.nodes.map(n => [n.id, n]));
  const degrees = new Map(graph.nodes.map(n => [n.id, 0]));
  for (const e of graph.edges) { degrees.set(e.source, degrees.get(e.source) + 1); degrees.set(e.target, degrees.get(e.target) + 1); }
  const labelled = new Set([...graph.nodes].sort((a, b) => degrees.get(b.id) - degrees.get(a.id) || compare(a.url, b.url)).slice(0, 65).map(n => n.id));
  const colour = NODE_COLORS;
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 3000 3000" width="3000" height="3000" role="img" aria-labelledby="graph-title graph-desc">\n'
    + `<title id="graph-title">Graf odkazů — ${xml(graph.site)}</title><desc id="graph-desc">${graph.nodes.length} uzlů, ${graph.edges.length} orientovaných vztahů. Modrá: stránky, hnědá: ostatní interní cíle, fialová: externí URL. Šipka míří k cíli vztahu. Čárkovaná hrana označuje vložení místní stránky nebo souboru přes iframe, object nebo embed; tečkovaná místní přesměrování v HTML; zelená použití obrázku. V přehledu jsou vidět názvy nejpropojenějších uzlů; ostatní při najetí. Interaktivní stránka nabízí všechny názvy i při hledání, výběru a přiblížení. Rozmístění je geometrické.</desc>`
    + '<style>[data-node] > text[data-label-priority="secondary"]{display:none}.show-all-labels [data-node] > text,[data-node]:hover > text{display:inline}.hover-labels-only [data-node] > text{display:none}.hover-labels-only [data-node]:hover > text{display:inline}</style>'
    + '<defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0L10 5L0 10" fill="#64748b"/></marker></defs>'
    + '<rect width="3000" height="3000" fill="white"/><text x="60" y="50" font-family="sans-serif" font-size="27" fill="#171717">Graf odkazů · modrá: stránky · hnědá: interní cíle · fialová: externí URL</text>'
    + '<g data-graph-viewport="">'
    + graph.edges.map(edge => {
      const a = nodes.get(edge.source), b = nodes.get(edge.target);
      const distance = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const x = b.x - (b.x - a.x) / distance * 8, y = b.y - (b.y - a.y) / distance * 8;
      const dash = edge.linkCount ? '' : edge.embedCount ? '9 6' : edge.redirectCount ? '2 6' : '';
      return `<path data-source="${a.id}" data-target="${b.id}" d="M${a.x} ${a.y}L${x.toFixed(1)} ${y.toFixed(1)}" stroke="${!edge.linkCount && !edge.embedCount && !edge.redirectCount && edge.imageCount ? '#28735c' : '#64748b'}" stroke-opacity="0.16"${dash ? ` stroke-dasharray="${dash}"` : ''} fill="none" marker-end="url(#graph-arrow)"><title>Odkazy: ${edge.linkCount}; vložení stránky nebo souboru: ${edge.embedCount}; přesměrování v HTML: ${edge.redirectCount}; použití obrázku: ${edge.imageCount}</title></path>`;
    }).join('')
    + graph.nodes.map(node => `<g data-node="${node.id}" transform="translate(${node.x} ${node.y})"><title>${xml(node.label)} — ${xml(node.url)}</title><circle r="${node.kind === 'page' ? 8 : 5}" fill="${colour[node.kind]}" stroke="white" stroke-width="1"/><text data-label-priority="${labelled.has(node.id) ? 'primary' : 'secondary'}" pointer-events="none" x="11" y="4" font-family="sans-serif" font-size="12" fill="#171717" paint-order="stroke" stroke="white" stroke-width="2" stroke-linejoin="round">${xml(node.label.length > 55 ? node.label.slice(0, 55) + '…' : node.label)}</text></g>`).join('')
    + '</g></svg>\n';
}

export async function generateLinkGraph({ dist = 'dist', site = SITE } = {}) {
  const page = await graphPage(dist);
  const graph = await collectGraph({ dist, site });
  if (!graph.nodes.length) throw new Error('No HTML pages found');
  const svg = toSVG(graph);
  const graphml = toGraphML(graph);
  const prefix = path.relative(path.dirname(page.file), path.join(dist, 'link-graph')).split(path.sep).join('/');
  const asset = name => (prefix ? prefix + '/' : './') + name;
  const rootPrefix = path.relative(path.dirname(page.file), dist).split(path.sep).join('/') || '.';
  const content = `<section data-link-graph-generated="" data-root-prefix="${xml(rootPrefix + '/')}">`
    + `<p>${graph.nodes.length} uzlů · ${graph.edges.length} orientovaných vztahů. Opakované vztahy jsou sloučeny; běžné odkazy, vložení stránek či souborů, přesměrování v HTML a použití obrázků mají vlastní počty výskytů.</p>`
    + `<div class="graph-canvas">${svg}</div>`
    + `<div class="graph-legend" role="group" aria-label="Legenda grafu"><p class="graph-legend-keys"><span class="graph-key" style="color:${NODE_COLORS.page}">HTML stránky</span><span class="graph-key" style="color:${NODE_COLORS.internal}">Ostatní interní cíle</span><span class="graph-key" style="color:${NODE_COLORS.external}">Externí URL</span></p><p class="graph-legend-keys"><span class="graph-line">Běžný odkaz</span><span class="graph-line graph-line-embed">Vložení stránky nebo souboru</span><span class="graph-line graph-line-redirect">Přesměrování v HTML</span><span class="graph-line graph-line-image">Použití obrázku</span></p><p>Ostatní interní cíle zahrnují soubory a nerozpoznané cesty. Rozmístění je geometrické; vzdálenost nevyjadřuje významovou podobnost.</p></div>`
    + `<p class="graph-downloads"><a href="${xml(asset('site-graph.svg'))}" download="site-graph.svg">Stáhnout obrázek (SVG)</a> · <a href="${xml(asset('site-graph.graphml'))}" download="site-graph.graphml">Stáhnout GraphML</a> · <a href="${xml(asset('site-graph.json'))}" download="site-graph.json">Stáhnout JSON</a></p>`
    + `<details class="graph-xml"><summary>Zobrazit GraphML</summary><pre tabindex="0"><code>${xml(graphml)}</code></pre></details>`
    + `<script type="application/json" id="link-graph-data">${scriptJson(graph)}</script></section>`;
  const html = replaceGraph(page.html, content);
  // Render all formats before writing anything; the wrapper removes partial
  // files and restores the fallback if any subsequent write fails.
  await mkdir(path.join(dist, 'link-graph'), { recursive: true });
  await writeFile(path.join(dist, 'link-graph/site-graph.json'), JSON.stringify(graph, null, 2) + '\n', 'utf8');
  await writeFile(path.join(dist, 'link-graph/site-graph.graphml'), graphml, 'utf8');
  await writeFile(path.join(dist, 'link-graph/site-graph.svg'), svg, 'utf8');
  await writeFile(page.file, html, 'utf8');
  return graph;
}
