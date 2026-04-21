# VojtaMaur Astro

A minimalist skeleton for a static website built with Astro + MDX, preserving the following URL scheme:

- `/volna-tvorba/`
- `/vystavy/`
- `/cestovani/`
- `/<article-slug>/`

## Quick Start

```bash
npm install
npm run dev
```

## Project Structure

- `src/pages/index.astro` - homepage, currently a placeholder
- `src/pages/volna-tvorba/index.astro` - Volná tvorba grid
- `src/pages/vystavy/index.astro` - Výstavy grid
- `src/pages/cestovani/index.astro` - Cestování grid
- `src/pages/[slug].astro` - individual articles at root-level URLs
- `src/content/posts/*.mdx` - article content
- `public/images/` - images and thumbnails
- `public/demos/` - standalone HTML/JS demos for iframe embedding

## How to Add an Article

1. Create a new `.mdx` file in `src/content/posts/`
2. Fill in the frontmatter:
   - `title`
   - `slug`
   - `section` (`volna-tvorba`, `vystavy`, `cestovani`)
   - `date`
   - `thumbnail`
   - `thumbnailAlt`
3. The article will automatically:
   - appear in the relevant section
   - be generated at the URL `/<slug>/`

## Recommended Pattern for Custom HTML/JS

Place interactive content in `public/demos/name/index.html` and embed it in an article using a component:

```mdx
import DemoEmbed from "../../components/DemoEmbed.astro";

<DemoEmbed src="/demos/name/" title="My demo" />
```

This keeps the demo independently archivable as well, without relying on an external service.

## URL Note

Root-level article URLs use the `slug` frontmatter field, not the file name. This means legacy links can be preserved exactly as needed.

## Copyright

Code is licensed under MIT.  
Content (texts, images, media) is not licensed for reuse without permission.

