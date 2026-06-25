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
- the same source can produce both a normal web build and a portable file-based build
- the English version is generated from the Czech source during the build workflow
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

## Project structure

```text
public/
  demos/        standalone HTML/JS demos and legacy static pages
  files/        PDFs and other downloadable or embeddable files
  images/       article images, thumbnails, and visual assets

src/
  components/   reusable Astro components
  content/      MDX articles and video metadata
  layouts/      shared page layouts
  lib/          shared utilities and i18n configuration
  pages/        Astro routes
  styles/       global styles

scripts/        build, translation, and portable-output utilities
translations/   cached generated English content
```

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

Before publishing the web build:

1. Run `npm run build:web:translate`.
2. Run `npm run build:web:strict`.
3. Run `npm run preview`.
4. Open at least one Czech article and one English article locally.
5. Check that the English article body is actually translated, not only the header and metadata.
6. Upload the complete `dist/` directory.
7. Overwrite existing files on the server instead of relying on partial FTP shortcuts.

For portable/offline output:

1. Run `npm run build:usb:translate`.
2. Run the strict USB check if available in `package.json`, or use the documented wrapper script.
3. Open the generated HTML directly from disk.
4. Check CSS, images, internal links, local demos, and English article content.

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
