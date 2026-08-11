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
