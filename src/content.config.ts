import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";
import { z } from "astro/zod";

const posts = defineCollection({
  loader: glob({ pattern: "**/*.mdx", base: "./src/content/posts" }),
  schema: z.object({
    title: z.string(),
    slug: z.string().min(1),

    section: z.enum(["volna-tvorba", "vystavy", "cestovani"]),

    date: z.coerce.date(),

    thumbnail: z.string().min(1),
    thumbnailAlt: z.string().min(1),

    excerpt: z.string().optional(),
    draft: z.boolean().default(false),

    // 🔽 VÝSTAVY
    dateFrom: z.string().optional(),
    dateTo: z.string().optional(),
    city: z.string().optional(),
    venue: z.string().optional(),
    exhibition: z.string().optional(),

    // 🔽 CESTOVÁNÍ
    year: z.string().optional(),
    media: z.string().optional()
  })
});

const videos = defineCollection({
  loader: glob({ pattern: "**/*.mdx", base: "./src/content/videos" }),
  schema: z.object({
    title: z.string(),
    url: z.string(),
    thumbnail: z.string(),
    thumbnailAlt: z.string(),
    draft: z.boolean().default(false)
  })
});

export const collections = { posts, videos };
