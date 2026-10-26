import { readFile } from 'node:fs/promises';
import path from 'node:path';

export const START = '<template id="link-graph-start"></template>';
export const END = '<template id="link-graph-end"></template>';
export const FALLBACK = '<p role="status">Graf pro tento build není k dispozici. Web můžete dále používat; podrobnosti jsou v logu buildu.</p>';

export function replaceGraph(html, content) {
  const start = html.indexOf(START);
  const end = html.indexOf(END, start + START.length);
  if (start < 0 || end < 0) throw new Error('Graph page placeholders are missing');
  return html.slice(0, start + START.length) + content + html.slice(end);
}

export async function graphPage(dist) {
  for (const file of ['link-graph/index.html', 'link-graph.html']) {
    const full = path.join(dist, file);
    try { return { file: full, html: await readFile(full, 'utf8') }; }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  throw new Error('Built link-graph page not found; run the Astro build first');
}
