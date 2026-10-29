# vojtamaur-web

Source repository for [vojtamaur.cz](https://vojtamaur.cz/), a static, file-oriented personal website by Vojta Maur.

The project is built with Astro and MDX. It is not a generic website template. Its main purpose is to preserve and publish texts, images, exhibitions, travel records, embedded media, and standalone interactive demos in a form that can be versioned, rebuilt, copied, archived, and migrated without depending on a CMS, database, or proprietary runtime.

## Live website

- Main site: https://vojtamaur.cz/
- English version: https://vojtamaur.cz/en/
- Technical documentation: https://vojtamaur.cz/documentation/
- Metaweb article: https://vojtamaur.cz/en/metawebovy-clanek/

## Purpose

This repository is the source of truth for the website.

The project is designed around a simple preservation model:

- content lives as files in the repository
- articles are written in MDX
- images, PDFs, demos, and other assets live in `public/`
- the final website is generated as static HTML
- the same source can produce a normal web build, a portable file-based build, an Arweave-compatible build, and a separate Gemini capsule
- the English version is generated from the Czech source during the build workflow
- finished builds include machine-readable integrity metadata, and selected builds can be signed with OpenPGP
- important outputs can be mirrored across repositories, archive services, and static snapshots

The goal is not only to run a website now, but to keep the content reconstructable later, including in degraded or migrated environments.  

## Technology

Core stack:

- [Astro](https://astro.build/) for static site generation
- MDX for article content
- Astro Content Collections for metadata validation
- reusable Astro components for layouts, media, embeds, and listings
- static assets copied directly from `public/`
- build-time postprocessing for English output and portable/offline builds

## Main commands

Install dependencies:

```bash
npm install
```

Start local development:

```bash
npm run dev
```

Build the standard web version:

```bash
npm run build:web
```

Build the web version and create missing English translation cache entries:

```bash
npm run build:web:translate
```

Build the translating production version and sign the finished checksum manifest:

```bash
npm run build:web:translate:signed
```

Check that the web build has no missing English translation cache entries:

```bash
npm run build:web:strict
```

Preview the production build locally:

```bash
npm run preview
```

Build the portable file-based version:

```bash
npm run build:usb
```

Build the portable version and create missing English translation cache entries:

```bash
npm run build:usb:translate
```

Build the Gemini capsule from a strict web build:

```bash
npm run build:gemini
```

Build the Arweave / Permaweb deployment output:

```bash
npm run build:arweave
```

The complete command list and exact build semantics are documented at:

https://vojtamaur.cz/documentation/

## Maintainer quick workflow

This is the normal local Windows CMD workflow used when publishing source changes to the repository mirrors and updating Codeberg Pages.

Set local-only environment variables. Never commit the actual DeepL key or private OpenPGP key material:

```bat
set "DEEPL_AUTH_KEY=YOUR_DEEPL_KEY"
set "GNUPGHOME=G:\vojtamaur-secrets\PGP\gnupg"
```

Audit public assets **before** building, committing, or pushing:

```bat
python scripts/audit-public-metadata.py --exiftool "D:\Program Files\exiftool\exiftool.exe"
```

If unintended metadata is found, preview the strip first, then strip and audit again:

```bat
python scripts/audit-public-metadata.py --exiftool "D:\Program Files\exiftool\exiftool.exe" --strip --dry-run
python scripts/audit-public-metadata.py --exiftool "D:\Program Files\exiftool\exiftool.exe" --strip
python scripts/audit-public-metadata.py --exiftool "D:\Program Files\exiftool\exiftool.exe"
```

Create the translating signed production build:

```bat
npm run build:web:translate:signed
```

Commit and push the canonical source and repository copies:

```bat
git status
git add .
git commit -m "Commit message"

git push origin main
git push gitlab main
git push codeberg main
```

Deploy the generated web output to the Codeberg Pages `pages` branch:

```bat
deploy-codeberg-pages.bat
```

The Codeberg deployment helper performs its own signed web rebuild from the committed `main` worktree before copying `dist/` into the separate `pages` worktree.

## Project structure

```text
public/
  demos/        standalone HTML/JS demos and legacy static pages
  files/        PDFs and other downloadable or embeddable files
  images/       article images, thumbnails, and visual assets
  keys/         public OpenPGP key and fingerprint

src/
  components/   reusable Astro components
  content/      MDX articles and video metadata
  layouts/      shared page layouts
  lib/          shared utilities and i18n configuration
  pages/        Astro routes
  styles/       global styles

scripts/        build, translation, signing, export, and deployment utilities
source-bundle/  templates for the reconstructable source package
translations/   cached generated English content

dist/           generated standard web or portable output
dist-arweave/   generated Arweave / Permaweb deployment output
dist-gemini/    generated Gemini capsule
```

Generated output directories are build artifacts and are not source content.

## Routing model

The website preserves a legacy-friendly URL structure.

Main public sections:

- `/volna-tvorba/`
- `/vystavy/`
- `/cestovani/`
- `/propagacni-videa/`
- `/o-mne/`
- `/kontakt/`

Article pages are generated at root-level URLs:

```text
/<article-slug>/
```

The URL is controlled by the `slug` field in the article frontmatter, not by the MDX filename. This allows old links to be preserved even if the internal file organization changes.

## Content model

Articles are stored in:

```text
src/content/posts/
```

Each article is an MDX file validated through the `posts` content collection.

Shared required frontmatter:

```yaml
title: "Article title"
slug: "article-slug"
section: "volna-tvorba"
date: 2026-04-19
thumbnail: "/images/example-thumbnail.jpg"
thumbnailAlt: "Thumbnail description"
```

Shared optional frontmatter:

```yaml
excerpt: ""
draft: false
```

Section-specific metadata may be used for exhibitions and travel entries, for example:

```yaml
dateFrom: "1. 1. 2024"
dateTo: "31. 1. 2024"
city: "Jindřichův Hradec"
venue: "Muzeum fotografie a moderních obrazových médií"
exhibition: "Obrazy nad čísly"
```

or:

```yaml
year: "2019"
media: "Fotografie"
```

Draft articles can be hidden by setting:

```yaml
draft: true
```

## Media and embeds

The project uses reusable components for media-heavy content:

- `ImageFigure` for standalone images
- `MediaRow` for image, PDF, and text grids
- `Embed` for iframe-based embeds such as YouTube, Google Maps, Sketchfab, and local demos

Standalone interactive demos should be placed in:

```text
public/demos/name/
```

They can then be embedded from MDX, for example:

```mdx
import Embed from "../../components/Embed.astro";

<Embed src="/demos/name/" kind="local" ratio="16 / 9" />
```

Keeping demos in `public/demos/` makes them part of the static output instead of depending on a third-party platform.

## English version

The Czech MDX content is the canonical source.

The English version is generated during the build process. Stable interface text is translated manually through the project i18n configuration, while article body content is translated by a postprocess step and stored in a cache under:

```text
translations/en/
```

The translation workflow uses a DeepL API key supplied through an environment variable:

```bash
DEEPL_AUTH_KEY
```

The key must not be committed to the repository, embedded in client-side code, or uploaded as a public file. 

For content that must remain unchanged in the English output, use `NoTranslate.astro` or HTML markers such as:

```html
<div class="notranslate" translate="no">
  This block will not be translated.
</div>
```

## Preservation and verification outputs

The default web and USB build pipelines also generate `/link-graph/`, an interactive directed link graph with downloadable SVG, GraphML and JSON at `/link-graph/site-graph.{svg,graphml,json}`. This step runs automatically, after HTML postprocessing and before integrity generation; Arweave builds inherit it from the web build. It uses Node.js APIs, the existing Cheerio parser and vanilla browser JavaScript, with no new dependencies or network crawling. The built page embeds its data and SVG, so it also works offline without fetching JSON. SVG and downloads remain usable without JavaScript.

Graph generation is optional for build success: import/parser/output errors print `[link-graph] WARNING`, remove incomplete graph downloads where possible, leave an explanatory page, and allow the normal build to continue. The graph is enabled by default. `npm run generate:link-graph` regenerates it from existing `dist/`; then rerun `npm run generate:integrity` (and sign again if needed), because this changes build bytes. Never regenerate after signing without refreshing integrity and the signature.

The graph supports one-finger panning and two-finger pinch zoom around the moving midpoint of the touches. Gestures can start on a node; a tap selects it, while a drag or pinch suppresses accidental selection. Lifting one finger continues as panning without a jump. Mouse dragging, zoom buttons and Ctrl + wheel remain available. The gestures use native Pointer Events without another dependency.

For an end-to-end failure check in PowerShell, set `$env:LINK_GRAPH_FORCE_FAILURE='1'`, run `npm run build:web`, then remove that test variable with `Remove-Item Env:LINK_GRAPH_FORCE_FAILURE`. A warning and a successful main build are expected; run a normal build afterwards to restore the graph.

The graph also inventories published content files under `files/`, `images/` and `keys/`, so unlinked files such as `/images/kurt-godel-rat.jpg` appear as isolated nodes. Only HTML documents from `demos/` are included; their support images/data are excluded even when linked. CSS/JavaScript and similar technical assets are excluded. The final SHA-256 manifest is produced after the graph and includes its artifacts; the graph enumerates those three finished content folders without rehashing them or depending on that manifest. The node browser is a full-width table with wrapping names/paths and separate incoming/outgoing columns.

The graph reads `a[href]` and `area[href]` from built HTML, including navigation, standalone demos and the custom `/404.html` recovery page with its archive-map links. The graph includes this document despite `noindex`; it does not invent incoming edges merely because a missing URL would return a 404 response. It also records `iframe[src]`, `object[data]` and `embed[src]` pointing to an existing local HTML page or inventoried content file. This connects embedded interactive demos and PDF documents to their containing articles. Explicit HTML `meta refresh` redirects to existing local HTML pages are also recorded (for example `/pf2026/` to its demo). Rendered `img[src]`, `img[srcset]` and `picture source[srcset]` also connect a page to existing inventoried local content files, including all declared responsive candidates, with `imageCount` recording image use. Each directed edge retains separate `linkCount`, `embedCount`, `redirectCount` and `imageCount` values; `count` is their sum. Embed-only edges are dashed, redirect-only edges dotted, image-only edges green, and the inspector identifies each relationship type. No remote or JavaScript redirects are inferred. Remote iframes, iframe `srcdoc`, embeds outside the selected content folders (apart from HTML pages), audio/video sources, remote images, images outside the selected content folders, CSS/JavaScript-created image references and JavaScript-created links are excluded. It cannot discover incoming links from the internet or links inside PDF/text exports; it does not check target availability. Internal fragments/query variants and external fragments are merged; external queries stay distinct. Mirrors are external, and non-page internal targets can include unresolved paths. See documentation section 9.6.14 and the graph page for the full scope.

Important files in the finished standard build include `ALL_POSTS.txt`, `ARCHIVE.txt`, the reconstructable `source/vojtamaur-web-source.zip`, the public OpenPGP material under `keys/`, and build-integrity files such as `SHA256SUMS.txt`, `BUILD_SHA256.txt`, `integrity.json`, and `SIGNING_STATUS.txt`.

Signed builds additionally create `SHA256SUMS.txt.asc`. The Gemini capsule is generated separately in `dist-gemini/` and is not covered by the `dist/` checksum manifest or its detached signature. The Arweave / Permaweb workflow uses a separate `dist-arweave/` output with its own integrity metadata.

## Portable build

The portable build is intended for offline use, file-based snapshots, archival copies, and transfer on external media.

In this mode, the project generates file-style HTML routes and rewrites root-relative paths so the output can work outside a normal web server root.

Standard web build:

```text
slug/index.html
```

Portable file-based build:

```text
slug.html
```

The portable build is not identical to normal hosting. External embeds and third-party services may behave differently when opened locally.

## Publishing checklist

Before publishing new or changed public assets, run the metadata audit and resolve unintended metadata **before committing**. Files under `public/` are copied into builds unchanged, while repository mirrors and archival ingests may preserve committed files permanently.

Before uploading the web build:

1. Run the translating build, preferably the signed production variant when a signed release is intended: `npm run build:web:translate:signed`.
2. Run `npm run build:web:strict` if a final cache-completeness check is needed.
3. Run `npm run preview`.
4. Check that `dist/SHA256SUMS.txt`, `dist/BUILD_SHA256.txt`, and `dist/integrity.json` exist.
5. For a signed build, also verify that `dist/SHA256SUMS.txt.asc` exists and that `SIGNING_STATUS.txt` reports a successful signature.
6. Open at least one Czech article and one English article locally.
7. Check that the English article body is actually translated, not only the header and metadata.
8. Upload the complete `dist/` directory, including preservation and integrity artifacts.
9. Overwrite existing files on the server instead of relying on partial FTP shortcuts.

For portable/offline output:

1. Run `npm run build:usb:translate`.
2. Run `npm run build:usb:strict`.
3. Check that `SHA256SUMS.txt`, `BUILD_SHA256.txt`, and `integrity.json` are present in the generated output.
4. Open the generated HTML directly from disk.
5. Check CSS, images, internal links, local demos, and English article content.

## Repository and archive topology

GitHub is the canonical source repository. GitLab and Codeberg contain repository copies, while Software Heritage preserves an archival ingest of the GitHub origin. Static snapshots and other preservation layers are maintained separately.

The current archive entry points and mirror topology are intentionally maintained outside this README so that they do not become a stale duplicated list. See the Metaweb article and `ARCHIVE.txt` for the current map.

## Optional archival PDF exports

The three manual exporters in `scripts/` support `--pdfa 2b` to retain the ordinary
PDF and create a separate `*-pdfa-2b.pdf`. Shared options are `--compress
none|light|medium|high`, `--image-dpi`, `--jpeg-quality`, and `--target-size`:

```bash
python scripts/export-site-pdf-ultra.py --pdfa 2b --compress medium --target-size 2M
```

Final processing requires Ghostscript; PDF/A also requires an RGB ICC profile,
normally detected from its installation. veraPDF is used when available; otherwise
the exporter explicitly reports that external PDF/A validation was not performed.
Ordinary PDF remains the default, and `export-all.bat` does not request PDF/A.
See documentation section 9.6.5 for presets, override semantics, validation and
the bounded target-size search (status 2 when the limit cannot be reached).

## Gallery image exports

`export-all.bat` now also converts its exact bilingual site PDF and Metaweb PDF
into separate timestamped `exports/vojtamaur-web-export-images-{all|metaweb}-.../`
editions. The full-site export has numbered `cs/` and `en/` images. Metaweb is
one bilingual numbered sequence directly in its edition folder, preserving every
PDF page exactly once in source order, including all appendices. Both contain a
manifest, SHA-256 checksums and configurable upload batch lists. No website build
is performed.
Standalone commands reuse the latest matching PDF and require its authentic
manifest (use `--pdf` and `--source-manifest` for custom/relocated inputs):

```bash
npm run export:images
npm run export:images:metaweb
python scripts/export-site-images.py --scope all --format jpg --quality 85 --dpi 150 --max-edge 2560
python scripts/export-site-images.py --verify "exports/EDITION-FOLDER"
```

Default `--format jpg` uses JPEG consistently for the complete edition. There
is no automatic format selection or mixing of file types. JPEG is lossy; choose
`--format png` to use lossless PNG for the complete edition instead. Existing
Pillow and pypdf dependencies are reused. Either existing Ghostscript or optional
Poppler (`pdftoppm`) renders the PDFs; nothing is downloaded or installed by the
image exporter. Missing optional tools return status 3 and do not block other
batch exports. Without Ghostscript the standard PDF step uses archive quality.
The full site's shared PDF index retains its original languages in both folders.
Metaweb retains the complete bilingual PDF as one sequence. See documentation section
9.6.15 for input selection, numbering, configuration and gallery limitations.

## Documentation

This README is only the public repository overview.

The detailed technical documentation is kept on the website:

https://vojtamaur.cz/documentation/

The preservation idea and archive entry points are described here:

https://vojtamaur.cz/en/metawebovy-clanek/

## License and reuse

Code is licensed under the MIT License.

Texts, images, media, and other content are not released as general-purpose reusable material. They may be copied, archived, and publicly mirrored for preservation purposes.

They may not be reused, modified, or republished outside that preservation context without permission.

Attribution to the original author and website is required for any public archival use:

```text
Vojta Maur
https://vojtamaur.cz/
```


## Published Rosetta translations

Keep finished, selected non-English translations as `public/rosetta/ALL_POSTS__lang-CODE.txt`. These stable repository files are published unchanged. `/rosetta/` lists the available languages; `/<CODE>/` shows a short localized notice and a link to its TXT, with links back to the full CS/EN homepages. English Rosetta is not published; `/en/` remains the normal English homepage.

An optional root `rosetta.json` keeps the matching export state and supplies translation-edition date and validation metadata during the build. It stays out of the public build and source ZIP. The build never reads `exports/` or calls a translation API. Replace the selected TXT and matching JSON manually when updating this edition. UI notices live in `src/lib/rosetta-copy.ts`. See documentation section 9.6.10 for publication and source-package recovery details.

After a web or USB build, run `npm run test:rosetta` to check all published language pages, dates, links and original TXT bytes.

## Meme archive export

Manual, independent meme editions embed real RFC 6330 RaptorQ symbols of the
compressed `ALL_POSTS.txt` in binary QR codes. Supports deterministic seeds,
continuous generation, resume, and reconstruction from image pixels. Existing
builds and `export-all.bat` do not invoke it. See
[scripts/meme-archive/README.md](scripts/meme-archive/README.md) for isolated
optional dependencies, commands, format specification and validation.
