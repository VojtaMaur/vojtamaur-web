import { defineConfig } from "astro/config";
import mdx from "@astrojs/mdx";
import sitemap from "@astrojs/sitemap";

const isUSB = process.env.BUILD_TARGET === "usb";

export default defineConfig({
  site: "https://vojtamaur.cz",
  integrations: [
    mdx(),
    ...(!isUSB ? [sitemap()] : []),
  ],
  trailingSlash: isUSB ? "never" : "always",
  build: {
    format: isUSB ? "file" : "directory",
  },
});