// Keep this entry point dependency-free: even a failed import of the optional
// generator (including a missing parser or syntax error) must not fail the build.
import { writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export async function runOptionalGraph({
  dist = 'dist',
  fail = process.env.LINK_GRAPH_FORCE_FAILURE === '1',
  loadGenerator = () => import('./lib/link-graph.mjs'),
  warn = message => console.warn(message),
} = {}) {
  try {
    if (fail) throw new Error('Simulated optional generator failure (LINK_GRAPH_FORCE_FAILURE=1)');
    const { generateLinkGraph } = await loadGenerator();
    const graph = await generateLinkGraph({ dist });
    console.log(`[link-graph] Generated JSON, GraphML and SVG: ${graph.nodes.length} nodes, ${graph.edges.length} directed edges.`);
    return { ok: true, graph };
  } catch (error) {
    warn(`[link-graph] WARNING: ${error instanceof Error ? error.message : String(error)}. Optional graph omitted; continuing the main website build.`);
    // A manual rerun must not advertise stale/partly written exports as current.
    try {
      const { FALLBACK, graphPage, replaceGraph } = await import('./lib/link-graph-page.mjs');
      const page = await graphPage(dist);
      await writeFile(page.file, replaceGraph(page.html, FALLBACK), 'utf8');
    } catch (cleanupError) { warn(`[link-graph] WARNING: Could not reset graph page: ${cleanupError.message}`); }
    for (const name of ['site-graph.json', 'site-graph.graphml', 'site-graph.svg']) {
      try { await rm(path.join(dist, 'link-graph', name), { force: true }); }
      catch (cleanupError) { warn(`[link-graph] WARNING: Could not remove ${name}: ${cleanupError.message}`); }
    }
    return { ok: false };
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await runOptionalGraph({ dist: process.argv[2] || 'dist' });
}
